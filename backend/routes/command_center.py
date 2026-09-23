from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Investigation Command Center API Router
Exposes:
- GET /cases/{case_id}/command-center
Assembles one consolidated, read-only command-center projection.
Strictly read-only; no database rows are mutated.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_db
from investigation.command_center import (
    CommandCenterProjection,
    build_command_center_projection,
)
from routes.auth import get_current_user
from routes.case_access import require_case_access

command_center_router = APIRouter()


@command_center_router.get(
    "/{case_id}/command-center",
    response_model=CommandCenterProjection,
    tags=["command-center"],
)
async def get_case_command_center(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return unified, read-only Investigation Command Center projection.
    Strictly read-only; no database rows mutated, no state version bumps.
    """
    case = await require_case_access(db, current_user, case_id)
    return await build_command_center_projection(db, case, current_user)
