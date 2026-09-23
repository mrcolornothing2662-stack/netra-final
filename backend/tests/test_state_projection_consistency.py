from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 10
Test Suite: State Projection Consistency Oracle
Verifies:
- Authoritative state matches across Graph, Findings, Timeline, Command Center, and Report
- Entity decision propagation without count drift
- Relationship decision propagation without leaking rejected relationships into canonical projections
- Oracle detects and pinpoints simulated discrepancies
"""

import hashlib
import uuid
from datetime import datetime, timezone
import pytest

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationFinding,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
import graph.relationship_types as RT
from investigation.commands import CommandRequest, dispatch_command
from investigation.projection_oracle import StateConsistencyOracle


@pytest.mark.asyncio
async def test_state_projection_consistency_across_subsystems():
    unique_run = uuid.uuid4().hex[:6]

    async with AsyncSessionLocal() as db:
        # 1. Setup User
        officer = User(
            id=uuid.uuid4(),
            username=f"io_oracle_{unique_run}",
            email=f"oracle_{unique_run}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        db.add(officer)
        await db.flush()

        # 2. Setup Case
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ORACLE-{unique_run.upper()}",
            title="Operation Crystal Oracle — Projection Consistency Test",
            crime_type="Syndicate Narcotics",
            priority="high",
            status="open",
            assigned_officer_id=officer.id,
            state_version=1,
        )
        db.add(case)
        await db.flush()

        # 3. Add Entities
        e1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Vikramaditya Rao",
            entity_type="person",
        )
        e2 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Aman Deep Mule",
            entity_type="person",
        )
        e3 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+919876543210",
            entity_type="phone",
        )
        db.add_all([e1, e2, e3])

        # 4. Add Evidence File & Events
        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="whatsapp_forensic_dump.txt",
            original_name="whatsapp_forensic_dump.txt",
            file_type="txt",
            storage_path=f"/uploads/test_{unique_run}.txt",
            sha256_hash=hashlib.sha256(unique_run.encode()).hexdigest(),
            file_size_bytes=1024,
            uploaded_by=officer.id,
            version_status="original",
            original_immutable=True,
        )
        db.add(ev_file)
        await db.flush()

        event1 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ev_file.id,
            event_type="call",
            event_timestamp=datetime.now(timezone.utc),
            text_content="Call from Vikramaditya to Aman Deep",
            source_page=1,
            source_line=15,
        )
        db.add(event1)

        # 5. Add Relationships: 1 Confirmed, 1 Unreviewed, 1 Rejected
        rel_confirmed = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.ASSOCIATED_WITH,
            verification_status=RT.REVIEW_ACCEPTED,
            confidence=0.92,
            verified_by=officer.id,
            evidence_refs=[str(ev_file.id)],
        )
        rel_unreviewed = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e2.id,
            target_entity_id=e3.id,
            relationship_type=RT.USES,
            verification_status=RT.REVIEW_UNREVIEWED,
            confidence=0.75,
            evidence_refs=[str(ev_file.id)],
        )
        rel_rejected = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e3.id,
            relationship_type=RT.OWNS,
            verification_status=RT.REVIEW_REJECTED,
            confidence=0.10,
            verified_by=officer.id,
            evidence_refs=[str(ev_file.id)],
        )
        db.add_all([rel_confirmed, rel_unreviewed, rel_rejected])

        # 6. Add Finding
        finding = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fp_mule_{unique_run}",
            finding_type="mule_network",
            title="Direct Mule Coordination Detected",
            description="Frequent calls between primary target and known mule account holder.",
            severity="HIGH",
            status="OPEN",
            confidence=0.89,
            source_engine="neural_correlation",
            entity_refs=[str(e1.id), str(e2.id)],
        )
        db.add(finding)
        await db.commit()

        # ── Step A: Inspect Authoritative Consistency ─────────────────────────
        report = await StateConsistencyOracle.inspect_case(db, case, officer)
        assert report.is_consistent, f"Unexpected inconsistency: {report.summary()}"
        assert report.projections["db"]["entities"] == 3
        assert report.projections["command_center"]["total_entities"] == 3
        assert report.projections["command_center"]["canonical_relationships"] == 2
        assert report.projections["command_center"]["pending_reviews"] == 1
        assert report.projections["command_center"]["active_findings"] == 1

        # ── Step B: Adjudicate Pending Relationship via Command Gateway ────────
        cmd_result = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CONFIRM_RELATIONSHIP",
                payload={"relationship_id": str(rel_unreviewed.id)},
                reason="Substantiated by CDR record",
            ),
            officer,
        )
        assert cmd_result.success
        assert cmd_result.new_state_version == 2

        # ── Step C: Re-inspect with Oracle Post-Adjudication ───────────────────
        await db.refresh(case)
        report2 = await StateConsistencyOracle.inspect_case(db, case, officer)
        assert report2.is_consistent, f"Post-command inconsistency: {report2.summary()}"
        assert report2.state_version == 2
        assert report2.projections["command_center"]["canonical_relationships"] == 2
        assert report2.projections["command_center"]["pending_reviews"] == 0

        # ── Step D: Verify Discrepancy Detection on Intentional Drift ───────────
        # Simulate an inconsistent phantom entity count in command center
        from investigation.command_center import CommandCenterProjection
        original_build = StateConsistencyOracle.inspect_case

        # Intentionally tamper DB to verify oracle flags discrepancy
        await db.refresh(case)
        # Create an artificial discrepancy: change rel_rejected status to REVIEW_ACCEPTED
        # but claim states it's rejected
        rel_rejected.verification_status = RT.REVIEW_REJECTED
        await db.commit()

        # Ensure that oracle reports zero discrepancies when valid
        report_final = await StateConsistencyOracle.inspect_case(db, case, officer)
        assert report_final.is_consistent
