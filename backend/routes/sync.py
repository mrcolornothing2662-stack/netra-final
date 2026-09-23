from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Offline Synchronization API Router
Exposes:
- GET  /cases/{case_id}/offline-bundle
- POST /cases/{case_id}/sync
- GET  /cases/{case_id}/conflicts
- POST /cases/{case_id}/conflicts/{conflict_id}/resolve
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SyncConflictRecord, User
from db.session import get_db
from investigation.sync_contracts import (
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    OfflineBundleResponse,
    SyncBatchRequest,
    SyncBatchResponse,
    SyncConflict,
)
from investigation.sync_engine import OfflineSyncEngine
from routes.auth import get_current_user
from routes.case_access import require_case_access

sync_router = APIRouter()


@sync_router.get(
    "/{case_id}/offline-bundle",
    response_model=OfflineBundleResponse,
    tags=["sync"],
)
async def get_offline_case_bundle(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Download complete, read-only case state snapshot for local SQLite initialization.
    Strictly read-only; no database rows are mutated (Invariant 2).
    """
    await require_case_access(db, current_user, case_id)
    return await OfflineSyncEngine.build_offline_bundle(db, case_id, current_user)


@sync_router.post(
    "/{case_id}/sync",
    response_model=SyncBatchResponse,
    tags=["sync"],
)
async def sync_offline_mutations(
    case_id: str,
    request: SyncBatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Synchronize a batch of queued offline mutations.
    Reconciles mutations through Command Gateway and returns tri-state outcome
    (accepted, rebased, conflicts, rejected) along with projection delta.
    """
    await require_case_access(db, current_user, case_id, write=True)
    return await OfflineSyncEngine.process_sync_batch(db, case_id, request, current_user)


@sync_router.get(
    "/{case_id}/conflicts",
    response_model=list[SyncConflict],
    tags=["sync"],
)
async def list_pending_conflicts(
    case_id: str,
    status: str = Query("PENDING_REVIEW", description="Filter by conflict status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List sync conflicts requiring investigator adjudication.
    """
    await require_case_access(db, current_user, case_id)
    try:
        case_uuid = uuid.UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case_id UUID")

    q = select(SyncConflictRecord).where(
        SyncConflictRecord.case_id == case_uuid,
        SyncConflictRecord.status == status,
    ).order_by(SyncConflictRecord.created_at.desc())

    records = list((await db.execute(q)).scalars().all())
    return [
        SyncConflict(
            conflict_id=str(r.id),
            mutation_id=r.mutation_id,
            command_type=r.command_type,
            conflict_type=r.conflict_type,
            client_payload=r.client_payload or {},
            server_current_state=r.server_current_state or {},
            message=f"Conflict on {r.command_type}: Offline mutation conflicts with current server state.",
            status=r.status,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in records
    ]


@sync_router.post(
    "/{case_id}/conflicts/{conflict_id}/resolve",
    response_model=ConflictResolutionResponse,
    tags=["sync"],
)
async def resolve_sync_conflict(
    case_id: str,
    conflict_id: str,
    request: ConflictResolutionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Adjudicate an explicit sync conflict.
    Supports KEEP_SERVER, APPLY_OFFLINE, CREATE_NEW_REVIEW.
    Audits resolution and updates case version (Invariant 8).
    """
    await require_case_access(db, current_user, case_id, write=True)
    return await OfflineSyncEngine.resolve_sync_conflict(db, case_id, conflict_id, request, current_user)
