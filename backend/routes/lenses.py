from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Forensic Lenses FastAPI Router
Exposes read-only, cross-lens synchronized projections:
- GET /cases/{case_id}/lenses
- GET /cases/{case_id}/lenses/money
- GET /cases/{case_id}/lenses/communications
- GET /cases/{case_id}/lenses/geographic
- GET /cases/{case_id}/lenses/{lens_type}/entity/{entity_id}
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_db
from forensic.contracts import (
    ForensicLensType,
    ForensicLensResponse,
    LensOverviewResponse,
)
from forensic.service import ForensicLensService
from routes.auth import get_current_user
from routes.case_access import require_case_access

lenses_router = APIRouter()


@lenses_router.get(
    "/{case_id}/lenses",
    response_model=LensOverviewResponse,
    tags=["lenses"],
)
async def get_lenses_overview(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Overview summary across all three forensic lenses for a case,
    including detected cross-domain coincidence counts.
    """
    await require_case_access(db, current_user, case_id)
    return await ForensicLensService.get_lenses_overview(db, case_id)


@lenses_router.get(
    "/{case_id}/lenses/money",
    response_model=ForensicLensResponse,
    tags=["lenses"],
)
async def get_money_trail_lens(
    case_id: str,
    entity_id: Optional[str] = Query(None, description="Filter by account, VPA, or entity ID"),
    start_time: Optional[datetime] = Query(None, description="Filter transactions after this timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter transactions before this timestamp"),
    state_version: Optional[int] = Query(None, description="Historical state version projection"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Money Trail Lens projection.
    Returns transaction flow graph, traceable ledger, rapid transfer signals, and round-number alerts.
    Strictly read-only; no database rows are mutated.
    """
    await require_case_access(db, current_user, case_id)
    return await ForensicLensService.get_forensic_lens(
        db=db,
        case_id=case_id,
        lens_type=ForensicLensType.MONEY,
        entity_id=entity_id,
        start_time=start_time,
        end_time=end_time,
        state_version=state_version,
    )


@lenses_router.get(
    "/{case_id}/lenses/communications",
    response_model=ForensicLensResponse,
    tags=["lenses"],
)
async def get_communications_lens(
    case_id: str,
    entity_id: Optional[str] = Query(None, description="Filter by phone number or participant entity"),
    start_time: Optional[datetime] = Query(None, description="Filter communications after this timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter communications before this timestamp"),
    state_version: Optional[int] = Query(None, description="Historical state version projection"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Communications Lens projection.
    Returns call graph, CDR and WhatsApp activity, 30-minute burst detection, and 24h temporal heatmap.
    Strictly read-only; no database rows are mutated.
    """
    await require_case_access(db, current_user, case_id)
    return await ForensicLensService.get_forensic_lens(
        db=db,
        case_id=case_id,
        lens_type=ForensicLensType.COMMUNICATION,
        entity_id=entity_id,
        start_time=start_time,
        end_time=end_time,
        state_version=state_version,
    )


@lenses_router.get(
    "/{case_id}/lenses/geographic",
    response_model=ForensicLensResponse,
    tags=["lenses"],
)
async def get_geographic_lens(
    case_id: str,
    entity_id: Optional[str] = Query(None, description="Filter by monitored phone identifier or tower"),
    start_time: Optional[datetime] = Query(None, description="Filter observations after this timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter observations before this timestamp"),
    state_version: Optional[int] = Query(None, description="Historical state version projection"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Travel / Geographic Lens projection.
    Returns cell-site association timeline, tower movement sequence, and non-GPS disclaimers.
    Strictly read-only; no database rows are mutated.
    """
    await require_case_access(db, current_user, case_id)
    return await ForensicLensService.get_forensic_lens(
        db=db,
        case_id=case_id,
        lens_type=ForensicLensType.GEOGRAPHIC,
        entity_id=entity_id,
        start_time=start_time,
        end_time=end_time,
        state_version=state_version,
    )


@lenses_router.get(
    "/{case_id}/lenses/{lens_type}/entity/{entity_id}",
    response_model=ForensicLensResponse,
    tags=["lenses"],
)
async def get_entity_focused_lens(
    case_id: str,
    lens_type: str,
    entity_id: str,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    state_version: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Entity-focused lens projection.
    Returns domain-specific lens filtered strictly to events and relationships involving entity_id.
    """
    await require_case_access(db, current_user, case_id)
    return await ForensicLensService.get_forensic_lens(
        db=db,
        case_id=case_id,
        lens_type=lens_type.upper(),
        entity_id=entity_id,
        start_time=start_time,
        end_time=end_time,
        state_version=state_version,
    )
