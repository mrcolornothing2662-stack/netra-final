from __future__ import annotations

"""
MO Fingerprinting Adapter (Feature 07 — Crime Script Matcher)

Mines case communications and multi-modal evidence into a behavioural stage sequence
and matches it against the crime-script playbooks. Only confident matches become
findings, and each finding cites the exact evidence lines, event IDs, and files.
"""
from typing import Any

from cognitive import data_path
from cognitive.mo import classify_case_evidence, load_playbooks
from orchestration.contracts import (
    MO_MATCH,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "MOEngine"
ENGINE_VERSION = "2.0"

COMMUNICATION_EVENTS = frozenset({"whatsapp_msg", "chat", "sms", "document_text", "text_record"})
MULTI_MODAL_EVENTS = frozenset({"bank_txn", "transaction", "call", "network_log"}) | COMMUNICATION_EVENTS


def applies(context: CaseContext) -> bool:
    """Trigger when any multi-modal evidence is present (communications, financial, CDR, network)."""
    return context.has_event_type(*MULTI_MODAL_EVENTS)


def run(context: CaseContext) -> list[CognitiveResult]:
    evidence_items = []
    line_to_event: dict[int, dict] = {}

    def _event_key(ev: dict) -> tuple:
        ts = str(ev.get("event_timestamp") or "")
        return (0, ts) if ts else (1, str(ev.get("id") or ""))

    # Sort all events chronologically so the behavioural trace reflects actual timeline
    ordered_events = sorted(context.events, key=_event_key)

    for idx, event in enumerate(ordered_events, start=1):
        etype = event.get("event_type")
        meta = event.get("event_metadata") or {}
        fid = str(event.get("evidence_file_id") or "")

        if etype in COMMUNICATION_EVENTS:
            evidence_items.append({
                "type": etype,
                "line_no": idx,
                "event_id": str(event.get("id") or ""),
                "evidence_file_id": fid,
                "sender": meta.get("sender") or "?",
                "text": event.get("text_content") or "",
                "timestamp": str(event.get("event_timestamp") or ""),
                "filename": meta.get("filename") or "",
            })
            line_to_event[idx] = event
        elif etype in ("bank_txn", "transaction"):
            evidence_items.append({
                "type": "bank_txn",
                "line_no": idx,
                "event_id": str(event.get("id") or ""),
                "evidence_file_id": fid,
                "narration": meta.get("narration") or meta.get("description") or event.get("text_content") or "",
                "amount": meta.get("amount"),
                "from_account": meta.get("from_account"),
                "to_account": meta.get("to_account"),
                "timestamp": str(event.get("event_timestamp") or ""),
                "filename": meta.get("filename") or "",
            })
            line_to_event[idx] = event
        elif etype == "call":
            evidence_items.append({
                "type": "call",
                "line_no": idx,
                "event_id": str(event.get("id") or ""),
                "evidence_file_id": fid,
                "caller": meta.get("caller") or "",
                "callee": meta.get("callee") or "",
                "duration_sec": meta.get("duration") or meta.get("duration_sec"),
                "timestamp": str(event.get("event_timestamp") or ""),
                "filename": meta.get("filename") or "",
            })
            line_to_event[idx] = event

    playbooks = load_playbooks(data_path("playbooks.json"))
    result = classify_case_evidence(evidence_items, playbooks)
    best = result.get("best_match")
    if result.get("verdict") != "MATCHED" or not best:
        return []

    similarity = float(best.get("similarity") or 0.0)
    trace = best.get("trace_evidence") or []
    event_refs: list[str] = []
    evidence_refs: list[str] = []
    senders: list[str] = []
    citations: list[dict[str, Any]] = []

    for hit in trace:
        line_no = int(hit.get("line_no") or 0)
        event = line_to_event.get(line_no)
        ev_id = str(event["id"]) if event else str(hit.get("event_id") or "")
        f_id = str(event.get("evidence_file_id")) if event and event.get("evidence_file_id") else str(hit.get("evidence_file_id") or "")

        if ev_id:
            event_refs.append(ev_id)
        if f_id:
            evidence_refs.append(f_id)

        sender = hit.get("sender")
        if sender and not str(sender).startswith("__") and str(sender) != "?":
            senders.append(str(sender))

        citations.append({
            "line_no": line_no,
            "stage": hit.get("stage"),
            "event_id": ev_id,
            "evidence_file_id": f_id,
            "matched_text": hit.get("matched_text"),
            "source_type": hit.get("source_type"),
        })

    return [CognitiveResult(
        finding_type=MO_MATCH,
        title=f"MO match — {best['playbook']}",
        description=(
            f"Behavioural sequence matches playbook '{best['playbook']}' "
            f"(similarity {round(similarity * 100)}%). Screening aid, not attribution."
        ),
        confidence=similarity,
        severity=SEVERITY_HIGH if similarity >= 0.8 else SEVERITY_MEDIUM,
        source_engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        entity_refs=list(dict.fromkeys(senders)),
        event_refs=list(dict.fromkeys(event_refs)),
        evidence_refs=list(dict.fromkeys(evidence_refs)),
        component_scores={
            "similarity": similarity,
            "levenshtein_distance": best.get("levenshtein_distance", 0),
            "coverage_ratio": best.get("coverage_ratio", 0.0),
            "observed_sequence": best.get("observed_sequence") or [],
            "playbook_sequence": [a.get("stage") for a in (best.get("alignment") or []) if a.get("in_playbook")],
            "calculation_breakdown": best.get("calculation_breakdown", {}),
        },
        reason_codes=["MO_MATCH", f"PLAYBOOK:{best['playbook']}", "BEHAVIORAL_SEQUENCE"],
        reasoning=result.get("note", ""),
        citations=citations,
        dedup_key=f"mo:{best['playbook']}",
    )]


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Crime-script (MO) behavioural sequence matching across multi-modal evidence.",
    applicability=applies,
    requires_event_types=MULTI_MODAL_EVENTS,
    skip_reason="no_relevant_evidence",
)
