from __future__ import annotations
"""Shared case authorization for all evidence-derived workflows."""
import logging
import uuid
from typing import Optional, Set

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, User, CaseCollaborator
from db.session import AsyncSessionLocal
from utils.audit import append_audit

logger = logging.getLogger("cyberdrishti.security")


async def log_case_authorization(
    action: str,  # "CASE_ACCESS_ALLOWED" | "CASE_ACCESS_DENIED"
    case_id: str,
    user: User,
    details: dict,
) -> None:
    """
    Log an access decision to the tamper-evident audit ledger in an isolated transaction.
    This guarantees authorization audit entries are committed even if the outer transaction
    rolls back (e.g. on 403/404 HTTP exceptions).
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            # Verify if user exists in committed DB state to prevent FK errors during isolated test transactions
            u_exists = await audit_session.get(User, user.id)
            user_id_val = str(user.id) if u_exists else None
            user_meta = {**details, "acting_user_id": str(user.id), "username": getattr(user, "username", None)}

            await append_audit(
                audit_session,
                action=action,
                resource_type="case",
                resource_id=case_id,
                details=user_meta,
                user_id=user_id_val,
            )
            await audit_session.commit()
    except Exception as e:
        logger.error(f"Failed to record {action} in audit ledger: {e}")


async def require_case_access(
    db: AsyncSession,
    current: User,
    case_id: str,
    *,
    write: bool = False,
    required_roles: Optional[Set[str]] = None,
) -> Case:
    """
    Enforce per-case access control:
    1. Assigned Lead Officer (case.assigned_officer_id == current.id)
    2. Case Collaborators (explicitly registered in case_collaborators table)
    3. Admins do NOT have universal case read/write access unless explicitly assigned.
    4. Observers have read-only access.
    5. Every authorization decision (ALLOW or DENY) is logged in the tamper-evident audit chain.
    """
    case = None
    try:
        case_uuid = uuid.UUID(str(case_id))
        case = await db.get(Case, case_uuid)
    except (TypeError, ValueError):
        pass

    if case is None:
        res = await db.execute(
            select(Case).where((Case.case_number == str(case_id)) | (Case.title.ilike(f"%{case_id}%")))
        )
        case = res.scalars().first()

    if case is None:
        await log_case_authorization(
            "CASE_ACCESS_DENIED",
            str(case_id),
            current,
            {"reason": "case_not_found", "write_requested": write},
        )
        raise HTTPException(404, "Case not found")

    is_assigned = (case.assigned_officer_id == current.id)
    collaborator_role: Optional[str] = None

    if not is_assigned:
        collab_res = await db.execute(
            select(CaseCollaborator).where(
                CaseCollaborator.case_id == case.id,
                CaseCollaborator.user_id == current.id,
            )
        )
        collab = collab_res.scalars().first()
        if collab:
            collaborator_role = collab.role

    has_access = is_assigned or (collaborator_role is not None)

    if not has_access:
        await log_case_authorization(
            "CASE_ACCESS_DENIED",
            str(case.id),
            current,
            {
                "reason": "unassigned_user",
                "user_role": current.role,
                "write_requested": write,
            },
        )
        # 404 to avoid leaking existence of an investigation
        raise HTTPException(404, "Case not found")

    effective_role = "lead_io" if is_assigned else (collaborator_role or "observer")

    if write:
        if effective_role == "observer":
            await log_case_authorization(
                "CASE_ACCESS_DENIED",
                str(case.id),
                current,
                {
                    "reason": "observer_readonly",
                    "effective_role": effective_role,
                    "write_requested": True,
                },
            )
            raise HTTPException(403, "Insufficient permissions: observers have read-only access")

        if required_roles and effective_role not in required_roles:
            await log_case_authorization(
                "CASE_ACCESS_DENIED",
                str(case.id),
                current,
                {
                    "reason": "insufficient_collaborator_role",
                    "effective_role": effective_role,
                    "required_roles": list(required_roles),
                    "write_requested": True,
                },
            )
            raise HTTPException(403, "Insufficient permissions for requested action")

    # Access permitted
    await log_case_authorization(
        "CASE_ACCESS_ALLOWED",
        str(case.id),
        current,
        {
            "effective_role": effective_role,
            "write": write,
        },
    )

    return case

