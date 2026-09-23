"""
CyberDrishti AI — Entity Explorer & Identity Conflict Routes (V5 Milestone 3)
authoritative endpoints for entity search, deep dossier inspection,
mention/evidence provenance, and identity candidate conflict adjudication.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    Relationship,
    User,
)
from db.session import get_db
from graph import relationship_types as RT
from graph.relationships import canonical_sql_predicate
from investigation.commands import CommandRequest, CommandResult, dispatch_command
from investigation.policies import (
    CAP_ENTITY_WRITE,
    user_has_capability,
)
from routes.auth import get_current_user
from routes.case_access import require_case_access

entities_router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ResolveIdentityCandidatePayload(BaseModel):
    verdict: str = Field(..., description="confirm_same | confirm_different | reject | resolve | keep_separate")
    reason: Optional[str] = Field(None, description="Investigator reason/justification for resolution")
    candidate_entity_id: Optional[str] = Field(None, description="Optional entity ID for candidate value if already materialized")
    base_case_version: Optional[int] = Field(None, description="Concurrency check against current case state version")


def _extract_signals(cand: IdentityCandidate) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse structured match signals and conflict signals from candidate JSON metadata."""
    supporting = cand.supporting_refs or []
    contradicting = cand.contradicting_refs or []

    match_signals: list[dict[str, Any]] = []
    for s in supporting:
        if isinstance(s, dict):
            match_signals.append({
                "signal": s.get("signal") or s.get("title") or "Matching Evidence",
                "detail": s.get("detail") or s.get("description") or str(s),
                "strength": s.get("strength") or "HIGH",
            })
        else:
            match_signals.append({
                "signal": "Matching Reference",
                "detail": str(s),
                "strength": "MEDIUM",
            })

    conflict_signals: list[dict[str, Any]] = []
    for c in contradicting:
        if isinstance(c, dict):
            conflict_signals.append({
                "signal": c.get("signal") or c.get("title") or "Conflicting Attribute",
                "detail": c.get("detail") or c.get("description") or str(c),
                "severity": c.get("severity") or "MEDIUM",
            })
        else:
            conflict_signals.append({
                "signal": "Conflicting Reference",
                "detail": str(c),
                "severity": "LOW",
            })

    return match_signals, conflict_signals


# ── 1. Entity Search & Summary Listing ────────────────────────────────────────

@entities_router.get("/{case_id}/entities")
async def list_case_entities(
    case_id: str,
    search: Optional[str] = Query(None, description="Search canonical value or aliases"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (PER, PHONE, ACCOUNT, etc.)"),
    epistemic_status: Optional[str] = Query(None, pattern="^(OBSERVED|INFERRED|INVESTIGATOR_ADDED)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """List and filter entities within a case with mention counts, relationship counts, and conflict indicators."""
    c = await require_case_access(db, current, case_id)

    q = select(Entity).where(Entity.case_id == c.id)

    if entity_type:
        q = q.where(Entity.entity_type == entity_type.strip().upper())

    if search:
        s_term = f"%{search.strip()}%"
        q = q.where(
            or_(
                Entity.canonical_value.ilike(s_term),
                func.cast(Entity.node_metadata, String).ilike(s_term),
            )
        )

    # Count total matching query
    total_q = select(func.count()).select_from(q.subquery())
    total_count = (await db.execute(total_q)).scalar() or 0

    q = q.order_by(Entity.canonical_value.asc()).limit(limit).offset(offset)
    entities = (await db.execute(q)).scalars().all()

    entity_ids = [e.id for e in entities]

    # Pre-fetch mention counts
    mention_counts: dict[uuid.UUID, int] = {}
    if entity_ids:
        mc_q = (
            select(EntityMention.entity_id, func.count(EntityMention.id))
            .where(EntityMention.entity_id.in_(entity_ids))
            .group_by(EntityMention.entity_id)
        )
        for eid, count in (await db.execute(mc_q)).all():
            mention_counts[eid] = count

    # Pre-fetch relationship counts
    rel_counts: dict[uuid.UUID, int] = {eid: 0 for eid in entity_ids}
    if entity_ids:
        src_q = (
            select(Relationship.source_entity_id, func.count(Relationship.id))
            .where(Relationship.case_id == c.id, Relationship.source_entity_id.in_(entity_ids))
            .group_by(Relationship.source_entity_id)
        )
        for eid, count in (await db.execute(src_q)).all():
            rel_counts[eid] = rel_counts.get(eid, 0) + count

        tgt_q = (
            select(Relationship.target_entity_id, func.count(Relationship.id))
            .where(Relationship.case_id == c.id, Relationship.target_entity_id.in_(entity_ids))
            .group_by(Relationship.target_entity_id)
        )
        for eid, count in (await db.execute(tgt_q)).all():
            rel_counts[eid] = rel_counts.get(eid, 0) + count

    # Pre-fetch open identity conflicts
    conflict_entity_ids: set[uuid.UUID] = set()
    conflict_values: set[str] = set()
    cand_q = select(IdentityCandidate).where(
        IdentityCandidate.case_id == c.id,
        IdentityCandidate.resolution_status == "UNRESOLVED",
    )
    unresolved_cands = (await db.execute(cand_q)).scalars().all()
    for cand in unresolved_cands:
        if cand.canonical_entity_id:
            conflict_entity_ids.add(cand.canonical_entity_id)
        if cand.candidate_value:
            conflict_values.add(cand.candidate_value.strip().lower())

    results: list[dict[str, Any]] = []
    observed_count = 0
    inferred_count = 0

    for e in entities:
        meta = e.node_metadata or {}
        aliases = meta.get("aliases") or []
        e_epistemic = meta.get("epistemic_status") or RT.OBSERVED
        if e_epistemic == RT.OBSERVED:
            observed_count += 1
        elif e_epistemic == RT.INFERRED:
            inferred_count += 1

        if epistemic_status and e_epistemic != epistemic_status:
            continue

        has_conflict = (
            e.id in conflict_entity_ids or
            e.canonical_value.strip().lower() in conflict_values
        )

        results.append({
            "id": str(e.id),
            "canonical_value": e.canonical_value,
            "entity_type": e.entity_type,
            "epistemic_status": e_epistemic,
            "first_seen": e.first_seen.isoformat() if e.first_seen else None,
            "last_seen": e.last_seen.isoformat() if e.last_seen else None,
            "mention_count": mention_counts.get(e.id, 0),
            "relationship_count": rel_counts.get(e.id, 0),
            "degree_centrality": e.degree_centrality or 0.0,
            "bridge_score": e.bridge_score or 0.0,
            "has_candidate_conflict": has_conflict,
            "aliases": aliases,
        })

    return {
        "case_id": case_id,
        "case_state_version": c.state_version or 1,
        "total": total_count,
        "returned": len(results),
        "limit": limit,
        "offset": offset,
        "summary": {
            "total_in_case": total_count,
            "pending_conflicts": len(unresolved_cands),
        },
        "entities": results,
    }


# ── 2. Deep Entity Dossier & Provenance ────────────────────────────────────────

@entities_router.get("/{case_id}/entities/{entity_id}")
async def get_entity_dossier(
    case_id: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Return comprehensive entity dossier:
    - Identity header & aliases
    - Provenance & source evidence artifacts
    - Mentions & occurrences with line/page citations
    - Chronological related evidence events
    - Dual projection relationships (Canonical vs Analytical)
    - Associated identity candidate conflicts
    """
    c = await require_case_access(db, current, case_id)

    try:
        e_uuid = uuid.UUID(str(entity_id))
    except (TypeError, ValueError):
        raise HTTPException(404, "Entity not found")

    entity = await db.get(Entity, e_uuid)
    if not entity or entity.case_id != c.id:
        raise HTTPException(404, "Entity not found in this case")

    # 1. Fetch mentions with linked events and evidence files
    mentions_q = (
        select(EntityMention, EvidenceEvent, EvidenceFile)
        .outerjoin(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
        .outerjoin(EvidenceFile, EvidenceEvent.evidence_file_id == EvidenceFile.id)
        .where(EntityMention.entity_id == entity.id)
        .order_by(EvidenceEvent.event_timestamp.desc().nullslast())
    )
    mentions_rows = (await db.execute(mentions_q)).all()

    mentions_detail: list[dict[str, Any]] = []
    source_files_map: dict[str, dict[str, Any]] = {}
    extractors: set[str] = set()

    for mention, event, ev_file in mentions_rows:
        if mention.extractor:
            extractors.add(mention.extractor)

        file_id_str = str(ev_file.id) if ev_file else None
        if ev_file and file_id_str and file_id_str not in source_files_map:
            source_files_map[file_id_str] = {
                "id": file_id_str,
                "filename": ev_file.filename,
                "file_type": ev_file.file_type,
                "sha256_hash": ev_file.sha256_hash,
                "uploaded_at": ev_file.uploaded_at.isoformat() if ev_file.uploaded_at else None,
            }

        mentions_detail.append({
            "id": str(mention.id),
            "raw_value": mention.raw_value,
            "entity_type": mention.entity_type,
            "confidence": mention.confidence,
            "extractor": mention.extractor or "system",
            "span_start": mention.span_start,
            "span_end": mention.span_end,
            "event_id": str(event.id) if event else None,
            "event_type": event.event_type if event else None,
            "event_timestamp": event.event_timestamp.isoformat() if event and event.event_timestamp else None,
            "source_doc": ev_file.filename if ev_file else None,
            "source_file_id": file_id_str,
            "source_line": event.source_line if event else None,
            "source_page": event.source_page if event else None,
            "snippet": event.text_content if event else None,
        })

    # 2. Fetch related chronological events
    event_ids = [m["event_id"] for m in mentions_detail if m["event_id"]]
    related_events: list[dict[str, Any]] = []
    if event_ids:
        events_q = (
            select(EvidenceEvent, EvidenceFile)
            .outerjoin(EvidenceFile, EvidenceEvent.evidence_file_id == EvidenceFile.id)
            .where(EvidenceEvent.id.in_([uuid.UUID(eid) for eid in event_ids]))
            .order_by(EvidenceEvent.event_timestamp.asc().nullslast())
        )
        for ev, ef in (await db.execute(events_q)).all():
            related_events.append({
                "id": str(ev.id),
                "event_type": ev.event_type,
                "event_timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                "text_content": ev.text_content,
                "source_doc": ef.filename if ef else None,
                "source_file_id": str(ef.id) if ef else None,
                "source_line": ev.source_line,
                "source_page": ev.source_page,
            })

    # 3. Fetch relationships (both outbound and inbound)
    rels_q = select(Relationship).where(
        Relationship.case_id == c.id,
        or_(
            Relationship.source_entity_id == entity.id,
            Relationship.target_entity_id == entity.id,
        )
    )
    rel_rows = (await db.execute(rels_q)).scalars().all()

    # Pre-fetch lookup of counterpart entity canonical values
    counterpart_ids: set[uuid.UUID] = set()
    for r in rel_rows:
        other_id = r.target_entity_id if r.source_entity_id == entity.id else r.source_entity_id
        counterpart_ids.add(other_id)

    ent_lookup: dict[uuid.UUID, Entity] = {}
    if counterpart_ids:
        found_ents = (await db.execute(select(Entity).where(Entity.id.in_(list(counterpart_ids))))).scalars().all()
        ent_lookup = {e.id: e for e in found_ents}

    canonical_relationships: list[dict[str, Any]] = []
    analytical_relationships: list[dict[str, Any]] = []

    for r in rel_rows:
        is_source = (r.source_entity_id == entity.id)
        other_id = r.target_entity_id if is_source else r.source_entity_id
        other_ent = ent_lookup.get(other_id)

        rel_item = {
            "id": str(r.id),
            "is_outbound": is_source,
            "direction": r.direction,
            "relationship_type": r.relationship_type,
            "target_entity_id": str(other_id),
            "target_canonical_value": other_ent.canonical_value if other_ent else "UNKNOWN",
            "target_entity_type": other_ent.entity_type if other_ent else "UNKNOWN",
            "epistemic_status": r.epistemic_status,
            "verification_status": r.verification_status,
            "is_canonical": bool(r.is_canonical),
            "confidence": r.confidence,
            "amount": r.amount,
            "evidence_refs": r.evidence_refs or [],
            "event_refs": r.event_refs or [],
            "reason_codes": r.reason_codes or [],
        }

        if r.is_canonical:
            canonical_relationships.append(rel_item)
        else:
            analytical_relationships.append(rel_item)

    # 4. Fetch associated identity candidate conflicts
    cand_q = select(IdentityCandidate).where(
        IdentityCandidate.case_id == c.id,
        or_(
            IdentityCandidate.canonical_entity_id == entity.id,
            IdentityCandidate.candidate_value.ilike(entity.canonical_value),
        )
    ).order_by(IdentityCandidate.created_at.desc())
    cand_rows = (await db.execute(cand_q)).scalars().all()

    candidates_detail: list[dict[str, Any]] = []
    for cand in cand_rows:
        matches, conflicts = _extract_signals(cand)
        candidates_detail.append({
            "id": str(cand.id),
            "canonical_entity_id": str(cand.canonical_entity_id) if cand.canonical_entity_id else None,
            "candidate_value": cand.candidate_value,
            "candidate_type": cand.candidate_type,
            "resolution_status": cand.resolution_status,
            "match_signals": matches,
            "conflict_signals": conflicts,
            "created_at": cand.created_at.isoformat() if cand.created_at else None,
            "resolved_at": cand.resolved_at.isoformat() if cand.resolved_at else None,
        })

    meta = entity.node_metadata or {}
    return {
        "case_id": case_id,
        "case_state_version": c.state_version or 1,
        "entity": {
            "id": str(entity.id),
            "canonical_value": entity.canonical_value,
            "entity_type": entity.entity_type,
            "epistemic_status": meta.get("epistemic_status") or RT.OBSERVED,
            "first_seen": entity.first_seen.isoformat() if entity.first_seen else None,
            "last_seen": entity.last_seen.isoformat() if entity.last_seen else None,
            "degree_centrality": entity.degree_centrality or 0.0,
            "bridge_score": entity.bridge_score or 0.0,
            "aliases": meta.get("aliases") or [],
            "risk": meta.get("risk"),
            "metadata": meta,
        },
        "provenance": {
            "source_evidence_files": list(source_files_map.values()),
            "extractors": sorted(list(extractors)),
            "mention_count": len(mentions_detail),
        },
        "mentions": mentions_detail,
        "related_events": related_events,
        "relationships": {
            "canonical": canonical_relationships,
            "analytical": analytical_relationships,
            "canonical_count": len(canonical_relationships),
            "analytical_count": len(analytical_relationships),
        },
        "identity_candidates": candidates_detail,
    }


# ── 3. Identity Candidate Conflict Review Queue ───────────────────────────────

@entities_router.get("/{case_id}/identity-candidates")
async def list_identity_candidates(
    case_id: str,
    resolution_status: str = Query(
        "ALL",
        pattern="^(ALL|UNRESOLVED|CONFIRMED_SAME|CONFIRMED_DIFFERENT|REJECTED)$",
        description="Filter by resolution status",
    ),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    List identity candidates for human adjudication with structured match signals,
    conflicting signals, and comparison details.
    """
    c = await require_case_access(db, current, case_id)

    q = select(IdentityCandidate).where(IdentityCandidate.case_id == c.id)
    if resolution_status != "ALL":
        q = q.where(IdentityCandidate.resolution_status == resolution_status)
    q = q.order_by(IdentityCandidate.created_at.desc())

    rows = (await db.execute(q)).scalars().all()

    # Pre-fetch canonical entity values
    canon_ids = [r.canonical_entity_id for r in rows if r.canonical_entity_id]
    ent_map: dict[uuid.UUID, Entity] = {}
    if canon_ids:
        ents = (await db.execute(select(Entity).where(Entity.id.in_(canon_ids)))).scalars().all()
        ent_map = {e.id: e for e in ents}

    # Also check if candidate value matches an existing entity in the case
    cand_vals = [r.candidate_value for r in rows if r.candidate_value]
    cand_ent_map: dict[str, Entity] = {}
    if cand_vals:
        cand_ents = (
            await db.execute(
                select(Entity).where(Entity.case_id == c.id, Entity.canonical_value.in_(cand_vals))
            )
        ).scalars().all()
        cand_ent_map = {e.canonical_value: e for e in cand_ents}

    items: list[dict[str, Any]] = []
    unresolved_count = 0

    for r in rows:
        if r.resolution_status == "UNRESOLVED":
            unresolved_count += 1

        matches, conflicts = _extract_signals(r)
        canonical_ent = ent_map.get(r.canonical_entity_id) if r.canonical_entity_id else None
        candidate_ent = cand_ent_map.get(r.candidate_value)

        items.append({
            "id": str(r.id),
            "canonical_entity": {
                "id": str(canonical_ent.id) if canonical_ent else None,
                "canonical_value": canonical_ent.canonical_value if canonical_ent else "UNKNOWN",
                "entity_type": canonical_ent.entity_type if canonical_ent else r.candidate_type,
                "first_seen": canonical_ent.first_seen.isoformat() if canonical_ent and canonical_ent.first_seen else None,
                "last_seen": canonical_ent.last_seen.isoformat() if canonical_ent and canonical_ent.last_seen else None,
            },
            "candidate_entity": {
                "id": str(candidate_ent.id) if candidate_ent else None,
                "canonical_value": r.candidate_value,
                "entity_type": candidate_ent.entity_type if candidate_ent else r.candidate_type,
                "first_seen": candidate_ent.first_seen.isoformat() if candidate_ent and candidate_ent.first_seen else None,
                "last_seen": candidate_ent.last_seen.isoformat() if candidate_ent and candidate_ent.last_seen else None,
            },
            "candidate_value": r.candidate_value,
            "candidate_type": r.candidate_type,
            "resolution_status": r.resolution_status,
            "match_signals": matches,
            "conflict_signals": conflicts,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        })

    return {
        "case_id": case_id,
        "case_state_version": c.state_version or 1,
        "count": len(items),
        "pending_count": unresolved_count,
        "capabilities": {
            "can_resolve": user_has_capability(current.role, CAP_ENTITY_WRITE),
        },
        "candidates": items,
    }


# ── 4. Candidate Adjudication Dispatch ───────────────────────────────────────

@entities_router.post(
    "/{case_id}/identity-candidates/{candidate_id}/resolve",
    response_model=CommandResult,
)
async def resolve_identity_candidate_endpoint(
    case_id: str,
    candidate_id: str,
    payload: ResolveIdentityCandidatePayload,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Record an investigator verdict on an identity candidate.

    Dispatches strictly through the Investigation Brain Command Gateway:
    - Enforces CAP_ENTITY_WRITE permission (403)
    - Records tamper-evident audit entry
    - Bumps case state-version
    - Emits investigation activity
    - Invalidates affected dependent findings
    """
    c = await require_case_access(db, current, case_id, write=True)

    try:
        cand_uuid = uuid.UUID(str(candidate_id))
    except (TypeError, ValueError):
        raise HTTPException(404, "Identity candidate not found")

    cand = await db.get(IdentityCandidate, cand_uuid)
    if not cand or cand.case_id != c.id:
        raise HTTPException(404, "Identity candidate not found in this case")

    return await dispatch_command(
        db,
        c.id,
        CommandRequest(
            command="RESOLVE_IDENTITY_CANDIDATE",
            payload={
                "candidate_id": str(cand.id),
                "resolution_status": payload.verdict,
                "candidate_entity_id": payload.candidate_entity_id,
            },
            reason=payload.reason or f"Investigator identity adjudication: {payload.verdict}",
            base_case_version=payload.base_case_version,
        ),
        current,
    )
