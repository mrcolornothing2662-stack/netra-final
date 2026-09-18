from __future__ import annotations

"""
Output Verifier — the orchestrator's boundary check.

Before findings are published, each one is checked for grounding: it must be
supported by at least one evidence or event reference, and every evidence id it
cites must exist in the case. Findings that fail become VERIFICATION findings
(not silent edits), so evidence, inference and assertion stay separable.

It also performs deterministic *graph* contradiction checks for structured
claims — e.g. a finding that calls an account the "final destination" while the
case graph contains an observed outgoing transfer from it.
"""
import re

from orchestration.contracts import (
    COUNTERFACTUAL,
    CROSS_CASE_SIGNAL,
    NEXT_BEST_ACTION,
    VERIFICATION,
    SEVERITY_HIGH,
    CaseContext,
    CognitiveResult,
)

VERIFIER_ENGINE = "OutputVerifier"
VERIFIER_VERSION = "1.1"

# Types that are legitimately not evidence-grounded: a zero-knowledge cross-case
# alert withholds references by design, counterfactuals are simulations, and a
# next-best action is prescriptive rather than a claim about evidence.
NOT_EVIDENCE_GROUNDED = frozenset({
    VERIFICATION, CROSS_CASE_SIGNAL, COUNTERFACTUAL, NEXT_BEST_ACTION,
})

# Structured "terminal/sink" claims that the graph can deterministically refute.
_TERMINAL_CLAIM_RE = re.compile(
    r"final destination|final recipient|terminal account|sink account|"
    r"no further (?:transfer|movement|activity)|end of the (?:trail|chain)",
    re.IGNORECASE,
)


def _terminal_claim_conflicts(result: CognitiveResult, context: CaseContext) -> list[str]:
    """Refute a terminal/sink claim when the graph shows observed onward movement."""
    if not _TERMINAL_CLAIM_RE.search(f"{result.title} {result.description}"):
        return []

    # Index observed outgoing monetary edges by source entity value.
    outgoing: set[str] = set()
    for rel in context.relationships:
        if str(rel.get("epistemic_status", "")).upper() != "OBSERVED":
            continue
        if rel.get("relationship_type") != "TRANSFERRED_TO":
            continue
        source = rel.get("source_value")
        if source:
            outgoing.add(str(source))

    for ref in result.entity_refs:
        if str(ref) in outgoing:
            return ["TERMINAL_CLAIM_CONTRADICTED_BY_GRAPH"]
    return []


def _check_problems(result: CognitiveResult, context: CaseContext) -> list[tuple[str, str]]:
    """Deterministic, structured checks. Returns (code, reason) pairs.

    These verify a claim against the case's structured state — they never
    determine guilt or turn an analytical disagreement into a criminal
    conclusion.
    """
    known_evidence = {str(ef.get("id")) for ef in context.evidence_files}
    known_events = {str(ev.get("id")) for ev in context.events if ev.get("id")}
    known_entities: set[str] = set()
    for ent in context.entities:
        if ent.get("id"):
            known_entities.add(str(ent["id"]))
        if ent.get("canonical_value"):
            known_entities.add(str(ent["canonical_value"]))

    problems: list[tuple[str, str]] = []

    if not result.evidence_refs and not result.event_refs:
        problems.append((
            "UNGROUNDED_ASSERTION",
            "No evidence or event reference supports this claim.",
        ))

    unknown_evidence = [r for r in result.evidence_refs if str(r) not in known_evidence]
    if unknown_evidence:
        problems.append((
            "UNKNOWN_EVIDENCE_REFERENCE",
            f"Evidence references not present in the case: {unknown_evidence}.",
        ))

    unknown_events = [r for r in result.event_refs if str(r) not in known_events]
    if unknown_events:
        problems.append((
            "UNKNOWN_EVENT_REFERENCE",
            f"Event references not present in the case: {unknown_events}.",
        ))

    unknown_entities = [r for r in result.entity_refs if str(r) not in known_entities]
    if unknown_entities:
        problems.append((
            "UNKNOWN_ENTITY_REFERENCE",
            f"Entity references not present in the case graph: {unknown_entities}.",
        ))

    for code in _terminal_claim_conflicts(result, context):
        problems.append((
            code,
            "The observed case graph contains an outgoing relationship from the "
            "entity the claim describes as terminal.",
        ))

    return problems


def verify_results(
    context: CaseContext,
    results: list[CognitiveResult],
) -> list[CognitiveResult]:
    """Return VERIFICATION findings for any result that fails grounding."""
    flags: list[CognitiveResult] = []

    for result in results:
        if result.finding_type in NOT_EVIDENCE_GROUNDED:
            continue
        problems = _check_problems(result, context)
        if not problems:
            continue

        checks = [
            {"check": code, "result": "FAILED", "reason": reason}
            for code, reason in problems
        ]
        flags.append(CognitiveResult(
            finding_type=VERIFICATION,
            title=f"Verification flag — {result.finding_type}",
            description=(
                f"Claim '{result.title}' failed verification: "
                + "; ".join(reason for _, reason in problems)
            ),
            # A deterministic rule check is not a probability — do not present it
            # as calibrated confidence.
            confidence=None,
            severity=SEVERITY_HIGH,
            source_engine=VERIFIER_ENGINE,
            engine_version=VERIFIER_VERSION,
            entity_refs=list(result.entity_refs),
            event_refs=list(result.event_refs),
            evidence_refs=list(result.evidence_refs),
            component_scores={
                "flagged_finding_fingerprint": result.fingerprint(),
                "confidence_status": "RULE_BASED",
                "checks": checks,
            },
            reason_codes=[code for code, _ in problems],
            reasoning=(
                "The verifier checks structured claims against the case's evidence, "
                "events and graph. It flags unsupported or contradicted assertions; "
                "it does not determine guilt."
            ),
            citations=[{
                "claim": result.title,
                "check": code,
                "result": "FAILED",
                "reason": reason,
            } for code, reason in problems],
            dedup_key=f"verification:{result.fingerprint()}:{','.join(c for c, _ in problems)}",
        ))
    return flags
