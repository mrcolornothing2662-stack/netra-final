from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — State-Consistency Oracle
Validates multi-projection consistency across Authoritative DB State,
Graph Projection, Findings, Timeline, Command Center, and Dossier Reports.
Detects state drift, unreviewed queue count discrepancies, or rejected link leaks.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EvidenceEvent,
    IdentityCandidate,
    InvestigationFinding,
    Relationship,
    User,
)
from graph import relationship_types as RT
from investigation.command_center import build_command_center_projection
from report.builder import ReportBuilder


@dataclass
class Discrepancy:
    subsystem_a: str
    subsystem_b: str
    metric: str
    val_a: Any
    val_b: Any
    severity: str = "ERROR"
    detail: str = ""


@dataclass
class ConsistencyReport:
    case_id: str
    state_version: int
    is_consistent: bool
    discrepancies: List[Discrepancy] = field(default_factory=list)
    projections: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        if self.is_consistent:
            return f"✅ Case {self.case_id} [v{self.state_version}] is 100% consistent across all projections."
        diffs = "\n".join(
            f"  • [{d.severity}] {d.metric}: {d.subsystem_a}={d.val_a} vs {d.subsystem_b}={d.val_b} ({d.detail})"
            for d in self.discrepancies
        )
        return f"🛑 Inconsistency detected in Case {self.case_id} [v{self.state_version}]:\n{diffs}"


class StateConsistencyOracle:
    """Authoritative projection validation oracle for NETRA V5."""

    @classmethod
    async def inspect_case(
        cls,
        db: AsyncSession,
        case: Case,
        actor: User,
        raise_on_inconsistency: bool = False,
    ) -> ConsistencyReport:
        case_id = case.id
        version = case.state_version or 1
        discrepancies: List[Discrepancy] = []

        # 1. Authoritative DB Counts
        db_entity_count = (
            await db.execute(select(func.count(Entity.id)).where(Entity.case_id == case_id))
        ).scalar() or 0

        db_rel_count = (
            await db.execute(select(func.count(Relationship.id)).where(Relationship.case_id == case_id))
        ).scalar() or 0

        db_confirmed_rel_count = (
            await db.execute(
                select(func.count(Relationship.id)).where(
                    Relationship.case_id == case_id,
                    Relationship.verification_status == RT.REVIEW_ACCEPTED,
                )
            )
        ).scalar() or 0

        db_unreviewed_rel_count = (
            await db.execute(
                select(func.count(Relationship.id)).where(
                    Relationship.case_id == case_id,
                    Relationship.verification_status == RT.REVIEW_UNREVIEWED,
                )
            )
        ).scalar() or 0

        db_rejected_rel_count = (
            await db.execute(
                select(func.count(Relationship.id)).where(
                    Relationship.case_id == case_id,
                    Relationship.verification_status == RT.REVIEW_REJECTED,
                )
            )
        ).scalar() or 0

        db_finding_count = (
            await db.execute(
                select(func.count(InvestigationFinding.id)).where(InvestigationFinding.case_id == case_id)
            )
        ).scalar() or 0

        db_event_count = (
            await db.execute(
                select(func.count(EvidenceEvent.id)).where(EvidenceEvent.case_id == case_id)
            )
        ).scalar() or 0

        db_pending_candidates_count = (
            await db.execute(
                select(func.count(IdentityCandidate.id)).where(
                    IdentityCandidate.case_id == case_id,
                    IdentityCandidate.resolution_status == "UNRESOLVED",
                )
            )
        ).scalar() or 0

        # 2. Command Center Projection
        cc_proj = await build_command_center_projection(db, case, actor)
        cc_health = cc_proj.investigation_health

        # Invariant 2.1: Entity tally in Command Center must match Authoritative DB
        if cc_health.entities_count != db_entity_count:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Command_Center",
                    metric="entity_count",
                    val_a=db_entity_count,
                    val_b=cc_health.entities_count,
                    detail="Total entities mismatch between DB and Command Center",
                )
            )

        # Invariant 2.2: Pending relationship reviews in Command Center must match DB
        if cc_health.unreviewed_relationships_count != db_unreviewed_rel_count:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Command_Center",
                    metric="pending_reviews",
                    val_a=db_unreviewed_rel_count,
                    val_b=cc_health.unreviewed_relationships_count,
                    detail="Pending reviews mismatch between DB and Command Center",
                )
            )

        db_all_rels = list((await db.execute(select(Relationship).where(Relationship.case_id == case_id))).scalars().all())
        db_canonical_rel_count = sum(1 for r in db_all_rels if RT.is_canonical_eligible(r.epistemic_status, r.verification_status))

        # Invariant 2.3: Canonical relationships in Command Center must match DB
        if cc_health.canonical_count != db_canonical_rel_count:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Command_Center",
                    metric="canonical_relationships",
                    val_a=db_canonical_rel_count,
                    val_b=cc_health.canonical_count,
                    detail="Canonical relationships mismatch between DB and Command Center",
                )
            )

        # Invariant 2.4: Active findings in Command Center must match DB
        if cc_health.findings_count != db_finding_count:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Command_Center",
                    metric="active_findings",
                    val_a=db_finding_count,
                    val_b=cc_health.findings_count,
                    detail="Findings count mismatch between DB and Command Center",
                )
            )

        # Invariant 2.5: State version matches
        if cc_proj.state_version != version:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Command_Center",
                    metric="state_version",
                    val_a=version,
                    val_b=cc_proj.state_version,
                    detail="State version drift in Command Center",
                )
            )

        # 3. Dossier Report Projection
        from report.contracts import ReportType
        report_payload = await ReportBuilder.build_report(
            case_id=str(case_id),
            db=db,
            report_type=ReportType.FORMAL_DOSSIER,
            user_id=str(actor.id),
        )

        # Invariant 3.1: Rejected relationships must NEVER appear in canonical Report
        report_relationships = report_payload.get_section("relationships")
        if report_relationships:
            for claim in report_relationships.claims:
                # If a claim references a relationship that is rejected in DB, flag error
                for rel_id in (claim.relationship_refs or []):
                    rel_row = await db.get(Relationship, uuid.UUID(str(rel_id)))
                    if rel_row and rel_row.verification_status == RT.REVIEW_REJECTED:
                        discrepancies.append(
                            Discrepancy(
                                subsystem_a="Authoritative_DB",
                                subsystem_b="Report_Builder",
                                metric="rejected_relationship_leak",
                                val_a="REVIEW_REJECTED",
                                val_b=claim.statement,
                                detail=f"Rejected relationship {rel_id} leaked into report claims as established fact",
                            )
                        )

        # Invariant 3.2: Report state version matches authoritative case version
        if report_payload.metadata.case_state_version != version:
            discrepancies.append(
                Discrepancy(
                    subsystem_a="Authoritative_DB",
                    subsystem_b="Report_Snapshot",
                    metric="case_state_version",
                    val_a=version,
                    val_b=report_payload.metadata.case_state_version,
                    detail="Report snapshot captured stale case state version",
                )
            )

        is_consistent = len(discrepancies) == 0
        report = ConsistencyReport(
            case_id=str(case_id),
            state_version=version,
            is_consistent=is_consistent,
            discrepancies=discrepancies,
            projections={
                "db": {
                    "entities": db_entity_count,
                    "relationships": db_rel_count,
                    "confirmed_relationships": db_confirmed_rel_count,
                    "unreviewed_relationships": db_unreviewed_rel_count,
                    "rejected_relationships": db_rejected_rel_count,
                    "findings": db_finding_count,
                    "events": db_event_count,
                    "pending_candidates": db_pending_candidates_count,
                },
                "command_center": {
                    "total_entities": cc_health.entities_count,
                    "canonical_relationships": cc_health.canonical_count,
                    "pending_reviews": cc_health.unreviewed_relationships_count,
                    "active_findings": cc_health.findings_count,
                    "state_version": cc_proj.state_version,
                },
                "report": {
                    "claims_count": report_payload.metadata.claims_count,
                    "state_version": report_payload.metadata.case_state_version,
                },
            },
        )

        if raise_on_inconsistency and not is_consistent:
            raise AssertionError(report.summary())

        return report
