from __future__ import annotations

"""
CyberDrishti AI — Behavioral Anomaly Engine Adapter (Feature 02)

Adapter implementing the EngineSpec contract: converts CaseContext into the
deterministic inputs expected by cognitive.anomaly.scan_behavioral_anomalies,
and maps every returned AnomalyFinding into a provenance-carrying CognitiveResult
of type BEHAVIORAL_ANOMALY.
"""
from typing import Any

from cognitive import anomaly as engine
from orchestration.contracts import (
    BEHAVIORAL_ANOMALY,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    CognitiveResult,
    CaseContext,
    EngineSpec,
)

ENGINE_NAME = "BehavioralAnomalyEngine"
ENGINE_VERSION = "1.0"


def _bank_events(context: CaseContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in context.events_of_type("bank_txn"):
        meta = event.get("event_metadata") or {}
        rows.append({
            "id": event.get("id"),
            "event_id": event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
            "timestamp": event.get("event_timestamp"),
            "metadata": meta,
        })
    return rows


def _call_events(context: CaseContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in context.events_of_type("call"):
        meta = event.get("event_metadata") or {}
        rows.append({
            "id": event.get("id"),
            "event_id": event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
            "timestamp": event.get("event_timestamp"),
            "metadata": meta,
        })
    return rows


def _location_events(context: CaseContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in context.events_of_type("location_timeline"):
        meta = event.get("event_metadata") or {}
        rows.append({
            "id": event.get("id"),
            "event_id": event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
            "timestamp": event.get("event_timestamp"),
            "metadata": meta,
        })
    return rows


def applies(context: CaseContext) -> bool:
    return bool(_bank_events(context)) or bool(_call_events(context)) or bool(_location_events(context))


def run(context: CaseContext) -> list[CognitiveResult]:
    bank_evs = _bank_events(context)
    call_evs = _call_events(context)
    loc_evs = _location_events(context)

    scan_res = engine.scan_behavioral_anomalies(bank_evs, call_evs, loc_evs)
    raw_findings = scan_res.get("findings", [])
    results: list[CognitiveResult] = []

    for f in raw_findings:
        sev = f.get("severity", SEVERITY_MEDIUM)
        event_refs = [str(x) for x in f.get("event_refs", []) if x]
        evidence_refs = [str(x) for x in f.get("evidence_refs", []) if x]

        results.append(CognitiveResult(
            finding_type=BEHAVIORAL_ANOMALY,
            title=f.get("title", "Behavioral Anomaly"),
            description=f.get("description", ""),
            confidence=f.get("confidence", 0.85),
            severity=sev,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            entity_refs=[f["entity"]] if f.get("entity") else [],
            event_refs=list(dict.fromkeys(event_refs)),
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            component_scores=f.get("component_scores", {}),
            reason_codes=f.get("reason_codes", []),
            reasoning=f.get("reasoning", ""),
            citations=f.get("citations", []),
            dedup_key=(
                f"anomaly:{f.get('anomaly_type')}:{f.get('entity')}:"
                f"{':'.join(event_refs[:2]) if event_refs else 'single'}"
            ),
        ))

    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Statistical entity baseline profiling & behavioral anomaly detection.",
    applicability=applies,
    requires_event_types=frozenset({"bank_txn", "call", "location_timeline"}),
)
