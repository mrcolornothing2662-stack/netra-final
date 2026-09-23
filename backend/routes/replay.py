from __future__ import annotations

"""
CyberDrishti AI — Investigation Replay Routes (V5 Milestone 4)
Endpoints for timeline replay scrubbing and read-only historical state projections.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_db
from investigation.replay import get_case_replay_index, reconstruct_historical_state
from routes.auth import get_current_user
from routes.case_access import require_case_access

replay_router = APIRouter()


@replay_router.get("/{case_id}/replay")
async def get_case_replay_summary(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Return all recorded case state version checkpoints ($1 ... v_current)
    with timestamps, trigger activities, and actors to initialize the replay deck.
    """
    c = await require_case_access(db, current, case_id)
    return await get_case_replay_index(db, c.id)


@replay_router.get("/{case_id}/replay/{state_version}")
async def get_historical_replay_state(
    case_id: str,
    state_version: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Reconstruct a consistent, read-only historical case state projection at state_version.
    Strictly read-only; never mutates case state or increments version numbers.
    """
    c = await require_case_access(db, current, case_id)
    return await reconstruct_historical_state(db, c.id, target_version=state_version)
