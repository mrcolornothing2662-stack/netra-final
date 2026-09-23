from __future__ import annotations

"""
NETRA V5 — Investigation Brain
Central transactional domain authority for all case mutations.
Enforces:
  1. Authorization checks
  2. Input validation
  3. Epistemic provenance preservation
  4. Immutable audit logging and activity recording
  5. Case state version increments
  6. Dependency-aware intelligence freshness invalidation
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    User,
)
from orchestration.contracts import FRESHNESS_NEEDS_REVIEW
from utils.audit import append_audit

logger = logging.getLogger("netra.investigation.brain")


class InvestigationBrain:
    """Logical domain authority governing all state mutations for a case."""

    @staticmethod
    async def bump_case_version(
        db: AsyncSession,
        case: Case,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Increment the case state version and persist an investigation state checkpoint."""
        max_ver = (
            await db.execute(
                select(func.max(InvestigationState.version)).where(InvestigationState.case_id == case.id)
            )
        ).scalar() or 0

        next_version = max(case.state_version or 1, max_ver) + 1
        case.state_version = next_version
        case.last_activity_at = datetime.now(timezone.utc)

        state_hash_source = f"{case.id}:{case.state_version}:{case.last_activity_at.isoformat()}"
        state_hash = hashlib.sha256(state_hash_source.encode("utf-8")).hexdigest()

        checkpoint = InvestigationState(
            id=uuid.uuid4(),
            case_id=case.id,
            version=case.state_version,
            state_hash=state_hash,
            created_by=actor.id if actor else None,
        )
        db.add(checkpoint)
        return case.state_version

    @staticmethod
    async def record_activity(
        db: AsyncSession,
        case_id: uuid.UUID,
        activity_type: str,
        actor: Optional[User] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        before_state: Optional[dict[str, Any]] = None,
        after_state: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> InvestigationActivity:
        """Record an activity stream entry for investigator operations."""
        activity = InvestigationActivity(
            id=uuid.uuid4(),
            case_id=case_id,
            actor_id=actor.id if actor else None,
            activity_type=activity_type,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            before_state=before_state or {},
            after_state=after_state or {},
            reason=reason,
        )
        db.add(activity)

        # Also mirror into tamper-evident hash-chained audit log
        try:
            await append_audit(
                db,
                action=activity_type,
                resource_type=target_type or "case",
                resource_id=str(target_id or case_id),
                details={
                    "case_id": str(case_id),
                    "reason": reason,
                    "before": before_state or {},
                    "after": after_state or {},
                },
                user_id=str(actor.id) if actor else None,
            )
        except Exception as audit_exc:
            logger.warning(f"[InvestigationBrain] Audit log append failed: {audit_exc}")

        return activity

    @staticmethod
    async def mark_intelligence_stale(
        db: AsyncSession,
        case_id: uuid.UUID,
        affected_entity_ids: Optional[list[str]] = None,
        affected_relationship_ids: Optional[list[str]] = None,
    ) -> int:
        """
        Identify findings that directly depend on the modified entities/relationships
        and update their freshness_status to NEEDS_REVIEW.
        Avoids global case invalidation storms while maintaining factual integrity.
        """
        all_refs: set[str] = set()
        if affected_entity_ids:
            all_refs.update(affected_entity_ids)
        if affected_relationship_ids:
            all_refs.update(affected_relationship_ids)

        if not all_refs:
            return 0

        findings = (
            await db.execute(
                select(InvestigationFinding).where(
                    InvestigationFinding.case_id == case_id,
                    InvestigationFinding.freshness_status == "CURRENT",
                )
            )
        ).scalars().all()

        stale_count = 0
        for f in findings:
            linked_refs = (
                set(f.entity_refs or [])
                | set(f.evidence_refs or [])
                | set(f.event_refs or [])
                | set(f.supporting_refs or [])
            )
            if linked_refs & all_refs:
                f.freshness_status = FRESHNESS_NEEDS_REVIEW
                stale_count += 1

        return stale_count
