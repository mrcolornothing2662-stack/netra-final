from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Security Event Center Routes
Provides controlled administrative projections of audit events, security denials,
active sessions/devices, and cryptographic chain verification.
Guarded by ADMIN_SECURITY capability.
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog, SyncConflictRecord, User, UserSession
from db.session import get_db
from investigation.policies import CAP_ADMIN_SECURITY, user_has_capability
from routes.auth import get_current_user, _revoke_jti
from security.audit_verifier import AuditVerifier
from utils.audit import append_audit

router = APIRouter()


def require_admin_security():
    async def _check(current: User = Depends(get_current_user)):
        if not user_has_capability(current.role, CAP_ADMIN_SECURITY):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Role '{current.role}' lacks '{CAP_ADMIN_SECURITY}' capability.",
            )
        return current
    return _check


CATEGORY_ACTION_MAP: dict[str, list[str]] = {
    "failed_auth": ["LOGIN_FAILED", "ACCOUNT_LOCKED"],
    "evidence_access": [
        "EVIDENCE_ACCESS_GRANTED",
        "EVIDENCE_ACCESS_DENIED",
        "EVIDENCE_DOWNLOADED",
        "EVIDENCE_MUTATION_BLOCKED",
        "EVIDENCE_DERIVATIVE_CREATED",
        "EVIDENCE_VARIANT_DELETED",
    ],
    "permission_denials": [
        "CASE_ACCESS_DENIED",
        "EVIDENCE_ACCESS_DENIED",
        "EVIDENCE_MUTATION_BLOCKED",
    ],
    "report_approvals": [
        "REPORT_SNAPSHOT_APPROVED",
        "REPORT_SNAPSHOT_REJECTED",
        "DOSSIER_EXPORT_APPROVED",
        "DOSSIER_EXPORT_REJECTED",
    ],
    "exports": [
        "REPORT_SNAPSHOT_EXPORTED",
        "DOSSIER_EXPORT_COMPLETED",
        "DOSSIER_EXPORT_APPROVED",
    ],
    "case_access": [
        "CASE_ACCESS_ALLOWED",
        "CASE_ACCESS_DENIED",
    ],
    "offline_conflicts": [
        "SYNC_CONFLICT_RECORDED",
        "SYNC_CONFLICT_RESOLVED",
        "SYNC_MUTATION_APPLIED",
    ],
    "sessions": [
        "SESSION_REVOKED",
        "SESSION_ELEVATED",
        "LOGIN_SUCCESS",
    ],
}


@router.get("/overview")
async def get_security_overview(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin_security()),
):
    """
    High-level security telemetry and cryptographic audit health status.
    Strictly read-only projection.
    """
    # 1. Cryptographic ledger verification
    ledger_status = await AuditVerifier.verify_ledger(db)

    # 2. Aggregations from AuditLog
    total_events = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0

    failed_auth_count = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action.in_(CATEGORY_ACTION_MAP["failed_auth"]))
    )).scalar() or 0

    denials_count = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action.in_(CATEGORY_ACTION_MAP["permission_denials"]))
    )).scalar() or 0

    evidence_access_count = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action.in_(CATEGORY_ACTION_MAP["evidence_access"]))
    )).scalar() or 0

    report_approvals_count = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action.in_(CATEGORY_ACTION_MAP["report_approvals"]))
    )).scalar() or 0

    export_count = (await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.action.in_(CATEGORY_ACTION_MAP["exports"]))
    )).scalar() or 0

    # 3. Active Sessions and Offline Conflicts
    active_sessions_count = (await db.execute(
        select(func.count(UserSession.id)).where(UserSession.revoked == False)
    )).scalar() or 0

    offline_conflicts_count = (await db.execute(
        select(func.count(SyncConflictRecord.id))
    )).scalar() or 0

    return {
        "status": "HEALTHY" if ledger_status.get("intact") else "TAMPERING_DETECTED",
        "audit_chain": ledger_status,
        "metrics": {
            "total_audit_events": total_events,
            "failed_auth_events": failed_auth_count,
            "permission_denials": denials_count,
            "evidence_access_events": evidence_access_count,
            "report_approvals": report_approvals_count,
            "export_events": export_count,
            "active_sessions": active_sessions_count,
            "offline_conflicts": offline_conflicts_count,
        },
    }


@router.get("/events")
async def list_security_events(
    category: str = Query("all", description="Category filter e.g. all, failed_auth, evidence_access, permission_denials, report_approvals, exports, case_access, offline_conflicts, sessions"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin_security()),
):
    """
    Paginated security event stream projected from the immutable audit ledger.
    """
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))

    cat_norm = category.strip().lower()
    if cat_norm != "all" and cat_norm in CATEGORY_ACTION_MAP:
        actions = CATEGORY_ACTION_MAP[cat_norm]
        stmt = stmt.where(AuditLog.action.in_(actions))
        count_stmt = count_stmt.where(AuditLog.action.in_(actions))

    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()

    items = []
    for r in rows:
        # Categorize
        event_cat = "other"
        for k, acts in CATEGORY_ACTION_MAP.items():
            if r.action in acts:
                event_cat = k
                break

        items.append({
            "id": r.id,
            "action": r.action,
            "category": event_cat,
            "user_id": str(r.user_id) if r.user_id else None,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "event_timestamp": r.event_timestamp.isoformat() if r.event_timestamp else None,
            "details": r.details_json or {},
            "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash,
        })

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "category": cat_norm,
        "items": items,
    }


@router.get("/sessions")
async def list_all_active_sessions(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin_security()),
):
    """
    Administrative overview of all active, expired, and revoked user device sessions.
    """
    stmt = (
        select(UserSession, User)
        .join(User, UserSession.user_id == User.id)
        .order_by(UserSession.last_seen.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "session_id": sess.id,
            "user_id": str(sess.user_id),
            "username": u.username,
            "full_name": u.full_name,
            "rank": u.rank,
            "role": u.role,
            "device_id": sess.device_id,
            "issued_at": sess.issued_at.isoformat() if sess.issued_at else None,
            "expires_at": sess.expires_at.isoformat() if sess.expires_at else None,
            "last_seen": sess.last_seen.isoformat() if sess.last_seen else None,
            "authentication_level": sess.authentication_level,
            "revoked": sess.revoked,
            "revoked_reason": sess.revoked_reason,
            "ip_address": sess.ip_address,
            "user_agent": sess.user_agent,
        }
        for sess, u in rows
    ]


@router.post("/sessions/{session_id}/revoke")
async def admin_revoke_session(
    session_id: str,
    reason: Optional[str] = Query("Administrative revocation"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_admin_security()),
):
    """
    Admin kill switch: Instantly revoke an active device session.
    """
    res = await db.execute(select(UserSession).where(UserSession.id == session_id))
    sess = res.scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    sess.revoked = True
    sess.revoked_reason = reason or "Administrative revocation"

    await _revoke_jti(session_id, 86400 * 7)

    await append_audit(
        db,
        action="SESSION_REVOKED_BY_ADMIN",
        user_id=current.id,
        resource_type="user_session",
        resource_id=session_id,
        details={
            "target_user_id": str(sess.user_id),
            "device_id": sess.device_id,
            "reason": reason,
        },
    )
    await db.commit()
    return {"status": "ok", "message": f"Session '{session_id}' revoked by administrator."}
