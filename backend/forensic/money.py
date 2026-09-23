from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Money Trail Lens Builder
Projects canonical financial evidence into structured flow graphs, ledger rows,
and investigative signals with strict provenance preservation.
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, EvidenceEvent, Entity, Relationship, InvestigationFinding, EvidenceFile
from forensic.contracts import (
    LensEntity,
    LensEvent,
    LensRelationship,
    LensSignal,
    LensFinding,
    EvidenceRef,
    LensTimelineEvent,
)
import graph.relationship_types as RT


def parse_amount(val: Any) -> float | None:
    """Safely parse Indian monetary value string or number to float."""
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


DEFAULT_RAPID_TRANSFER_WINDOW_MINUTES: int = 60
DEFAULT_ROUND_NUMBER_INCREMENTS: tuple[int, ...] = (10000, 50000)


async def build_money_lens(
    db: AsyncSession,
    case: Case,
    entity_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    cutoff_timestamp: Optional[datetime] = None,
    rapid_window_minutes: int = DEFAULT_RAPID_TRANSFER_WINDOW_MINUTES,
    round_increments: tuple[int, ...] = DEFAULT_ROUND_NUMBER_INCREMENTS,
) -> dict[str, Any]:
    """
    Build the Money Trail Lens projection.
    Strictly read-only; no database rows are mutated.
    """
    case_id = case.id

    # 1. Fetch financial evidence events
    query = (
        select(EvidenceEvent)
        .where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type.in_(["bank_txn", "upi_txn", "financial", "transaction"]),
        )
        .order_by(EvidenceEvent.event_timestamp.asc().nulls_last())
    )
    if cutoff_timestamp:
        query = query.where(EvidenceEvent.created_at < cutoff_timestamp)

    events_raw = list((await db.execute(query)).scalars().all())

    # 2. Filter events by time range
    filtered_events: list[EvidenceEvent] = []
    for ev in events_raw:
        if ev.event_timestamp:
            ev_ts = ev.event_timestamp
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            if start_time and ev_ts < start_time:
                continue
            if end_time and ev_ts > end_time:
                continue
        filtered_events.append(ev)

    # 3. Process events, build ledger, extract accounts and signals
    signals: list[LensSignal] = []
    transactions: list[LensEvent] = []
    events: list[LensEvent] = transactions
    timeline_events: list[LensTimelineEvent] = []
    evidence_file_ids: set[uuid.UUID] = set()

    total_volume: float = 0.0
    total_debit: float = 0.0
    total_credit: float = 0.0
    counterparties: dict[str, float] = defaultdict(float)
    account_nodes: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "id": "",
        "canonical_value": "",
        "entity_type": "ACCOUNT",
        "role": "ACCOUNT",
        "mention_count": 0,
        "total_volume": 0.0,
    })

    timestamped_txns: list[tuple[datetime, EvidenceEvent, float, str]] = []

    for ev in filtered_events:
        meta = ev.event_metadata or {}
        debit = parse_amount(meta.get("debit") or meta.get("withdrawal"))
        credit = parse_amount(meta.get("credit") or meta.get("deposit"))
        balance = parse_amount(meta.get("balance"))

        amt = debit or credit or parse_amount(meta.get("amount")) or 0.0
        direction = "DEBIT" if debit else ("CREDIT" if credit else meta.get("direction", "TRANSFER"))
        if debit:
            total_debit += debit
        if credit:
            total_credit += credit
        total_volume += amt

        sender = meta.get("sender") or meta.get("source_account") or meta.get("account") or "Unknown"
        receiver = meta.get("receiver") or meta.get("target_account") or meta.get("vpa") or meta.get("beneficiary") or "Unknown"
        narration = meta.get("narration") or meta.get("description") or getattr(ev, "text_content", "") or getattr(ev, "summary", "") or ""
        if narration:
            counterparties[narration[:50]] += amt

        # Provenance metadata
        source_doc = meta.get("source_doc")
        source_page = ev.source_page
        source_line = ev.source_line

        if ev.evidence_file_id:
            evidence_file_ids.add(ev.evidence_file_id)

        ev_time_iso = ev.event_timestamp.isoformat() if ev.event_timestamp else None
        time_conf = "CONFIRMED" if ev.event_timestamp else "RECORDED_ONLY"

        if ev.event_timestamp:
            timestamped_txns.append((ev.event_timestamp, ev, amt, narration))

        summary_label = f"₹{amt:,.2f} ({direction}) {sender} ➔ {receiver}"
        events.append(
            LensEvent(
                id=str(ev.id),
                event_type=ev.event_type,
                event_time=ev_time_iso,
                recorded_at=ev.created_at.isoformat() if ev.created_at else datetime.now(timezone.utc).isoformat(),
                time_confidence=time_conf,
                summary=summary_label,
                details={
                    "amount": amt,
                    "direction": direction,
                    "sender": sender,
                    "receiver": receiver,
                    "source_account": sender,
                    "target_account": receiver,
                    "narration": narration,
                    "channel": meta.get("channel", "BANK"),
                },
                evidence_file_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
                provenance_confidence=meta.get("confidence", 0.95),
            )
        )

        timeline_events.append(
            LensTimelineEvent(
                id=str(ev.id),
                timestamp=ev_time_iso,
                label=summary_label,
                category="FINANCIAL",
                entities=[p for p in [sender, receiver] if p and p != "Unknown"],
                evidence_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
            )
        )

        # Track account statistics
        acc = sender if sender != "Unknown" else receiver
        if acc not in account_nodes:
            account_nodes[acc] = {
                "id": str(uuid.uuid4()),
                "canonical_value": acc,
                "entity_type": "ACCOUNT" if not acc.endswith("@") and "@" not in acc else "UPI",
                "role": "ACCOUNT",
                "mention_count": 0,
                "total_volume": 0.0,
            }
        account_nodes[acc]["mention_count"] += 1
        account_nodes[acc]["total_volume"] += amt

        # Round number signal (heuristic pattern)
        is_round = any(amt >= inc and amt % inc == 0 for inc in round_increments) or (amt >= 5000 and amt % 1000 == 0)
        if is_round:
            signals.append(
                LensSignal(
                    id=str(uuid.uuid4()),
                    signal_type="ROUND_NUMBER_TXN",
                    severity="LOW",
                    title=f"Heuristic Pattern Signal: Round-Number Transaction (₹{amt:,.0f})",
                    description=f"Analytical heuristic: Transaction of exactly ₹{amt:,.0f} observed ({direction.lower()}) with narration '{narration[:60]}'.",
                    timestamp=ev_time_iso,
                    entities_involved=[acc],
                    evidence_refs=[str(ev.evidence_file_id)] if ev.evidence_file_id else [],
                    event_refs=[str(ev.id)],
                    metrics={
                        "amount": amt,
                        "direction": direction,
                        "source_doc": source_doc,
                        "source_page": source_page,
                        "source_line": source_line,
                    },
                )
            )

    # 4. Rapid Transfer Signal Detection (configurable rapid_window_minutes)
    timestamped_txns.sort(key=lambda x: x[0])
    rapid_window_sec = rapid_window_minutes * 60
    for i in range(len(timestamped_txns) - 1):
        t1, ev1, amt1, narr1 = timestamped_txns[i]
        t2, ev2, amt2, narr2 = timestamped_txns[i + 1]
        gap_sec = (t2 - t1).total_seconds()
        if 0 < gap_sec <= rapid_window_sec:
            gap_min = round(gap_sec / 60, 1)
            signals.append(
                LensSignal(
                    id=str(uuid.uuid4()),
                    signal_type="RAPID_TRANSFER",
                    severity="MEDIUM",
                    title=f"Heuristic Pattern Signal: Rapid Velocity Transfer ({gap_min} min)",
                    description=(
                        f"Analytical heuristic: Transfer pair observed in rapid succession: ₹{amt1:,.2f} followed by ₹{amt2:,.2f} "
                        f"with {gap_min} minutes gap (threshold <= {rapid_window_minutes} min)."
                    ),
                    timestamp=t2.isoformat(),
                    entities_involved=[p for p in [ev1.event_metadata.get("account"), ev2.event_metadata.get("account")] if p],
                    evidence_refs=[str(e) for e in [ev1.evidence_file_id, ev2.evidence_file_id] if e],
                    event_refs=[str(ev1.id), str(ev2.id)],
                    metrics={
                        "txn_a_amount": amt1,
                        "txn_b_amount": amt2,
                        "gap_minutes": gap_min,
                        "txn_a_doc": ev1.event_metadata.get("source_doc"),
                        "txn_b_doc": ev2.event_metadata.get("source_doc"),
                        "txn_a_page": ev1.source_page,
                        "txn_b_page": ev2.source_page,
                    },
                )
            )

    # 5. Fetch Canonical Entities from DB
    ent_q = select(Entity).where(Entity.case_id == case_id)
    if cutoff_timestamp:
        ent_q = ent_q.where(Entity.created_at < cutoff_timestamp)
    db_entities = list((await db.execute(ent_q)).scalars().all())

    lens_entities: list[LensEntity] = []
    for e in db_entities:
        if e.entity_type in ["ACCOUNT", "UPI", "PER", "ORG"]:
            lens_entities.append(
                LensEntity(
                    id=str(e.id),
                    canonical_value=e.canonical_value,
                    entity_type=e.entity_type,
                    role="ACCOUNT" if e.entity_type in ["ACCOUNT", "UPI"] else "HOLDER",
                    degree_centrality=e.degree_centrality or 0.0,
                    bridge_score=e.bridge_score or 0.0,
                    mention_count=0,
                    node_metadata=e.node_metadata or {},
                )
            )

    # Add dynamically identified accounts from ledger if not in entities table
    existing_vals = {le.canonical_value.lower() for le in lens_entities}
    for acc_val, acc_info in account_nodes.items():
        if acc_val.lower() not in existing_vals:
            lens_entities.append(
                LensEntity(
                    id=acc_info["id"],
                    canonical_value=acc_info["canonical_value"],
                    entity_type=acc_info["entity_type"],
                    role=acc_info["role"],
                    mention_count=acc_info["mention_count"],
                    node_metadata={"total_volume": acc_info["total_volume"]},
                )
            )

    # 6. Fetch Relationships
    rel_q = select(Relationship).where(Relationship.case_id == case_id)
    if cutoff_timestamp:
        rel_q = rel_q.where(Relationship.created_at < cutoff_timestamp)
    db_rels = list((await db.execute(rel_q)).scalars().all())

    lens_relationships: list[LensRelationship] = []
    for r in db_rels:
        is_canon = RT.is_canonical_eligible(r.epistemic_status, r.verification_status)
        if r.verification_status == RT.REVIEW_REJECTED:
            is_canon = False

        # Only include financial-relevant relationships
        if r.relationship_type in ["TRANSFERRED_TO", "TRANSACTED_WITH", "REGISTERED_TO", "ASSOCIATED_WITH", "SAME_AS"]:
            lens_relationships.append(
                LensRelationship(
                    id=str(r.id),
                    source_entity_id=str(r.source_entity_id),
                    target_entity_id=str(r.target_entity_id),
                    relationship_type=r.relationship_type,
                    direction=r.direction,
                    epistemic_status=r.epistemic_status,
                    verification_status=r.verification_status,
                    is_canonical=is_canon,
                    confidence=r.confidence or 1.0,
                    evidence_refs=[str(ref) for ref in (r.evidence_refs or [])],
                    event_refs=[str(ref) for ref in (r.event_refs or [])],
                    created_by=str(r.created_by) if r.created_by else None,
                )
            )

    # 7. Fetch Findings relevant to financial domain
    find_q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
    if cutoff_timestamp:
        find_q = find_q.where(InvestigationFinding.created_at < cutoff_timestamp)
    db_findings = list((await db.execute(find_q)).scalars().all())

    lens_findings: list[LensFinding] = []
    for f in db_findings:
        if f.finding_type in ["MONEY_FLOW", "ROUND_NUMBER", "RAPID_TRANSFER", "UNUSUAL_VOLUME", "MULE_ACCOUNT", "FINANCIAL_ANOMALY"] or "money" in f.title.lower() or "bank" in f.title.lower() or "upi" in f.title.lower():
            lens_findings.append(
                LensFinding(
                    id=str(f.id),
                    finding_type=f.finding_type,
                    title=f.title,
                    severity=f.severity,
                    confidence=float(f.confidence) if f.confidence is not None else 0.8,
                    status=f.status,
                    freshness_status=getattr(f, "freshness_status", "CURRENT") or "CURRENT",
                    generated_at_case_version=getattr(f, "generated_at_case_version", 1) or 1,
                    evidence_refs=[str(ref) for ref in (f.evidence_refs or [])],
                    entity_refs=[str(ref) for ref in (f.entity_refs or [])],
                    event_refs=[str(ref) for ref in (f.event_refs or [])],
                )
            )

    # 8. Evidence File References
    evidence_refs: list[EvidenceRef] = []
    if evidence_file_ids:
        file_q = select(EvidenceFile).where(EvidenceFile.id.in_(list(evidence_file_ids)))
        db_files = list((await db.execute(file_q)).scalars().all())
        for fl in db_files:
            evidence_refs.append(
                EvidenceRef(
                    id=str(fl.id),
                    file_name=fl.filename,
                    file_type=fl.file_type,
                    sha256=fl.sha256_hash,
                    uploaded_at=fl.uploaded_at.isoformat() if fl.uploaded_at else None,
                )
            )

    summary = {
        "total_transactions": len(transactions),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "net_flow": round(total_credit - total_debit, 2),
        "unique_accounts": len(account_nodes),
        "rapid_transfers_count": len([s for s in signals if s.signal_type == "RAPID_TRANSFER"]),
        "round_number_count": len([s for s in signals if s.signal_type == "ROUND_NUMBER_TXN"]),
        "top_counterparties": sorted(
            [{"name": k, "amount": round(v, 2)} for k, v in counterparties.items()],
            key=lambda x: x["amount"],
            reverse=True,
        )[:10],
    }

    return {
        "summary": summary,
        "entities": lens_entities,
        "events": transactions,
        "relationships": lens_relationships,
        "signals": signals,
        "findings": lens_findings,
        "evidence_refs": evidence_refs,
        "timeline": timeline_events,
    }
