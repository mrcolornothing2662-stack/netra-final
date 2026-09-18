from __future__ import annotations
"""
CyberDrishti AI — Intelligence Analysis Routes
Communication analysis (CDR/WhatsApp) and Financial analysis (bank transactions).
"""
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EvidenceEvent, Entity, EntityMention, User
from db.session import get_db
from orchestration.finding_service import list_findings, serialize_finding
from orchestration.intelligence_state import compute_state, get_state, serialize_state
from orchestration.investigation_orchestrator import InvestigationOrchestrator
from routes.auth import get_current_user
from routes.case_access import require_case_access

router = APIRouter()


# ── Communication Intelligence ────────────────────────────────────────────────

@router.get("/communication/{case_id}")
async def communication_intelligence(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Analyze communication patterns from CDR and WhatsApp evidence.
    Returns call pair frequencies, burst detection, and message analysis.
    """
    case = await require_case_access(db, current, case_id)
    c_id = case.id

    # Fetch call events
    call_events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == c_id,
            EvidenceEvent.event_type == "call",
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()

    # Fetch WhatsApp events
    wa_events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == c_id,
            EvidenceEvent.event_type == "whatsapp_msg",
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()

    # ── Call pair analysis ────────────────────────────────────────────────────
    call_pairs: dict[tuple[str, str], dict] = {}
    all_call_timestamps: list[datetime] = []

    for ev in call_events:
        meta = ev.event_metadata or {}
        # Parser may store caller/callee as None (key present, value None) —
        # `.get(k, "")` returns None in that case, so coerce with `or ""` before strip.
        caller = (meta.get("caller") or "").strip()
        callee = (meta.get("callee") or "").strip()
        if not caller or not callee:
            continue

        # Normalize pair (alphabetical sort for undirected)
        pair_key = tuple(sorted([caller, callee]))
        # CDR parser emits the canonical key `duration_sec` (not `duration`).
        duration = meta.get("duration_sec", 0)
        try:
            dur_sec = int(duration) if str(duration).isdigit() else 0
        except (ValueError, TypeError):
            dur_sec = 0

        if pair_key not in call_pairs:
            call_pairs[pair_key] = {
                "caller": pair_key[0],
                "callee": pair_key[1],
                "call_count": 0,
                "total_duration_sec": 0,
                "first_call": None,
                "last_call": None,
                "timestamps": [],
            }

        entry = call_pairs[pair_key]
        entry["call_count"] += 1
        entry["total_duration_sec"] += dur_sec

        if ev.event_timestamp:
            ts = ev.event_timestamp
            all_call_timestamps.append(ts)
            entry["timestamps"].append(ts.isoformat())
            if entry["first_call"] is None or ts < datetime.fromisoformat(entry["first_call"]):
                entry["first_call"] = ts.isoformat()
            if entry["last_call"] is None or ts > datetime.fromisoformat(entry["last_call"]):
                entry["last_call"] = ts.isoformat()

    # ── Burst detection (>= 3 calls within 30 minutes) ────────────────────────
    bursts = []
    sorted_ts = sorted(all_call_timestamps)
    BURST_WINDOW_SEC = 1800   # 30 minutes
    BURST_MIN_CALLS = 3

    i = 0
    while i < len(sorted_ts):
        j = i
        while j < len(sorted_ts) and (sorted_ts[j] - sorted_ts[i]).total_seconds() <= BURST_WINDOW_SEC:
            j += 1
        count = j - i
        if count >= BURST_MIN_CALLS:
            bursts.append({
                "start": sorted_ts[i].isoformat(),
                "end": sorted_ts[j - 1].isoformat(),
                "call_count": count,
                "duration_minutes": round((sorted_ts[j - 1] - sorted_ts[i]).total_seconds() / 60, 1),
            })
        i += 1

    # ── WhatsApp sender analysis ──────────────────────────────────────────────
    sender_stats: dict[str, dict] = {}
    hour_distribution: dict[int, int] = defaultdict(int)

    for ev in wa_events:
        meta = ev.event_metadata or {}
        sender = (meta.get("sender") or "Unknown").strip()

        if sender not in sender_stats:
            sender_stats[sender] = {
                "sender": sender,
                "message_count": 0,
                "first_message": None,
                "last_message": None,
            }

        s = sender_stats[sender]
        s["message_count"] += 1

        if ev.event_timestamp:
            ts = ev.event_timestamp
            hour_distribution[ts.hour] += 1
            if s["first_message"] is None or ts.isoformat() < s["first_message"]:
                s["first_message"] = ts.isoformat()
            if s["last_message"] is None or ts.isoformat() > s["last_message"]:
                s["last_message"] = ts.isoformat()

    # Sort call pairs by frequency
    sorted_pairs = sorted(call_pairs.values(), key=lambda x: x["call_count"], reverse=True)
    for p in sorted_pairs:
        p.pop("timestamps", None)  # Don't send raw timestamps in list

    return {
        "case_id": case_id,
        "call_pairs": sorted_pairs,
        "call_pair_count": len(sorted_pairs),
        "total_calls": len(call_events),
        "total_whatsapp_messages": len(wa_events),
        "communication_bursts": bursts,
        "whatsapp_senders": sorted(sender_stats.values(), key=lambda x: x["message_count"], reverse=True),
        "hourly_message_distribution": {str(h): c for h, c in sorted(hour_distribution.items())},
    }


# ── Financial Intelligence ────────────────────────────────────────────────────

@router.get("/financial/{case_id}")
async def financial_intelligence(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Analyze financial patterns from bank transaction evidence.
    Returns transaction pairs, money flow, round-number signals, rapid transfers.
    """
    case = await require_case_access(db, current, case_id)
    c_id = case.id

    bank_events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == c_id,
            EvidenceEvent.event_type == "bank_txn",
        ).order_by(EvidenceEvent.event_timestamp)
    )).scalars().all()

    transactions = []
    total_debit = 0.0
    total_credit = 0.0
    round_number_txns = []
    narration_stats: dict[str, float] = defaultdict(float)

    for ev in bank_events:
        meta = ev.event_metadata or {}
        parse_status = meta.get("parser_status", "OK")
        # `narration` may be present with a None value (the parser stores None for
        # an empty narration), so a `.get(key, default)` would return None and
        # `.strip()` would raise → HTTP 500. Coerce with `or`.
        narration = (meta.get("narration") or meta.get("description") or "").strip()
        # Never surface parser corruption as transaction text.
        if parse_status == "PARSE_ERROR" or meta.get("narration_valid") is False:
            narration = "Unparsed transaction"

        debit = _parse_amount(meta.get("debit") or meta.get("withdrawal"))
        credit = _parse_amount(meta.get("credit") or meta.get("deposit"))
        balance = _parse_amount(meta.get("balance"))

        txn = {
            "id": str(ev.id),
            "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            "narration": narration,
            "debit": debit,
            "credit": credit,
            "balance": balance,
            "source_line": ev.source_line,
            "source_page": ev.source_page,
            "source_doc": (meta.get("source_doc", "")),
            "parse_status": parse_status,
        }
        transactions.append(txn)
        total_debit += debit or 0.0
        total_credit += credit or 0.0

        # Round-number detection (multiples of 1000, >=5000)
        for amt in [debit, credit]:
            if amt and amt >= 5000 and amt % 1000 == 0:
                round_number_txns.append({
                    "amount": amt,
                    "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                    "narration": narration,
                    "direction": "debit" if amt == debit else "credit",
                })

        # Narration-based counterparty tracking
        if narration:
            amount = debit or credit or 0.0
            narration_stats[narration[:60]] += amount

    # ── Rapid transfer detection (>= 2 transactions within 2 hours) ──────────
    rapid_transfers = []
    timestamped = [
        (ev.event_timestamp, ev)
        for ev in bank_events if ev.event_timestamp
    ]
    timestamped.sort(key=lambda x: x[0])

    RAPID_WINDOW_SEC = 7200  # 2 hours
    for i in range(len(timestamped) - 1):
        ts_a, ev_a = timestamped[i]
        ts_b, ev_b = timestamped[i + 1]
        diff_sec = (ts_b - ts_a).total_seconds()
        if diff_sec <= RAPID_WINDOW_SEC:
            meta_a = ev_a.event_metadata or {}
            meta_b = ev_b.event_metadata or {}
            rapid_transfers.append({
                "txn_a_id": str(ev_a.id),
                "txn_b_id": str(ev_b.id),
                "txn_a_ts": ts_a.isoformat(),
                "txn_b_ts": ts_b.isoformat(),
                "gap_minutes": round(diff_sec / 60, 1),
                "txn_a_narration": (meta_a.get("narration") or "")[:60],
                "txn_b_narration": (meta_b.get("narration") or "")[:60],
            })

    # Top counterparties by volume
    top_counterparties = sorted(
        [{"narration": k, "total_amount": round(v, 2)} for k, v in narration_stats.items()],
        key=lambda x: x["total_amount"],
        reverse=True,
    )[:20]

    return {
        "case_id": case_id,
        "total_transactions": len(transactions),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "net_flow": round(total_credit - total_debit, 2),
        "transactions": transactions[:200],  # cap for response size
        "round_number_transactions": round_number_txns,
        "rapid_transfers": rapid_transfers,
        "top_counterparties_by_volume": top_counterparties,
    }


# ── Unified findings / intelligence state / orchestration ─────────────────────

@router.post("/cases/{case_id}/analyze")
async def analyze_case(
    case_id: str,
    body:    dict | None = Body(None),
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Run the cognitive orchestrator over the case's current evidence. Selects
    only applicable engines, persists their unified findings and refreshes the
    intelligence state. Records an AnalysisRun either way.
    """
    case = await require_case_access(db, current, case_id, write=True)
    engine_names = (body or {}).get("engines")
    try:
        result = await InvestigationOrchestrator().run(
            db, case.id, trigger="manual", engine_names=engine_names, actor_id=str(current.id)
        )
    except Exception as exc:
        # Persist the failed run for the audit trail, then surface the error.
        await db.commit()
        raise HTTPException(500, f"Cognitive analysis failed: {exc}")
    await db.commit()
    return result


@router.get("/cases/{case_id}/findings")
async def case_findings(
    case_id:         str,
    finding_type:    str | None = Query(None),
    severity:        str | None = Query(None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"),
    status:          str | None = Query(None, pattern="^(OPEN|CONFIRMED|DISMISSED|SUPERSEDED)$"),
    min_confidence:  float | None = Query(None, ge=0.0, le=1.0),
    limit:           int = Query(200, ge=1, le=1000),
    offset:          int = Query(0, ge=0),
    db:              AsyncSession = Depends(get_db),
    current:         User = Depends(get_current_user),
):
    """Unified findings for a case, ranked by confidence."""
    case = await require_case_access(db, current, case_id)
    rows = await list_findings(
        db, case.id,
        finding_type=finding_type, severity=severity, status=status,
        min_confidence=min_confidence, limit=limit, offset=offset,
    )
    return {
        "case_id": case_id,
        "count":   len(rows),
        "findings": [serialize_finding(row) for row in rows],
    }


@router.get("/cases/{case_id}/state")
async def case_intelligence_state(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Materialised intelligence snapshot; computed live if never analysed."""
    case = await require_case_access(db, current, case_id)
    row = await get_state(db, case.id)
    if row is not None:
        return serialize_state(row, case_id)
    state = await compute_state(db, case.id)
    return {"case_id": case_id, "computed": True, "last_run_at": None, **state}


def _parse_amount(val) -> float | None:
    """Parse Indian monetary value to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
    if not s or s == "-":
        return None
    try:
        multiplier = 1.0
        lower = s.lower()
        if "crore" in lower or "cr" in lower:
            s = lower.replace("crore", "").replace("cr", "").strip()
            multiplier = 1e7
        elif "lakh" in lower or "lac" in lower:
            s = lower.replace("lakh", "").replace("lac", "").strip()
            multiplier = 1e5
        elif s.lower().endswith("k"):
            s = s[:-1].strip()
            multiplier = 1000.0
        return float(s) * multiplier
    except (ValueError, TypeError):
        return None
