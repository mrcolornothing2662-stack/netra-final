from __future__ import annotations

"""
NETRA 5.0 — Forensic Structured Retriever
Exact-fact retrieval layer querying PostgreSQL ground-truth records:
- Bank transactions (amounts, accounts, directions, ref_nos, narrations)
- Communications (call logs, whatsapp messages, participants, cell towers)
- Network activity (IPs, ports, destinations, actions)
- Location timeline (cell-site records, timestamps, coordinates)
- Entities & Entity Mentions (canonical resolution, risk/centrality metrics)
- Cognitive findings (syndicate rings, anomalies, hidden links)
- Case summary snapshot (ground-truth metadata and counts)

Enforces strict case boundary isolation on every query:
`assert record.case_id == requested_case_id`
Produces exact StructuredRecordSnippet objects and unified RetrievedItem candidates.
"""

import datetime
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, Entity, EntityMention, EvidenceEvent, EvidenceFile, InvestigationFinding, Relationship
from .config import CopilotConfig, get_copilot_config
from .schemas import (
    CaseContextSnapshot,
    ModalityType,
    QueryIntentType,
    QueryPlan,
    RetrievedItem,
    StructuredRecordContext,
    StructuredRecordSnippet,
)

logger = logging.getLogger(__name__)

# Amount extraction regex: "over 50,000", "greater than 50000", "under 1,00,000", etc.
AMOUNT_OVER_RE = re.compile(
    r"(?:over|above|greater\s+than|>|more\s+than|min(?:imum)?)\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+)",
    re.IGNORECASE,
)
AMOUNT_UNDER_RE = re.compile(
    r"(?:under|below|less\s+than|<|max(?:imum)?)\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+)",
    re.IGNORECASE,
)
AMOUNT_BETWEEN_RE = re.compile(
    r"between\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+)\s*(?:and|to|-)\s*(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+)",
    re.IGNORECASE,
)


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _extract_amount_from_meta(meta: Dict[str, Any]) -> Optional[float]:
    if not isinstance(meta, dict):
        return None
    for k in ("amount", "debit", "credit"):
        val = meta.get(k)
        amt = _safe_float(val)
        if amt is not None:
            return amt
    return None


def _format_currency(amt: Optional[float]) -> str:
    if amt is None:
        return "N/A"
    return f"₹{amt:,.2f}"


def _normalize_dt(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


class StructuredRetriever:
    """Exact-fact investigative retriever operating over PostgreSQL tables."""

    def __init__(self, config: Optional[CopilotConfig] = None):
        self.config = config or get_copilot_config()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. High-Level Plan Adapter
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_for_plan(
        self,
        db: AsyncSession,
        case_id: str,
        plan: QueryPlan,
        limit: Optional[int] = None,
    ) -> Tuple[StructuredRecordContext, List[RetrievedItem]]:
        """
        Extract exact structured records according to the QueryPlan.
        Strictly enforces case_id boundary isolation.
        """
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            logger.warning("Malformed case_id '%s' passed to StructuredRetriever", case_id)
            return StructuredRecordContext(case_id=case_id, records=[]), []

        max_limit = limit or self.config.structured_top_k
        min_amt, max_amt = self._extract_amount_bounds(plan.original_query)

        # Parse target entities
        accounts: List[str] = []
        phones: List[str] = []
        upis: List[str] = []
        ips: List[str] = []
        target_tags: List[str] = list(plan.target_entities)

        for tag in target_tags:
            if ":" in tag:
                etype, val = tag.split(":", 1)
                etype_u = etype.strip().upper()
                v_clean = val.strip()
                if etype_u == "ACCOUNT":
                    accounts.append(v_clean)
                elif etype_u == "PHONE":
                    phones.append(v_clean)
                elif etype_u == "UPI":
                    upis.append(v_clean)
                elif etype_u == "IP":
                    ips.append(v_clean)
            else:
                # Raw identifier heuristics
                if tag.startswith("+") or (tag.isdigit() and len(tag) == 10):
                    phones.append(tag)
                elif "@" in tag:
                    upis.append(tag)
                elif tag.isdigit():
                    accounts.append(tag)

        records: List[StructuredRecordSnippet] = []

        # 1. Transactions
        tx_query_needed = (
            bool(accounts or upis or min_amt is not None or max_amt is not None)
            or any(kw in plan.original_query.lower() for kw in ("transaction", "transfer", "amount", "paid", "credit", "debit", "balance", "bank"))
            or plan.intent in (QueryIntentType.FACTUAL, QueryIntentType.RELATIONAL)
        )
        if tx_query_needed:
            acct_filter = accounts[0] if accounts else None
            upi_filter = upis[0] if upis else None
            tx_snippets = await self.retrieve_transactions(
                db=db,
                case_id=str(case_uuid),
                account=acct_filter,
                upi_id=upi_filter,
                min_amount=min_amt,
                max_amount=max_amt,
                start_time=plan.time_window_start,
                end_time=plan.time_window_end,
                limit=max_limit,
            )
            records.extend(tx_snippets)

        # 2. Communications (Calls / Messages)
        comm_needed = (
            bool(phones)
            or any(kw in plan.original_query.lower() for kw in ("call", "phone", "whatsapp", "chat", "message", "contact", "spoke"))
            or plan.intent in (QueryIntentType.FACTUAL, QueryIntentType.TEMPORAL)
        )
        if comm_needed:
            phone_filter = phones[0] if phones else None
            comm_snippets = await self.retrieve_communications(
                db=db,
                case_id=str(case_uuid),
                participant=phone_filter,
                start_time=plan.time_window_start,
                end_time=plan.time_window_end,
                limit=max_limit,
            )
            records.extend(comm_snippets)

        # 3. Network activity
        net_needed = (
            bool(ips)
            or any(kw in plan.original_query.lower() for kw in ("ip", "network", "port", "packet", "log", "proxy", "vpn"))
        )
        if net_needed:
            ip_filter = ips[0] if ips else None
            net_snippets = await self.retrieve_network_activity(
                db=db,
                case_id=str(case_uuid),
                ip=ip_filter,
                start_time=plan.time_window_start,
                end_time=plan.time_window_end,
                limit=max_limit,
            )
            records.extend(net_snippets)

        # 4. Locations
        loc_needed = any(kw in plan.original_query.lower() for kw in ("location", "tower", "cell", "city", "lat", "lon", "site", "travel"))
        if loc_needed:
            loc_snippets = await self.retrieve_locations(
                db=db,
                case_id=str(case_uuid),
                phone=phones[0] if phones else None,
                start_time=plan.time_window_start,
                end_time=plan.time_window_end,
                limit=max_limit,
            )
            records.extend(loc_snippets)

        # 5. Entities
        ent_snippets = await self.retrieve_entities(
            db=db,
            case_id=str(case_uuid),
            target_tags=target_tags if target_tags else None,
            limit=max_limit,
        )
        records.extend(ent_snippets)

        # 6. Findings
        findings_needed = (
            any(kw in plan.original_query.lower() for kw in ("finding", "anomaly", "suspicious", "flagged", "syndicate", "ring", "mule", "risk"))
            or plan.intent in (QueryIntentType.FACTUAL, QueryIntentType.RELATIONAL, QueryIntentType.ADVERSARIAL)
        )
        if findings_needed:
            finding_snippets = await self.retrieve_findings(
                db=db,
                case_id=str(case_uuid),
                limit=max_limit,
            )
            records.extend(finding_snippets)

        # Deduplicate snippets by record_id and table_name
        seen_keys: Set[Tuple[str, str]] = set()
        dedup_records: List[StructuredRecordSnippet] = []
        for rec in records:
            k = (rec.table_name, rec.record_id)
            if k not in seen_keys:
                seen_keys.add(k)
                dedup_records.append(rec)

        # Sort: priority to exact identifier matches, then timestamps
        def _sort_key(r: StructuredRecordSnippet) -> Tuple[int, float]:
            ts_epoch = r.timestamp.timestamp() if r.timestamp else 0.0
            is_match = 1 if any(t.split(":")[-1].lower() in r.summary_text.lower() for t in target_tags) else 0
            return (is_match, ts_epoch)

        dedup_records.sort(key=_sort_key, reverse=True)
        final_records = dedup_records[:max_limit]

        # Convert to unified RetrievedItems
        items: List[RetrievedItem] = []
        for rec in final_records:
            score = self._compute_score(rec, plan)
            item = self._to_retrieved_item(rec, score)
            items.append(item)

        context = StructuredRecordContext(
            case_id=str(case_uuid),
            records=final_records,
            total_count=len(final_records),
        )

        return context, items

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Database Domain Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_transactions(
        self,
        db: AsyncSession,
        case_id: str,
        account: Optional[str] = None,
        upi_id: Optional[str] = None,
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch exact bank transaction events from evidence_events table."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(["bank_txn", "transaction"]),
        )

        if start_time:
            q = q.where(EvidenceEvent.event_timestamp >= start_time)
        if end_time:
            q = q.where(EvidenceEvent.event_timestamp <= end_time)

        q = q.order_by(EvidenceEvent.event_timestamp.desc())
        all_events = (await db.execute(q)).scalars().all()

        # Build file lookup map for provenance
        ev_files = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case_uuid))).scalars().all()
        file_map = {f.id: f.original_name or f.filename for f in ev_files}

        snippets: List[StructuredRecordSnippet] = []
        for ev in all_events:
            meta = ev.event_metadata or {}
            amt = _extract_amount_from_meta(meta)

            # Amount filtering
            if min_amount is not None and (amt is None or amt < min_amount):
                continue
            if max_amount is not None and (amt is None or amt > max_amount):
                continue

            # Account filtering
            if account:
                acct_clean = account.strip().lower()
                from_acc = str(meta.get("from_account") or "").lower()
                to_acc = str(meta.get("to_account") or "").lower()
                acc = str(meta.get("account") or "").lower()
                text = (ev.text_content or "").lower()
                if (acct_clean not in from_acc and acct_clean not in to_acc and acct_clean not in acc and acct_clean not in text):
                    continue

            # UPI filtering
            if upi_id:
                upi_clean = upi_id.strip().lower()
                ev_upi = str(meta.get("upi_id") or "").lower()
                if upi_clean not in ev_upi and upi_clean not in (ev.text_content or "").lower():
                    continue

            source_doc = file_map.get(ev.evidence_file_id, "Bank Statement")
            summary = self._format_transaction_text(ev, meta, amt)
            exact_payload = {
                "event_id": str(ev.id),
                "event_type": ev.event_type,
                "amount": amt,
                "debit": meta.get("debit"),
                "credit": meta.get("credit"),
                "balance": meta.get("balance"),
                "from_account": meta.get("from_account"),
                "to_account": meta.get("to_account"),
                "account": meta.get("account") or meta.get("to_account") or meta.get("from_account"),
                "upi_id": meta.get("upi_id"),
                "ref_no": meta.get("ref_no"),
                "narration": meta.get("narration") or ev.text_content,
                "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                "source_doc": source_doc,
            }

            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(ev.id),
                    table_name="evidence_events",
                    record_type="bank_txn",
                    timestamp=ev.event_timestamp,
                    summary_text=summary,
                    exact_payload=exact_payload,
                    source_file=source_doc,
                    source_line=str(ev.source_line) if ev.source_line is not None else None,
                    source_page=str(ev.source_page) if ev.source_page is not None else None,
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_communications(
        self,
        db: AsyncSession,
        case_id: str,
        participant: Optional[str] = None,
        event_types: Optional[Sequence[str]] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch call logs and messages from evidence_events table."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        types = list(event_types) if event_types else ["call", "whatsapp_msg", "chat", "message"]
        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(types),
        )

        if start_time:
            q = q.where(EvidenceEvent.event_timestamp >= start_time)
        if end_time:
            q = q.where(EvidenceEvent.event_timestamp <= end_time)

        q = q.order_by(EvidenceEvent.event_timestamp.desc())
        all_events = (await db.execute(q)).scalars().all()

        ev_files = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case_uuid))).scalars().all()
        file_map = {f.id: f.original_name or f.filename for f in ev_files}

        snippets: List[StructuredRecordSnippet] = []
        for ev in all_events:
            meta = ev.event_metadata or {}

            if participant:
                p_clean = participant.strip().lower()
                caller = str(meta.get("caller") or "").lower()
                callee = str(meta.get("callee") or "").lower()
                sender = str(meta.get("sender") or "").lower()
                phone = str(meta.get("phone") or "").lower()
                text = (ev.text_content or "").lower()
                if (p_clean not in caller and p_clean not in callee and p_clean not in sender and p_clean not in phone and p_clean not in text):
                    continue

            source_doc = file_map.get(ev.evidence_file_id, "Communication Log")
            summary = self._format_communication_text(ev, meta)
            exact_payload = {
                "event_id": str(ev.id),
                "event_type": ev.event_type,
                "caller": meta.get("caller"),
                "callee": meta.get("callee"),
                "sender": meta.get("sender"),
                "duration_sec": meta.get("duration_sec"),
                "call_type": meta.get("call_type"),
                "cell_id": meta.get("cell_id"),
                "imei": meta.get("imei"),
                "text": ev.text_content,
                "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                "source_doc": source_doc,
            }

            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(ev.id),
                    table_name="evidence_events",
                    record_type=ev.event_type,
                    timestamp=ev.event_timestamp,
                    summary_text=summary,
                    exact_payload=exact_payload,
                    source_file=source_doc,
                    source_line=str(ev.source_line) if ev.source_line is not None else None,
                    source_page=str(ev.source_page) if ev.source_page is not None else None,
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_network_activity(
        self,
        db: AsyncSession,
        case_id: str,
        ip: Optional[str] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch network logs and IP connection records."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(["network_log", "network"]),
        )
        if start_time:
            q = q.where(EvidenceEvent.event_timestamp >= start_time)
        if end_time:
            q = q.where(EvidenceEvent.event_timestamp <= end_time)

        q = q.order_by(EvidenceEvent.event_timestamp.desc())
        all_events = (await db.execute(q)).scalars().all()

        snippets: List[StructuredRecordSnippet] = []
        for ev in all_events:
            meta = ev.event_metadata or {}
            if ip:
                ip_clean = ip.strip().lower()
                src_ip = str(meta.get("ip") or "").lower()
                dst_ip = str(meta.get("destination") or "").lower()
                text = (ev.text_content or "").lower()
                if ip_clean not in src_ip and ip_clean not in dst_ip and ip_clean not in text:
                    continue

            summary = self._format_network_text(ev, meta)
            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(ev.id),
                    table_name="evidence_events",
                    record_type="network_log",
                    timestamp=ev.event_timestamp,
                    summary_text=summary,
                    exact_payload={
                        "event_id": str(ev.id),
                        "ip": meta.get("ip"),
                        "destination": meta.get("destination"),
                        "port": meta.get("port"),
                        "action": meta.get("action"),
                        "text": ev.text_content,
                        "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                    },
                    source_file=meta.get("source_doc") or "Network Log",
                    source_line=str(ev.source_line) if ev.source_line is not None else None,
                    source_page=str(ev.source_page) if ev.source_page is not None else None,
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_locations(
        self,
        db: AsyncSession,
        case_id: str,
        phone: Optional[str] = None,
        cell_tower: Optional[str] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch location timeline events and cell-site logs."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_type.in_(["location_timeline", "location", "cell_site"]),
        )
        if start_time:
            q = q.where(EvidenceEvent.event_timestamp >= start_time)
        if end_time:
            q = q.where(EvidenceEvent.event_timestamp <= end_time)

        q = q.order_by(EvidenceEvent.event_timestamp.desc())
        all_events = (await db.execute(q)).scalars().all()

        snippets: List[StructuredRecordSnippet] = []
        for ev in all_events:
            meta = ev.event_metadata or {}
            if phone:
                p_clean = phone.strip().lower()
                ev_phone = str(meta.get("phone") or "").lower()
                text = (ev.text_content or "").lower()
                if p_clean not in ev_phone and p_clean not in text:
                    continue

            if cell_tower:
                t_clean = cell_tower.strip().lower()
                ev_tower = str(meta.get("cell_tower") or "").lower()
                if t_clean not in ev_tower:
                    continue

            summary = self._format_location_text(ev, meta)
            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(ev.id),
                    table_name="evidence_events",
                    record_type="location_timeline",
                    timestamp=ev.event_timestamp,
                    summary_text=summary,
                    exact_payload={
                        "event_id": str(ev.id),
                        "phone": meta.get("phone"),
                        "cell_tower": meta.get("cell_tower"),
                        "city": meta.get("city"),
                        "location_reference": meta.get("location_reference"),
                        "observation": meta.get("observation"),
                        "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                    },
                    source_file=meta.get("source_doc") or "Location Report",
                    source_line=str(ev.source_line) if ev.source_line is not None else None,
                    source_page=str(ev.source_page) if ev.source_page is not None else None,
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_entities(
        self,
        db: AsyncSession,
        case_id: str,
        target_tags: Optional[Sequence[str]] = None,
        entity_types: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch canonical entities and their metadata/metrics."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        q = select(Entity).where(Entity.case_id == case_uuid)
        if entity_types:
            q = q.where(Entity.entity_type.in_(entity_types))

        rows = (await db.execute(q)).scalars().all()
        snippets: List[StructuredRecordSnippet] = []

        for ent in rows:
            if target_tags:
                val = ent.canonical_value.lower()
                matched = any(t.split(":")[-1].lower() in val for t in target_tags)
                if not matched:
                    continue

            meta = ent.node_metadata or {}
            risk = float(getattr(ent, "risk_score", meta.get("risk_score", getattr(ent, "degree_centrality", 0.0) or 0.0)) or 0.0)
            bridge = float(getattr(ent, "bridge_score", 0.0) or 0.0)
            summary = f"[ENTITY] Type: {ent.entity_type} | Value: {ent.canonical_value} | Risk: {risk:.2f} | Bridge: {bridge:.2f}"

            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(ent.id),
                    table_name="entities",
                    record_type="entity",
                    timestamp=ent.created_at,
                    summary_text=summary,
                    exact_payload={
                        "entity_id": str(ent.id),
                        "canonical_value": ent.canonical_value,
                        "entity_type": ent.entity_type,
                        "risk_score": risk,
                        "bridge_score": bridge,
                        "degree_centrality": ent.degree_centrality,
                        "community_id": ent.community_id,
                    },
                    source_file="Case Graph (Entities)",
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_findings(
        self,
        db: AsyncSession,
        case_id: str,
        finding_types: Optional[Sequence[str]] = None,
        min_severity: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[StructuredRecordSnippet]:
        """Fetch cognitive investigation findings."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_uuid)
        if finding_types:
            q = q.where(InvestigationFinding.finding_type.in_(finding_types))

        q = q.order_by(InvestigationFinding.created_at.desc())
        all_findings = (await db.execute(q)).scalars().all()

        sev_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        min_rank = sev_rank.get((min_severity or "LOW").upper(), 1)

        snippets: List[StructuredRecordSnippet] = []
        for f in all_findings:
            if sev_rank.get((f.severity or "LOW").upper(), 1) < min_rank:
                continue

            summary = f"[FINDING] Severity: {f.severity} | Type: {f.finding_type} | Title: {f.title} | Status: {f.status}"
            if f.reasoning:
                summary += f" | Reasoning: {f.reasoning[:150]}"

            snippets.append(
                StructuredRecordSnippet(
                    record_id=str(f.id),
                    table_name="findings",
                    record_type="finding",
                    timestamp=f.observed_at or f.created_at,
                    summary_text=summary,
                    exact_payload={
                        "finding_id": str(f.id),
                        "title": f.title,
                        "finding_type": f.finding_type,
                        "severity": f.severity,
                        "status": f.status,
                        "confidence": f.confidence,
                        "source_engine": f.source_engine,
                        "reason_codes": f.reason_codes or [],
                        "reasoning": f.reasoning,
                        "entity_refs": f.entity_refs or [],
                    },
                    source_file="Cognitive Intelligence (Findings)",
                )
            )
            if limit and len(snippets) >= limit:
                break

        return snippets

    async def retrieve_case_snapshot(
        self,
        db: AsyncSession,
        case_id: str,
    ) -> Optional[CaseContextSnapshot]:
        """Fetch high-level case metadata and entity/event/file statistics."""
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return None

        case = (await db.execute(select(Case).where(Case.id == case_uuid))).scalar_one_or_none()
        if not case:
            return None

        total_files = (await db.execute(
            select(func.count(EvidenceFile.id)).where(EvidenceFile.case_id == case_uuid)
        )).scalar_one() or 0

        total_ents = (await db.execute(
            select(func.count(Entity.id)).where(Entity.case_id == case_uuid)
        )).scalar_one() or 0

        total_evs = (await db.execute(
            select(func.count(EvidenceEvent.id)).where(EvidenceEvent.case_id == case_uuid)
        )).scalar_one() or 0

        total_finds = (await db.execute(
            select(func.count(InvestigationFinding.id)).where(InvestigationFinding.case_id == case_uuid)
        )).scalar_one() or 0

        return CaseContextSnapshot(
            case_id=str(case.id),
            case_number=case.case_number,
            title=case.title,
            crime_type=case.crime_type,
            status=case.status,
            priority=case.priority,
            total_evidence_files=total_files,
            total_entities=total_ents,
            total_events=total_evs,
            total_findings=total_finds,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 3. In-Memory / Test-Mode Methods
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve_from_memory(
        self,
        case_id: str,
        events: Sequence[Dict[str, Any]] = (),
        entities: Sequence[Dict[str, Any]] = (),
        findings: Sequence[Dict[str, Any]] = (),
        query_plan: Optional[QueryPlan] = None,
        target_tags: Sequence[str] = (),
        min_amount: Optional[float] = None,
        max_amount: Optional[float] = None,
        start_time: Optional[datetime.datetime] = None,
        end_time: Optional[datetime.datetime] = None,
        limit: Optional[int] = None,
    ) -> Tuple[StructuredRecordContext, List[RetrievedItem]]:
        """
        Pure in-memory execution for unit tests and local evaluation.
        Guarantees strict case_id matching.
        """
        max_limit = limit or 50
        tags = list(target_tags)
        if query_plan and query_plan.target_entities:
            tags.extend(query_plan.target_entities)

        # 1. Filter events strictly by case_id
        valid_events = [e for e in events if str(e.get("case_id")) == str(case_id)]
        valid_entities = [e for e in entities if str(e.get("case_id")) == str(case_id)]
        valid_findings = [f for f in findings if str(f.get("case_id")) == str(case_id)]

        records: List[StructuredRecordSnippet] = []

        # Process events (transactions, calls, whatsapp, network, location)
        for ev in valid_events:
            etype = ev.get("event_type", "")
            meta = ev.get("metadata", {}) or {}
            ts = ev.get("event_timestamp") or ev.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.datetime.fromisoformat(ts)
                except Exception:
                    ts = None

            # Time window filtering
            if start_time and ts and _normalize_dt(ts) < _normalize_dt(start_time):
                continue
            if end_time and ts and _normalize_dt(ts) > _normalize_dt(end_time):
                continue

            amt = _extract_amount_from_meta(meta)
            if amt is None:
                amt = _safe_float(ev.get("amount"))

            # Amount filter for transactions
            if min_amount is not None and (amt is None or amt < min_amount):
                continue
            if max_amount is not None and (amt is None or amt > max_amount):
                continue

            # Tag / identifier filter
            if tags:
                matches_any = False
                for tag in tags:
                    val = tag.split(":")[-1].strip().lower()
                    ev_text = (ev.get("text_content") or ev.get("text") or "").lower()
                    meta_vals = " ".join(str(v) for v in meta.values()).lower()
                    if val in ev_text or val in meta_vals:
                        matches_any = True
                        break
                if not matches_any:
                    continue

            # Format summary
            summary = self._format_raw_event_summary(ev, etype, meta, amt, ts)
            records.append(
                StructuredRecordSnippet(
                    record_id=str(ev.get("id", str(uuid.uuid4()))),
                    table_name="evidence_events",
                    record_type=etype,
                    timestamp=ts,
                    summary_text=summary,
                    exact_payload={
                        "event_id": str(ev.get("id", "")),
                        "event_type": etype,
                        "amount": amt,
                        **meta,
                        "metadata": meta,
                        "text": ev.get("text_content") or ev.get("text"),
                        "timestamp": ts.isoformat() if ts else None,
                    },
                    source_file=ev.get("source_doc") or ev.get("source_file") or "Evidence Event",
                    source_line=str(ev.get("source_line")) if ev.get("source_line") is not None else None,
                    source_page=str(ev.get("source_page")) if ev.get("source_page") is not None else None,
                )
            )

        # Process entities
        for ent in valid_entities:
            c_val = ent.get("canonical_value", "")
            if tags:
                matches_any = any(t.split(":")[-1].strip().lower() in c_val.lower() for t in tags)
                if not matches_any:
                    continue

            risk = float(ent.get("risk_score", 0.0) or 0.0)
            bridge = float(ent.get("bridge_score", 0.0) or 0.0)
            summary = f"[ENTITY] Type: {ent.get('entity_type', 'UNKNOWN')} | Value: {c_val} | Risk: {risk:.2f} | Bridge: {bridge:.2f}"
            records.append(
                StructuredRecordSnippet(
                    record_id=str(ent.get("id", c_val)),
                    table_name="entities",
                    record_type="entity",
                    summary_text=summary,
                    exact_payload=dict(ent),
                    source_file="Case Graph (Entities)",
                )
            )

        # Process findings
        for f in valid_findings:
            summary = f"[FINDING] Severity: {f.get('severity', 'MEDIUM')} | Type: {f.get('finding_type')} | Title: {f.get('title')} | Status: {f.get('status', 'OPEN')}"
            records.append(
                StructuredRecordSnippet(
                    record_id=str(f.get("id", str(uuid.uuid4()))),
                    table_name="findings",
                    record_type="finding",
                    summary_text=summary,
                    exact_payload=dict(f),
                    source_file="Cognitive Intelligence (Findings)",
                )
            )

        records = records[:max_limit]
        items: List[RetrievedItem] = []
        for rec in records:
            score = 1.0 if tags and any(t.split(":")[-1].lower() in rec.summary_text.lower() for t in tags) else 0.9
            items.append(self._to_retrieved_item(rec, score))

        context = StructuredRecordContext(
            case_id=case_id,
            records=records,
            total_count=len(records),
        )
        return context, items

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Helper Parsers & Formatters
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_amount_bounds(self, query: str) -> Tuple[Optional[float], Optional[float]]:
        """Parse natural language amount filters from user prompt."""
        # 1. Between
        m_between = AMOUNT_BETWEEN_RE.search(query)
        if m_between:
            low = _safe_float(m_between.group(1))
            high = _safe_float(m_between.group(2))
            return low, high

        # 2. Over
        min_amt = None
        m_over = AMOUNT_OVER_RE.search(query)
        if m_over:
            min_amt = _safe_float(m_over.group(1))

        # 3. Under
        max_amt = None
        m_under = AMOUNT_UNDER_RE.search(query)
        if m_under:
            max_amt = _safe_float(m_under.group(1))

        return min_amt, max_amt

    def _format_transaction_text(
        self,
        ev: EvidenceEvent,
        meta: Dict[str, Any],
        amt: Optional[float],
    ) -> str:
        ts_str = ev.event_timestamp.strftime("%Y-%m-%d %H:%M") if ev.event_timestamp else "N/A"
        dir_label = "DEBIT" if meta.get("debit") else ("CREDIT" if meta.get("credit") else "TXN")
        from_acc = meta.get("from_account") or "?"
        to_acc = meta.get("to_account") or "?"
        ref = meta.get("ref_no") or "N/A"
        narration = meta.get("narration") or ev.text_content or "Bank Transaction"

        return (
            f"[TRANSACTION] Date: {ts_str} | Amount: {_format_currency(amt)} ({dir_label}) | "
            f"From: {from_acc} | To: {to_acc} | Ref: {ref} | Narration: {narration[:120]}"
        )

    def _format_communication_text(self, ev: EvidenceEvent, meta: Dict[str, Any]) -> str:
        ts_str = ev.event_timestamp.strftime("%Y-%m-%d %H:%M") if ev.event_timestamp else "N/A"
        if ev.event_type == "call":
            caller = meta.get("caller") or "?"
            callee = meta.get("callee") or "?"
            dur = f"{meta.get('duration_sec')}s" if meta.get("duration_sec") is not None else "N/A"
            cell = meta.get("cell_id") or "N/A"
            return f"[CALL] Date: {ts_str} | Caller: {caller} -> Callee: {callee} | Duration: {dur} | Cell Tower: {cell}"
        elif ev.event_type == "whatsapp_msg":
            sender = meta.get("sender") or "?"
            txt = (ev.text_content or "").strip()
            return f"[WHATSAPP] Date: {ts_str} | Sender: {sender} | Message: {txt[:140]}"
        return f"[COMMUNICATION] Date: {ts_str} | {ev.text_content or ''}"

    def _format_network_text(self, ev: EvidenceEvent, meta: Dict[str, Any]) -> str:
        ts_str = ev.event_timestamp.strftime("%Y-%m-%d %H:%M") if ev.event_timestamp else "N/A"
        ip = meta.get("ip") or "?"
        dest = meta.get("destination") or "?"
        port = meta.get("port") or "?"
        act = meta.get("action") or "LOG"
        return f"[NETWORK] Date: {ts_str} | IP: {ip} -> Dest: {dest}:{port} | Action: {act}"

    def _format_location_text(self, ev: EvidenceEvent, meta: Dict[str, Any]) -> str:
        ts_str = ev.event_timestamp.strftime("%Y-%m-%d %H:%M") if ev.event_timestamp else "N/A"
        phone = meta.get("phone") or "?"
        city = meta.get("city") or "?"
        tower = meta.get("cell_tower") or "?"
        obs = meta.get("observation") or "routine"
        return f"[LOCATION] Date: {ts_str} | Phone: {phone} | Location: {city} ({tower}) | Obs: {obs}"

    def _format_raw_event_summary(
        self,
        ev: Dict[str, Any],
        etype: str,
        meta: Dict[str, Any],
        amt: Optional[float],
        ts: Optional[datetime.datetime],
    ) -> str:
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "N/A"
        if etype in ("bank_txn", "transaction"):
            from_acc = meta.get("from_account") or "?"
            to_acc = meta.get("to_account") or "?"
            return f"[TRANSACTION] Date: {ts_str} | Amount: {_format_currency(amt)} | From: {from_acc} | To: {to_acc}"
        elif etype == "call":
            return f"[CALL] Date: {ts_str} | Caller: {meta.get('caller', '?')} -> Callee: {meta.get('callee', '?')}"
        elif etype == "whatsapp_msg":
            return f"[WHATSAPP] Date: {ts_str} | Sender: {meta.get('sender', '?')} | Text: {(ev.get('text_content') or ev.get('text') or '')[:100]}"
        elif etype == "network_log":
            return f"[NETWORK] Date: {ts_str} | IP: {meta.get('ip', '?')} -> Dest: {meta.get('destination', '?')}"
        elif etype == "location_timeline":
            return f"[LOCATION] Date: {ts_str} | Phone: {meta.get('phone', '?')} | City: {meta.get('city', '?')}"
        return f"[{etype.upper()}] Date: {ts_str} | {ev.get('text_content') or ev.get('text') or ''}"

    def _compute_score(self, rec: StructuredRecordSnippet, plan: QueryPlan) -> float:
        """Deterministic score calculation."""
        text_lower = rec.summary_text.lower()
        # 1. Exact identifier match
        for tag in plan.target_entities:
            val = tag.split(":")[-1].lower()
            if val in text_lower:
                return 1.00

        # 2. Time window match
        if plan.time_window_start and rec.timestamp and _normalize_dt(rec.timestamp) >= _normalize_dt(plan.time_window_start):
            return 0.90

        # 3. Field / category match
        return 0.85

    def _to_retrieved_item(self, rec: StructuredRecordSnippet, score: float) -> RetrievedItem:
        return RetrievedItem(
            id=f"{rec.table_name}:{rec.record_id}",
            modality=ModalityType.STRUCTURED,
            score=score,
            text=rec.summary_text,
            source_file=rec.source_file or rec.table_name,
            source_line=rec.source_line,
            source_page=rec.source_page,
            raw_payload=rec.exact_payload,
        )
