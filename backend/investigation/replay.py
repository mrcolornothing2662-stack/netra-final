from __future__ import annotations

"""
NETRA V5 — Historical Investigation Replay Service
Reconstructs a consistent, read-only historical case state projection at any
valid state_version (1 <= v <= current_version) using existing relational
case state, InvestigationState checkpoints, and InvestigationActivity audit trails.

Guarantees:
1. Strict Read-Only Execution: Zero mutations, zero DB writes, zero version bumps.
2. Invariant: Rejected relationships never become canonical during replay.
3. Invariant: Identity candidates remain UNRESOLVED until their decision event.
4. Preserves evidence provenance and source citations across historical projections.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
)
from graph import relationship_types as RT


async def get_case_replay_index(
    db: AsyncSession,
    case_id: str | uuid.UUID,
) -> dict[str, Any]:
    """
    Return a list of all recorded case state versions with checkpoint timestamps,
    actors, and triggering activities to drive the timeline replay cursor.
    """
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    case = await db.get(Case, case_uuid)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    current_version = case.state_version or 1

    # Fetch all state checkpoints for this case
    state_q = (
        select(InvestigationState)
        .where(InvestigationState.case_id == case_uuid)
        .order_by(InvestigationState.version.asc())
    )
    checkpoints = list((await db.execute(state_q)).scalars().all())

    # Map version -> checkpoint
    ckpt_by_version = {c.version: c for c in checkpoints}

    # Fetch activities for this case
    act_q = (
        select(InvestigationActivity)
        .where(InvestigationActivity.case_id == case_uuid)
        .order_by(InvestigationActivity.created_at.asc())
    )
    activities = list((await db.execute(act_q)).scalars().all())

    # Match activities to checkpoints
    versions_list: list[dict[str, Any]] = []

    for v in range(1, current_version + 1):
        ckpt = ckpt_by_version.get(v)
        ckpt_time = ckpt.created_at if ckpt else (case.created_at or datetime.now(timezone.utc))

        # Determine cutoff for version v:
        # If v < current_version, anything before ckpt_{v+1}.created_at belongs to v.
        ckpt_next = ckpt_by_version.get(v + 1)
        cutoff = ckpt_next.created_at if (ckpt_next and ckpt_next.created_at) else None

        # Find closest activity triggering this version
        trigger_act = None
        if v == 1:
            trigger_summary = "Case initialized"
            trigger_type = "CASE_CREATED"
            actor_name = "system"
        else:
            # Find the latest activity that belongs to version v
            candidate_acts = [
                act for act in activities
                if (cutoff is None or (act.created_at and act.created_at < cutoff))
            ]
            if candidate_acts:
                trigger_act = candidate_acts[-1]

            trigger_summary = (
                f"{trigger_act.activity_type}: {trigger_act.target_type or 'resource'} {trigger_act.target_id or ''}".strip()
                if trigger_act
                else f"State version {v} checkpoint"
            )
            trigger_type = trigger_act.activity_type if trigger_act else "STATE_CHECKPOINT"
            actor_name = str(trigger_act.actor_id) if trigger_act and trigger_act.actor_id else "system"

        versions_list.append({
            "version": v,
            "timestamp": ckpt_time.isoformat() if ckpt_time else None,
            "state_hash": ckpt.state_hash if ckpt else None,
            "activity_type": trigger_type,
            "summary": trigger_summary,
            "actor": actor_name,
        })

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "title": case.title,
        "current_version": current_version,
        "total_versions": len(versions_list),
        "versions": versions_list,
    }


async def reconstruct_historical_state(
    db: AsyncSession,
    case_id: str | uuid.UUID,
    target_version: int,
) -> dict[str, Any]:
    """
    Reconstruct a read-only historical projection of case state at target_version.
    Strictly read-only; no database rows are mutated.
    """
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    case = await db.get(Case, case_uuid)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    current_version = case.state_version or 1

    if target_version < 1 or target_version > current_version:
        raise HTTPException(
            status_code=400,
            detail=f"Target version {target_version} must be between 1 and current case version {current_version}"
        )

    # 1. Determine checkpoint timestamp T_v for target_version
    ckpt_q = select(InvestigationState).where(
        InvestigationState.case_id == case_uuid,
        InvestigationState.version == target_version,
    )
    ckpt = (await db.execute(ckpt_q)).scalars().first()

    if ckpt and ckpt.created_at:
        t_v = ckpt.created_at
        state_hash = ckpt.state_hash
    else:
        # Fallback for version 1 if no explicit checkpoint was inserted
        t_v = case.created_at or datetime.now(timezone.utc)
        state_hash = None

    # Determine cutoff timestamp T_cutoff for target_version
    # If target_version < current_version, find checkpoint for target_version + 1.
    # Anything strictly before T_cutoff was part of target_version or earlier.
    # Anything at or after T_cutoff belongs to target_version + 1 or later.
    t_cutoff = None
    if target_version < current_version:
        ckpt_next_q = select(InvestigationState).where(
            InvestigationState.case_id == case_uuid,
            InvestigationState.version == target_version + 1,
        )
        ckpt_next = (await db.execute(ckpt_next_q)).scalars().first()
        if ckpt_next and ckpt_next.created_at:
            t_cutoff = ckpt_next.created_at
        else:
            t_cutoff = t_v

    # 2. Query all activities for this case
    all_acts_q = (
        select(InvestigationActivity)
        .where(InvestigationActivity.case_id == case_uuid)
        .order_by(InvestigationActivity.created_at.asc())
    )
    activities = list((await db.execute(all_acts_q)).scalars().all())

    if t_cutoff is None:
        # target_version == current_version: all activities are before or at cursor
        acts_before = activities
        acts_after = []
    else:
        acts_before = [a for a in activities if a.created_at and a.created_at < t_cutoff]
        acts_after = [a for a in activities if a.created_at and a.created_at >= t_cutoff]

    # Map of relationship status changes that occurred AFTER target_version
    rel_changed_after: dict[str, dict[str, Any]] = {}
    for a in acts_after:
        if a.target_type == "relationship" and a.target_id:
            rel_changed_after[a.target_id] = {
                "activity_type": a.activity_type,
                "created_at": a.created_at,
            }

    # Map of candidate resolutions that occurred AFTER target_version
    cand_resolved_after: set[str] = set()
    for a in acts_after:
        if a.activity_type == "IDENTITY_CANDIDATE_RESOLVED" and a.target_id:
            cand_resolved_after.add(a.target_id)

    # 3. Entities present at target_version
    if t_cutoff is None:
        ent_q = select(Entity).where(Entity.case_id == case_uuid)
    else:
        ent_q = select(Entity).where(
            Entity.case_id == case_uuid,
            Entity.created_at < t_cutoff,
        )
    entities = list((await db.execute(ent_q)).scalars().all())

    # 4. Relationships created at or before target_version
    if t_cutoff is None:
        rel_q = select(Relationship).where(Relationship.case_id == case_uuid)
    else:
        rel_q = select(Relationship).where(
            Relationship.case_id == case_uuid,
            Relationship.created_at < t_cutoff,
        )
    relationships = list((await db.execute(rel_q)).scalars().all())

    canonical_rels_projected: list[dict[str, Any]] = []
    inferred_rels_projected: list[dict[str, Any]] = []

    for r in relationships:
        r_id_str = str(r.id)

        # Check if this relationship was modified by an activity after target_version
        if r_id_str in rel_changed_after:
            # If reviewed after target_version, at target_version its status was UNREVIEWED
            v_status = RT.REVIEW_UNREVIEWED
            is_canon = (r.epistemic_status == RT.OBSERVED)
        else:
            v_status = r.verification_status
            is_canon = RT.is_canonical_eligible(r.epistemic_status, r.verification_status)

        # Invariant: Rejected relationships are NEVER canonical
        if v_status == RT.REVIEW_REJECTED:
            is_canon = False

        rel_data = {
            "id": r_id_str,
            "source_entity_id": str(r.source_entity_id),
            "target_entity_id": str(r.target_entity_id),
            "relationship_type": r.relationship_type,
            "direction": r.direction,
            "epistemic_status": r.epistemic_status,
            "verification_status": v_status,
            "is_canonical": is_canon,
            "confidence": r.confidence,
            "evidence_refs": r.evidence_refs or [],
            "event_refs": r.event_refs or [],
        }

        if is_canon:
            canonical_rels_projected.append(rel_data)
        else:
            inferred_rels_projected.append(rel_data)

    # 5. Identity candidates present at target_version
    if t_cutoff is None:
        cand_q = select(IdentityCandidate).where(IdentityCandidate.case_id == case_uuid)
    else:
        cand_q = select(IdentityCandidate).where(
            IdentityCandidate.case_id == case_uuid,
            IdentityCandidate.created_at < t_cutoff,
        )
    candidates = list((await db.execute(cand_q)).scalars().all())

    candidates_projected: list[dict[str, Any]] = []
    unresolved_cand_count = 0

    for c in candidates:
        c_id_str = str(c.id)
        # If resolved after target_version, at target_version it was UNRESOLVED
        if c_id_str in cand_resolved_after or (t_cutoff is not None and c.resolved_at and c.resolved_at >= t_cutoff):
            res_status = "UNRESOLVED"
        else:
            res_status = c.resolution_status

        if res_status == "UNRESOLVED":
            unresolved_cand_count += 1

        candidates_projected.append({
            "id": c_id_str,
            "canonical_entity_id": str(c.canonical_entity_id) if c.canonical_entity_id else None,
            "candidate_value": c.candidate_value,
            "candidate_type": c.candidate_type,
            "resolution_status": res_status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    # 6. Findings present at or before target_version
    if t_cutoff is None:
        finding_q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_uuid)
    else:
        finding_q = select(InvestigationFinding).where(
            InvestigationFinding.case_id == case_uuid,
            InvestigationFinding.created_at < t_cutoff,
        )
    findings = list((await db.execute(finding_q)).scalars().all())

    # Filter findings generated on or before target_version
    findings_projected: list[dict[str, Any]] = []
    for f in findings:
        gen_v = getattr(f, "generated_at_case_version", 1) or 1
        if gen_v <= target_version:
            findings_projected.append({
                "id": str(f.id),
                "finding_type": f.finding_type,
                "title": f.title,
                "severity": f.severity,
                "confidence": f.confidence,
                "status": f.status,
                "freshness_status": getattr(f, "freshness_status", "CURRENT"),
                "generated_at_case_version": gen_v,
                "evidence_refs": f.evidence_refs or [],
                "entity_refs": f.entity_refs or [],
            })

    # 7. Evidence files present at target_version
    if t_cutoff is None:
        file_q = select(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
    else:
        file_q = select(EvidenceFile).where(
            EvidenceFile.case_id == case_uuid,
            EvidenceFile.uploaded_at < t_cutoff,
        )
    evidence_files = list((await db.execute(file_q)).scalars().all())

    # Determine triggering activity at cursor
    cursor_activity = None
    if acts_before:
        latest_act = acts_before[-1]
        cursor_activity = {
            "id": str(latest_act.id),
            "activity_type": latest_act.activity_type,
            "target_type": latest_act.target_type,
            "target_id": latest_act.target_id,
            "actor_id": str(latest_act.actor_id) if latest_act.actor_id else None,
            "reason": latest_act.reason,
            "created_at": latest_act.created_at.isoformat() if latest_act.created_at else None,
        }

    return {
        "case_id": str(case.id),
        "case_number": case.case_number,
        "title": case.title,
        "state_version": target_version,
        "current_case_version": current_version,
        "is_historical": (target_version < current_version),
        "checkpoint_timestamp": t_v.isoformat() if t_v else None,
        "state_hash": state_hash,
        "cursor_activity": cursor_activity,
        "metrics": {
            "entities_count": len(entities),
            "canonical_relationships_count": len(canonical_rels_projected),
            "inferred_relationships_count": len(inferred_rels_projected),
            "findings_count": len(findings_projected),
            "unresolved_candidates_count": unresolved_cand_count,
            "evidence_files_count": len(evidence_files),
        },
        "entities": [
            {
                "id": str(e.id),
                "canonical_value": e.canonical_value,
                "entity_type": e.entity_type,
                "degree_centrality": e.degree_centrality or 0.0,
                "bridge_score": e.bridge_score or 0.0,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entities
        ],
        "relationships": {
            "canonical": canonical_rels_projected,
            "inferred": inferred_rels_projected,
        },
        "identity_candidates": candidates_projected,
        "findings": findings_projected,
    }
