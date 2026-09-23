"""
CyberDrishti AI — Audit Routes (Phase 7)
Tamper-evident audit chain verification.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog, User
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access

router = APIRouter()


def _canonical_ts(dt: datetime | None) -> str:
    """Reproduce the exact timestamp string that append_audit hashed.

    append_audit hashes ``datetime.now(timezone.utc).isoformat()`` — a UTC
    *aware* value ending in ``+00:00``. PostgreSQL (TIMESTAMPTZ) returns that
    unchanged, but SQLite/aiosqlite drops the tzinfo on read, yielding a naive
    datetime whose ``.isoformat()`` has no offset. Recomputing the chain with
    that naive string produced a hash mismatch on every entry, so a perfectly
    intact chain was reported BROKEN on SQLite deployments. Normalising the
    read-back value back to UTC-aware makes verification reproduce the bytes
    that were actually signed, on either dialect, without weakening tamper
    detection (a real edit to any field still changes the hash).
    """
    if dt is None:
        return ""
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.isoformat()


@router.get("")
@router.get("/")
async def list_all_audit_logs(
    page:          int = 1,
    page_size:     int = 50,
    action:        str | None = None,
    resource_type: str | None = None,
    case_id:       str | None = None,
    db:            AsyncSession = Depends(get_db),
    current:       User = Depends(get_current_user),
):
    """Paginated global audit ledger for admin/analyst, with optional filters.

    Filters (all optional): action, resource_type, case_id (matches rows whose
    resource_type == 'case' AND resource_id == case_id).
    """
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if case_id:
        conditions.append(AuditLog.resource_type == "case")
        conditions.append(AuditLog.resource_id == case_id)

    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)
    stmt = stmt.order_by(AuditLog.id.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = (await db.execute(stmt)).scalars().all()

    total = (await db.execute(count_stmt)).scalar() or 0

    return {
        "page":  page,
        "total": total,
        "items": [
            {
                "id":              row.id,
                "action":          row.action,
                "user_id":         str(row.user_id) if row.user_id else None,
                "resource_type":   row.resource_type,
                "resource_id":     row.resource_id,
                "prev_hash":       row.prev_hash,
                "entry_hash":      row.entry_hash,
                "event_timestamp": row.event_timestamp.isoformat() if row.event_timestamp else None,
                "details":         row.details_json,
            }
            for row in rows
        ],
    }


@router.get("/verify")
async def verify_global_audit_chain(
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Recompute the entire global audit chain from the genesis entry using AuditVerifier."""
    from security.audit_verifier import AuditVerifier
    return await AuditVerifier.verify_ledger(db)


@router.get("/verify/{case_id}")
async def verify_audit_chain(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("fiu_analyst", "admin", "io", "investigator", "manager")),
):
    """
    Recompute the entire audit chain for a given case from the genesis entry.
    Returns {"intact": true} or {"intact": false, "first_broken_entry_id": <id>}.
    """
    await require_case_access(db, current, case_id)
    from security.audit_verifier import AuditVerifier
    return await AuditVerifier.verify_ledger(db, case_id=case_id)



@router.get("/{case_id}")
async def list_audit_log(
    case_id:   str,
    page:      int = 1,
    page_size: int = 50,
    db:        AsyncSession = Depends(get_db),
    current:   User = Depends(get_current_user),
):
    """Paginated audit log for a case."""
    await require_case_access(db, current, case_id)
    rows = (await db.execute(
        select(AuditLog)
        .where(AuditLog.resource_id == case_id)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    total = (await db.execute(
        select(func.count()).select_from(AuditLog).where(AuditLog.resource_id == case_id)
    )).scalar() or 0

    return {
        "page":  page,
        "total": total,
        "items": [
            {
                "id":             row.id,
                "action":         row.action,
                "user_id":        str(row.user_id) if row.user_id else None,
                "entry_hash":     row.entry_hash,
                "event_timestamp": row.event_timestamp.isoformat() if row.event_timestamp else None,
                "details":        row.details_json,
            }
            for row in rows
        ],
    }
