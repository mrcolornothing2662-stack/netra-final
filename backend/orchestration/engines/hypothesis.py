from __future__ import annotations

"""
Hypothesis Engine Adapter (ACH & GraphRAG Evidence Grounding)

Ranks competing hypotheses against the shared evidence under Heuer's ACH discipline:
  • Emits a HYPOTHESIS finding for the leading hypothesis carrying the full evidence matrix
    and refuting indicators.
  • Emits an UNCERTAINTY finding when unobserved indicators mean the evidence cannot
    yet distinguish the hypotheses.

Posteriors stay uncalibrated by design (R v T [2010] EWCA Crim 2439): the finding
carries the rank and the refuting evidence, never a fabricated percentage.
"""
from datetime import datetime

from cognitive import data_path
from cognitive.hypothesis import evaluate, load_model
from orchestration.contracts import (
    HYPOTHESIS,
    UNCERTAINTY,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "HypothesisEngine"
ENGINE_VERSION = "2.0"


def _bank_rows(context: CaseContext) -> list[dict]:
    rows = []
    for event in context.events_of_type("bank_txn"):
        meta = event.get("event_metadata") or event.get("metadata") or {}
        rows.append({
            "credit": float(meta.get("credit") or 0.0),
            "debit": float(meta.get("debit") or 0.0),
            "amount": float(meta.get("amount") or meta.get("amount_inr") or 0.0),
            "timestamp": event.get("event_timestamp"),
            "evidence_file_id": event.get("evidence_file_id"),
            "event_id": event.get("id"),
        })
    return rows


def _build_observations(context: CaseContext) -> tuple[dict[str, float], dict[str, dict]]:
    observations: dict[str, float] = {}
    provenance: dict[str, dict] = {}

    # 1. Inbound victim calls (CDR)
    call_events = context.events_of_type("call")
    if call_events:
        callers = {(e.get("event_metadata") or e.get("metadata") or {}).get("caller") for e in call_events}
        victim_count = float(len({c for c in callers if c}))
        observations["inbound_victim_calls"] = victim_count
        first_call = call_events[0]
        provenance["victim_contact"] = {
            "source_file": first_call.get("source_file") or "04_call_detail_record.csv",
            "source_line": first_call.get("source_line") or 1,
            "event_type": "call",
            "sample_text": f"Aggregated {len(call_events)} calls from {int(victim_count)} distinct callers.",
        }

    # 2. Bank events
    rows = _bank_rows(context)
    if rows:
        credits = [r for r in rows if r["credit"] > 0]
        debits = [r for r in rows if r["debit"] > 0]
        if credits and debits and credits[0]["timestamp"] and debits[0]["timestamp"]:
            try:
                t_credit = datetime.fromisoformat(str(credits[0]["timestamp"]).replace("Z", "+00:00"))
                t_debit = datetime.fromisoformat(str(debits[0]["timestamp"]).replace("Z", "+00:00"))
                velocity = abs((t_debit - t_credit).total_seconds()) / 60.0
                observations["velocity_minutes"] = max(round(velocity, 1), 1.0)
                observations["pass_through_velocity_minutes"] = observations["velocity_minutes"]
                provenance["pass_through_speed"] = {
                    "source_file": "bank_statement.csv",
                    "source_line": 1,
                    "event_type": "bank_txn",
                    "sample_text": f"Rapid debit occurred {velocity:.1f}m after initial credit.",
                }
            except (ValueError, TypeError):
                pass

        total_turnover = sum(r["credit"] + r["debit"] + r["amount"] for r in rows)
        if total_turnover > 0:
            observations["turnover_volume_inr"] = total_turnover
            provenance["turnover_scale"] = {
                "source_file": "bank_statement.csv",
                "source_line": 1,
                "event_type": "bank_txn",
                "sample_text": f"Aggregated transaction turnover of ₹{total_turnover:,.2f}",
            }

        # Timestamps span
        ts_list = []
        for r in rows:
            if r["timestamp"]:
                try:
                    ts_list.append(datetime.fromisoformat(str(r["timestamp"]).replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    pass
        if ts_list:
            ts_list.sort()
            span = max((ts_list[-1] - ts_list[0]).total_seconds() / 86400.0, 1.0)
            observations["account_age_days"] = round(span, 1)
            provenance["account_age"] = {
                "source_file": "bank_statement.csv",
                "source_line": 1,
                "event_type": "bank_txn",
                "sample_text": f"Observed account activity across {span:.1f} days.",
            }

            if len(ts_list) >= 3:
                gaps = [(ts_list[i] - ts_list[i - 1]).total_seconds() / 86400.0 for i in range(1, len(ts_list))]
                max_gap = max(gaps)
                observations["dormancy_before_crime_days"] = round(max_gap, 1)
                provenance["dormancy"] = {
                    "source_file": "bank_statement.csv",
                    "source_line": 1,
                    "event_type": "bank_txn",
                    "sample_text": f"Dormancy gap of {max_gap:.1f} days between activity bursts.",
                }

    # 3. Network log events
    net_events = context.events_of_type("network_log")
    if net_events:
        ip_device_set = set()
        for ev in net_events:
            meta = ev.get("event_metadata") or ev.get("metadata") or {}
            ip = meta.get("ip") or meta.get("ip_address")
            imei = meta.get("imei")
            if ip:
                ip_device_set.add(f"IP:{ip}")
            if imei:
                ip_device_set.add(f"IMEI:{imei}")
        if ip_device_set:
            observations["device_sharing_count"] = float(len(ip_device_set))
            provenance["device_dispersion"] = {
                "source_file": "08_network_log.csv",
                "source_line": 1,
                "event_type": "network_log",
                "sample_text": f"Associated with {len(ip_device_set)} distinct network/device identifiers.",
            }

    return observations, provenance


def _evidence(context: CaseContext) -> tuple[list[str], list[str]]:
    events = context.events_of_type("bank_txn", "call", "network_log")
    event_refs = [str(e["id"]) for e in events]
    evidence_refs = [str(e["evidence_file_id"]) for e in events if e.get("evidence_file_id")]
    return list(dict.fromkeys(event_refs)), list(dict.fromkeys(evidence_refs))


def applies(context: CaseContext) -> bool:
    obs, _ = _build_observations(context)
    return bool(obs)


def run(context: CaseContext) -> list[CognitiveResult]:
    observations, provenance = _build_observations(context)
    if not observations:
        return []

    model = load_model(data_path("hypotheses.json"))
    assessment = evaluate(observations, model, provenance_map=provenance)

    ranked = assessment.get("ranked_labels") or []
    hypotheses = assessment.get("hypotheses") or []
    if not hypotheses:
        return []

    leading = hypotheses[0]
    event_refs, evidence_refs = _evidence(context)
    display_label = assessment.get("display_label") or "Rule-based hypothesis ranking."

    results = [
        CognitiveResult(
            finding_type=HYPOTHESIS,
            title=f"Leading hypothesis — {leading['label']}",
            description=(
                f"Ranked {len(hypotheses)} competing hypotheses against "
                f"{len(assessment.get('evidence_matrix') or [])} observed indicator(s)."
            ),
            confidence=None,  # rule-based ranking, not a calibrated probability
            severity=SEVERITY_MEDIUM,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            event_refs=event_refs,
            evidence_refs=evidence_refs,
            component_scores={
                "ranked_labels": ranked,
                "observations": observations,
                "diagnostic_indicators": len(assessment.get("evidence_matrix") or []),
                "leading_hypothesis": leading["label"],
                "inconsistency_score": leading.get("inconsistency_score", 0.0),
            },
            reason_codes=[assessment.get("assessment_type", "RULE_BASED_ASSESSMENT"), "ACH", f"ROLE:{leading['label']}"],
            reasoning=display_label,
            citations=assessment.get("evidence_matrix") or [],
            observed_at=None,
            dedup_key="hypothesis:leading",
        )
    ]

    unobserved = assessment.get("unobserved_indicators") or []
    if unobserved:
        results.append(
            CognitiveResult(
                finding_type=UNCERTAINTY,
                title="Hypothesis assessment incomplete — unobserved indicators",
                description=(
                    "The evidence cannot yet definitively distinguish all hypotheses. Missing "
                    "indicators: " + ", ".join(unobserved) + "."
                ),
                confidence=None,
                severity=SEVERITY_MEDIUM,
                source_engine="UncertaintyEngine",
                engine_version=ENGINE_VERSION,
                event_refs=event_refs,
                evidence_refs=evidence_refs,
                component_scores={"unobserved_count": len(unobserved)},
                reason_codes=["UNOBSERVED_INDICATORS"] + list(unobserved),
                reasoning=(
                    "Conformal-style abstention: additional statutory evidence is required before a "
                    "hypothesis can be conclusively preferred."
                ),
                citations=assessment.get("unobserved_details") or [],
                dedup_key="uncertainty:hypothesis-indicators",
            )
        )
    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Competing-hypothesis (ACH) assessment + uncertainty abstention.",
    applicability=applies,
    skip_reason="no_observable_indicators",
)
