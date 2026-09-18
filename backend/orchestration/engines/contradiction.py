from __future__ import annotations

"""
CyberDrishti AI — Contradiction Engine Adapter

Reference implementation of the EngineSpec contract: it converts a CaseContext
into the deterministic inputs cognitive.contradiction.scan_all expects, and maps
every returned LedgerFinding / TravelFinding into a provenance-carrying
CognitiveResult.

This is the first engine wired through the orchestrator; the remaining engines
attach the same way in Phase 3.
"""
from typing import Any

from cognitive import contradiction as engine
from orchestration.contracts import (
    CONTRADICTION,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    CognitiveResult,
    CaseContext,
    EngineSpec,
)

ENGINE_NAME = "ContradictionEngine"
ENGINE_VERSION = "2.0"


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ledger_rows(context: CaseContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in context.events_of_type("bank_txn"):
        meta = event.get("event_metadata") or {}
        if meta.get("balance") in (None, ""):
            continue
        rows.append({
            "credit":           _num(meta.get("credit")),
            "debit":            _num(meta.get("debit")),
            "balance":          _num(meta.get("balance")),
            "event_id":         event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
            "row_index":        len(rows),
        })
    return rows


def _travel_events(context: CaseContext) -> list[dict[str, Any]]:
    from cognitive.anomaly import resolve_coordinates

    events: list[dict[str, Any]] = []
    for event in context.events_of_type("call"):
        meta = event.get("event_metadata") or {}
        coords = resolve_coordinates(meta)
        if not coords:
            continue
        events.append({
            "entity":           meta.get("caller") or "?",
            "timestamp":        event.get("event_timestamp") or "",
            "lat":              coords[0],
            "lon":              coords[1],
            "source":           meta.get("cell_id") or "call",
            "event_id":         event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
        })

    for event in context.events_of_type("location_timeline"):
        meta = event.get("event_metadata") or {}
        coords = resolve_coordinates(meta)
        if not coords:
            continue
        events.append({
            "entity":           meta.get("phone") or "?",
            "timestamp":        event.get("event_timestamp") or "",
            "lat":              coords[0],
            "lon":              coords[1],
            "source":           meta.get("cell_tower") or meta.get("city") or "location_timeline",
            "event_id":         event.get("id"),
            "evidence_file_id": event.get("evidence_file_id"),
        })
    return events


def applies(context: CaseContext) -> bool:
    return bool(_ledger_rows(context)) or bool(_travel_events(context))


def run(context: CaseContext) -> list[CognitiveResult]:
    ledger_rows = _ledger_rows(context)
    travel_events = _travel_events(context)
    report = engine.scan_all(ledger_rows, travel_events, ordering_events=[], ordering_rules=[])
    findings = report.get("findings", {})
    results: list[CognitiveResult] = []

    for finding in findings.get("ledger", []):
        row = ledger_rows[finding.row_index] if 0 <= finding.row_index < len(ledger_rows) else None
        event_refs = [row["event_id"]] if row and row.get("event_id") else []
        evidence_refs = [row["evidence_file_id"]] if row and row.get("evidence_file_id") else []
        results.append(CognitiveResult(
            finding_type=CONTRADICTION,
            title=f"Ledger balance inconsistency ({finding.kind})",
            description=finding.explanation,
            confidence=0.98,
            severity=SEVERITY_CRITICAL if finding.kind == "ALTERED_BALANCE" else SEVERITY_HIGH,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            event_refs=event_refs,
            evidence_refs=evidence_refs,
            component_scores={
                "row_index": finding.row_index,
                "expected_balance": finding.expected_balance,
                "reported_balance": finding.reported_balance,
                "discrepancy": finding.discrepancy,
            },
            reason_codes=[finding.kind, "ledger_arithmetic"],
            reasoning="Per-row ledger arithmetic derived from observed statement rows.",
            citations=[{
                "row_index": finding.row_index,
                "expected_balance": finding.expected_balance,
                "reported_balance": finding.reported_balance,
            }],
            dedup_key=f"contradiction:ledger:{event_refs[0] if event_refs else finding.row_index}:{finding.kind}",
        ))

    for finding in findings.get("travel", []):
        event_a, event_b = finding.event_a, finding.event_b
        event_refs = [x for x in (event_a.get("event_id"), event_b.get("event_id")) if x]
        evidence_refs = [x for x in (event_a.get("evidence_file_id"), event_b.get("evidence_file_id")) if x]
        results.append(CognitiveResult(
            finding_type=CONTRADICTION,
            title=f"{finding.kind.replace('_', ' ').title()} — {finding.entity}",
            description=finding.explanation,
            confidence=0.90,
            severity=SEVERITY_CRITICAL if finding.kind == "IMPOSSIBLE_TRAVEL" else SEVERITY_HIGH,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            entity_refs=[finding.entity],
            event_refs=list(dict.fromkeys(event_refs)),
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            component_scores={
                "velocity_kmh": finding.velocity_kmh,
                "distance_km": finding.distance_km,
                "time_gap_s": finding.time_gap_s,
            },
            reason_codes=[finding.kind, "tower_derived_location"],
            reasoning="Tower/city-derived location delta yields a physically implausible velocity.",
            citations=[{
                "entity": finding.entity,
                "distance_km": finding.distance_km,
                "velocity_kmh": finding.velocity_kmh,
            }],
            dedup_key=(
                f"contradiction:travel:{finding.entity}:"
                f"{event_a.get('event_id')}:{event_b.get('event_id')}:{finding.kind}"
            ),
        ))

    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Ledger arithmetic audit + impossible-travel detection.",
    applicability=applies,
    requires_event_types=frozenset({"bank_txn", "call", "location_timeline"}),
)
