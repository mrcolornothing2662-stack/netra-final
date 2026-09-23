import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from db.models import Case, Entity, Relationship, IdentityCandidate, Hypothesis, User
from db.session import AsyncSessionLocal
from investigation.brain import InvestigationBrain
from investigation.commands import (
    CommandRequest,
    dispatch_command,
    handle_confirm_relationship,
    handle_reject_relationship,
    handle_add_investigator_relationship,
)
from investigation.policies import user_has_capability, CAP_CASE_CLOSE, CAP_RELATIONSHIP_CONFIRM
from investigation.state import get_case_workspace_snapshot
from graph import relationship_types as RT


@pytest.mark.asyncio
async def test_investigation_brain_versioning_and_activity():
    async with AsyncSessionLocal() as db:
        # Create test user and case
        user = User(
            id=uuid.uuid4(),
            username=f"officer_{uuid.uuid4().hex[:6]}",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hash",
            role="io",
        )
        db.add(user)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-BRAIN-{uuid.uuid4().hex[:6]}",
            title="Brain Test Case",
            priority="medium",
            status="open",
            assigned_officer_id=user.id,
            state_version=1,
        )
        db.add(case)
        await db.flush()

        # Bump version
        v2 = await InvestigationBrain.bump_case_version(db, case, actor=user, reason="Initial setup")
        assert v2 == 2
        assert case.state_version == 2

        # Record activity
        act = await InvestigationBrain.record_activity(
            db,
            case_id=case.id,
            activity_type="EVIDENCE_VERIFIED",
            actor=user,
            target_type="evidence",
            target_id="EVID-001",
            reason="SHA-256 verified",
        )
        assert act.activity_type == "EVIDENCE_VERIFIED"
        assert act.case_id == case.id

        await db.commit()


@pytest.mark.asyncio
async def test_command_gateway_confirm_and_reject_relationship():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_{uuid.uuid4().hex[:6]}",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hash",
            role="io",
        )
        db.add(user)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-REL-{uuid.uuid4().hex[:6]}",
            title="Relationship Review Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=1,
        )
        db.add(case)
        await db.flush()

        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Suspect A", entity_type="PERSON")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="+919876543210", entity_type="PHONE")
        db.add_all([e1, e2])
        await db.flush()

        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.USES,
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_UNREVIEWED,
        )
        db.add(rel)
        await db.commit()

        # 1. Dispatch CONFIRM_RELATIONSHIP
        req = CommandRequest(
            command="CONFIRM_RELATIONSHIP",
            payload={"relationship_id": str(rel.id)},
            reason="Confirmed via subscriber form",
        )
        res = await dispatch_command(db, case.id, req, user)
        assert res.success is True
        assert res.new_state_version == 2

        # Verify DB state
        async with AsyncSessionLocal() as db2:
            rel_refreshed = await db2.get(Relationship, rel.id)
            assert rel_refreshed.verification_status == RT.REVIEW_ACCEPTED
            assert rel_refreshed.verified_by == user.id

        # 2. Dispatch REJECT_RELATIONSHIP
        req_reject = CommandRequest(
            command="REJECT_RELATIONSHIP",
            payload={"relationship_id": str(rel.id)},
            reason="Disproved by alibi",
        )
        res2 = await dispatch_command(db, case.id, req_reject, user)
        assert res2.success is True
        assert res2.new_state_version == 3

        async with AsyncSessionLocal() as db3:
            rel_refreshed2 = await db3.get(Relationship, rel.id)
            assert rel_refreshed2.verification_status == RT.REVIEW_REJECTED
            assert not RT.is_canonical_eligible(rel_refreshed2.epistemic_status, rel_refreshed2.verification_status)


@pytest.mark.asyncio
async def test_add_investigator_relationship():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_{uuid.uuid4().hex[:6]}",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hash",
            role="io",
        )
        db.add(user)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-INV-{uuid.uuid4().hex[:6]}",
            title="Investigator Edge Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=5,
        )
        db.add(case)
        await db.flush()

        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Account A", entity_type="ACCOUNT")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Account B", entity_type="ACCOUNT")
        db.add_all([e1, e2])
        await db.commit()

        req = CommandRequest(
            command="ADD_INVESTIGATOR_RELATIONSHIP",
            payload={
                "source_entity_id": str(e1.id),
                "target_entity_id": str(e2.id),
                "relationship_type": RT.ASSOCIATED_WITH,
            },
            reason="Confidential informant confirmed shared control",
        )
        res = await dispatch_command(db, case.id, req, user)
        assert res.success is True
        assert res.new_state_version == 6

        async with AsyncSessionLocal() as db2:
            new_rel_id = uuid.UUID(res.data["relationship_id"])
            saved_rel = await db2.get(Relationship, new_rel_id)
            assert saved_rel.epistemic_status == RT.INVESTIGATOR_ADDED
            assert saved_rel.verification_status == RT.REVIEW_ACCEPTED
            assert RT.is_canonical_eligible(saved_rel.epistemic_status, saved_rel.verification_status) is True


@pytest.mark.asyncio
async def test_workspace_snapshot():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_{uuid.uuid4().hex[:6]}",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hash",
            role="io",
        )
        db.add(user)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-SNAP-{uuid.uuid4().hex[:6]}",
            title="Snapshot Test Case",
            priority="high",
            status="ACTIVE",
            assigned_officer_id=user.id,
            state_version=10,
        )
        db.add(case)
        await db.commit()

        snapshot = await get_case_workspace_snapshot(db, case.id, user)
        assert snapshot["case"]["case_number"] == case.case_number
        assert snapshot["case"]["state_version"] == 10
        assert "permissions" in snapshot
        assert "metrics" in snapshot
        assert "important_findings" in snapshot
        assert "open_hypotheses" in snapshot
