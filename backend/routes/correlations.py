from __future__ import annotations
"""
CyberDrishti AI — Correlation / Hidden-Link Routes
POST /correlations/{case_id}/run   — trigger rule-based correlation analysis
GET  /correlations/{case_id}       — list flagged correlations with explanations
POST /correlations/{id}/verify     — investigator confirms/disputes a correlation

The scan itself lives in ``correlation.runner`` so the cognitive orchestrator can
materialise inferred relationships using the exact same logic.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from correlation.runner import DEFAULT_THRESHOLD, WEIGHTS, run_case_correlations
from db.models import Correlation, Entity, User
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access
from utils.audit import append_audit

router = APIRouter()


class VerifyPayload(BaseModel):
    verdict: str   # "confirmed" | "disputed"
    notes: Optional[str] = None


# ── Endpoint: Run correlation analysis ──────────────────────────────────────

@router.post("/{case_id}/run")
async def run_correlations(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Trigger rule-based hidden-link analysis for a case. Delegates to the shared
    runner (also used by the cognitive orchestrator) so inferred edges are
    produced identically whether the run is manual or automatic.
    """
    case = await require_case_access(db, current, case_id)
    result = await run_case_correlations(db, case)

    await append_audit(
        db,
        action="CORRELATION_RUN",
        resource_type="case",
        resource_id=str(case.id),
        details={
            "flagged_count": result.get("flagged", 0),
            "entity_count": result.get("entity_count", 0),
            "inferred_relationships": result.get("inferred_relationships", 0),
        },
        user_id=str(current.id),
    )
    await db.commit()

    result["case_id"] = str(case.id)
    return result


# ── Endpoint: List correlations ───────────────────────────────────────────────

@router.get("/{case_id}")
async def list_correlations(
    case_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """List flagged correlations for a case, enriched with entity details."""
    case = await require_case_access(db, current, case_id)
    c_id = case.id

    corrs = (await db.execute(
        select(Correlation).where(
            Correlation.case_id == c_id,
            Correlation.decision == "flagged",
        ).order_by(Correlation.final_score.desc()).limit(limit)
    )).scalars().all()

    # Fetch entity details
    entity_ids = set()
    for c in corrs:
        entity_ids.add(c.entity_a_id)
        entity_ids.add(c.entity_b_id)

    entities_map = {}
    if entity_ids:
        rows = (await db.execute(
            select(Entity).where(Entity.id.in_(list(entity_ids)))
        )).scalars().all()
        entities_map = {e.id: e for e in rows}

    result = []
    for c in corrs:
        ea = entities_map.get(c.entity_a_id)
        eb = entities_map.get(c.entity_b_id)
        if ea and ea.entity_type in {"AMOUNT", "KEYWORD"}:
            continue
        if eb and eb.entity_type in {"AMOUNT", "KEYWORD"}:
            continue
        result.append({
            "id": str(c.id),
            "case_id": case_id,
            "entity_a": {
                "id": str(c.entity_a_id),
                "type": ea.entity_type if ea else "UNKNOWN",
                "value": ea.canonical_value if ea else str(c.entity_a_id),
            },
            "entity_b": {
                "id": str(c.entity_b_id),
                "type": eb.entity_type if eb else "UNKNOWN",
                "value": eb.canonical_value if eb else str(c.entity_b_id),
            },
            "final_score": round(c.final_score, 4),
            "threshold": c.threshold,
            "decision": c.decision,
            "component_scores": c.component_scores or {},
            "model_weights": c.model_weights or {},
            "source_citations": c.source_citations or [],
            "verified_by": str(c.verified_by) if c.verified_by else None,
            "verified_at": c.verified_at.isoformat() if c.verified_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return {"case_id": case_id, "count": len(result), "correlations": result}


# ── Endpoint: Verify/dispute a correlation ────────────────────────────────────

@router.post("/{correlation_id}/verify")
async def verify_correlation(
    correlation_id: str,
    payload: VerifyPayload,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """Investigator confirms or disputes a flagged hidden link."""
    # Coerce the path id to the PK's Python type before db.get. The cross-dialect
    # UUID column (Uuid(as_uuid=True) on SQLite) binds via value.hex and raises
    # 'str has no attribute hex' if handed a raw string — so a bare db.get with
    # the path string 500s on SQLite. Matches routes/case_access.require_case_access.
    try:
        corr_uuid = uuid.UUID(str(correlation_id))
    except (TypeError, ValueError):
        raise HTTPException(404, "Correlation not found")
    corr = await db.get(Correlation, corr_uuid)
    if not corr:
        raise HTTPException(404, "Correlation not found")

    # Case isolation: a correlation may only be verified by someone with access
    # to the case it belongs to (admin, or the assigned officer). Without this
    # an authenticated user could mutate the verdict of any case's correlation
    # by ID (IDOR). require_case_access raises 404 for inaccessible cases.
    await require_case_access(db, current, str(corr.case_id), write=True)

    if payload.verdict not in ("confirmed", "disputed"):
        raise HTTPException(400, "verdict must be 'confirmed' or 'disputed'")

    # Map the investigator's verdict onto the detector-decision domain the schema
    # permits (CHECK ck_correlations_decision IN ('flagged','not_flagged')).
    # verified_by/verified_at record that a human reviewed the link; `decision`
    # holds the post-review truth — a confirmed link stays flagged, a disputed one
    # becomes not_flagged and correctly drops out of the flagged list. The exact
    # human verdict is preserved verbatim in the tamper-evident audit entry below,
    # so no information is lost. Writing the raw verdict into `decision` would
    # violate the CHECK constraint and 500 on every verification.
    corr.decision = "flagged" if payload.verdict == "confirmed" else "not_flagged"
    corr.verified_by = current.id
    corr.verified_at = datetime.now(timezone.utc)
    if payload.notes:
        scores = dict(corr.component_scores or {})
        scores["investigator_notes"] = payload.notes
        corr.component_scores = scores

    await append_audit(
        db,
        action="CORRELATION_VERIFIED",
        resource_type="correlation",
        resource_id=correlation_id,
        details={"verdict": payload.verdict, "notes": payload.notes},
        user_id=str(current.id),
    )
    await db.commit()

    return {"id": correlation_id, "verdict": payload.verdict, "verified_by": str(current.id)}
