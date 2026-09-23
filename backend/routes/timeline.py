from __future__ import annotations

"""
CyberDrishti AI — Unified Investigation Timeline Routes (V5 Milestone 4)
Provides normalized timeline streams:
  • Incident Timeline: Underlying real-world events ordered strictly by event_time.
  • Investigation Replay Timeline: NETRA & investigator actions ordered by state_version and recorded_at.

Invariants:
  • event_time and recorded_at are strictly distinct.
  • Missing event_time is NEVER back-filled with ingestion time.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    User,
)
from db.session import get_db
from routes.auth import get_current_user
from routes.case_access import require_case_access

timeline_router = APIRouter()


def _epoch(dt: Optional[datetime]) -> float:
    if dt is None:
        return float("-inf")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _categorize_event_type(ev_type: Optional[str]) -> str:
    if not ev_type:
        return "GENERAL"
    et = ev_type.upper()
    if any(k in et for k in ("CALL", "CDR", "CHAT", "MESSAGE", "WHATSAPP", "SMS")):
        return "COMMUNICATION"
    if any(k in et for k in ("BANK", "TXN", "TRANSACTION", "UPI", "TRANSFER", "WIRE")):
        return "TRANSACTION"
    if any(k in et for k in ("LOC", "TOWER", "GPS", "CELL", "GEO")):
        return "LOCATION"
    if any(k in et for k in ("DEVICE", "IMEI", "MAC", "IP", "SYS", "PC")):
        return "DEVICE"
    return "EVIDENCE"


# ── 1. Unified Timeline Endpoint ──────────────────────────────────────────────

@timeline_router.get("/{case_id}/timeline")
async def get_unified_case_timeline(
    case_id: str,
    mode: str = Query("all", pattern="^(all|incident|investigation)$", description="Filter timeline stream mode"),
    category: Optional[str] = Query(None, description="Category filter (COMMUNICATION, TRANSACTION, LOCATION, DEVICE, DECISION, etc.)"),
    entity_id: Optional[str] = Query(None, description="Filter timeline items referencing entity ID"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Unified multi-stream timeline combining real-world incident events with
    investigative activities, entity discoveries, relationship adjudications,
    and cognitive findings.
    """
    c = await require_case_access(db, current, case_id)
    case_uuid = c.id
    items: list[dict[str, Any]] = []

    # 1. Collect Incident Events (from EvidenceEvent)
    if mode in ("all", "incident"):
        ev_q = select(EvidenceEvent, EvidenceFile).outerjoin(
            EvidenceFile, EvidenceEvent.evidence_file_id == EvidenceFile.id
        ).where(EvidenceEvent.case_id == case_uuid)

        events_rows = (await db.execute(ev_q)).all()

        # Pre-fetch mentions for entity_refs
        event_ids = [ev.id for ev, _ in events_rows]
        event_entity_refs: dict[uuid.UUID, list[str]] = {eid: [] for eid in event_ids}
        if event_ids:
            mentions_q = select(EntityMention.evidence_event_id, EntityMention.entity_id).where(
                EntityMention.evidence_event_id.in_(event_ids)
            )
            for evid, entid in (await db.execute(mentions_q)).all():
                if entid:
                    event_entity_refs[evid].append(str(entid))

        for ev, ef in events_rows:
            meta = ev.event_metadata or {}
            event_time = ev.event_timestamp.isoformat() if ev.event_timestamp else None
            recorded_at = ev.created_at.isoformat() if ev.created_at else None
            time_status = "OK" if event_time else "TIME_NORMALIZATION_REQUIRED"
            cat = _categorize_event_type(ev.event_type)

            if category and category.upper() != cat and category.upper() != "ALL":
                continue

            refs = event_entity_refs.get(ev.id, [])
            if entity_id and entity_id not in refs:
                continue

            items.append({
                "id": str(ev.id),
                "case_id": str(case_uuid),
                "event_time": event_time,
                "recorded_at": recorded_at,
                "time_status": time_status,
                "activity_type": ev.event_type or "EVIDENCE_EVENT",
                "mode": "incident",
                "category": cat,
                "actor": "evidence_ingest",
                "source": ef.filename if ef else (meta.get("source_doc") or "Seized Artifact"),
                "title": f"{cat.capitalize()} Observation: {ev.event_type or 'Event'}",
                "summary": (ev.text_content or "")[:300],
                "entity_refs": refs,
                "evidence_refs": [str(ef.id)] if ef else [],
                "relationship_refs": [],
                "finding_refs": [],
                "case_state_version": None,
                "provenance": {
                    "source_doc": ef.filename if ef else meta.get("source_doc"),
                    "source_line": ev.source_line,
                    "source_page": ev.source_page,
                    "file_hash": ef.sha256_hash if ef else None,
                },
            })

    # 2. Collect Investigation Activities (from InvestigationActivity)
    if mode in ("all", "investigation"):
        act_q = (
            select(InvestigationActivity, User.username)
            .outerjoin(User, InvestigationActivity.actor_id == User.id)
            .where(InvestigationActivity.case_id == case_uuid)
        )
        activities = (await db.execute(act_q)).all()

        for act, actor_name in activities:
            after = act.after_state or {}
            before = act.before_state or {}
            recorded_at = act.created_at.isoformat() if act.created_at else None

            # Determine entity refs
            act_entity_refs: list[str] = []
            if act.target_type == "entity" and act.target_id:
                act_entity_refs.append(act.target_id)
            if "canonical_entity_id" in after and after["canonical_entity_id"]:
                act_entity_refs.append(str(after["canonical_entity_id"]))

            if entity_id and entity_id not in act_entity_refs:
                continue

            act_cat = "DECISION" if "CONFIRM" in act.activity_type or "RESOLVE" in act.activity_type or "REJECT" in act.activity_type else "INVESTIGATION"
            if category and category.upper() != act_cat and category.upper() != "ALL":
                continue

            summary_text = act.reason or f"{act.activity_type} on {act.target_type or 'resource'}"
            if "verification_status" in after:
                summary_text += f" -> {after['verification_status']}"
            if "resolution_status" in after:
                summary_text += f" -> {after['resolution_status']}"

            items.append({
                "id": str(act.id),
                "case_id": str(case_uuid),
                "event_time": None,  # Investigation activities do NOT have a crime event timestamp
                "recorded_at": recorded_at,
                "time_status": "INVESTIGATION_ACTION",
                "activity_type": act.activity_type,
                "mode": "investigation",
                "category": act_cat,
                "actor": actor_name or "system",
                "source": "Investigation Brain Command Gateway",
                "title": f"Investigator Action: {act.activity_type}",
                "summary": summary_text,
                "entity_refs": act_entity_refs,
                "evidence_refs": [],
                "relationship_refs": [act.target_id] if act.target_type == "relationship" and act.target_id else [],
                "finding_refs": [act.target_id] if act.target_type == "finding" and act.target_id else [],
                "case_state_version": None,
                "provenance": {
                    "reason": act.reason,
                    "target_type": act.target_type,
                    "target_id": act.target_id,
                },
            })

    # Sort items based on requested mode:
    #   - For "incident": sort by event_time (chronological order of the crime)
    #   - For "investigation": sort by recorded_at desc (audit order)
    #   - For "all": items with event_time ordered chronologically, followed by investigation actions
    if mode == "incident":
        def _sort_key(it):
            dt = datetime.fromisoformat(it["event_time"]) if it["event_time"] else None
            return (it["event_time"] is None, _epoch(dt))
        items.sort(key=_sort_key)
    else:
        def _sort_key_desc(it):
            t_str = it["recorded_at"] or it["event_time"]
            dt = datetime.fromisoformat(t_str) if t_str else None
            return _epoch(dt)
        items.sort(key=_sort_key_desc, reverse=True)

    total_count = len(items)
    paged_items = items[offset : offset + limit]

    return {
        "case_id": str(case_uuid),
        "mode": mode,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "items": paged_items,
    }


# ── 2. Activity Log Endpoint ──────────────────────────────────────────────────

@timeline_router.get("/{case_id}/activity")
async def get_case_activity_log(
    case_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Return raw activity stream entries for case audit inspection."""
    c = await require_case_access(db, current, case_id)
    case_uuid = c.id

    q = (
        select(InvestigationActivity, User.username)
        .outerjoin(User, InvestigationActivity.actor_id == User.id)
        .where(InvestigationActivity.case_id == case_uuid)
        .order_by(InvestigationActivity.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(q)).all()

    total_q = select(func.count()).select_from(InvestigationActivity).where(InvestigationActivity.case_id == case_uuid)
    total_count = (await db.execute(total_q)).scalar() or 0

    return {
        "case_id": str(case_uuid),
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "activities": [
            {
                "id": str(act.id),
                "activity_type": act.activity_type,
                "target_type": act.target_type,
                "target_id": act.target_id,
                "actor": username or "system",
                "reason": act.reason,
                "before_state": act.before_state,
                "after_state": act.after_state,
                "created_at": act.created_at.isoformat() if act.created_at else None,
            }
            for act, username in rows
        ],
    }
