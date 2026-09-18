from __future__ import annotations

"""
CyberDrishti AI — Intelligence State

Materialises "what NETRA currently knows about this case" — evidence, entities,
relationships and findings counts — so the Cognitive tab can render intelligence
without recomputing engines. One row per case, refreshed after each analysis run.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    CaseIntelligenceState,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
)
from graph.relationship_types import INFERRED, OBSERVED
from orchestration.contracts import HIGH_PRIORITY_SEVERITIES


async def _count(db: AsyncSession, column, *where) -> int:
    q = select(func.count()).select_from(column)
    if where:
        q = q.where(*where)
    return int((await db.execute(q)).scalar() or 0)


async def compute_state(
    db: AsyncSession,
    case_id,
    *,
    engine_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the current intelligence snapshot for a case."""
    evidence_count = await _count(db, EvidenceFile, EvidenceFile.case_id == case_id)
    processed_evidence_count = await _count(
        db, EvidenceFile, EvidenceFile.case_id == case_id, EvidenceFile.upload_status == "processed"
    )
    entity_count = await _count(db, Entity, Entity.case_id == case_id)
    event_count = await _count(db, EvidenceEvent, EvidenceEvent.case_id == case_id)
    relationship_count = await _count(db, Relationship, Relationship.case_id == case_id)
    observed_relationship_count = await _count(
        db, Relationship, Relationship.case_id == case_id, Relationship.epistemic_status == OBSERVED
    )
    inferred_relationship_count = await _count(
        db, Relationship, Relationship.case_id == case_id, Relationship.epistemic_status == INFERRED
    )
    finding_count = await _count(db, InvestigationFinding, InvestigationFinding.case_id == case_id)
    high_priority_count = await _count(
        db, InvestigationFinding,
        InvestigationFinding.case_id == case_id,
        InvestigationFinding.severity.in_(tuple(HIGH_PRIORITY_SEVERITIES)),
    )

    by_type_rows = (await db.execute(
        select(InvestigationFinding.finding_type, func.count())
        .where(InvestigationFinding.case_id == case_id)
        .group_by(InvestigationFinding.finding_type)
    )).all()
    findings_by_type = {str(t): int(c) for t, c in by_type_rows}

    state = {
        "evidence_count":              evidence_count,
        "processed_evidence_count":    processed_evidence_count,
        "entity_count":                entity_count,
        "event_count":                 event_count,
        "relationship_count":          relationship_count,
        "observed_relationship_count": observed_relationship_count,
        "inferred_relationship_count": inferred_relationship_count,
        "finding_count":               finding_count,
        "high_priority_count":         high_priority_count,
        "findings_by_type":            findings_by_type,
    }
    if engine_status is not None:
        state["engine_status"] = engine_status
    return state


async def persist_state(
    db: AsyncSession,
    case_id,
    state: dict[str, Any],
    *,
    last_run_id=None,
) -> CaseIntelligenceState:
    """Upsert the single per-case state row from a computed snapshot."""
    row = (await db.execute(
        select(CaseIntelligenceState).where(CaseIntelligenceState.case_id == case_id)
    )).scalar_one_or_none()

    if row is None:
        row = CaseIntelligenceState(case_id=case_id)
        db.add(row)

    row.evidence_count = state.get("evidence_count", 0)
    row.processed_evidence_count = state.get("processed_evidence_count", 0)
    row.entity_count = state.get("entity_count", 0)
    row.event_count = state.get("event_count", 0)
    row.relationship_count = state.get("relationship_count", 0)
    row.observed_relationship_count = state.get("observed_relationship_count", 0)
    row.inferred_relationship_count = state.get("inferred_relationship_count", 0)
    row.finding_count = state.get("finding_count", 0)
    row.high_priority_count = state.get("high_priority_count", 0)
    row.findings_by_type = state.get("findings_by_type", {})
    if "engine_status" in state:
        row.engine_status = state["engine_status"]
    if last_run_id is not None:
        row.last_run_id = last_run_id
        row.last_run_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def get_state(db: AsyncSession, case_id) -> CaseIntelligenceState | None:
    return (await db.execute(
        select(CaseIntelligenceState).where(CaseIntelligenceState.case_id == case_id)
    )).scalar_one_or_none()


def serialize_state(row: CaseIntelligenceState | None, case_id: str) -> dict[str, Any]:
    if row is None:
        return {"case_id": case_id, "computed": False}
    return {
        "case_id":                      case_id,
        "computed":                     True,
        "evidence_count":               row.evidence_count,
        "processed_evidence_count":     row.processed_evidence_count,
        "entity_count":                 row.entity_count,
        "event_count":                  row.event_count,
        "relationship_count":           row.relationship_count,
        "observed_relationship_count":  row.observed_relationship_count,
        "inferred_relationship_count":  row.inferred_relationship_count,
        "finding_count":                row.finding_count,
        "high_priority_count":          row.high_priority_count,
        "findings_by_type":             row.findings_by_type or {},
        "engine_status":                row.engine_status or {},
        "last_run_id":                  str(row.last_run_id) if row.last_run_id else None,
        "last_run_at":                  row.last_run_at.isoformat() if row.last_run_at else None,
        "updated_at":                   row.updated_at.isoformat() if row.updated_at else None,
    }
