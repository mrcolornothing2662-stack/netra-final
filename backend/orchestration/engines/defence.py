from __future__ import annotations

"""
CyberDrishti AI — Defence Bot Engine Adapter

Adapter implementing the EngineSpec contract: converts CaseContext into the
inputs expected by cognitive.defence.audit_case_defensibility, and maps
every returned DefenceChallenge into a provenance-carrying CognitiveResult
of type DEFENCE_CHALLENGE.
"""
from typing import Any

from cognitive import defence as engine
from orchestration.contracts import (
    DEFENCE_CHALLENGE,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    CognitiveResult,
    CaseContext,
    EngineSpec,
)

ENGINE_NAME = "DefenceBotEngine"
ENGINE_VERSION = "1.0"


def applies(context: CaseContext) -> bool:
    """Defence Bot applies whenever a case has evidence files or existing findings/hypotheses."""
    return bool(context.evidence_files) or bool(context.findings)


def run(context: CaseContext) -> list[CognitiveResult]:
    # Extract evidence files, events, and findings from context
    evidence_files = context.evidence_files
    events = context.events
    findings = context.findings

    audit_report = engine.audit_case_defensibility(
        case_id=context.case_id,
        evidence_files=evidence_files,
        events=events,
        findings=findings,
    )

    results: list[CognitiveResult] = []
    for ch in audit_report.challenges:
        sev = ch.vulnerability_severity
        if sev not in (SEVERITY_CRITICAL, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW):
            sev = SEVERITY_MEDIUM

        # Format descriptive text detailing counter-hypothesis and reasonable doubts
        desc_parts = [ch.defense_counter_hypothesis]
        if ch.reasonable_doubts:
            desc_parts.append("Reasonable Doubts: " + "; ".join(ch.reasonable_doubts[:2]))
        if ch.missing_evidence:
            missing_names = [m.get("item", "") for m in ch.missing_evidence[:2] if m.get("item")]
            if missing_names:
                desc_parts.append("Missing Evidence: " + ", ".join(missing_names))

        description = " ".join(desc_parts)

        component_scores: dict[str, Any] = {
            "defensibility_score": audit_report.defensibility_score,
            "risk_level": audit_report.risk_level,
            "missing_evidence_count": len(ch.missing_evidence),
            "rebuttal_strategy_count": len(ch.rebuttal_strategy),
            "target_hypothesis": ch.target_hypothesis,
        }

        # Build citations from statutory vulnerabilities and missing evidence
        citations: list[dict[str, Any]] = []
        for v in ch.statutory_vulnerabilities:
            citations.append({
                "statute": v.get("statute"),
                "issue": v.get("issue"),
                "defense_challenge": v.get("defense_challenge"),
            })
        for m in ch.missing_evidence:
            citations.append({
                "missing_item": m.get("item"),
                "reason": m.get("reason"),
                "statute": m.get("statutory_rule"),
            })

        rebuttal_recs = [r.get("recommendation", "") for r in ch.rebuttal_strategy if r.get("recommendation")]
        reasoning = (
            f"Adversarial Red-Team Analysis: Tested {ch.target_hypothesis} for {ch.target_entity}. "
            f"Vulnerabilities identified: {len(ch.statutory_vulnerabilities)} statutory point(s), "
            f"{len(ch.missing_evidence)} missing evidentiary element(s). "
            f"Rebuttal: {'; '.join(rebuttal_recs[:2]) if rebuttal_recs else 'Collect independent corroboration.'}"
        )

        ev_refs = ch.evidence_refs
        if not ev_refs and not ch.event_refs:
            ev_refs = [str(f.get("id")) for f in evidence_files if f.get("id")]

        results.append(CognitiveResult(
            finding_type=DEFENCE_CHALLENGE,
            title=f"Defence Challenge — {ch.target_hypothesis} ({ch.target_entity})",
            description=description,
            confidence=ch.confidence,
            severity=sev,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            entity_refs=[ch.target_entity] if ch.target_entity else [],
            event_refs=ch.event_refs,
            evidence_refs=ev_refs,
            component_scores=component_scores,
            reason_codes=[ch.target_hypothesis, "ADVERSARIAL_CHALLENGE"],
            reasoning=reasoning,
            citations=citations,
            dedup_key=f"defence:{ch.challenge_id}",
        ))

    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Adversarial hypothesis stress-testing, evidentiary gap audit & prosecution rebuttal strategy.",
    applicability=applies,
)
