import asyncio
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from db.models import Case, Entity, EvidenceEvent, IdentityCandidate, Hypothesis, InvestigationFinding, Relationship, User
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from investigation.brain import InvestigationBrain
from investigation.commands import CommandRequest, dispatch_command
from investigation.state import get_case_workspace_snapshot
from orchestration.contracts import (
    FRESHNESS_CURRENT, FRESHNESS_NEEDS_REVIEW, CognitiveResult, NormalizedEvent
)
from orchestration.finding_service import upsert_finding, serialize_finding


@pytest.mark.asyncio
async def test_v5_dual_projection_and_review_lifecycle():
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"V5-DUAL-{uuid.uuid4().hex[:6]}",
            title="V5 Dual Projection Test Case",
            status="open",
            state_version=1,
        )
        uid = uuid.uuid4().hex[:6]
        officer = User(
            id=uuid.uuid4(),
            username=f"officer_{uid}",
            email=f"officer_{uid}@police.gov.in",
            full_name="Inspector Rao",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        # Create two entities
        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Vikram Singhania", entity_type="PER")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="ACC-998811", entity_type="ACCOUNT")
        db.add_all([e1, e2])
        await db.commit()

        # 1. Create an INFERRED relationship (e.g. from correlation runner)
        rel_inferred = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.OWNS,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            direction=RT.OUTBOUND,
            confidence=0.88,
        )
        db.add(rel_inferred)
        await db.commit()

        # Snapshot before confirmation: inferred edge must be in analytical overlay, NOT in canonical graph
        snap1 = await get_case_workspace_snapshot(db, case.id, officer)
        assert snap1["state_version"] == 1
        canon_rel_ids = [r["id"] for r in snap1["canonical_relationships"]]
        assert str(rel_inferred.id) not in canon_rel_ids
        analyt_rel_ids = [r["id"] for r in snap1["analytical_relationships"]]
        assert str(rel_inferred.id) in analyt_rel_ids

        # 2. Investigator confirms relationship via Command Gateway
        cmd_result = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CONFIRM_RELATIONSHIP",
                payload={"relationship_id": str(rel_inferred.id)},
                reason="Confirmed via bank branch KYC verification",
            ),
            officer,
        )
        assert cmd_result.success is True

        # Check state version incremented
        snap2 = await get_case_workspace_snapshot(db, case.id, officer)
        assert snap2["state_version"] == 2
        canon_rel_ids_2 = [r["id"] for r in snap2["canonical_relationships"]]
        assert str(rel_inferred.id) in canon_rel_ids_2

        # 3. Add an investigator-added edge
        e3 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Safehouse Alpha", entity_type="LOCATION")
        db.add(e3)
        await db.commit()

        cmd_add_rel = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="ADD_INVESTIGATOR_RELATIONSHIP",
                payload={
                    "source_entity_id": str(e1.id),
                    "target_entity_id": str(e3.id),
                    "relationship_type": RT.LOCATED_AT,
                },
                reason="Confidential informant field sighting",
            ),
            officer,
        )
        assert cmd_add_rel.success is True
        new_rel_id = cmd_add_rel.data["relationship_id"]

        snap3 = await get_case_workspace_snapshot(db, case.id, officer)
        assert snap3["state_version"] == 3
        assert any(r["id"] == new_rel_id for r in snap3["canonical_relationships"])


@pytest.mark.asyncio
async def test_v5_finding_freshness_lifecycle_and_invalidation():
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"V5-FRESH-{uuid.uuid4().hex[:6]}",
            title="Freshness Lifecycle Test",
            status="open",
            state_version=1,
        )
        uid2 = uuid.uuid4().hex[:6]
        officer = User(
            id=uuid.uuid4(),
            username=f"investigator_{uid2}",
            email=f"investigator_{uid2}@police.gov.in",
            full_name="Inspector Dave",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Suspect X", entity_type="PER")
        db.add(e1)
        await db.commit()

        # Engine produces a finding associated with entity e1
        cog_result = CognitiveResult(
            finding_type="MO_MATCH",
            title="Suspect matches Phishing MO Script",
            description="Phishing operation pattern identified.",
            confidence=0.92,
            severity="HIGH",
            status="OPEN",
            source_engine="MOMatchEngine",
            engine_version="2.0",
            entity_refs=[str(e1.id)],
            supporting_refs=["CDR-001.csv"],
            contradicting_refs=[],
            missing_information=["Tower location for 2026-03-01"],
            suggested_actions=["Issue notice u/s 94 BNSS to Telecom Operator"],
            generated_at_case_version=1,
            freshness_status=FRESHNESS_CURRENT,
        )

        finding_row, created = await upsert_finding(db, case.id, cog_result)
        await db.commit()
        assert created is True
        assert finding_row.freshness_status == FRESHNESS_CURRENT

        # Serialized finding verification
        f_dict = serialize_finding(finding_row)
        assert f_dict["freshness_status"] == FRESHNESS_CURRENT
        assert f_dict["generated_at_case_version"] == 1
        assert "CDR-001.csv" in f_dict["supporting_refs"]
        assert len(f_dict["suggested_actions"]) > 0

        # State mutation affecting e1 occurs -> invalidates finding
        await InvestigationBrain.mark_intelligence_stale(
            db,
            case_id=case.id,
            affected_entity_ids=[str(e1.id)],
        )
        await db.commit()

        # Reload finding: must now be NEEDS_REVIEW
        await db.refresh(finding_row)
        assert finding_row.freshness_status == FRESHNESS_NEEDS_REVIEW


@pytest.mark.asyncio
async def test_v5_identity_candidate_and_hypothesis_commands():
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"V5-CMD-{uuid.uuid4().hex[:6]}",
            title="Identity and Hypothesis Test",
            status="open",
            state_version=1,
        )
        uid3 = uuid.uuid4().hex[:6]
        officer = User(
            id=uuid.uuid4(),
            username=f"sup_{uid3}",
            email=f"sup_{uid3}@police.gov.in",
            full_name="Superintendent Sharma",
            role="admin",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        # 1. Identity Candidate Resolution
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            candidate_value="A. K. Sharma",
            candidate_type="PER",
            resolution_status="UNRESOLVED",
        )
        db.add(cand)
        await db.commit()

        res_cand = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="RESOLVE_IDENTITY_CANDIDATE",
                payload={
                    "candidate_id": str(cand.id),
                    "resolution_status": "CONFIRMED_SAME",
                },
                reason="Aadhaar matching verified identity alias",
            ),
            officer,
        )
        assert res_cand.success is True

        await db.refresh(cand)
        assert cand.resolution_status == "CONFIRMED_SAME"

        # 2. Hypothesis Creation via Command Gateway
        res_hypo = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CREATE_HYPOTHESIS",
                payload={
                    "title": "Mule Ring operating out of Jamtara cluster",
                    "description": "Cross-border call forwarding network",
                },
                reason="Intercept analysis indicates centralized coordinator",
            ),
            officer,
        )
        assert res_hypo.success is True
        hypo_id = uuid.UUID(res_hypo.data["hypothesis_id"])
        hypo = await db.get(Hypothesis, hypo_id)
        assert hypo is not None
        assert hypo.title == "Mule Ring operating out of Jamtara cluster"
        assert hypo.status == "OPEN"

        # 3. NormalizedEvent Contract
        norm_evt = NormalizedEvent.from_dict({
            "event_type": "bank_txn",
            "text": "Transfer of Rs. 50,000 from ACC-1 to ACC-2",
            "metadata": {"amount": 50000.0, "source_doc": "bank_statement.csv"},
        })
        assert norm_evt.event_type == "bank_txn"
        assert norm_evt.source_doc == "bank_statement.csv"
        assert norm_evt.amount == 50000.0
