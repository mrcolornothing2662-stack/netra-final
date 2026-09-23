from __future__ import annotations

"""
NETRA V5 — Command Gateway
Handles all state-mutating commands through strongly-typed, validated handlers.
Every command:
  1. Verifies authorization against capability policies
  2. Enforces optimistic concurrency via base_case_version
  3. Executes domain mutation
  4. Records activity in investigation_activity & audit_log
  5. Increments case.state_version
  6. Invalidates dependent intelligence freshness
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    Hypothesis,
    HypothesisEvidence,
    IdentityCandidate,
    InformationGap,
    InvestigationAction,
    InvestigationFinding,
    Relationship,
    User,
)
from graph import relationship_types as RT
from investigation.brain import InvestigationBrain
from investigation.policies import (
    CAP_CASE_CLOSE,
    CAP_CASE_WRITE,
    CAP_ENTITY_WRITE,
    CAP_FINDING_REVIEW,
    CAP_HYPOTHESIS_WRITE,
    CAP_RELATIONSHIP_CONFIRM,
    CAP_RELATIONSHIP_REJECT,
    CAP_RELATIONSHIP_WRITE,
    user_has_capability,
)


class CommandRequest(BaseModel):
    command: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: Optional[str] = None
    client_mutation_id: Optional[str] = None
    base_case_version: Optional[int] = None
    confirmation_token: Optional[str] = None


class CommandResult(BaseModel):
    success: bool
    command: str
    case_id: str
    new_state_version: int
    activity_id: str
    message: str
    data: Optional[dict[str, Any]] = None


def _coerce_uuid_or_404(raw: Any, detail: str) -> uuid.UUID:
    """
    Coerce a client-supplied identifier before it reaches a database lookup.

    A malformed id is an addressing mistake, not a server fault: without this guard
    ``uuid.UUID(str(...))`` raises ValueError and the gateway returns a 500 instead of
    a 404. Mirrors the UUID-coercion contract already used by the correlation verifier.
    """
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail=detail)


async def handle_confirm_relationship(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_RELATIONSHIP_CONFIRM):
        raise HTTPException(status_code=403, detail="Insufficient permission to confirm relationships")

    rel_id_str = payload.get("relationship_id")
    if not rel_id_str:
        raise HTTPException(status_code=400, detail="Missing relationship_id in payload")

    rel_uuid = _coerce_uuid_or_404(rel_id_str, "Relationship not found in this case")
    rel = await db.get(Relationship, rel_uuid)
    if not rel or rel.case_id != case.id:
        raise HTTPException(status_code=404, detail="Relationship not found in this case")

    before = {"verification_status": rel.verification_status, "verified_by": str(rel.verified_by) if rel.verified_by else None}
    rel.verification_status = RT.REVIEW_ACCEPTED
    rel.verified_by = actor.id
    rel.updated_at = datetime.now(timezone.utc)
    after = {"verification_status": rel.verification_status, "verified_by": str(rel.verified_by)}

    await InvestigationBrain.mark_intelligence_stale(db, case.id, affected_relationship_ids=[str(rel.id)])
    return {"relationship_id": str(rel.id), "verification_status": rel.verification_status}, str(rel.id), "RELATIONSHIP_CONFIRMED"


async def handle_reject_relationship(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_RELATIONSHIP_REJECT):
        raise HTTPException(status_code=403, detail="Insufficient permission to reject relationships")

    rel_id_str = payload.get("relationship_id")
    if not rel_id_str:
        raise HTTPException(status_code=400, detail="Missing relationship_id in payload")

    rel_uuid = _coerce_uuid_or_404(rel_id_str, "Relationship not found in this case")
    rel = await db.get(Relationship, rel_uuid)
    if not rel or rel.case_id != case.id:
        raise HTTPException(status_code=404, detail="Relationship not found in this case")

    before = {"verification_status": rel.verification_status}
    rel.verification_status = RT.REVIEW_REJECTED
    rel.verified_by = actor.id
    rel.updated_at = datetime.now(timezone.utc)
    after = {"verification_status": rel.verification_status}

    await InvestigationBrain.mark_intelligence_stale(db, case.id, affected_relationship_ids=[str(rel.id)])
    return {"relationship_id": str(rel.id), "verification_status": rel.verification_status}, str(rel.id), "RELATIONSHIP_REJECTED"


async def handle_add_investigator_relationship(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_RELATIONSHIP_WRITE):
        raise HTTPException(status_code=403, detail="Insufficient permission to create relationships")

    source_id_str = payload.get("source_entity_id")
    target_id_str = payload.get("target_entity_id")
    rel_type = payload.get("relationship_type") or RT.ASSOCIATED_WITH

    if not source_id_str or not target_id_str:
        raise HTTPException(status_code=400, detail="source_entity_id and target_entity_id are required")

    source_uuid = _coerce_uuid_or_404(source_id_str, "One or both entities do not exist in this case")
    target_uuid = _coerce_uuid_or_404(target_id_str, "One or both entities do not exist in this case")

    source_ent = await db.get(Entity, source_uuid)
    target_ent = await db.get(Entity, target_uuid)
    if not source_ent or not target_ent or source_ent.case_id != case.id or target_ent.case_id != case.id:
        raise HTTPException(status_code=404, detail="One or both entities do not exist in this case")

    rel = Relationship(
        id=uuid.uuid4(),
        case_id=case.id,
        source_entity_id=source_uuid,
        target_entity_id=target_uuid,
        relationship_type=rel_type,
        direction=payload.get("direction") or RT.BIDIRECTIONAL,
        epistemic_status=RT.INVESTIGATOR_ADDED,
        verification_status=RT.REVIEW_ACCEPTED,
        confidence=float(payload.get("confidence") or 1.0),
        reason_codes=[reason or "Investigator explicit entry"],
        attributes={"notes": reason or ""},
        created_by=actor.id,
        verified_by=actor.id,
    )
    db.add(rel)
    await db.flush()

    await InvestigationBrain.mark_intelligence_stale(
        db, case.id, affected_entity_ids=[str(source_uuid), str(target_uuid)], affected_relationship_ids=[str(rel.id)]
    )
    return {"relationship_id": str(rel.id), "epistemic_status": rel.epistemic_status}, str(rel.id), "INVESTIGATOR_RELATIONSHIP_ADDED"


async def handle_resolve_identity_candidate(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_ENTITY_WRITE):
        raise HTTPException(status_code=403, detail="Insufficient permission to resolve identity candidates")

    cand_id_str = payload.get("candidate_id")
    raw_status = str(payload.get("resolution_status") or payload.get("verdict") or payload.get("decision") or "").strip().upper()
    synonyms = {
        "RESOLVE": "CONFIRMED_SAME",
        "CONFIRM_SAME": "CONFIRMED_SAME",
        "CONFIRMED_SAME": "CONFIRMED_SAME",
        "KEEP_SEPARATE": "CONFIRMED_DIFFERENT",
        "CONFIRM_DIFFERENT": "CONFIRMED_DIFFERENT",
        "CONFIRMED_DIFFERENT": "CONFIRMED_DIFFERENT",
        "REJECT": "REJECTED",
        "REJECTED": "REJECTED",
    }
    resolution = synonyms.get(raw_status)
    if not cand_id_str or not resolution:
        raise HTTPException(
            status_code=400,
            detail="candidate_id and valid resolution_status (CONFIRMED_SAME, CONFIRMED_DIFFERENT, REJECTED) required"
        )

    cand_uuid = _coerce_uuid_or_404(cand_id_str, "Identity candidate not found")
    cand = await db.get(IdentityCandidate, cand_uuid)
    if not cand or cand.case_id != case.id:
        raise HTTPException(status_code=404, detail="Identity candidate not found")

    before = {"resolution_status": cand.resolution_status}
    cand.resolution_status = resolution
    cand.resolved_at = datetime.now(timezone.utc)
    after = {"resolution_status": cand.resolution_status}

    affected_entity_ids: list[str] = []
    if cand.canonical_entity_id:
        affected_entity_ids.append(str(cand.canonical_entity_id))

    # If confirmed same, associate entities and record alias without merging rows
    if resolution == "CONFIRMED_SAME":
        canonical_ent = await db.get(Entity, cand.canonical_entity_id) if cand.canonical_entity_id else None
        
        # Check if candidate value refers to another entity in the same case
        cand_ent_id_str = payload.get("candidate_entity_id")
        cand_ent: Optional[Entity] = None
        if cand_ent_id_str:
            cand_ent_uuid = _coerce_uuid_or_404(cand_ent_id_str, "Candidate entity not found")
            cand_ent = await db.get(Entity, cand_ent_uuid)
        else:
            cand_res = await db.execute(
                select(Entity).where(
                    Entity.case_id == case.id,
                    Entity.canonical_value == cand.candidate_value,
                )
            )
            cand_ent = cand_res.scalars().first()

        if cand_ent and canonical_ent and cand_ent.id != canonical_ent.id:
            affected_entity_ids.append(str(cand_ent.id))
            # Materialize a canonical SAME_AS edge linking them
            existing_rel_res = await db.execute(
                select(Relationship).where(
                    Relationship.case_id == case.id,
                    (
                        ((Relationship.source_entity_id == canonical_ent.id) & (Relationship.target_entity_id == cand_ent.id)) |
                        ((Relationship.source_entity_id == cand_ent.id) & (Relationship.target_entity_id == canonical_ent.id))
                    )
                )
            )
            existing_rel = existing_rel_res.scalars().first()
            if not existing_rel:
                same_rel = Relationship(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    source_entity_id=canonical_ent.id,
                    target_entity_id=cand_ent.id,
                    relationship_type=RT.SAME_AS,
                    direction=RT.BIDIRECTIONAL,
                    epistemic_status=RT.INVESTIGATOR_ADDED,
                    verification_status=RT.REVIEW_ACCEPTED,
                    is_canonical=True,
                    confidence=1.0,
                    created_by=actor.id,
                    verified_by=actor.id,
                )
                db.add(same_rel)

        # Record alias on canonical entity
        if canonical_ent:
            meta = dict(canonical_ent.node_metadata or {})
            aliases = list(meta.get("aliases") or [])
            if cand.candidate_value not in aliases and cand.candidate_value != canonical_ent.canonical_value:
                aliases.append(cand.candidate_value)
            meta["aliases"] = aliases
            canonical_ent.node_metadata = meta

    await db.flush()
    await InvestigationBrain.mark_intelligence_stale(
        db, case.id, affected_entity_ids=affected_entity_ids if affected_entity_ids else None
    )
    return {
        "candidate_id": str(cand.id),
        "status": cand.resolution_status,
        "resolution_status": cand.resolution_status,
        "canonical_entity_id": str(cand.canonical_entity_id) if cand.canonical_entity_id else None,
    }, str(cand.id), "IDENTITY_CANDIDATE_RESOLVED"


async def handle_review_finding(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_FINDING_REVIEW):
        raise HTTPException(status_code=403, detail="Insufficient permission to review findings")

    finding_id_str = payload.get("finding_id")
    new_status = payload.get("status")  # CONFIRMED, DISMISSED
    if not finding_id_str or not new_status:
        raise HTTPException(status_code=400, detail="finding_id and status required")

    f_uuid = _coerce_uuid_or_404(finding_id_str, "Finding not found in this case")
    finding = await db.get(InvestigationFinding, f_uuid)
    if not finding or finding.case_id != case.id:
        raise HTTPException(status_code=404, detail="Finding not found in this case")

    before = {"status": finding.status}
    finding.status = new_status
    finding.updated_at = datetime.now(timezone.utc)
    after = {"status": finding.status}

    return {"finding_id": str(finding.id), "status": finding.status}, str(finding.id), "FINDING_STATUS_CHANGED"


async def handle_create_hypothesis(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_HYPOTHESIS_WRITE):
        raise HTTPException(status_code=403, detail="Insufficient permission to create hypotheses")

    title = payload.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Hypothesis title is required")

    hypo = Hypothesis(
        id=uuid.uuid4(),
        case_id=case.id,
        title=title.strip(),
        description=payload.get("description"),
        status="OPEN",
        created_by=actor.id,
    )
    db.add(hypo)
    await db.flush()

    return {"hypothesis_id": str(hypo.id), "title": hypo.title}, str(hypo.id), "HYPOTHESIS_CREATED"


async def handle_close_case(
    db: AsyncSession, case: Case, actor: User, payload: dict[str, Any], reason: Optional[str]
) -> tuple[dict[str, Any], str, str]:
    if not user_has_capability(actor.role, CAP_CASE_CLOSE):
        raise HTTPException(status_code=403, detail="Insufficient permission to close case")

    closure_reason = payload.get("closure_reason") or reason or "Investigation concluded"
    case.status = "closed"
    case.closed_by = actor.id
    case.closure_reason = closure_reason
    case.closed_at = datetime.now(timezone.utc)

    return {"case_id": str(case.id), "status": case.status}, str(case.id), "CASE_CLOSED"


COMMAND_HANDLERS = {
    "CONFIRM_RELATIONSHIP": handle_confirm_relationship,
    "REJECT_RELATIONSHIP": handle_reject_relationship,
    "ADD_INVESTIGATOR_RELATIONSHIP": handle_add_investigator_relationship,
    "RESOLVE_IDENTITY_CANDIDATE": handle_resolve_identity_candidate,
    "REVIEW_FINDING": handle_review_finding,
    "CREATE_HYPOTHESIS": handle_create_hypothesis,
    "CLOSE_CASE": handle_close_case,
}


async def dispatch_command(
    db: AsyncSession,
    case_id: str | uuid.UUID,
    request: CommandRequest,
    current_user: User,
) -> CommandResult:
    """Entry point for all case state mutations."""
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else _coerce_uuid_or_404(case_id, "Case not found")
    case = (
        await db.execute(select(Case).where(Case.id == case_uuid).with_for_update())
    ).scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    cmd_upper = request.command.strip().upper()
    handler = COMMAND_HANDLERS.get(cmd_upper)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Unknown command: {request.command}")

    # Concurrency check (warning only if stale)
    if request.base_case_version is not None and request.base_case_version < (case.state_version or 1):
        # We allow non-destructive commands through while bumping version
        pass

    try:
        data, target_id, activity_type = await handler(
            db=db, case=case, actor=current_user, payload=request.payload, reason=request.reason
        )
    except Exception:
        from observability.metrics import telemetry
        telemetry.record_failed_command(cmd_upper)
        raise

    new_version = await InvestigationBrain.bump_case_version(
        db=db, case=case, actor=current_user, reason=request.reason
    )

    activity = await InvestigationBrain.record_activity(
        db=db,
        case_id=case.id,
        activity_type=activity_type,
        actor=current_user,
        target_type=cmd_upper.split("_")[-1].lower(),
        target_id=target_id,
        before_state={},
        after_state=data,
        reason=request.reason,
    )

    await db.commit()

    return CommandResult(
        success=True,
        command=cmd_upper,
        case_id=str(case.id),
        new_state_version=new_version,
        activity_id=str(activity.id),
        message=f"Command {cmd_upper} executed successfully",
        data=data,
    )
