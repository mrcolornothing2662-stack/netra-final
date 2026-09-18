from __future__ import annotations
"""
CyberDrishti AI — Case Analytics, Communications, Financial Trail & Cross-Case Intel
Provides structured, real-data endpoints for:
- Case Summary & Investigation Progress (GET /api/v1/cases/{case_id}/summary)
- Communications & CDR Logs (GET /api/v1/cases/{case_id}/communications)
- Financial Trail & Velocity Analysis (GET /api/v1/cases/{case_id}/transactions)
- Cross-Case Intelligence Search (GET /api/v1/intel/cross-match)
- Live Server-Sent Events (GET /api/v1/events/cases/{case_id})
"""
import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case, EvidenceFile, EvidenceEvent, Entity, EntityMention,
    Correlation, AuditLog, User
)
from db.session import get_db, AsyncSessionLocal
from routes.auth import get_current_user, get_current_user_token_or_header
from routes.case_access import require_case_access

router = APIRouter()
intel_router = APIRouter()
events_router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CaseProgress(BaseModel):
    evidence_collection: int
    entity_extraction: int
    correlation_analysis: int
    financial_analysis: int
    report_ready: int


class FindingItem(BaseModel):
    id: str
    title: str
    description: str
    confidence: float
    finding_type: str
    risk_level: str
    related_entities: list[str] = []


class CaseSummaryOut(BaseModel):
    case_id: str
    case_number: str
    title: str
    status: str
    priority: str
    crime_type: Optional[str]
    fir_number: Optional[str]
    police_station: Optional[str]
    lead_officer: Optional[str]
    created_at: str
    counts: dict[str, int]
    progress: CaseProgress
    recent_activity: list[dict[str, Any]]
    findings: list[FindingItem]


class CdrRecord(BaseModel):
    id: str
    caller: str
    recipient: str
    duration_sec: Optional[int]
    duration_formatted: str
    call_type: Optional[str]
    timestamp: Optional[str]
    tower: Optional[str]
    imei: Optional[str]
    source_file: Optional[str]
    is_suspect: bool = False
    risk_reason: Optional[str] = None


class ChatMessage(BaseModel):
    id: str
    sender: str
    sender_name: Optional[str]
    recipient: Optional[str]
    text: str
    timestamp: Optional[str]
    source_file: Optional[str]
    is_system: bool = False
    is_suspect: bool = False
    entities_detected: list[dict[str, str]] = []


class CommunicationsResponse(BaseModel):
    case_id: str
    total_calls: int
    total_messages: int
    unique_numbers: int
    suspicious_contacts_count: int
    calls: list[CdrRecord]
    messages: list[ChatMessage]


class TransactionRecord(BaseModel):
    id: str
    timestamp: Optional[str]
    narration: str
    debit: Optional[float]
    credit: Optional[float]
    amount: float
    balance: Optional[float]
    ref_no: Optional[str]
    from_entity: str
    to_entity: str
    method: str
    status: str = "success"
    flagged: bool = False
    reason: Optional[str] = None
    source_file: Optional[str] = None
    parse_status: str = "OK"
    parse_errors: Optional[list[str]] = None


class FlowNode(BaseModel):
    id: str
    label: str
    entity_type: str
    is_source: bool = False
    is_mule: bool = False
    is_sink: bool = False


class FlowEdge(BaseModel):
    id: str
    source: str
    target: str
    amount: float
    method: str
    timestamp: Optional[str]
    flagged: bool = False


class FinancialTrailResponse(BaseModel):
    case_id: str
    total_volume: float
    flagged_volume: float
    total_transactions: int
    unique_accounts: int
    mule_accounts_count: int
    transactions: list[TransactionRecord]
    flow_graph: dict[str, list[Any]]


class CrossMatchItem(BaseModel):
    case_id: str
    case_number: str
    case_title: str
    crime_type: Optional[str]
    priority: str
    status: str
    entity_value: str
    entity_type: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    mention_count: int


class CrossMatchResponse(BaseModel):
    query: str
    normalized_query: str
    total_matches: int
    matches: list[CrossMatchItem]


class SyndicateCaseItem(BaseModel):
    case_id: str
    case_number: str
    case_title: str
    crime_type: Optional[str] = None
    priority: str
    status: str


class SyndicateEntityOut(BaseModel):
    canonical_value: str
    entity_type: str
    case_count: int
    cases: list[SyndicateCaseItem] = []


class SyndicateListResponse(BaseModel):
    total_syndicates: int
    syndicates: list[SyndicateEntityOut]


# ── Helper Functions ──────────────────────────────────────────────────────────

def _resolve_case_uuid(case_id: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(case_id)
    except Exception:
        return None


def _format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "--"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _extract_payment_method(text: str) -> str:
    upper = text.upper()
    if "UPI" in upper or "@" in text:
        return "UPI"
    if "IMPS" in upper:
        return "IMPS"
    if "NEFT" in upper:
        return "NEFT"
    if "RTGS" in upper:
        return "RTGS"
    if "ATM" in upper or "CASH" in upper or "WDL" in upper:
        return "ATM / Cash"
    return "Bank Transfer"


# ── Endpoints: Case Summary ───────────────────────────────────────────────────

@router.get("/{case_id}/summary", response_model=CaseSummaryOut)
async def get_case_summary(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Returns consolidated case investigation status, progress metrics, and key findings."""
    case = await require_case_access(db, current, case_id)
    case_uuid = case.id

    # Counts
    ev_count = (await db.execute(
        select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
    )).scalar() or 0

    entity_count = (await db.execute(
        select(func.count()).select_from(Entity).where(Entity.case_id == case_uuid)
    )).scalar() or 0

    event_count = (await db.execute(
        select(func.count()).select_from(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
    )).scalar() or 0

    conn_count = (await db.execute(
        select(func.count()).select_from(Correlation).where(Correlation.case_id == case_uuid)
    )).scalar() or 0

    flagged_conn_count = (await db.execute(
        select(func.count()).select_from(Correlation).where(
            Correlation.case_id == case_uuid, Correlation.decision == "flagged"
        )
    )).scalar() or 0

    # Investigation Progress Calculation
    progress_ev = min(100, ev_count * 35) if ev_count > 0 else 0
    progress_ent = 100 if entity_count > 0 else 0
    progress_corr = 100 if conn_count > 0 else (60 if entity_count > 2 else 0)
    
    # Check bank events
    bank_ev_count = (await db.execute(
        select(func.count()).select_from(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid, EvidenceEvent.event_type == "bank_txn"
        )
    )).scalar() or 0
    progress_fin = 100 if bank_ev_count > 0 else (30 if ev_count > 0 else 0)
    progress_rep = 100 if (ev_count > 0 and entity_count > 0) else 15

    # Lead officer name
    lead_officer_name = None
    if case.assigned_officer_id:
        officer = await db.get(User, case.assigned_officer_id)
        if officer:
            lead_officer_name = officer.full_name or officer.username

    # Recent activity from audit log for this specific case only
    recent_logs = (await db.execute(
        select(AuditLog).where(
            AuditLog.resource_id == str(case_uuid)
        ).order_by(desc(AuditLog.event_timestamp)).limit(5)
    )).scalars().all()

    recent_activity = []
    for l in recent_logs:
        recent_activity.append({
            "id": l.id,
            "action": l.action,
            "timestamp": l.event_timestamp.isoformat() if l.event_timestamp else "",
            "details": l.details_json or {},
        })

    # High confidence findings from flagged correlations & transactions
    findings: list[FindingItem] = []
    flagged_corrs = (await db.execute(
        select(Correlation).where(
            Correlation.case_id == case_uuid, Correlation.decision == "flagged"
        ).limit(5)
    )).scalars().all()

    for fc in flagged_corrs:
        findings.append(FindingItem(
            id=str(fc.id),
            title="Suspicious Hidden Connection Discovered",
            description=f"Strong behavioral and temporal correlation detected between entities (Score: {fc.final_score:.2f})",
            confidence=round(fc.final_score, 2),
            finding_type="HIDDEN_LINK",
            risk_level="HIGH" if fc.final_score > 0.85 else "MEDIUM",
            related_entities=[],
        ))

    if not findings and entity_count > 0:
        findings.append(FindingItem(
            id="f-initial",
            title="Cross-Evidence Entity Graph Constructed",
            description=f"{entity_count} unique entities extracted across {ev_count} evidence files.",
            # Deterministic count of extracted entities — not a probabilistic score.
            confidence=1.0,
            finding_type="ENTITY_GRAPH",
            risk_level="LOW",
            related_entities=[],
        ))

    return CaseSummaryOut(
        case_id=str(case.id),
        case_number=case.case_number,
        title=case.title,
        status=case.status,
        priority=case.priority,
        crime_type=case.crime_type,
        fir_number=case.fir_number,
        police_station=case.police_station,
        lead_officer=lead_officer_name,
        created_at=case.created_at.isoformat() if case.created_at else "",
        counts={
            "evidence": ev_count,
            "entities": entity_count,
            "connections": conn_count,
            "events": event_count,
            "suspicious_findings": flagged_conn_count + len(findings),
        },
        progress=CaseProgress(
            evidence_collection=progress_ev,
            entity_extraction=progress_ent,
            correlation_analysis=progress_corr,
            financial_analysis=progress_fin,
            report_ready=progress_rep,
        ),
        recent_activity=recent_activity,
        findings=findings,
    )


# ── Endpoints: Communications & CDR ──────────────────────────────────────────

@router.get("/{case_id}/communications", response_model=CommunicationsResponse)
async def get_case_communications(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Extracts real Call Detail Records (CDR) and WhatsApp chat transcripts for the case."""
    case = await require_case_access(db, current, case_id)
    case_uuid = case.id

    # Fetch evidence events
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(["call", "whatsapp_msg", "chat"])
        ).order_by(EvidenceEvent.event_timestamp.asc())
    )).scalars().all()

    # Fetch evidence files map for source doc names
    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
    )).scalars().all()
    file_map = {f.id: f.original_name for f in ev_files}

    # Fetch mentions for entities detected
    mention_rows = (await db.execute(
        select(EntityMention, Entity)
        .join(Entity, EntityMention.entity_id == Entity.id)
        .where(Entity.case_id == case_uuid)
    )).all()

    mentions_by_event: dict[str, list[dict[str, str]]] = {}
    for mention, entity in mention_rows:
        mentions_by_event.setdefault(str(mention.evidence_event_id), []).append({
            "type": entity.entity_type,
            "value": entity.canonical_value,
        })

    calls: list[CdrRecord] = []
    messages: list[ChatMessage] = []
    phone_set: set[str] = set()
    suspicious_contacts: set[str] = set()

    suspect_keywords = [
        "kyc", "otp", "apk", "transfer", "block", "urgent", "lottery",
        "pin", "password", "bank", "freeze", "account", "police", "arrest"
    ]

    for ev in events:
        ev_id = str(ev.id)
        meta = ev.event_metadata or {}
        source_doc = file_map.get(ev.evidence_file_id, "Evidence Document")

        if ev.event_type == "call":
            caller = meta.get("caller") or "Unknown"
            callee = meta.get("callee") or "Unknown"
            dur_sec = meta.get("duration_sec")
            tower = meta.get("cell_id") or meta.get("location")
            imei = meta.get("imei")
            call_type = meta.get("call_type") or "Voice Call"

            if caller != "Unknown":
                phone_set.add(caller)
            if callee != "Unknown":
                phone_set.add(callee)

            # Mark suspect if duration is anomalous or caller repeats
            is_susp = False
            risk_reason = None
            if dur_sec and dur_sec > 600:
                is_susp = True
                risk_reason = "Prolonged call duration with potential syndicate member"
            elif call_type and "international" in call_type.lower():
                is_susp = True
                risk_reason = "International gateway call routing"

            if is_susp and caller != "Unknown":
                suspicious_contacts.add(caller)

            calls.append(CdrRecord(
                id=ev_id,
                caller=caller,
                recipient=callee,
                duration_sec=dur_sec,
                duration_formatted=_format_duration(dur_sec),
                call_type=call_type,
                timestamp=ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                tower=tower,
                imei=imei,
                source_file=source_doc,
                is_suspect=is_susp,
                risk_reason=risk_reason,
            ))

        elif ev.event_type in ("whatsapp_msg", "chat"):
            sender = meta.get("sender") or "Participant"
            text_body = ev.text_content or ""
            is_sys = meta.get("is_system", False) or sender == "__system__"
            
            # Check suspicious keyword triggers
            is_susp = any(kw in text_body.lower() for kw in suspect_keywords)
            if is_susp and sender and sender != "Participant":
                suspicious_contacts.add(sender)

            if sender and sender.startswith("+"):
                phone_set.add(sender)

            messages.append(ChatMessage(
                id=ev_id,
                sender=sender,
                sender_name=meta.get("sender_name") or sender,
                recipient=meta.get("recipient"),
                text=text_body,
                timestamp=ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                source_file=source_doc,
                is_system=is_sys,
                is_suspect=is_susp,
                entities_detected=mentions_by_event.get(ev_id, []),
            ))

    return CommunicationsResponse(
        case_id=str(case_uuid),
        total_calls=len(calls),
        total_messages=len(messages),
        unique_numbers=len(phone_set),
        suspicious_contacts_count=len(suspicious_contacts),
        calls=calls,
        messages=messages,
    )


# ── Endpoints: Financial Trail & Velocity ────────────────────────────────────

@router.get("/{case_id}/transactions", response_model=FinancialTrailResponse)
async def get_case_transactions(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Extracts real bank statement transactions, detects rapid layering, and builds directed flow graph."""
    case = await require_case_access(db, current, case_id)
    case_uuid = case.id

    # Fetch bank transaction evidence events
    events = (await db.execute(
        select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(["bank_txn", "transaction"])
        ).order_by(EvidenceEvent.event_timestamp.asc())
    )).scalars().all()

    ev_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
    )).scalars().all()
    file_map = {f.id: f.original_name for f in ev_files}

    transactions: list[TransactionRecord] = []
    total_vol = 0.0
    flagged_vol = 0.0
    accounts_seen: set[str] = set()
    mule_accounts: set[str] = set()

    # Flow Graph nodes and edges
    flow_nodes_map: dict[str, FlowNode] = {}
    flow_edges: list[FlowEdge] = []

    for idx, ev in enumerate(events):
        ev_id = str(ev.id)
        meta = ev.event_metadata or {}
        narration = meta.get("narration") or ev.text_content or "Bank Transaction"
        debit = meta.get("debit")
        credit = meta.get("credit")
        balance = meta.get("balance")
        ref_no = meta.get("ref_no")
        source_doc = file_map.get(ev.evidence_file_id, "Bank Statement")

        # A row the parser could not read reliably is surfaced as PARSE_ERROR —
        # never normalised into a fabricated amount or counterparty.
        parse_status = meta.get("parser_status", "OK")
        parse_errors = meta.get("parse_errors") or []
        if parse_status == "PARSE_ERROR":
            transactions.append(TransactionRecord(
                id=ev_id,
                timestamp=ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                narration=narration,
                debit=None, credit=None, amount=0.0, balance=None,
                ref_no=ref_no,
                from_entity="Unparsed", to_entity="Unparsed",
                method="UNKNOWN",
                status="parse_error",
                flagged=True,
                reason="Parser could not read this transaction reliably",
                source_file=source_doc,
                parse_status=parse_status,
                parse_errors=parse_errors,
            ))
            continue

        amount = float(credit or debit or 0.0)
        total_vol += amount

        # Method extraction
        method = _extract_payment_method(narration)

        # Counterparty is derived ONLY from the transaction narration itself.
        # A VPA/account parsed from the narration is a real counterparty; when
        # none is present we label it "Unidentified counterparty" rather than
        # round-robin-assigning an arbitrary known account (which would fabricate
        # an unproven relationship between the transaction and that account).
        from_ent = "Victim Account"
        to_ent = "Unidentified counterparty"

        # Regex for VPA or Account in narration
        upi_match = re.search(r'[\w.\-]{2,64}@[a-zA-Z]{2,32}', narration)
        acc_match = re.search(r'\b\d{9,18}\b', narration)

        if upi_match:
            to_ent = upi_match.group(0)
        elif acc_match:
            to_ent = f"ACCT-{acc_match.group(0)[-4:]}"

        if debit:
            from_ent = "Victim Account"
        else:
            from_ent = to_ent
            to_ent = "Unidentified counterparty"

        accounts_seen.add(from_ent)
        accounts_seen.add(to_ent)

        # Flagging heuristics: Rapid high amount or round sums
        flagged = False
        reason = None
        if amount >= 50000:
            flagged = True
            reason = "High-value suspicious transfer above standard monitoring threshold"
        elif "crypto" in narration.lower() or "binance" in narration.lower() or "wazirx" in narration.lower():
            flagged = True
            reason = "Crypto exchange P2P off-ramping marker"
            mule_accounts.add(from_ent)
        elif idx > 0 and amount == transactions[-1].amount:
            flagged = True
            reason = "Rapid split layering pass-through"
            mule_accounts.add(from_ent)

        if flagged:
            flagged_vol += amount

        tx_record = TransactionRecord(
            id=ev_id,
            timestamp=ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            narration=narration,
            debit=float(debit) if debit is not None else None,
            credit=float(credit) if credit is not None else None,
            amount=amount,
            balance=float(balance) if balance is not None else None,
            ref_no=ref_no,
            from_entity=from_ent,
            to_entity=to_ent,
            method=method,
            status="success",
            flagged=flagged,
            reason=reason,
            source_file=source_doc,
            parse_status=parse_status,
            parse_errors=parse_errors,
        )
        transactions.append(tx_record)

        # Flow Graph
        if from_ent not in flow_nodes_map:
            flow_nodes_map[from_ent] = FlowNode(
                id=from_ent, label=from_ent, entity_type="ACCOUNT",
                is_source=(from_ent == "Victim Account"), is_mule=(from_ent in mule_accounts)
            )
        if to_ent not in flow_nodes_map:
            flow_nodes_map[to_ent] = FlowNode(
                id=to_ent, label=to_ent, entity_type="UPI" if "@" in to_ent else "ACCOUNT",
                is_sink=("Cash" in to_ent or "ATM" in to_ent), is_mule=(to_ent in mule_accounts)
            )

        flow_edges.append(FlowEdge(
            id=f"e-{ev_id}",
            source=from_ent,
            target=to_ent,
            amount=amount,
            method=method,
            timestamp=ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            flagged=flagged,
        ))

    return FinancialTrailResponse(
        case_id=str(case_uuid),
        total_volume=round(total_vol, 2),
        flagged_volume=round(flagged_vol, 2),
        total_transactions=len(transactions),
        unique_accounts=len(accounts_seen),
        mule_accounts_count=len(mule_accounts),
        transactions=transactions,
        flow_graph={
            "nodes": list(flow_nodes_map.values()),
            "edges": flow_edges,
        },
    )


@intel_router.get("/syndicates", response_model=SyndicateListResponse)
async def list_syndicates(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List cross-case entities spanning across multiple distinct cases to expose organized syndicates."""
    syndicate_q = (
        select(
            Entity.canonical_value,
            Entity.entity_type,
            func.count(func.distinct(Entity.case_id)).label("case_count")
        )
        .where(Entity.entity_type.notin_(["AMOUNT", "KEYWORD"]))
        .group_by(Entity.canonical_value, Entity.entity_type)
        .having(func.count(func.distinct(Entity.case_id)) > 1)
        .order_by(func.count(func.distinct(Entity.case_id)).desc())
        .limit(limit)
    )
    rows = (await db.execute(syndicate_q)).all()

    syndicates = []
    for cv, et, count in rows:
        cases_q = (
            select(Case)
            .join(Entity, Entity.case_id == Case.id)
            .where(Entity.canonical_value == cv, Entity.entity_type == et)
            .distinct()
        )
        c_rows = (await db.execute(cases_q)).scalars().all()
        syndicates.append(SyndicateEntityOut(
            canonical_value=cv,
            entity_type=et,
            case_count=count,
            cases=[
                SyndicateCaseItem(
                    case_id=str(c.id),
                    case_number=c.case_number,
                    case_title=c.title,
                    crime_type=c.crime_type,
                    priority=c.priority,
                    status=c.status,
                )
                for c in c_rows
            ]
        ))

    return SyndicateListResponse(
        total_syndicates=len(syndicates),
        syndicates=syndicates,
    )


@intel_router.get("/cross-match", response_model=CrossMatchResponse)
async def cross_match_intel(
    query: Optional[str] = Query(None, description="Search term across cases"),
    q: Optional[str] = Query(None, description="Alias for search term"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Searches across all cases in the database for matching canonical entities to detect organized crime syndicates."""
    search_term = query or q or ""
    clean_q = search_term.strip()

    norm_q = clean_q.lower().replace("+91", "").replace("-", "").replace(" ", "") if clean_q else ""

    if clean_q:
        matched_entities = (await db.execute(
            select(Entity, Case)
            .join(Case, Entity.case_id == Case.id)
            .where(
                (Entity.entity_type.notin_(["AMOUNT", "KEYWORD"])) &
                (
                    (Entity.canonical_value.ilike(f"%{clean_q}%")) |
                    (Entity.canonical_value.ilike(f"%{norm_q}%"))
                )
            )
            .order_by(Entity.canonical_value)
            .limit(100)
        )).all()
    else:
        # Return matches for top cross-case syndicate entities when no search term given
        top_syndicate_vals = (await db.execute(
            select(Entity.canonical_value)
            .where(Entity.entity_type.notin_(["AMOUNT", "KEYWORD"]))
            .group_by(Entity.canonical_value)
            .having(func.count(func.distinct(Entity.case_id)) > 1)
            .order_by(func.count(func.distinct(Entity.case_id)).desc())
            .limit(10)
        )).scalars().all()

        if top_syndicate_vals:
            matched_entities = (await db.execute(
                select(Entity, Case)
                .join(Case, Entity.case_id == Case.id)
                .where(Entity.canonical_value.in_(top_syndicate_vals))
                .order_by(Entity.canonical_value)
            )).all()
        else:
            matched_entities = []

    matches: list[CrossMatchItem] = []
    for entity, case in matched_entities:
        # Count mentions
        m_count = (await db.execute(
            select(func.count()).select_from(EntityMention).where(EntityMention.entity_id == entity.id)
        )).scalar() or 1

        matches.append(CrossMatchItem(
            case_id=str(case.id),
            case_number=case.case_number,
            case_title=case.title,
            crime_type=case.crime_type,
            priority=case.priority,
            status=case.status,
            entity_value=entity.canonical_value,
            entity_type=entity.entity_type,
            first_seen=entity.first_seen.isoformat() if entity.first_seen else None,
            last_seen=entity.last_seen.isoformat() if entity.last_seen else None,
            mention_count=m_count,
        ))

    return CrossMatchResponse(
        query=search_term or "Top Syndicate IOCs",
        normalized_query=norm_q,
        total_matches=len(matches),
        matches=matches,
    )


# ── Endpoints: Real-Time Server-Sent Events (SSE) ────────────────────────────

@events_router.get("/cases/{case_id}")
async def stream_case_events(
    case_id: str,
    request: Request,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user_token_or_header),
):
    """
    Server-Sent Events channel for a case.

    NOTE: This currently emits only a connection acknowledgement followed by
    periodic heartbeat pings. It does NOT yet stream real ingestion status,
    agent actions, or notifications — no fabricated activity events are emitted.
    Real event streaming is a later-sprint concern.
    """
    # Enforce case access even though the channel is currently ack+heartbeat only
    # — otherwise it would leak the existence of inaccessible cases.
    await require_case_access(db, current, case_id)

    async def event_generator():
        yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'case_id': case_id})}\n\n"

        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(5)
            # Heartbeat ping only — not a live activity event.
            yield f"event: ping\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'heartbeat': True})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
