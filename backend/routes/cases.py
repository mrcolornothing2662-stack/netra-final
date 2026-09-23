"""
CyberDrishti AI — Cases Routes
CRUD for cases + audit logging on every mutation.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog, Case, User, EvidenceFile, EvidenceEvent, Entity, EntityMention, Correlation, InvestigationFinding, Relationship, CaseCollaborator
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class CaseCreate(BaseModel):
    title:          str
    description:    str | None = None
    crime_type:     str | None = None
    fir_number:     str | None = None
    police_station: str | None = None
    priority:       str = "medium"
    tags:           list[str] = Field(default_factory=list)


class CaseUpdate(BaseModel):
    title:              str | None = None
    description:        str | None = None
    crime_type:         str | None = None
    fir_number:         str | None = None
    police_station:     str | None = None
    priority:           str | None = None
    status:             str | None = None
    assigned_officer_id: str | None = None
    tags:               list[str] | None = None


class CaseOut(BaseModel):
    id:             str
    case_number:    str
    title:          str
    description:    str | None
    crime_type:     str | None
    fir_number:     str | None
    police_station: str | None
    priority:       str
    status:         str
    assigned_officer_id: str | None
    tags:           list[str] | None
    state_version:  int = 1
    created_at:     str
    updated_at:     str

    @classmethod
    def from_orm(cls, c: Case) -> "CaseOut":
        return cls(
            id=str(c.id),
            case_number=c.case_number,
            title=c.title,
            description=c.description,
            crime_type=c.crime_type,
            fir_number=c.fir_number,
            police_station=c.police_station,
            priority=c.priority,
            status=c.status,
            assigned_officer_id=str(c.assigned_officer_id) if c.assigned_officer_id else None,
            tags=c.tags or [],
            state_version=c.state_version or 1,
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else "",
        )


class CollaboratorAdd(BaseModel):
    user_id: str
    role: str = "io"  # lead_io, assisting_io, fiu_analyst, observer, supervisor, io


class CollaboratorOut(BaseModel):
    id: str
    case_id: str
    user_id: str
    username: str | None = None
    full_name: str | None = None
    role: str
    assigned_by: str | None = None
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _audit(db: AsyncSession, user: User, action: str, case_id: str, details: dict):
    """Append a tamper-evident audit log entry via the canonical writer.

    Delegates to utils.audit.append_audit so there is exactly ONE audit-writer
    implementation (previously this file duplicated the hashing logic). The
    canonical writer also serializes appends under a Postgres advisory lock.
    """
    from utils.audit import append_audit

    await append_audit(
        db=db,
        action=action,
        resource_type="case",
        resource_id=case_id,
        details=details,
        user_id=str(user.id),
    )


def _gen_case_number() -> str:
    ts = datetime.now(timezone.utc)
    return f"CYB-{ts.year}-{str(uuid.uuid4())[:8].upper()}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_cases(
    status:   str | None = Query(None),
    priority: str | None = Query(None),
    page:     int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    collab_subq = select(CaseCollaborator.case_id).where(CaseCollaborator.user_id == current.id)
    q = select(Case)
    if current.role != "admin":
        q = q.where((Case.assigned_officer_id == current.id) | (Case.id.in_(collab_subq)))
    if status:
        q = q.where(Case.status == status)
    if priority:
        q = q.where(Case.priority == priority)
    q = q.order_by(Case.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    cases = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return {
        "total": total,
        "page":  page,
        "items": [CaseOut.from_orm(c) for c in cases],
    }


@router.post("", response_model=CaseOut, status_code=201)
async def create_case(
    body:    CaseCreate,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    pri = (body.priority or "medium").lower()
    if pri in ("critical", "urgent"):
        pri = "high"
    elif pri not in ("high", "medium", "low"):
        pri = "medium"

    c = Case(
        case_number=_gen_case_number(),
        title=body.title,
        description=body.description,
        crime_type=body.crime_type,
        fir_number=body.fir_number,
        police_station=body.police_station,
        priority=pri,
        tags=body.tags,
        assigned_officer_id=current.id,
    )
    db.add(c)
    await db.flush()
    await _audit(db, current, "CASE_CREATED", str(c.id), {"title": c.title})
    return CaseOut.from_orm(c)


# NOTE: /stats/summary MUST be declared before /{case_id} to prevent
# FastAPI from capturing 'stats' as a case_id path parameter.
@router.get("/stats/summary", response_model=dict)
async def case_stats(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    collab_subq = select(CaseCollaborator.case_id).where(CaseCollaborator.user_id == current.id)
    access_filter = [] if current.role == "admin" else [(Case.assigned_officer_id == current.id) | (Case.id.in_(collab_subq))]
    
    total     = (await db.execute(select(func.count()).select_from(Case).where(*access_filter))).scalar() or 0
    open_c    = (await db.execute(select(func.count()).select_from(Case).where(
        *access_filter, Case.status.in_(["open", "in_progress"])))).scalar() or 0
    high_pri  = (await db.execute(select(func.count()).select_from(Case).where(
        *access_filter, Case.priority == "high"))).scalar() or 0
    closed    = (await db.execute(select(func.count()).select_from(Case).where(
        *access_filter, Case.status == "closed"))).scalar() or 0
    entities  = (await db.execute(select(func.count()).select_from(Entity))).scalar() or 0
    evidence  = (await db.execute(select(func.count()).select_from(EvidenceFile))).scalar() or 0

    return {
        "total": total,
        "open":  open_c,
        "high_priority": high_pri,
        "closed": closed,
        "entities": entities,
        "evidence": evidence,
    }


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    c = await require_case_access(db, current, case_id)
    return CaseOut.from_orm(c)


@router.patch("/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: str,
    body:    CaseUpdate,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    c = await require_case_access(db, current, case_id, write=True)

    updates: dict = body.model_dump(exclude_none=True)
    for key, val in updates.items():
        setattr(c, key, val)
    c.updated_at = datetime.now(timezone.utc)

    if body.status == "closed":
        c.closed_at = datetime.now(timezone.utc)

    await _audit(db, current, "CASE_UPDATED", case_id, updates)
    return CaseOut.from_orm(c)


@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("admin", "io", "fiu_analyst")),
):
    c = await require_case_access(db, current, case_id, write=True)
    case_uuid = c.id

    # Cascade delete child records using direct indexed case_id lookups
    await db.execute(delete(Relationship).where(Relationship.case_id == case_uuid))
    await db.execute(delete(InvestigationFinding).where(InvestigationFinding.case_id == case_uuid))
    await db.execute(delete(Correlation).where(Correlation.case_id == case_uuid))
    await db.execute(delete(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid))
    await db.execute(delete(Entity).where(Entity.case_id == case_uuid))
    await db.execute(delete(EvidenceFile).where(EvidenceFile.case_id == case_uuid))

    await _audit(db, current, "CASE_DELETED", str(case_uuid), {"title": c.title})
    await db.delete(c)
    return {"status": "success", "message": f"Case {c.case_number} deleted successfully"}


# ── Collaborator Endpoints ───────────────────────────────────────────────────

@router.get("/{case_id}/collaborators", response_model=list[CollaboratorOut])
async def list_case_collaborators(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    c = await require_case_access(db, current, case_id)
    res = await db.execute(
        select(CaseCollaborator, User.username, User.full_name)
        .join(User, CaseCollaborator.user_id == User.id)
        .where(CaseCollaborator.case_id == c.id)
        .order_by(CaseCollaborator.created_at)
    )
    results = []
    for collab, uname, fname in res.all():
        results.append(CollaboratorOut(
            id=str(collab.id),
            case_id=str(collab.case_id),
            user_id=str(collab.user_id),
            username=uname,
            full_name=fname,
            role=collab.role,
            assigned_by=str(collab.assigned_by) if collab.assigned_by else None,
            created_at=collab.created_at.isoformat() if collab.created_at else "",
        ))
    return results


@router.post("/{case_id}/collaborators", response_model=CollaboratorOut, status_code=201)
async def add_case_collaborator(
    case_id: str,
    body: CollaboratorAdd,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "admin")),
):
    c = await require_case_access(db, current, case_id, write=True)

    try:
        target_uuid = uuid.UUID(str(body.user_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid target user UUID")

    target_user = await db.get(User, target_uuid)
    if not target_user:
        raise HTTPException(404, "Target user to add as collaborator not found")

    role_norm = body.role.strip().lower()
    valid_roles = {"lead_io", "assisting_io", "fiu_analyst", "observer", "supervisor", "io"}
    if role_norm not in valid_roles:
        raise HTTPException(400, f"Invalid collaborator role. Allowed: {sorted(list(valid_roles))}")

    existing = (await db.execute(
        select(CaseCollaborator).where(
            CaseCollaborator.case_id == c.id,
            CaseCollaborator.user_id == target_uuid,
        )
    )).scalars().first()

    if existing:
        existing.role = role_norm
        collab = existing
    else:
        collab = CaseCollaborator(
            case_id=c.id,
            user_id=target_uuid,
            role=role_norm,
            assigned_by=current.id,
        )
        db.add(collab)

    await db.flush()
    await _audit(db, current, "COLLABORATOR_ASSIGNED", str(c.id), {
        "collaborator_id": str(target_uuid),
        "username": target_user.username,
        "role": role_norm,
    })

    return CollaboratorOut(
        id=str(collab.id),
        case_id=str(collab.case_id),
        user_id=str(collab.user_id),
        username=target_user.username,
        full_name=target_user.full_name,
        role=collab.role,
        assigned_by=str(collab.assigned_by) if collab.assigned_by else None,
        created_at=collab.created_at.isoformat() if collab.created_at else datetime.now(timezone.utc).isoformat(),
    )


@router.delete("/{case_id}/collaborators/{collaborator_user_id}")
async def remove_case_collaborator(
    case_id: str,
    collaborator_user_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "admin")),
):
    c = await require_case_access(db, current, case_id, write=True)

    try:
        target_uuid = uuid.UUID(str(collaborator_user_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid collaborator user UUID")

    res = await db.execute(
        select(CaseCollaborator).where(
            CaseCollaborator.case_id == c.id,
            CaseCollaborator.user_id == target_uuid,
        )
    )
    collab = res.scalars().first()
    if not collab:
        raise HTTPException(404, "Collaborator record not found")

    await db.delete(collab)
    await _audit(db, current, "COLLABORATOR_REMOVED", str(c.id), {
        "collaborator_id": str(target_uuid),
    })
    return {"status": "success", "message": "Collaborator removed successfully"}


@router.get("/{case_id}/evidence/{evidence_id}/usage")
async def get_case_evidence_usage(
    case_id: str,
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Bidirectional Evidence Usage: returns findings, relationships, and report claims citing this evidence.
    """
    from routes.reports import get_evidence_usage
    return await get_evidence_usage(case_id=case_id, evidence_id=evidence_id, db=db, current=current)
