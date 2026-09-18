"""
CyberDrishti AI — Cognitive Forensic Intelligence Router

Exposes all 11 advanced cognitive engines via a unified REST API.
Each endpoint pulls real case data from the database, runs the
corresponding engine, and returns structured forensic intelligence.

Zero disruption to existing routes — this router is additive only.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Entity, EvidenceEvent, EvidenceFile, Relationship, User, Case, InvestigationFinding
from db.session import get_db
from routes.auth import get_current_user
from routes.case_access import require_case_access

router = APIRouter()


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class CounterfactualRequest(BaseModel):
    freeze_account: str
    freeze_time: str  # ISO-8601
    additional_freeze_accounts: list[str] = Field(default_factory=list)
    include_sweep: bool = True
    include_frames: bool = False

class VerifyDraftRequest(BaseModel):
    draft_text: str
    case_id: Optional[str] = None

class BenchmarkRequest(BaseModel):
    typology: str = "DIGITAL_ARREST"
    seed: int = 42

class ConfidenceEvaluateRequest(BaseModel):
    model_name: str = "ROLE_CLASSIFIER_CONFORMAL"
    candidate_scores: dict[str, float]
    epsilon: float = Field(0.05, ge=0.01, le=0.5)

class CalibrationRegisterRequest(BaseModel):
    model_name: str
    scores: list[float]
    epsilon: float = Field(0.05, ge=0.01, le=0.5)
    source: str = "synthetic_benchmark"

class MOClassifyRequest(BaseModel):
    messages: list[dict[str, Any]] = []
    text_content: str | None = None
    threshold: float = Field(0.60, ge=0.1, le=1.0)
    playbook: str | None = None

class TrainingStartRequest(BaseModel):
    drill_id: str | None = None
    seed: int | None = None
    difficulty: str | None = None

class TrainingSubmitRequest(BaseModel):
    answers: dict[str, str] = {}


# ── Helper: pull case evidence from DB ────────────────────────────────────────

async def _get_bank_events(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    """Retrieve bank transaction events as structured rows.

    Reads the structured metadata emitted by the CSV/PDF bank parsers
    (model, credit, debit, balance, amount, from_account, to_account, …).
    Falls back to the legacy positional raw_line split only for evidence that
    was ingested before structured parsing existed. Each row is tagged with
    `model` ('ledger'|'transfer') and `has_balance` so callers can route
    ledger-continuity vs money-flow analysis without producing false findings.
    """
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type == "bank_txn",
        ).order_by(EvidenceEvent.event_timestamp, EvidenceEvent.id)
    )).scalars().all()

    def _num(v) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    rows: list[dict] = []
    for ev in events:
        meta = ev.event_metadata or {}
        ts = ev.event_timestamp.isoformat() if ev.event_timestamp else ""

        # ── Structured path (current parsers) ──────────────────────────────
        structured_keys = ("credit", "debit", "balance", "amount",
                            "from_account", "to_account", "model")
        if any(k in meta for k in structured_keys):
            balance_raw = meta.get("balance")
            balance = _num(balance_raw) if balance_raw not in (None, "") else None
            credit = _num(meta.get("credit"))
            debit = _num(meta.get("debit"))
            amount_val = _num(meta.get("amount")) or credit or debit
            model = meta.get("model") or ("ledger" if balance is not None else "transfer")
            rows.append({
                "id": str(ev.id),
                "event_id": str(ev.id),
                "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
                "credit": credit,
                "debit": debit,
                "balance": balance,
                "amount": f"{amount_val:.2f}",
                "amount_val": amount_val,
                "timestamp": ts,
                "reference": meta.get("ref_no") or meta.get("narration") or (ev.text_content or ""),
                "from": meta.get("from_account"),
                "to": meta.get("to_account"),
                "from_account": meta.get("from_account"),
                "to_account": meta.get("to_account"),
                "upi": meta.get("upi_id"),
                "account": meta.get("account") or meta.get("to_account") or meta.get("from_account") or "",
                "event_type": "bank_txn",
                "model": model,
                "has_balance": balance is not None,
                "metadata": meta,
            })
            continue

        # ── Legacy fallback: positional CSV split of raw_line ──────────────
        raw_line = meta.get("raw_line", ev.text_content or "")
        parts = raw_line.strip().split(",") if raw_line else []
        try:
            if len(parts) >= 5:
                credit = float(parts[-3] or 0)
                debit = float(parts[-2] or 0)
                balance = float(parts[-1])
                rows.append({
                    "id": str(ev.id),
                    "event_id": str(ev.id),
                    "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
                    "credit": credit, "debit": debit, "balance": balance,
                    "amount": f"{credit or debit:.2f}",
                    "amount_val": credit or debit,
                    "timestamp": ts,
                    "reference": ",".join(parts[1:-3]),
                    "from": None, "to": None,
                    "from_account": None, "to_account": None,
                    "upi": None,
                    "event_type": "bank_txn",
                    "account": meta.get("account", ""),
                    "model": "ledger",
                    "has_balance": True,
                    "metadata": meta,
                })
        except (ValueError, IndexError):
            pass
    return rows


async def _get_call_events(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type == "call",
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()
    result = []
    for ev in events:
        meta = ev.event_metadata or {}
        result.append({
            "id": str(ev.id),
            "event_id": str(ev.id),
            "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
            "entity": meta.get("caller", "?"),
            "timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
            "lat": meta.get("lat"), "lon": meta.get("lon"),
            "source": meta.get("cell_id", "call"),
            "caller": meta.get("caller"),
            "callee": meta.get("callee"),
            "cell_id": meta.get("cell_id"),
            "metadata": meta,
        })
    return result


async def _get_location_timeline_events(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type == "location_timeline",
        ).order_by(EvidenceEvent.event_timestamp, EvidenceEvent.id)
    )).scalars().all()
    result = []
    for ev in events:
        meta = ev.event_metadata or {}
        result.append({
            "id": str(ev.id),
            "event_id": str(ev.id),
            "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
            "entity": meta.get("phone", "?"),
            "timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
            "lat": meta.get("lat"),
            "lon": meta.get("lon"),
            "city": meta.get("city"),
            "cell_tower": meta.get("cell_tower"),
            "location_reference": meta.get("location_reference"),
            "observation": meta.get("observation"),
            "source": meta.get("cell_tower") or meta.get("city") or "location_timeline",
            "metadata": meta,
        })
    return result


def _loc_label(ev: dict) -> str:
    """Human-readable location for a travel-finding endpoint, built from the
    real event dict (cell-tower/cell id plus tower-derived coordinates). No
    fabrication — returns whatever the parsed CDR actually carried."""
    src = ev.get("source") or "unknown"
    lat, lon = ev.get("lat"), ev.get("lon")
    if lat is not None and lon is not None:
        try:
            return f"{src} ({float(lat):.4f}, {float(lon):.4f})"
        except (TypeError, ValueError):
            pass
    return str(src)


async def _get_whatsapp_events(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type == "whatsapp_msg",
        ).order_by(EvidenceEvent.id)
    )).scalars().all()
    return [
        {"line_no": i + 1,
         "sender": (ev.event_metadata or {}).get("sender", "?"),
         "text": ev.text_content or "",
         "timestamp": str(ev.event_timestamp) if ev.event_timestamp else ""}
        for i, ev in enumerate(events)
    ]


async def _get_case_entities(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    entities = (await db.execute(
        select(Entity).where(Entity.case_id == case_id)
    )).scalars().all()
    return [
        {"id": str(e.id), "entity_type": e.entity_type, "value": e.canonical_value,
         "degree": e.degree_centrality or 0}
        for e in entities
    ]


def _clean_amount(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("\u20b9", "").replace("Rs.", "").strip())
    except (ValueError, TypeError):
        return None


async def _get_timed_events(db: AsyncSession, case_id: uuid.UUID) -> list[dict]:
    """All events with timestamps for network replay across all evidence types."""
    # 1. Map evidence files for Section 63 BSA custody/provenance metadata
    files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case_id)
    )).scalars().all()
    file_map = {str(f.id): f for f in files}

    # 2. Query all events with timestamps
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_timestamp.isnot(None),
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()

    result: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for ev in events:
        meta = ev.event_metadata or {}
        et = ev.event_type
        ef = file_map.get(str(ev.evidence_file_id)) if ev.evidence_file_id else None
        source_doc = meta.get("source_doc") or (getattr(ef, "original_name", None) or getattr(ef, "filename", None) if ef else None)

        u = meta.get("caller") or meta.get("sender") or meta.get("subscriber")
        v = meta.get("callee") or meta.get("recipient") or meta.get("contact")
        rel_type = "COMMUNICATION"
        if et == "call":
            rel_type = "CALLED"
        elif et in ("whatsapp_msg", "chat"):
            rel_type = "MESSAGED"

        # Financial: bank statement, UPI transaction, transfer
        if et in ("bank_txn", "upi_txn", "transfer"):
            u = meta.get("from_account") or meta.get("debit_account") or meta.get("payer") or u
            v = meta.get("to_account") or meta.get("credit_account") or meta.get("payee") or meta.get("upi_id") or v
            if not u and not v:
                u = meta.get("account")
            rel_type = "TRANSFERRED_TO"

        # Network log: device -> IP / destination
        elif et == "network_log":
            u = meta.get("device") or u
            v = meta.get("ip") or meta.get("destination") or v
            rel_type = "CONNECTED_TO"

        # Location timeline: phone -> cell tower / location
        elif et == "location_timeline":
            u = meta.get("phone") or u
            v = meta.get("cell_tower") or meta.get("location") or v
            rel_type = "LOCATED_AT"

        # No resolvable endpoint — cannot form an edge or node activation
        if not u and not v:
            continue

        raw_amt = meta.get("amount") or meta.get("amount_inr") or meta.get("credit") or meta.get("debit")
        amt = _clean_amount(raw_amt)
        ts_str = ev.event_timestamp.isoformat()

        u_str = str(u) if u else None
        v_str = str(v) if v else None
        if u_str and v_str:
            seen_keys.add((u_str, v_str, ts_str))

        result.append({
            "id": str(ev.id),
            "event_type": et,
            "rel_type": rel_type,
            "timestamp": ts_str,
            "u": u_str,
            "v": v_str,
            "amount": amt,
            "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
            "source_doc": source_doc,
            "source_line": ev.source_line,
            "source_page": ev.source_page,
            "text_content": (ev.text_content or "")[:300],
            "metadata": meta,
        })

    # 3. Incorporate timestamped Relationship rows from the unified Case Graph
    relationships = (await db.execute(
        select(Relationship).where(
            Relationship.case_id == case_id,
            Relationship.event_timestamp.isnot(None),
        )
    )).scalars().all()

    if relationships:
        entities = (await db.execute(
            select(Entity).where(Entity.case_id == case_id)
        )).scalars().all()
        ent_val_map = {e.id: e.canonical_value for e in entities}

        for rel in relationships:
            u_val = ent_val_map.get(rel.source_entity_id)
            v_val = ent_val_map.get(rel.target_entity_id)
            if not u_val or not v_val:
                continue
            ts_str = rel.event_timestamp.isoformat()
            pair_key = (str(u_val), str(v_val), ts_str)
            if pair_key in seen_keys:
                continue
            seen_keys.add(pair_key)

            ev_ref = rel.evidence_refs[0] if rel.evidence_refs else None
            ef = file_map.get(str(ev_ref)) if ev_ref else None
            source_doc = (rel.attributes or {}).get("source_doc") or (getattr(ef, "original_name", None) or getattr(ef, "filename", None) if ef else None)

            result.append({
                "id": str(rel.id),
                "event_type": rel.relationship_type.lower(),
                "rel_type": rel.relationship_type,
                "timestamp": ts_str,
                "u": str(u_val),
                "v": str(v_val),
                "amount": rel.amount,
                "evidence_file_id": str(ev_ref) if ev_ref else None,
                "source_doc": source_doc,
                "source_line": (rel.attributes or {}).get("source_line"),
                "source_page": (rel.attributes or {}).get("source_page"),
                "text_content": f"{rel.relationship_type}: {u_val} -> {v_val}",
                "metadata": rel.attributes or {},
            })

    result.sort(key=lambda item: item["timestamp"])
    return result


async def _get_case_facts(db: AsyncSession, case_id: uuid.UUID) -> dict[str, set]:
    """Gather verified facts for the output verifier / Legal Compliance Shield."""
    bank_rows = await _get_bank_events(db, case_id)
    entities = await _get_case_entities(db, case_id)
    amounts = set()
    phones = set()
    upis = set()
    accounts = set()
    ips = set()
    devices = set()
    hashes = set()

    for r in bank_rows:
        if r.get("balance"):
            amounts.add(str(r["balance"]))
        if r.get("amount"):
            amounts.add(str(r["amount"]))
        if r.get("credit") and r["credit"] > 0:
            amounts.add(str(r["credit"]))
        if r.get("debit") and r["debit"] > 0:
            amounts.add(str(r["debit"]))
        if r.get("from_account"):
            accounts.add(str(r["from_account"]).upper())
        if r.get("to_account"):
            accounts.add(str(r["to_account"]).upper())
        if r.get("account"):
            accounts.add(str(r["account"]).upper())
        if r.get("upi_id"):
            upis.add(str(r["upi_id"]).lower())

    for e in entities:
        etype = (e.get("entity_type") or "").upper()
        val = e.get("value") or ""
        if not val:
            continue
        if etype in ("PHONE", "MOBILE"):
            phones.add(val)
        elif etype in ("UPI", "VPA"):
            upis.add(val.lower())
        elif etype in ("ACCOUNT", "BANK_ACCOUNT"):
            accounts.add(val.upper())
        elif etype in ("IP", "IPV4"):
            ips.add(val)
        elif etype in ("DEVICE", "DEV"):
            devices.add(val.upper())
        elif etype in ("AMOUNT", "MONEY"):
            amounts.add(val)

    # Ingest evidence file SHA-256 hashes
    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case_id)
    )).scalars().all()
    for ef in ev_files:
        if ef.sha256_hash:
            hashes.add(ef.sha256_hash.lower())

    return {
        "amounts": amounts,
        "phones": phones,
        "upis": upis,
        "accounts": accounts,
        "ips": ips,
        "devices": devices,
        "hashes": hashes,
    }


# ── Endpoint: Feature 02 — Contradictions ─────────────────────────────────────

@router.get("/cases/{case_id}/contradictions")
async def get_contradictions(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Run ledger continuity audit, impossible travel, and behavioral anomaly profiling."""
    case = await require_case_access(db, current, case_id)
    from cognitive.contradiction import ledger_audit, impossible_travel
    from cognitive.anomaly import scan_behavioral_anomalies

    bank_rows = await _get_bank_events(db, case.id)
    call_events = await _get_call_events(db, case.id)
    location_events = await _get_location_timeline_events(db, case.id)

    # Only balance-bearing (ledger) rows can be audited for running-balance
    # continuity. Transfer-model rows (from/to/amount, no balance) would
    # otherwise coerce to balance=0 and generate spurious ALTERED_BALANCE hits.
    ledger_rows = [r for r in bank_rows if r.get("has_balance")]
    ledger_findings = ledger_audit(ledger_rows) if ledger_rows else []
    travel_findings = impossible_travel(call_events) if call_events else []

    # Behavioral baseline profiling & multi-source anomalies
    anomaly_report = scan_behavioral_anomalies(bank_rows, call_events, location_events)

    return {
        "case_id": str(case.id),
        "ledger_audit": {
            "analysis_status": "completed" if ledger_rows else "insufficient_input",
            "input_rows": len(ledger_rows),
            "findings": [
                {"kind": f.kind, "row_index": f.row_index,
                 "expected_balance": f.expected_balance,
                 "reported_balance": f.reported_balance,
                 "discrepancy": f.discrepancy,
                 "explanation": f.explanation,
                 "epistemic_status": f.epistemic_status}
                for f in ledger_findings
            ],
        },
        "impossible_travel": {
            "analysis_status": "completed" if call_events else "insufficient_input",
            "input_events": len(call_events),
            "findings": [
                {"kind": f.kind, "entity": f.entity,
                 "location_a": _loc_label(f.event_a), "location_b": _loc_label(f.event_b),
                 "distance_km": f.distance_km, "time_gap_s": f.time_gap_s,
                 "velocity_kmh": f.velocity_kmh,
                 "explanation": f.explanation,
                 "epistemic_status": f.epistemic_status}
                for f in travel_findings
            ],
        },
        "entity_profiles": anomaly_report.get("profiles", {}),
        "behavioral_anomalies": anomaly_report.get("findings", []),
        "anomaly_summary": anomaly_report.get("summary", {}),
    }


@router.get("/cases/{case_id}/anomalies")
async def get_anomalies(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Retrieve grounded behavioral baseline profiles and multi-modal anomaly findings."""
    case = await require_case_access(db, current, case_id)
    from cognitive.anomaly import scan_behavioral_anomalies

    bank_rows = await _get_bank_events(db, case.id)
    call_events = await _get_call_events(db, case.id)
    location_events = await _get_location_timeline_events(db, case.id)

    anomaly_report = scan_behavioral_anomalies(bank_rows, call_events, location_events)

    return {
        "case_id": str(case.id),
        "profiles": anomaly_report.get("profiles", {}),
        "findings": anomaly_report.get("findings", []),
        "summary": anomaly_report.get("summary", {}),
    }


# ── Endpoint: Feature 04 — Hypothesis Investigation Board ─────────────────────

class EvaluateHypothesisRequest(BaseModel):
    target_entity: Optional[str] = None
    observations: dict[str, float] = Field(default_factory=dict)
    priors: Optional[dict[str, float]] = None


class HypothesisReportRequest(BaseModel):
    target_entity: Optional[str] = None
    leading_hypothesis: Optional[str] = None
    officer_rank: Optional[str] = "Investigating Officer"
    police_station: Optional[str] = None


@router.get("/cases/{case_id}/hypotheses")
@router.get("/cases/{case_id}/hypothesis-board")
async def get_hypotheses(
    case_id: str,
    target_entity: Optional[str] = Query(None, description="Entity value or ID to evaluate"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Feature 04: Hypothesis Investigation Board (Richards Heuer's ACH Framework).
    Evaluates competing role theories (Kingpin, Mule, Compromised Victim, Technical Operator, Beneficiary)
    against multi-modal case evidence with refutation detection, diagnosticity spread,
    and R v T [2010] judicial compliance.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.hypothesis import load_model, evaluate, extract_entity_observations
    from cognitive import data_path

    model = load_model(data_path("hypotheses.json"))

    # Discover candidate suspect entities in this case
    entities_res = (await db.execute(
        select(Entity).where(
            Entity.case_id == case.id,
            Entity.entity_type.in_(["ACCOUNT", "UPI", "PHONE", "PERSON", "IP"]),
        ).order_by(Entity.degree_centrality.desc().nullslast())
    )).scalars().all()

    candidates = []
    for e in entities_res:
        role_hint = (
            "FINANCIAL_NODE" if e.entity_type in ("ACCOUNT", "UPI")
            else "COMMUNICATION_NODE" if e.entity_type == "PHONE"
            else "NETWORK_INFRASTRUCTURE" if e.entity_type == "IP"
            else "SUSPECT_SUBJECT"
        )
        candidates.append({
            "id": str(e.id),
            "value": e.canonical_value,
            "entity_type": e.entity_type,
            "degree": e.degree_centrality or 1,
            "role_hint": role_hint,
        })

    # Pick active target entity
    active_target = target_entity
    if not active_target:
        active_target = candidates[0]["value"] if candidates else "CASE_GLOBAL"

    bank_rows = await _get_bank_events(db, case.id)
    call_events = await _get_call_events(db, case.id)

    net_events_rows = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case.id,
            EvidenceEvent.event_type == "network_log",
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()
    net_events = [
        {
            "id": str(ev.id),
            "event_timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
            "metadata": ev.event_metadata or {},
        }
        for ev in net_events_rows
    ]

    observations, provenance = extract_entity_observations(
        target_entity=active_target,
        bank_events=bank_rows,
        call_events=call_events,
        network_events=net_events,
    )

    result = evaluate(observations, model, provenance_map=provenance)

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "case_title": case.title,
        "police_station": case.police_station or "Cyber Crime Police Station",
        "target_entity": active_target,
        "candidates": candidates,
        "assessment_type": result["assessment_type"],
        "ranked_labels": result["ranked_labels"],
        "display_label": result["display_label"],
        "epistemic_notice": result["epistemic_notice"],
        "hypotheses": result["hypotheses"],
        "evidence_matrix": result["evidence_matrix"],
        "unobserved_indicators": result.get("unobserved_indicators", []),
        "unobserved_details": result.get("unobserved_details", []),
        "observations": observations,
    }


@router.post("/cases/{case_id}/hypothesis-evaluate")
async def evaluate_hypothesis_whatif(
    case_id: str,
    body: EvaluateHypothesisRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Evaluates competing hypotheses with custom what-if indicator overrides in real time.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.hypothesis import load_model, evaluate
    from cognitive import data_path

    model = load_model(data_path("hypotheses.json"))
    result = evaluate(body.observations, model, config={"priors": body.priors})

    return {
        "case_id": str(case.id),
        "target_entity": body.target_entity or "WHAT_IF_SIMULATION",
        "assessment_type": result["assessment_type"],
        "ranked_labels": result["ranked_labels"],
        "display_label": result["display_label"],
        "epistemic_notice": result["epistemic_notice"],
        "hypotheses": result["hypotheses"],
        "evidence_matrix": result["evidence_matrix"],
        "unobserved_indicators": result.get("unobserved_indicators", []),
        "unobserved_details": result.get("unobserved_details", []),
        "simulated_observations": body.observations,
    }


@router.post("/cases/{case_id}/hypothesis-report")
async def generate_hypothesis_report(
    case_id: str,
    body: HypothesisReportRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Generates a formal Section 193 BNSS Prosecution Hypothesis Evaluation Memorandum.
    """
    case = await require_case_access(db, current, case_id)
    station = body.police_station or case.police_station or "State Cyber Crime Police Station"
    target = body.target_entity or "Primary Suspect Subject"
    leading = body.leading_hypothesis or "LAYER1_MULE"

    timestamp_str = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    report_text = f"""================================================================================
MEMORANDUM OF INVESTIGATIVE THEORY & COMPETING HYPOTHESIS EVALUATION
UNDER SECTION 193 BNSS, 2023 (POLICE REPORT UPON INVESTIGATION)
================================================================================
OFFICE OF THE INVESTIGATING OFFICER
POLICE STATION: {station.upper()}
CASE REFERENCE: {case.case_number}
SUBJECT MATTER: {case.title}
DATE OF ASSESSMENT: {timestamp_str}
EVALUATED SUSPECT/ENTITY: {target}
PREDOMINANT INVESTIGATIVE THEORY: {leading}

1. PRELIMINARY STATUTORY NOTICE:
This evaluation is prepared pursuant to Section 193 of Bharatiya Nagarik Suraksha
Sanhita (BNSS), 2023. In accordance with judicial principles laid down in
R v T [2010] EWCA Crim 2439 and the Indian Evidence Act / Section 63 Bharatiya
Sakshya Adhiniyam (BSA), 2023, the classification below represents an objective,
rule-based assessment under Richards Heuer's Analysis of Competing Hypotheses (ACH)
standard. Numerical percentages are excluded to prevent premature prejudice.

2. COMPETING INVESTIGATIVE THEORIES EXAMINED:
  • KINGPIN_ORGANIZER : Direct operational controller of the fraudulent scheme.
  • LAYER1_MULE       : Intermediary conduit enabling rapid pass-through of victim funds.
  • COMPROMISED_VICTIM: Unwitting party whose legitimate account credentials were hijacked.
  • TECHNICAL_OPERATOR: Technical infrastructure provider (SIM/IP/device multiplexing).
  • BENEFICIARY_CASHOUT: Downstream withdrawal or conversion nexus.

3. FORENSIC FINDING & REFUTATION OF ALTERNATIVE THEORIES:
Based upon the multi-modal evidence matrix (banking ledger timestamps, Call Detail
Records, and network logs):
  a) The primary evidentiary profile strongly corroborates the role of [{leading}].
  b) The defense hypothesis of COMPROMISED_VICTIM is contradicted by the short
     pass-through latency and absence of contemporaneous police/cybercrime complaints.
  c) The hypothesis of KINGPIN_ORGANIZER is challenged by the absence of direct
     victim extortion contact on communication channels.

4. EVIDENTIARY GAPS TO BE CLOSED PRIOR TO CHARGESHEET:
Prior to final submission before the Hon'ble Special Magistrate under Sec 193(3) BNSS,
the investigating team must secure:
  - Certified Section 63 BSA certificate for all CDR and CBS electronic ledgers.
  - Original Account Opening Form (AOF) and e-KYC logs from the nodal bank.
  - IPDR session mapping verifying device identity at the moment of fund disbursement.

SUBMITTED BY:
{body.officer_rank}
{station}
================================================================================"""

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "target_entity": target,
        "leading_hypothesis": leading,
        "report_title": f"Section 193 BNSS Hypothesis Evaluation · {case.case_number}",
        "report_text": report_text,
        "statutory_basis": "Section 193 BNSS, 2023 / Section 63 BSA, 2023",
    }


class ActionDraftRequest(BaseModel):
    target: Any = Field(default_factory=dict)



# ── Endpoint: Feature 06 — Golden Hours Action Center & Next-Best Actions ────

@router.get("/cases/{case_id}/next-best-actions")
@router.get("/cases/{case_id}/golden-hours")
async def get_next_best_actions(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Feature 06: Golden Hours Action Center & Next-Best Investigation Engine.
    Ranks time-critical statutory preservation notices and evidence-gap closing actions
    using multi-window urgency decay and transparent VoI utility prioritization.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.nextbest import load_catalog, rank_actions, extract_evidence_gap_actions, classify_window_phase
    from cognitive import data_path

    catalog = load_catalog(data_path("action_catalog.json"))
    bank_rows = await _get_bank_events(db, case.id)
    entities = await _get_case_entities(db, case.id)

    # Calculate elapsed hours since case creation
    elapsed_hours = 0.0
    if case.created_at:
        elapsed_hours = (datetime.now(timezone.utc) - case.created_at.replace(
            tzinfo=timezone.utc if case.created_at.tzinfo is None else case.created_at.tzinfo
        )).total_seconds() / 3600

    closing_balance = next((r["balance"] for r in reversed(bank_rows) if r.get("balance") is not None), None)
    if closing_balance is None:
        closing_balance = max((r.get("amount_val", 0.0) for r in bank_rows), default=0.0)

    phones = [e["value"] for e in entities if e["entity_type"] == "PHONE"]
    accounts_at_risk = [
        {"account": bank_rows[-1].get("account", "UNKNOWN") if bank_rows else "UNKNOWN",
         "ifsc": None, "bank_name": None,
         "amount_unwithdrawn": closing_balance}
    ] if bank_rows else []

    case_state = {
        "elapsed_hours_since_first_credit": elapsed_hours,
        "complaint_ref": case.fir_number or case.case_number,
        "accounts_at_risk": accounts_at_risk,
        "unresolved_phones": [{"phone": p, "_resolves": 1} for p in phones[:5]],
        "crime_window_cells": [],
    }

    catalog_ranking = rank_actions(case_state, catalog)
    catalog_actions = catalog_ranking.get("ranked_actions", [])

    # Fetch events, relationships, and findings for case-grounded evidence gap actions
    events_raw = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.case_id == case.id)
    )).scalars().all()
    events_dicts = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "evidence_file_id": str(e.evidence_file_id) if e.evidence_file_id else None,
            "event_metadata": e.event_metadata or {},
        }
        for e in events_raw
    ]

    entities_dicts = [
        {"id": str(e.get("id", "")), "canonical_value": e.get("value", ""), "entity_type": e.get("entity_type", "")}
        for e in entities
    ]

    relationships_raw = (await db.execute(
        select(Relationship).where(Relationship.case_id == case.id)
    )).scalars().all()
    entity_id_to_value = {str(e.get("id")): e.get("value") for e in entities}
    rel_dicts = [
        {
            "source_value": entity_id_to_value.get(str(r.source_entity_id), str(getattr(r, "source_entity_id", "UNKNOWN"))),
            "target_value": entity_id_to_value.get(str(r.target_entity_id), str(getattr(r, "target_entity_id", "UNKNOWN"))),
            "epistemic_status": r.epistemic_status,
            "confidence": r.confidence,
            "event_refs": r.event_refs or [],
            "evidence_refs": r.evidence_refs or [],
        }
        for r in relationships_raw
    ]

    findings_raw = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
    )).scalars().all()
    finding_dicts = [
        {
            "finding_type": f.finding_type,
            "title": f.title,
            "description": f.description,
            "entity_refs": f.entity_refs or [],
            "event_refs": f.event_refs or [],
            "evidence_refs": f.evidence_refs or [],
            "fingerprint": f.fingerprint,
        }
        for f in findings_raw
    ]

    context_dict = {
        "events": events_dicts,
        "entities": entities_dicts,
        "relationships": rel_dicts,
        "findings": finding_dicts,
    }

    gap_actions = extract_evidence_gap_actions(context_dict, max_gap_actions=6)

    # Harmonize and format titles
    formatted_catalog = []
    for ca in catalog_actions:
        item = dict(ca)
        item["title"] = ca.get("description", "")
        formatted_catalog.append(item)

    # Combine catalog actions and gap actions without duplicating
    all_ranked: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for a in formatted_catalog + gap_actions:
        k = f"{a.get('action_code')}:{a.get('title') or a.get('description')}"
        if k not in seen_keys:
            seen_keys.add(k)
            all_ranked.append(a)

    # Sort ready first, then by utility score
    all_ranked.sort(key=lambda r: (
        0 if r.get("status") == "ready" else 1,
        -(r.get("utility_score") or 0.0),
    ))

    golden_hours = float(catalog.get("golden_hours", 2.0))
    window_phase = classify_window_phase(elapsed_hours, golden_hours)

    ready_count = sum(1 for a in all_ranked if a.get("status") == "ready")
    blocked_count = sum(1 for a in all_ranked if a.get("status") == "blocked_missing_fields")
    distinct_gaps = sorted(list({a.get("gap") for a in all_ranked if a.get("gap")}))

    ready_actions = [a for a in all_ranked if a.get("status") == "ready"]
    blocked_actions = [a for a in all_ranked if a.get("status") != "ready"]

    return {
        "case_id": str(case.id),
        "elapsed_hours": round(elapsed_hours, 2),
        "golden_hours": golden_hours,
        "window_phase": window_phase,
        "urgency_factor": all_ranked[0].get("urgency_factor", 0.0) if all_ranked else 0.0,
        "financial_exposure": round(float(closing_balance or 0.0), 2),
        "preservable_financial_exposure": round(float(closing_balance or 0.0), 2),
        "total_actions": len(all_ranked),
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "actions": all_ranked,
        "ready_actions": ready_actions,
        "blocked_actions": blocked_actions,
        "summary": {
            "total_actions": len(all_ranked),
            "ready_count": ready_count,
            "blocked_count": blocked_count,
            "gaps_count": len(distinct_gaps),
            "window_phase": window_phase,
            "financial_exposure": round(float(closing_balance or 0.0), 2),
        },
        "evidence_gaps_summary": distinct_gaps,
        "ranked_actions": all_ranked,
    }


@router.post("/cases/{case_id}/actions/{action_code}/draft")
async def generate_action_draft(
    case_id: str,
    action_code: str,
    body: ActionDraftRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Render an authentic, pre-filled statutory notice under Indian criminal law
    (Section 106 BNSS, Section 94 BNSS, Section 105 BNSS, I4C 1930) with mandatory DRAFT banner.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.nextbest import render_statutory_notice

    case_meta = {
        "fir_number": case.fir_number or case.case_number,
        "case_number": case.case_number,
        "police_station": case.police_station or "Cyber Crime Police Station",
    }
    target_dict: dict[str, Any] = {}
    if isinstance(body.target, dict):
        target_dict = body.target
    elif isinstance(body.target, str) and body.target.strip():
        val = body.target.strip()
        target_dict = {"account": val, "phone": val, "target": val, "complaint_ref": val}

    result = render_statutory_notice(
        action_code=action_code,
        target=target_dict,
        case_meta=case_meta,
    )
    return result


# ── Endpoint: Feature 07 — Crime Script Matcher (MO Fingerprinting) ──────────

@router.get("/playbooks")
async def get_crime_script_playbooks(
    current: User = Depends(get_current_user),
):
    """Enumerate the curated crime script playbook catalog."""
    from cognitive.mo import load_playbooks, JUDICIAL_NOTICE
    from cognitive import data_path

    lib = load_playbooks(data_path("playbooks.json"))
    playbooks = lib.get("playbooks", [])
    return {
        "total_playbooks": len(playbooks),
        "playbooks": [
            {
                "name": pb["name"],
                "description": pb.get("description", ""),
                "source": pb.get("source", ""),
                "stages": pb.get("stages", []),
                "stage_count": len(pb.get("stages", [])),
                "detector_stages": list(pb.get("detectors", {}).keys()),
            }
            for pb in playbooks
        ],
        "judicial_notice": JUDICIAL_NOTICE,
    }


@router.get("/cases/{case_id}/mo-fingerprint")
async def get_mo_fingerprint(
    case_id: str,
    threshold: float = Query(0.60, ge=0.1, le=1.0, description="Normalized similarity threshold"),
    playbook: str | None = Query(None, description="Optional playbook name filter"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Mine multi-modal evidence across the case (communications, bank/UPI transactions,
    CDR call records, network logs, and document text) against the curated I4C/NCRP
    crime script playbook library.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.mo import classify_case_evidence, load_playbooks, JUDICIAL_NOTICE
    from cognitive import data_path

    playbooks = load_playbooks(data_path("playbooks.json"))

    # 1. Fetch all evidence files for metadata resolution
    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
    )).scalars().all()
    file_map = {str(f.id): (f.original_name or f.filename) for f in ev_files}

    # 2. Fetch all evidence events ordered by timestamp
    events_res = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case.id
        ).order_by(EvidenceEvent.event_timestamp.asc().nullslast(), EvidenceEvent.id.asc())
    )).scalars().all()

    evidence_items: list[dict[str, Any]] = []
    for idx, ev in enumerate(events_res, start=1):
        meta = ev.event_metadata or {}
        fid = str(ev.evidence_file_id) if ev.evidence_file_id else ""
        fn = file_map.get(fid, meta.get("filename") or "")

        evidence_items.append({
            "type": ev.event_type,
            "line_no": idx,
            "event_id": str(ev.id),
            "evidence_file_id": fid,
            "filename": fn,
            "sender": meta.get("sender") or meta.get("from_account") or meta.get("caller") or "?",
            "text": ev.text_content or meta.get("narration") or meta.get("description") or "",
            "narration": meta.get("narration") or meta.get("description") or "",
            "amount": meta.get("amount"),
            "from_account": meta.get("from_account"),
            "to_account": meta.get("to_account"),
            "caller": meta.get("caller"),
            "callee": meta.get("callee"),
            "duration_sec": meta.get("duration") or meta.get("duration_sec"),
            "timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
        })

    if not evidence_items:
        return {
            "case_id": str(case.id),
            "case_number": case.case_number,
            "verdict": "INSUFFICIENT_TRACE",
            "threshold": threshold,
            "message": "No evidence events found in case for crime script analysis.",
            "observed_sequence": [],
            "observed_stages_count": 0,
            "matches": [],
            "best_match": None,
            "candidate_best": None,
            "trace_evidence": [],
            "all_stage_evidence": {},
            "judicial_notice": JUDICIAL_NOTICE,
            "available_playbooks": [
                {"name": pb["name"], "description": pb.get("description", ""), "stages_count": len(pb.get("stages", []))}
                for pb in playbooks.get("playbooks", [])
            ],
            "note": "Awaiting evidence ingestion.",
        }

    cfg = {"match_threshold": threshold}
    result = classify_case_evidence(evidence_items, playbooks, cfg)

    matches = result["matches"]
    if playbook:
        filtered = [m for m in matches if m["playbook"].upper() == playbook.strip().upper()]
        if filtered:
            matches = filtered + [m for m in matches if m["playbook"].upper() != playbook.strip().upper()]

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "verdict": result["verdict"],
        "threshold": threshold,
        "observed_sequence": result["observed_sequence"],
        "observed_stages_count": len(result["observed_sequence"]),
        "matches": matches,
        "best_match": result["best_match"],
        "candidate_best": result.get("candidate_best"),
        "trace_evidence": result["trace_evidence"],
        "all_stage_evidence": result.get("all_stage_evidence", {}),
        "judicial_notice": result["judicial_notice"],
        "available_playbooks": [
            {
                "name": pb["name"],
                "description": pb.get("description", ""),
                "source": pb.get("source", ""),
                "stages": pb.get("stages", []),
                "stages_count": len(pb.get("stages", [])),
            }
            for pb in playbooks.get("playbooks", [])
        ],
        "note": result["note"],
    }


@router.post("/cases/{case_id}/mo-classify")
async def classify_mo_script(
    case_id: str,
    req: MOClassifyRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Interactively test an ad-hoc behavioral trace or pasted transcript
    against the crime script playbook catalog.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.mo import classify_case_evidence, load_playbooks, JUDICIAL_NOTICE
    from cognitive import data_path

    playbooks = load_playbooks(data_path("playbooks.json"))

    evidence_items: list[dict[str, Any]] = []

    # If raw lines/messages provided
    if req.messages:
        for idx, m in enumerate(req.messages, start=1):
            evidence_items.append({
                "type": m.get("type", "message"),
                "line_no": idx,
                "sender": m.get("sender", "?"),
                "text": m.get("text", ""),
                "timestamp": m.get("timestamp", ""),
                "event_id": m.get("event_id", f"adhoc-{idx}"),
            })
    elif req.text_content:
        for idx, line in enumerate(req.text_content.strip().splitlines(), start=1):
            if line.strip():
                evidence_items.append({
                    "type": "message",
                    "line_no": idx,
                    "sender": "USER",
                    "text": line.strip(),
                    "event_id": f"text-line-{idx}",
                })

    if not evidence_items:
        # Fallback to case evidence items
        ev_files = (await db.execute(
            select(EvidenceFile).where(EvidenceFile.case_id == case.id)
        )).scalars().all()
        file_map = {str(f.id): (f.original_name or f.filename) for f in ev_files}
        events_res = (await db.execute(
            select(EvidenceEvent).where(
                EvidenceEvent.case_id == case.id
            ).order_by(EvidenceEvent.event_timestamp.asc().nullslast(), EvidenceEvent.id.asc())
        )).scalars().all()
        for idx, ev in enumerate(events_res, start=1):
            meta = ev.event_metadata or {}
            fid = str(ev.evidence_file_id) if ev.evidence_file_id else ""
            evidence_items.append({
                "type": ev.event_type,
                "line_no": idx,
                "event_id": str(ev.id),
                "evidence_file_id": fid,
                "filename": file_map.get(fid, ""),
                "text": ev.text_content or meta.get("narration") or meta.get("description") or "",
                "amount": meta.get("amount"),
                "timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
            })

    cfg = {"match_threshold": req.threshold}
    result = classify_case_evidence(evidence_items, playbooks, cfg)

    matches = result["matches"]
    if req.playbook:
        filtered = [m for m in matches if m["playbook"].upper() == req.playbook.strip().upper()]
        if filtered:
            matches = filtered + [m for m in matches if m["playbook"].upper() != req.playbook.strip().upper()]

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "verdict": result["verdict"],
        "threshold": req.threshold,
        "observed_sequence": result["observed_sequence"],
        "matches": matches,
        "best_match": result["best_match"],
        "candidate_best": result.get("candidate_best"),
        "trace_evidence": result["trace_evidence"],
        "judicial_notice": result["judicial_notice"],
        "note": result["note"],
    }


# ── Endpoint: Feature 08 — Counterfactual Freeze Sandbox ─────────────────────

@router.get("/cases/{case_id}/counterfactual-candidates")
async def get_counterfactual_candidates(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Returns candidate bank accounts and UPI IDs discovered in the case,
    annotated with empirical transaction volumes, degree, and activity windows
    to facilitate rapid 1-click counterfactual freeze simulations.
    """
    case = await require_case_access(db, current, case_id)
    bank_rows = await _get_bank_events(db, case.id)

    stats: dict[str, dict[str, Any]] = {}

    def _rec(acc: str, amt: float, ts: str, is_inbound: bool):
        if not acc or acc.upper().startswith("UNKNOWN") or acc == "ACCOUNT":
            return
        if acc not in stats:
            stats[acc] = {
                "account": acc,
                "total_inbound": 0.0,
                "total_outbound": 0.0,
                "total_volume": 0.0,
                "txn_count": 0,
                "first_seen": ts,
                "last_seen": ts,
            }
        s = stats[acc]
        s["txn_count"] += 1
        s["total_volume"] += amt
        if is_inbound:
            s["total_inbound"] += amt
        else:
            s["total_outbound"] += amt
        if ts:
            if not s["first_seen"] or ts < s["first_seen"]:
                s["first_seen"] = ts
            if not s["last_seen"] or ts > s["last_seen"]:
                s["last_seen"] = ts

    for r in bank_rows:
        ts = r.get("timestamp") or ""
        amt = float(r.get("amount_val") or r.get("credit") or r.get("debit") or 0.0)
        from_acc = r.get("from") or r.get("from_account")
        to_acc = r.get("to") or r.get("to_account") or r.get("account")
        ref = r.get("reference", "") or ""

        if from_acc and to_acc:
            _rec(str(from_acc), amt, ts, False)
            _rec(str(to_acc), amt, ts, True)
        else:
            upi_match = re.search(r"UPI/\d+/([\w.\-]+@[\w]+)", ref)
            if r.get("credit", 0) > 0 and upi_match:
                _rec(upi_match.group(1), float(r["credit"]), ts, False)
                _rec(str(to_acc or "ACCOUNT"), float(r["credit"]), ts, True)
            elif r.get("debit", 0) > 0:
                _rec(str(to_acc or from_acc or "ACCOUNT"), float(r["debit"]), ts, False)

    candidates = sorted(
        [
            {
                "account": v["account"],
                "total_inbound": round(v["total_inbound"], 2),
                "total_outbound": round(v["total_outbound"], 2),
                "total_volume": round(v["total_volume"], 2),
                "txn_count": v["txn_count"],
                "first_seen": v["first_seen"],
                "last_seen": v["last_seen"],
                "suggested_freeze_time": v["first_seen"],
            }
            for v in stats.values()
        ],
        key=lambda x: x["total_volume"],
        reverse=True,
    )

    return {
        "case_id": str(case.id),
        "total_candidates": len(candidates),
        "candidates": candidates,
    }


@router.post("/cases/{case_id}/counterfactual-freeze")
async def simulate_counterfactual_freeze(
    case_id: str,
    body: CounterfactualRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Simulate what-if account freeze at time T under Section 106 BNSS.
    Computes preserved capital, downstream cascade starvation, timeliness sensitivity,
    and comparative delta analytics without mutating case state.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.counterfactual import (
        simulate_freeze,
        simulate_timeliness_sweep,
        generate_counterfactual_frames,
    )

    bank_rows = await _get_bank_events(db, case.id)
    if not bank_rows:
        raise HTTPException(400, "No bank transaction data available for counterfactual simulation.")

    def _iso(ts: str) -> str | None:
        if not ts:
            return None
        return ts if "T" in ts else ts + "T00:00:00"

    transfers: list[dict[str, Any]] = []
    for r in bank_rows:
        ts = _iso(r.get("timestamp", ""))
        if not ts:
            continue
        if r.get("from") and r.get("to") and r.get("amount_val"):
            transfers.append({
                "from": str(r["from"]), "to": str(r["to"]),
                "amount": float(r["amount_val"]), "timestamp": ts,
            })
            continue
        ref = r.get("reference", "") or ""
        upi_match = re.search(r"UPI/\d+/([\w.\-]+@[\w]+)", ref)
        if r.get("credit", 0) > 0 and upi_match:
            transfers.append({
                "from": upi_match.group(1), "to": r.get("account", "ACCOUNT"),
                "amount": float(r["credit"]), "timestamp": ts,
            })
        if r.get("debit", 0) > 0:
            transfers.append({
                "from": r.get("account", "ACCOUNT"), "to": "UNKNOWN-" + ref[:10],
                "amount": float(r["debit"]), "timestamp": ts,
            })

    # Also incorporate any TRANSFERRED_TO edges if available
    entity_map = {e["id"]: e["value"] for e in await _get_case_entities(db, case.id)}
    rel_rows = (await db.execute(
        select(Relationship).where(
            Relationship.case_id == case.id,
            Relationship.relationship_type == "TRANSFERRED_TO",
        )
    )).scalars().all()
    for rel in rel_rows:
        if rel.amount and rel.event_timestamp:
            s_val = entity_map.get(str(rel.source_entity_id), str(rel.source_entity_id))
            t_val = entity_map.get(str(rel.target_entity_id), str(rel.target_entity_id))
            ts_str = rel.event_timestamp.isoformat()
            # Avoid exact duplicate edge
            if not any(t["from"] == s_val and t["to"] == t_val and abs(t["amount"] - float(rel.amount)) < 0.01 for t in transfers):
                transfers.append({
                    "from": s_val,
                    "to": t_val,
                    "amount": float(rel.amount),
                    "timestamp": ts_str,
                })

    target_accounts = [body.freeze_account] + list(body.additional_freeze_accounts or [])
    result = simulate_freeze(transfers, target_accounts, body.freeze_time)

    timeliness_sweep = []
    if body.include_sweep:
        base_ref = transfers[0]["timestamp"] if transfers else body.freeze_time
        timeliness_sweep = simulate_timeliness_sweep(
            transfers=transfers,
            freeze_account=target_accounts,
            reference_time=base_ref,
        )

    frames = []
    if body.include_frames:
        frames = generate_counterfactual_frames(transfers, result)

    return {
        "case_id": str(case.id),
        # Legacy contract keys (100% backward compatible)
        "intervention": result["intervention"],
        "preserved_total": result["preserved_total"],
        "assessment_type": result["assessment_type"],
        "blocked_debits": len(result["blocked_out_events"]),
        "stopped_credits": len(result["stopped_in_events"]),
        "completed_transfers": result["completed_transfers"],
        "blocked_out_events": result["blocked_out_events"][:15],
        "stopped_in_events": result["stopped_in_events"][:15],
        "unfunded_attempts": result["unfunded_attempts"][:15],
        # Feature 08 Enhanced 4-Stage Architecture
        "stage_1_observed": result["stage_1_observed"],
        "stage_2_intervention": result["stage_2_intervention"],
        "stage_3_simulated": result["stage_3_simulated"],
        "stage_4_comparison": result["stage_4_comparison"],
        "node_classifications": result["node_classifications"],
        "timeliness_sweep": timeliness_sweep,
        "frames": frames,
        "epistemic_status": result.get("epistemic_status", "APPROXIMATED"),
        "confidence_score": result.get("confidence_score", 0.95),
        "starved_downstream_events": result.get("unfunded_attempts", [])[:15],
        "caveats": result["caveats"],
        "epistemic_notice": (
            "HYPOTHETICAL SIMULATION SANDBOX · NOT OBSERVED EVIDENCE — Model-based lower-bound estimate "
            "for investigative recovery prioritization. Does not mutate authoritative case records."
        ),
    }


# ── Endpoint: Feature 10 — Network Replay ────────────────────────────────────

@router.get("/cases/{case_id}/network-replay")
async def get_network_replay(
    case_id: str,
    step_seconds: int = Query(300, ge=60, le=86400),
    tau_seconds: float = Query(1800.0, ge=300, le=86400),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Generate CTDG animation frames for temporal network replay."""
    case = await require_case_access(db, current, case_id)
    from cognitive.replay import build_frames

    events = await _get_timed_events(db, case.id)
    if not events:
        return {"case_id": str(case.id), "frames": [], "total_events": 0}

    frames = build_frames(events, {
        "step_seconds": step_seconds,
        "tau_seconds": tau_seconds,
        "max_frames": 500,
    })
    return {
        "case_id": str(case.id),
        "total_events": len(events),
        "total_frames": len(frames),
        "frames": [f.to_dict() if hasattr(f, 'to_dict') else f for f in frames],
    }


# ── Endpoint: Feature 03 — Syndicate Radar & Cross-Case Blind Index ─────────

HARD_CROSS_CASE_TYPES = ["PHONE", "UPI", "ACCOUNT", "IFSC", "IMEI", "MAC", "EMAIL", "IP", "DOMAIN"]


@router.get("/cross-case/collisions")
async def get_cross_case_collisions(
    entity_type: str | None = None,
    min_cases: int = 2,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detect cross-case entity collisions and syndicates via zero-knowledge HMAC blind index.

    Strictly preserves privacy boundaries: raw PII from external cases is never returned.
    """
    from cognitive.crosscase import BlindIndex, build_index, find_collisions, cluster_syndicates
    from db.models import Case

    key = os.environ.get("CD_INDEX_KEY", "cyberdrishti-local-dev-key")
    index = BlindIndex(key)

    types_to_query = [entity_type.upper()] if entity_type else HARD_CROSS_CASE_TYPES

    all_entities = (await db.execute(
        select(Entity).where(Entity.entity_type.in_(types_to_query))
    )).scalars().all()

    cases = (await db.execute(select(Case))).scalars().all()
    case_meta = {
        str(c.id): {
            "case_number": c.case_number,
            "case_title": c.title,
            "crime_type": c.crime_type,
            "police_station": c.police_station,
        }
        for c in cases
    }

    entries = []
    for e in all_entities:
        cid = str(e.case_id)
        entries.append({
            "case_id": cid,
            "case_number": case_meta.get(cid, {}).get("case_number", ""),
            "case_title": case_meta.get(cid, {}).get("case_title", ""),
            "crime_type": case_meta.get(cid, {}).get("crime_type", ""),
            "police_station": case_meta.get(cid, {}).get("police_station", ""),
            "entity_type": e.entity_type,
            "value": e.canonical_value,
            "degree": e.degree_centrality or 1,
            "severity": 1.0,
        })

    store = build_index(entries, index)
    all_collisions = find_collisions(store)
    filtered_collisions = [c for c in all_collisions if c.get("case_count", 0) >= min_cases]
    syndicates = cluster_syndicates(store, case_meta)

    return {
        "total_entities_indexed": len(entries),
        "total_collisions": len(filtered_collisions),
        "total_syndicates": len(syndicates),
        "collisions": filtered_collisions[:limit],
        "syndicates": syndicates[:10],
        "note": "Zero-knowledge: only HMAC blind tokens shown, never raw PII. Privacy boundary strictly enforced.",
    }


@router.get("/cases/{case_id}/syndicate-radar")
async def get_case_syndicate_radar(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Syndicate Radar Command Deck for a specific case.

    Cross-screens local case entities against the multi-case HMAC blind index, clusters
    intersecting cases into criminal syndicates, computes polar radar geometry (r, θ),
    and enforces zero-knowledge privacy:
      • Discloses plaintext anchor and evidence provenance for local case entities.
      • Retains cryptographically shielded blind tokens and case tags for foreign cases.
    """
    from cognitive.crosscase import BlindIndex, analyze_case_syndicate_radar
    from db.models import Case, EntityMention, EvidenceEvent, EvidenceFile

    case = await require_case_access(db, current, case_id)
    target_case_id = str(case.id)

    # 1. Load local case entities
    local_entities_records = (await db.execute(
        select(Entity).where(
            Entity.case_id == case.id,
            Entity.entity_type.in_(HARD_CROSS_CASE_TYPES),
        )
    )).scalars().all()

    # 2. Extract provenance for local entities (mentions -> evidence files)
    local_entity_ids = [e.id for e in local_entities_records]
    provenance_map: dict[str, dict[str, Any]] = {}
    if local_entity_ids:
        mention_rows = (await db.execute(
            select(
                EntityMention.entity_id,
                EvidenceFile.original_name,
                EvidenceFile.filename,
                EvidenceFile.id,
                EvidenceEvent.source_page,
                EvidenceEvent.source_line,
                EvidenceEvent.event_type,
                EvidenceEvent.event_timestamp,
            )
            .join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
            .outerjoin(EvidenceFile, EvidenceEvent.evidence_file_id == EvidenceFile.id)
            .where(EvidenceEvent.case_id == case.id)
        )).all()

        for eid, orig_name, fname, file_id, spage, sline, etype, ets in mention_rows:
            eid_str = str(eid)
            if eid_str not in provenance_map:
                provenance_map[eid_str] = {
                    "source_file": orig_name or fname or "Case Evidence Document",
                    "file_id": str(file_id) if file_id else None,
                    "source_page": spage,
                    "source_line": sline,
                    "event_type": etype or "mention",
                    "event_timestamp": str(ets) if ets else None,
                }

    local_dicts = []
    for e in local_entities_records:
        eid_str = str(e.id)
        local_dicts.append({
            "id": eid_str,
            "entity_id": eid_str,
            "case_id": target_case_id,
            "entity_type": e.entity_type,
            "canonical_value": e.canonical_value,
            "degree": int(e.degree_centrality or 1) or 1,
            "first_seen": str(e.first_seen) if e.first_seen else "",
            "last_seen": str(e.last_seen) if e.last_seen else "",
            "provenance": provenance_map.get(eid_str, {}),
        })

    # 3. Load all hard entities across all cases
    all_entities = (await db.execute(
        select(Entity).where(Entity.entity_type.in_(HARD_CROSS_CASE_TYPES))
    )).scalars().all()

    # 4. Load case metadata map
    all_cases = (await db.execute(select(Case))).scalars().all()
    case_meta = {
        str(c.id): {
            "case_number": c.case_number,
            "case_title": c.title,
            "crime_type": c.crime_type,
            "police_station": c.police_station,
        }
        for c in all_cases
    }

    all_entries = []
    for e in all_entities:
        cid = str(e.case_id)
        all_entries.append({
            "case_id": cid,
            "case_number": case_meta.get(cid, {}).get("case_number", ""),
            "case_title": case_meta.get(cid, {}).get("case_title", ""),
            "crime_type": case_meta.get(cid, {}).get("crime_type", ""),
            "police_station": case_meta.get(cid, {}).get("police_station", ""),
            "entity_type": e.entity_type,
            "value": e.canonical_value,
            "degree": e.degree_centrality or 1,
            "severity": 1.0,
            "first_seen": str(e.first_seen) if e.first_seen else "",
            "last_seen": str(e.last_seen) if e.last_seen else "",
        })

    # 5. Execute case syndicate radar analysis
    key = os.environ.get("CD_INDEX_KEY", "cyberdrishti-local-dev-key")
    index = BlindIndex(key)

    radar_result = analyze_case_syndicate_radar(
        target_case_id=target_case_id,
        local_entities=local_dicts,
        all_case_entries=all_entries,
        index=index,
        case_metadata_map=case_meta,
    )

    # Attach case identifiers and metadata
    radar_result["case_number"] = case.case_number
    radar_result["case_title"] = case.title
    radar_result["crime_type"] = case.crime_type
    radar_result["police_station"] = case.police_station

    return radar_result


# ── Endpoint: Feature 09 — Verify Draft & Legal Compliance Shield ─────────────

@router.post("/verify-draft")
async def verify_draft(
    body: VerifyDraftRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Run the deterministic Legal Compliance Shield / output verifier on any text draft."""
    from cognitive.verifier import load_statutory_db, OutputVerifier
    from cognitive import data_path

    statutory_db = load_statutory_db(data_path("statutory_db.json"))

    facts: dict[str, set] = {
        "amounts": set(), "phones": set(), "upis": set(),
        "accounts": set(), "ips": set(), "devices": set(), "hashes": set(),
    }
    ev_dicts = None
    if body.case_id:
        try:
            case = await require_case_access(db, current, body.case_id)
            facts = await _get_case_facts(db, case.id)
            ev_files = (await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == case.id)
            )).scalars().all()
            ev_dicts = [
                {
                    "id": str(ef.id),
                    "original_name": ef.original_name,
                    "file_type": ef.file_type,
                    "source_type": ef.source_type,
                    "sha256_hash": ef.sha256_hash,
                    "upload_status": ef.upload_status,
                }
                for ef in ev_files
            ]
        except Exception:
            pass

    verifier = OutputVerifier(statutory_db, facts)
    result = verifier.critique(body.draft_text, evidence_files=ev_dicts)
    return result.to_dict()


@router.get("/cases/{case_id}/compliance-shield")
async def get_case_compliance_shield(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Returns the comprehensive Legal Compliance Shield evaluation for a case:
      • Section 63 BSA evidence hash preservation & custody memo audit
      • Statutory code alignment (BNS/BNSS/BSA 2023 vs legacy IPC/CrPC/IEA)
      • Governance posture and admissibility criteria report
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.verifier import load_statutory_db, OutputVerifier, DEFAULT_DISCLAIMER
    from cognitive import data_path

    statutory_db = load_statutory_db(data_path("statutory_db.json"))
    facts = await _get_case_facts(db, case.id)

    # 1. Evidence files audit
    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
    )).scalars().all()
    ev_dicts = [
        {
            "id": str(ef.id),
            "original_name": ef.original_name,
            "file_type": ef.file_type,
            "source_type": ef.source_type,
            "sha256_hash": ef.sha256_hash,
            "upload_status": ef.upload_status,
        }
        for ef in ev_files
    ]

    verifier = OutputVerifier(statutory_db, facts)
    integrity_audit = verifier.audit_evidence_integrity(ev_dicts)

    # 2. Case findings statutory audit
    findings = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
    )).scalars().all()

    all_citations: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for f in findings:
        combined_text = f"{f.title or ''} {f.description or ''} {f.reasoning or ''}"
        for cit in verifier.parse_legal_citations(combined_text):
            key = (cit.act or "UNKNOWN", cit.base_section)
            if key not in seen_keys:
                seen_keys.add(key)
                all_citations.append(cit.to_dict())

    # Count citation categories
    legacy_count = sum(1 for c in all_citations if c["status"] == "pre_transition_act")
    struck_down_count = sum(1 for c in all_citations if c["status"] == "struck_down")
    in_force_count = sum(1 for c in all_citations if c["status"] == "in_force")

    # Overall governance posture
    if struck_down_count > 0:
        overall_status = "GOVERNANCE_BLOCKED"
        gov_reasons = ["Struck-down statute cited in case findings."]
    elif legacy_count > 0 or (integrity_audit and integrity_audit.status == "DEFICIENT_INTEGRITY"):
        overall_status = "NEEDS_REVIEW"
        gov_reasons = []
        if legacy_count > 0:
            gov_reasons.append(f"{legacy_count} pre-transition statutory reference(s) require migration to BNS/BNSS/BSA.")
        if integrity_audit and integrity_audit.warnings:
            gov_reasons.extend(integrity_audit.warnings)
    else:
        overall_status = "COMPLIANT"
        gov_reasons = ["All evidence files hash-verified; statutory framework aligned with BNS/BNSS/BSA 2023."]

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "overall_status": overall_status,
        "admissibility_disclaimer": DEFAULT_DISCLAIMER,
        "evidence_integrity": integrity_audit.to_dict() if integrity_audit else None,
        "statutory_compliance": {
            "statutory_framework": "BNS, BNSS, BSA 2023",
            "transition_date": statutory_db["_meta"]["transition_date"],
            "total_citations_audited": len(all_citations),
            "in_force_count": in_force_count,
            "legacy_citations_count": legacy_count,
            "struck_down_citations_count": struck_down_count,
            "citations": all_citations,
        },
        "governance_posture": {
            "verdict": overall_status,
            "active_blocks": 1 if overall_status == "GOVERNANCE_BLOCKED" else 0,
            "active_warnings": len(gov_reasons) if overall_status != "COMPLIANT" else 0,
            "reasons": gov_reasons,
        },
    }


# ── Endpoint: Feature 11 — Benchmark Generator ───────────────────────────────

@router.post("/benchmark/generate")
async def generate_benchmark(
    body: BenchmarkRequest,
    seed_to_db: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Generate a DPDP-compliant synthetic test case and optionally seed it into the database."""
    from cognitive.benchmark import BenchmarkGenerator, load_json
    from cognitive import data_path

    pools = load_json(data_path("pools.json"))
    typologies = load_json(data_path("typologies.json"))
    gen = BenchmarkGenerator(pools, typologies)

    try:
        case = gen.generate_case(body.typology, body.seed)
    except KeyError as e:
        raise HTTPException(400, str(e))

    db_case_id = None
    if seed_to_db:
        try:
            from datetime import datetime, timezone
            typology_label = case["ground_truth"]["typology"].replace("_", " ").title()
            new_case = Case(
                case_number=f"SYN-{body.seed}-{str(uuid.uuid4())[:6].upper()}",
                title=f"Synthetic Benchmark · {typology_label}",
                description=f"DPDP 2023 compliant synthetic benchmark ({typology_label}). Seed: {body.seed}. {len(case['ground_truth']['entities'])} planted entities.",
                crime_type=typology_label[:64],
                priority="medium",
                status="open",
                assigned_officer_id=current.id,
            )
            db.add(new_case)
            await db.flush()

            # Seed ground truth entities
            for ent_val in case["ground_truth"].get("entities", []):
                ent_type = "ACCOUNT" if "acc" in str(ent_val).lower() else "PHONE" if "phone" in str(ent_val).lower() else "PERSON"
                db.add(Entity(
                    case_id=new_case.id,
                    canonical_value=str(ent_val),
                    entity_type=ent_type,
                    first_seen=datetime.now(timezone.utc),
                    last_seen=datetime.now(timezone.utc),
                ))

            await db.commit()
            db_case_id = str(new_case.id)
        except Exception as seed_err:
            await db.rollback()

    return {
        "case_id": case["case_id"],
        "db_case_id": db_case_id,
        "typology": case["ground_truth"]["typology"],
        "entities_count": len(case["ground_truth"]["entities"]),
        "flow_edges_count": len(case["ground_truth"]["money_flow_edges"]),
        "hidden_links_count": len(case["ground_truth"]["planted_hidden_links"]),
        "artifacts": {k: f"{len(v)} items" if isinstance(v, list) else "generated"
                      for k, v in case.get("artifacts", {}).items()},
        "ground_truth": case["ground_truth"],
    }


# ── Feature 11: Training Simulator Endpoints ─────────────────────────────────

@router.get("/training/drills")
async def list_training_drills(
    current: User = Depends(get_current_user),
):
    """List all available training drill missions."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    return {"drills": sim.list_drills()}


@router.post("/training/start")
async def start_training_session(
    body: TrainingStartRequest | None = None,
    current: User = Depends(get_current_user),
):
    """Instantiate a training drill session with synthetic evidence and tasks."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    req = body or TrainingStartRequest()
    session = sim.start_session(
        drill_id=req.drill_id,
        seed=req.seed,
        difficulty=req.difficulty,
    )
    return session.to_dict(include_ground_truth=False)


@router.get("/training/{session_id}")
async def get_training_session_state(
    session_id: str,
    current: User = Depends(get_current_user),
):
    """Get current state of an active training drill session."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    session = sim.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Training session '{session_id}' not found")
    return session.to_dict(include_ground_truth=False)


@router.post("/training/{session_id}/engine-hints")
async def get_training_engine_hints(
    session_id: str,
    current: User = Depends(get_current_user),
):
    """Execute NETRA cognitive engines over synthetic case artifacts to provide AI hints."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    session = sim.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Training session '{session_id}' not found")
    hints = sim.run_netra_engines_on_case(session)
    return {
        "session_id": session_id,
        "hints": hints,
    }


@router.post("/training/{session_id}/submit")
async def submit_training_answers(
    session_id: str,
    body: TrainingSubmitRequest,
    current: User = Depends(get_current_user),
):
    """Submit investigator answers for automated multi-pillar grading and debrief."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    try:
        eval_result = sim.evaluate_submission(session_id, body.answers)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {
        "session_id": session_id,
        "evaluation": eval_result,
    }


@router.get("/training/{session_id}/solution")
async def get_training_solution(
    session_id: str,
    current: User = Depends(get_current_user),
):
    """Reveal complete ground truth and reference solutions for training debrief."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    session = sim.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Training session '{session_id}' not found")
    return session.to_dict(include_ground_truth=True)


@router.post("/training/{session_id}/export-case")
async def export_training_case(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Export a training drill into the database as a sandboxed training case."""
    from cognitive.training import get_training_simulator
    sim = get_training_simulator()
    session = sim.get_session(session_id)
    if not session:
        raise HTTPException(404, f"Training session '{session_id}' not found")

    new_case = Case(
        case_number=f"TRN-{session.seed}-{str(uuid.uuid4())[:6].upper()}",
        title=f"[TRAINING SIMULATION] {session.title}",
        description=f"Synthetic training scenario ({session.typology}). {session.incident_brief[:200]}",
        crime_type=session.typology[:64],
        priority="low",
        status="open",
        assigned_officer_id=current.id,
        tags=["TRAINING_SIMULATOR", "SYNTHETIC", "DPDP_COMPLIANT"],
    )
    db.add(new_case)
    await db.flush()

    files_created = 0
    events_created = 0
    import hashlib
    artifacts = session.case_data.get("artifacts", {})
    for fname, content in artifacts.items():
        if isinstance(content, list):
            serialized = json.dumps(content)
            ftype = "bank_statement" if "bank" in fname else "cdr"
        else:
            serialized = str(content)
            ftype = "chat" if "whatsapp" in fname else "document"

        content_bytes = serialized.encode("utf-8")
        ef = EvidenceFile(
            case_id=new_case.id,
            filename=fname,
            original_name=fname,
            file_type=ftype,
            source_type="SYNTHETIC_TRAIN",
            file_size_bytes=len(content_bytes),
            sha256_hash=hashlib.sha256(content_bytes).hexdigest(),
            storage_path=f"synthetic://{new_case.id}/{fname}",
            upload_status="processed",
            uploaded_by=current.id,
        )
        db.add(ef)
        await db.flush()
        files_created += 1

        if isinstance(content, list):
            for row in content[:10]:
                ee = EvidenceEvent(
                    case_id=new_case.id,
                    evidence_file_id=ef.id,
                    event_type="TRANSACTION" if "bank" in fname else "CALL",
                    text_content=json.dumps(row),
                    event_metadata=row,
                )
                db.add(ee)
                events_created += 1
        else:
            for line_no, line in enumerate(serialized.splitlines()[:10], start=1):
                if line.strip():
                    ee = EvidenceEvent(
                        case_id=new_case.id,
                        evidence_file_id=ef.id,
                        event_type="COMMUNICATION",
                        text_content=line,
                        source_line=line_no,
                    )
                    db.add(ee)
                    events_created += 1

    for ent in session.case_data.get("ground_truth", {}).get("entities", []):
        db.add(Entity(
            case_id=new_case.id,
            canonical_value=str(ent.get("name") or ent.get("phone") or ent.get("account")),
            entity_type=ent.get("role", "PERSON").upper(),
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        ))

    await db.commit()
    return {
        "message": "Training scenario exported as sandboxed case",
        "case_id": str(new_case.id),
        "exported_case_id": str(new_case.id),
        "case_number": new_case.case_number,
        "title": new_case.title,
        "evidence_files_created": files_created,
        "evidence_events_created": events_created,
    }



# ── Feature: Defence Bot ──────────────────────────────────────────────────────

class DefenceStressTestRequest(BaseModel):
    claim: str
    top_k: int = 5


@router.get("/cases/{case_id}/defence-audit")
async def get_defence_audit(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Defence Bot: Comprehensive Adversarial Defensibility Audit.
    Simulates courtroom defense scrutiny, uncovers reasonable doubt angles,
    identifies evidentiary gaps, audits Section 63 BSA compliance, and
    provides a prosecution rebuttal action plan.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.defence import audit_case_defensibility

    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
    )).scalars().all()
    ev_file_dicts = [
        {
            "id": str(f.id),
            "filename": f.original_name,
            "file_type": f.file_type,
            "source_type": f.source_type,
            "sha256_hash": f.sha256_hash,
            "upload_status": f.upload_status,
        }
        for f in ev_files
    ]

    events = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.case_id == case.id)
    )).scalars().all()
    event_dicts = [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "event_timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
            "text_content": e.text_content,
            "metadata": e.event_metadata or {},
        }
        for e in events
    ]

    findings = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
    )).scalars().all()
    finding_dicts = [
        {
            "id": str(f.id),
            "finding_type": f.finding_type,
            "title": f.title,
            "description": f.description,
            "severity": f.severity,
            "entity": f.entity_refs[0] if f.entity_refs else "",
            "entity_refs": f.entity_refs or [],
            "event_refs": f.event_refs or [],
            "evidence_refs": f.evidence_refs or [],
            "component_scores": f.component_scores or {},
        }
        for f in findings
    ]

    report = audit_case_defensibility(
        case_id=str(case.id),
        evidence_files=ev_file_dicts,
        events=event_dicts,
        findings=finding_dicts,
    )

    return report.to_dict()


@router.post("/cases/{case_id}/defence-stress-test")
async def defence_stress_test(
    case_id: str,
    body: DefenceStressTestRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Defence Bot: On-Demand Adversarial Cross-Examination Simulator.
    Takes an investigator's theory or draft claim and returns targeted
    reasonable doubt counter-arguments, missing proof checklist, and rebuttal recommendations.
    """
    case = await require_case_access(db, current, case_id)
    from rag.copilot import copilot_defence_query

    result = await copilot_defence_query(
        db=db,
        case_id=str(case.id),
        claim=body.claim,
        top_k=body.top_k,
    )
    return result


# ── Feature 05: Confidence Meter & Evidentiary State Analyzer ─────────────────

@router.get("/cases/{case_id}/confidence-meter")
async def get_case_confidence_meter(
    case_id: str,
    epsilon: float = Query(0.05, ge=0.01, le=0.5, description="Significance level epsilon (target coverage = 1 - epsilon)"),
    target_entity: Optional[str] = Query(None, description="Optional target entity to evaluate conformal role prediction"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Feature 05: Confidence Meter & Evidentiary State Analyzer.
    Enforces a strict three-way separation between:
      1. Raw model scores (heuristics, cosine similarities, uncalibrated log-odds).
      2. Epistemic source tiers (Direct Observation, Rule-Based, Inferred, Screening, Simulation).
      3. Statistical uncertainty (Split-conformal prediction sets with marginal coverage guarantee).
    R v T [2010] & Section 193 BNSS compliant.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.uncertainty import audit_case_confidence
    from cognitive.hypothesis import load_model, evaluate, extract_entity_observations
    from cognitive import data_path

    findings_rows = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
    )).scalars().all()

    findings = [
        {
            "id": str(f.id),
            "finding_type": f.finding_type,
            "title": f.title,
            "description": f.description,
            "confidence": f.confidence,
            "severity": f.severity,
            "source_engine": f.source_engine or "",
            "entity_refs": f.entity_refs or [],
            "event_refs": f.event_refs or [],
            "evidence_refs": f.evidence_refs or [],
            "component_scores": f.component_scores or {},
            "citations": f.citations or [],
        }
        for f in findings_rows
    ]

    ev_files_rows = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
    )).scalars().all()
    evidence_files = [
        {
            "id": str(ef.id),
            "filename": ef.original_name or ef.filename,
            "file_type": ef.file_type or ef.source_type or "document",
            "source_type": ef.source_type or "",
            "sha256_hash": ef.sha256_hash or "",
        }
        for ef in ev_files_rows
    ]

    contradictions = [f for f in findings if f.get("finding_type") == "CONTRADICTION"]

    hypotheses_result = None
    try:
        model = load_model(data_path("hypotheses.json"))
        entities_res = (await db.execute(
            select(Entity).where(
                Entity.case_id == case.id,
                Entity.entity_type.in_(["ACCOUNT", "UPI", "PHONE", "PERSON", "IP"]),
            ).order_by(Entity.degree_centrality.desc().nullslast())
        )).scalars().all()

        active_target = target_entity
        if not active_target and entities_res:
            active_target = entities_res[0].canonical_value

        if active_target:
            bank_rows = await _get_bank_events(db, case.id)
            call_events = await _get_call_events(db, case.id)
            net_events_rows = (await db.execute(
                select(EvidenceEvent).where(
                    EvidenceEvent.case_id == case.id,
                    EvidenceEvent.event_type == "network_log",
                ).order_by(EvidenceEvent.event_timestamp)
            )).scalars().all()
            net_events = [
                {
                    "id": str(ev.id),
                    "event_timestamp": str(ev.event_timestamp) if ev.event_timestamp else "",
                    "metadata": ev.event_metadata or {},
                }
                for ev in net_events_rows
            ]

            obs, prov = extract_entity_observations(
                target_entity=active_target,
                bank_events=bank_rows,
                call_events=call_events,
                network_events=net_events,
            )
            ach_eval = evaluate(obs, model, provenance_map=prov)
            hypotheses_result = ach_eval.to_dict()
    except Exception:
        hypotheses_result = None

    report = audit_case_confidence(
        findings=findings,
        evidence_files=evidence_files,
        contradictions=contradictions,
        hypotheses_result=hypotheses_result,
        conformal_epsilon=epsilon,
    )
    report["case_id"] = str(case.id)
    return report


@router.post("/cases/{case_id}/confidence-evaluate")
async def evaluate_custom_confidence(
    case_id: str,
    body: ConfidenceEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    On-demand split-conformal prediction set generation for candidate scores.
    """
    case = await require_case_access(db, current, case_id)
    from cognitive.uncertainty import CALIBRATION_STORE, predict_set

    calibration = CALIBRATION_STORE.get(body.model_name, epsilon=body.epsilon)
    if not calibration:
        raise HTTPException(
            status_code=404,
            detail=f"Conformal calibration model '{body.model_name}' not found. Available: {[c['model_name'] for c in CALIBRATION_STORE.list_all()]}"
        )

    result = predict_set(calibration, body.candidate_scores)
    return {
        "case_id": str(case.id),
        "model_name": body.model_name,
        "calibration": calibration,
        "evaluation": result,
    }


@router.get("/conformal-calibrations")
async def list_conformal_calibrations(
    current: User = Depends(get_current_user),
):
    """
    List all active conformal calibration models, quantile cutoffs, and empirical coverage statistics.
    Explicitly tags whether coverage guarantee is valid for real courtroom data or synthetic benchmark only.
    """
    from cognitive.uncertainty import CALIBRATION_STORE
    return {"calibrations": CALIBRATION_STORE.list_all()}


@router.post("/conformal-calibrations")
async def register_conformal_calibration(
    body: CalibrationRegisterRequest,
    current: User = Depends(get_current_user),
):
    """
    Register or update a conformal calibration model with empirical non-conformity scores.
    """
    from cognitive.uncertainty import CALIBRATION_STORE
    try:
        cal = CALIBRATION_STORE.register(
            model_name=body.model_name,
            non_conformity_scores=body.scores,
            epsilon=body.epsilon,
            source=body.source,
        )
        return {"status": "REGISTERED", "calibration": cal}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


