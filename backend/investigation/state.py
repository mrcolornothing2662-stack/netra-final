from __future__ import annotations

"""
NETRA V5 — Workspace State Projection
Aggregates a consistent case workspace snapshot to power the case dashboard
without triggering dozens of disparate HTTP roundtrips.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    EvidenceEvent,
    EvidenceFile,
    Entity,
    Hypothesis,
    IdentityCandidate,
    InformationGap,
    InvestigationAction,
    InvestigationActivity,
    InvestigationFinding,
    Relationship,
    User,
)
from graph import relationship_types as RT
from investigation.policies import ROLE_CAPABILITIES


async def get_case_workspace_snapshot(
    db: AsyncSession,
    case_id: str | uuid.UUID,
    current_user: User,
) -> dict[str, Any]:
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
    case = await db.get(Case, case_uuid)
    if not case:
        return {"error": "case_not_found"}

    # User capabilities for this case
    norm_role = (current_user.role or "constable").lower()
    capabilities = list(ROLE_CAPABILITIES.get(norm_role, set()))

    # Counts
    ev_count = (await db.execute(
        select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
    )).scalar() or 0

    ev_proc_count = (await db.execute(
        select(func.count()).select_from(EvidenceFile).where(
            EvidenceFile.case_id == case_uuid, EvidenceFile.upload_status == "processed"
        )
    )).scalar() or 0

    entity_count = (await db.execute(
        select(func.count()).select_from(Entity).where(Entity.case_id == case_uuid)
    )).scalar() or 0

    event_count = (await db.execute(
        select(func.count()).select_from(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
    )).scalar() or 0

    all_relationships = (await db.execute(
        select(Relationship).where(Relationship.case_id == case_uuid)
    )).scalars().all()

    canonical_rels = [
        r for r in all_relationships if RT.is_canonical_eligible(r.epistemic_status, r.verification_status)
    ]
    analytical_rels = [
        r for r in all_relationships if r.epistemic_status == RT.INFERRED and r.verification_status == RT.REVIEW_UNREVIEWED
    ]

    findings = (await db.execute(
        select(InvestigationFinding)
        .where(InvestigationFinding.case_id == case_uuid)
        .order_by(InvestigationFinding.confidence.desc().nullslast(), InvestigationFinding.created_at.desc())
    )).scalars().all()

    important_findings = [
        {
            "id": str(f.id),
            "finding_type": f.finding_type,
            "title": f.title,
            "description": f.description,
            "severity": f.severity,
            "confidence": f.confidence,
            "status": f.status,
            "freshness_status": getattr(f, "freshness_status", "CURRENT"),
            "supporting_refs": getattr(f, "supporting_refs", []) or [],
            "contradicting_refs": getattr(f, "contradicting_refs", []) or [],
            "missing_information": getattr(f, "missing_information", []) or [],
            "suggested_actions": getattr(f, "suggested_actions", []) or [],
            "evidence_refs": f.evidence_refs or [],
            "entity_refs": f.entity_refs or [],
            "source_engine": f.source_engine,
            "generated_at_case_version": getattr(f, "generated_at_case_version", 1),
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in findings[:15]
    ]

    hypotheses = (await db.execute(
        select(Hypothesis).where(Hypothesis.case_id == case_uuid).order_by(Hypothesis.created_at.desc())
    )).scalars().all()

    candidates = (await db.execute(
        select(IdentityCandidate).where(
            IdentityCandidate.case_id == case_uuid, IdentityCandidate.resolution_status == "UNRESOLVED"
        )
    )).scalars().all()

    gaps = (await db.execute(
        select(InformationGap).where(InformationGap.case_id == case_uuid, InformationGap.status == "OPEN")
    )).scalars().all()

    activities = (await db.execute(
        select(InvestigationActivity)
        .where(InvestigationActivity.case_id == case_uuid)
        .order_by(InvestigationActivity.created_at.desc())
        .limit(10)
    )).scalars().all()

    return {
        "case_id": str(case.id),
        "state_version": case.state_version or 1,
        "case": {
            "id": str(case.id),
            "case_number": case.case_number,
            "title": case.title,
            "description": case.description,
            "crime_type": case.crime_type,
            "fir_number": case.fir_number,
            "priority": case.priority,
            "status": case.status,
            "state_version": case.state_version or 1,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "last_activity_at": case.last_activity_at.isoformat() if case.last_activity_at else None,
            "assigned_officer_id": str(case.assigned_officer_id) if case.assigned_officer_id else None,
        },
        "canonical_relationships": [
            {
                "id": str(r.id),
                "source_entity_id": str(r.source_entity_id),
                "target_entity_id": str(r.target_entity_id),
                "relationship_type": r.relationship_type,
                "epistemic_status": r.epistemic_status,
                "verification_status": r.verification_status,
                "is_canonical": True,
            }
            for r in canonical_rels
        ],
        "analytical_relationships": [
            {
                "id": str(r.id),
                "source_entity_id": str(r.source_entity_id),
                "target_entity_id": str(r.target_entity_id),
                "relationship_type": r.relationship_type,
                "epistemic_status": r.epistemic_status,
                "verification_status": r.verification_status,
                "is_canonical": False,
            }
            for r in analytical_rels
        ],
        "permissions": capabilities,
        "metrics": {
            "evidence_count": ev_count,
            "processed_evidence_count": ev_proc_count,
            "entity_count": entity_count,
            "event_count": event_count,
            "relationship_count": len(all_relationships),
            "canonical_relationship_count": len(canonical_rels),
            "analytical_relationship_count": len(analytical_rels),
            "finding_count": len(findings),
            "open_hypotheses_count": len(hypotheses),
            "unresolved_identity_candidates": len(candidates),
            "open_information_gaps": len(gaps),
        },
        "important_findings": important_findings,
        "open_hypotheses": [
            {
                "id": str(h.id),
                "title": h.title,
                "description": h.description,
                "status": h.status,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hypotheses
        ],
        "unresolved_identities": [
            {
                "id": str(c.id),
                "canonical_entity_id": str(c.canonical_entity_id) if c.canonical_entity_id else None,
                "candidate_value": c.candidate_value,
                "candidate_type": c.candidate_type,
                "status": c.resolution_status,
                "source_refs": c.source_refs or [],
            }
            for c in candidates
        ],
        "open_information_gaps": [
            {
                "id": str(g.id),
                "description": g.description,
                "importance": g.importance,
                "status": g.status,
            }
            for g in gaps
        ],
        "recent_activity": [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "reason": a.reason,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
    }
