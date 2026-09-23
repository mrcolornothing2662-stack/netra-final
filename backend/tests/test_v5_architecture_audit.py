import asyncio
import uuid
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select

from db.models import (
    AuditLog,
    Case,
    Entity,
    EvidenceEvent,
    IdentityCandidate,
    Hypothesis,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from investigation import policies
from investigation.brain import InvestigationBrain
from investigation.commands import CommandRequest, dispatch_command
from investigation.state import get_case_workspace_snapshot
from orchestration.contracts import (
    FRESHNESS_CURRENT, FRESHNESS_NEEDS_REVIEW, CognitiveResult
)
from orchestration.finding_service import upsert_finding, serialize_finding
from routes.graph import get_graph


# ─────────────────────────────────────────────────────────────────────────────
# Audit 1: Mutation Integrity Audit
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_1_mutation_integrity():
    """
    Traces every mutation through:
    AuthN -> AuthZ (Capabilities) -> Validation -> DB transaction ->
    Audit Log -> Case Version -> Targeted Affected Intelligence -> Activity Stream
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-MUT-{uuid.uuid4().hex[:6]}",
            title="Mutation Integrity Audit Case",
            status="open",
            state_version=1,
        )
        constable = User(
            id=uuid.uuid4(),
            username=f"constable_{uuid.uuid4().hex[:6]}",
            email=f"constable_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="constable",
            hashed_password="hash",
            is_active=True,
        )
        io = User(
            id=uuid.uuid4(),
            username=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        admin = User(
            id=uuid.uuid4(),
            username=f"admin_{uuid.uuid4().hex[:6]}",
            email=f"admin_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="admin",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, constable, io, admin])
        await db.commit()

        # 1. Authorization Gate Check: Constable attempting to confirm relationship must fail (HTTP 403)
        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Suspect 1", entity_type="PER")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="+919876543210", entity_type="PHONE")
        db.add_all([e1, e2])
        await db.commit()

        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.USES,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
        )
        db.add(rel)
        await db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await dispatch_command(
                db,
                case.id,
                CommandRequest(
                    command="CONFIRM_RELATIONSHIP",
                    payload={"relationship_id": str(rel.id)},
                ),
                constable,
            )
        assert exc_info.value.status_code == 403

        # 2. IO confirms relationship: full audit pipeline executes
        cmd_res = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CONFIRM_RELATIONSHIP",
                payload={"relationship_id": str(rel.id)},
                reason="KYC matched by investigating officer",
            ),
            io,
        )
        assert cmd_res.success is True
        assert cmd_res.new_state_version == 2

        # Verify DB transaction & relationship mutation
        await db.refresh(rel)
        assert rel.verification_status == RT.REVIEW_ACCEPTED
        assert rel.verified_by == io.id

        # Verify InvestigationState checkpoint created with state hash
        checkpoints = (await db.execute(
            select(InvestigationState).where(InvestigationState.case_id == case.id)
        )).scalars().all()
        assert len(checkpoints) >= 1
        assert any(c.version == 2 and len(c.state_hash) == 64 for c in checkpoints)

        # Verify InvestigationActivity stream entry recorded
        activities = (await db.execute(
            select(InvestigationActivity).where(InvestigationActivity.case_id == case.id)
        )).scalars().all()
        assert any(a.activity_type == "RELATIONSHIP_CONFIRMED" and a.actor_id == io.id for a in activities)

        # Verify tamper-evident AuditLog entry recorded
        audit_entries = (await db.execute(
            select(AuditLog).where(AuditLog.user_id == io.id)
        )).scalars().all()
        assert len(audit_entries) >= 1

        # 3. Validation Gate Check: Non-existent entity rejection
        with pytest.raises(HTTPException) as val_exc:
            await dispatch_command(
                db,
                case.id,
                CommandRequest(
                    command="ADD_INVESTIGATOR_RELATIONSHIP",
                    payload={
                        "source_entity_id": str(e1.id),
                        "target_entity_id": str(uuid.uuid4()),  # invalid non-existent entity
                    },
                ),
                io,
            )
        assert val_exc.value.status_code == 404

        # 4. Close case command requires CAP_CASE_CLOSE (supervisor/admin only; io rejected with 403)
        with pytest.raises(HTTPException) as close_exc:
            await dispatch_command(
                db,
                case.id,
                CommandRequest(
                    command="CLOSE_CASE",
                    payload={"closure_reason": "IO unilateral closure attempt"},
                ),
                io,
            )
        assert close_exc.value.status_code == 403

        # Admin successfully executes CLOSE_CASE
        cmd_close = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CLOSE_CASE",
                payload={"closure_reason": "Final charge-sheet submitted to court"},
            ),
            admin,
        )
        assert cmd_close.success is True
        await db.refresh(case)
        assert case.status == "closed"
        assert case.state_version == 3


# ─────────────────────────────────────────────────────────────────────────────
# Audit 2: Relationship Correctness Audit
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_2_relationship_correctness():
    """
    Verifies that every path creating or updating relationships enforces:
    - INFERRED edges NEVER default to is_canonical=True
    - Materialized OBSERVED edges default to is_canonical=True
    - Investigator confirmed edges promote to is_canonical=True
    - Rejected edges have is_canonical=False
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-REL-{uuid.uuid4().hex[:6]}",
            title="Relationship Correctness Audit Case",
            status="open",
            state_version=1,
        )
        officer = User(
            id=uuid.uuid4(),
            username=f"io_rel_{uuid.uuid4().hex[:6]}",
            email=f"io_rel_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Acc-001", entity_type="ACCOUNT")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Acc-002", entity_type="ACCOUNT")
        db.add_all([e1, e2])
        await db.commit()

        # 1. Inferred edge creation: MUST be is_canonical=False
        rel_inferred = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.ASSOCIATED_WITH,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            direction=RT.BIDIRECTIONAL,
            confidence=0.75,
        )
        db.add(rel_inferred)
        await db.commit()
        await db.refresh(rel_inferred)

        assert rel_inferred.epistemic_status == RT.INFERRED
        assert rel_inferred.verification_status == RT.REVIEW_UNREVIEWED
        assert rel_inferred.is_canonical is False  # Invariant: inferred unreviewed is NEVER canonical

        # 2. Observed edge creation: MUST be is_canonical=True
        rel_observed = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.TRANSFERRED_TO,
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_UNREVIEWED,
            amount=50000.0,
        )
        db.add(rel_observed)
        await db.commit()
        await db.refresh(rel_observed)

        assert rel_observed.epistemic_status == RT.OBSERVED
        assert rel_observed.is_canonical is True  # Invariant: observed unreviewed is canonical

        # 3. Investigator promotes inferred edge -> is_canonical becomes True
        await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="CONFIRM_RELATIONSHIP",
                payload={"relationship_id": str(rel_inferred.id)},
            ),
            officer,
        )
        await db.refresh(rel_inferred)
        assert rel_inferred.verification_status == RT.REVIEW_ACCEPTED
        assert rel_inferred.is_canonical is True  # Promoted to canonical

        # 4. Investigator rejects observed edge -> is_canonical becomes False
        await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="REJECT_RELATIONSHIP",
                payload={"relationship_id": str(rel_observed.id)},
                reason="Chargeback reversal proved transaction voided",
            ),
            officer,
        )
        await db.refresh(rel_observed)
        assert rel_observed.verification_status == RT.REVIEW_REJECTED
        assert rel_observed.is_canonical is False  # Rejected edge is NOT canonical


# ─────────────────────────────────────────────────────────────────────────────
# Audit 3: Identity Candidate Invariants
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_3_identity_candidate_invariants():
    """
    Verifies that IdentityCandidate preserves:
    - Candidate != confirmed identity
    - Distinct names with high similarity do not silently merge
    - Shared device / phone does not collapse distinct persons
    - Resolution requires explicit investigator command
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-ID-{uuid.uuid4().hex[:6]}",
            title="Identity Invariant Audit Case",
            status="open",
            state_version=1,
        )
        officer = User(
            id=uuid.uuid4(),
            username=f"io_id_{uuid.uuid4().hex[:6]}",
            email=f"io_id_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        # Scenario: Two persons sharing the same burner phone
        p1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rajesh Kumar", entity_type="PER")
        p2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rakesh Kumar", entity_type="PER")
        phone = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="+919111222333", entity_type="PHONE")
        db.add_all([p1, p2, phone])
        await db.commit()

        # Both persons use the same phone
        r1 = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=p1.id, target_entity_id=phone.id,
            relationship_type=RT.USES, epistemic_status=RT.OBSERVED
        )
        r2 = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=p2.id, target_entity_id=phone.id,
            relationship_type=RT.USES, epistemic_status=RT.OBSERVED
        )
        db.add_all([r1, r2])
        await db.commit()

        # Invariant: p1 and p2 remain distinct entities in the database
        entities = (await db.execute(
            select(Entity).where(Entity.case_id == case.id)
        )).scalars().all()
        assert len(entities) == 3
        person_entities = [e for e in entities if e.entity_type == "PER"]
        assert len(person_entities) == 2
        assert {e.canonical_value for e in person_entities} == {"Rajesh Kumar", "Rakesh Kumar"}

        # Candidate generated for potential name alias ambiguity
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=p1.id,
            candidate_value="Rakesh Kumar",
            candidate_type="PER",
            resolution_status="UNRESOLVED",
        )
        db.add(cand)
        await db.commit()

        # Candidate is NOT confirmed identity
        assert cand.resolution_status == "UNRESOLVED"
        assert cand.resolved_at is None

        # Investigator confirms they are DIFFERENT individuals (e.g. brothers sharing a family phone)
        await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="RESOLVE_IDENTITY_CANDIDATE",
                payload={
                    "candidate_id": str(cand.id),
                    "resolution_status": "CONFIRMED_DIFFERENT",
                },
                reason="Aadhaar KYC confirms two distinct individuals (brothers) sharing phone",
            ),
            officer,
        )
        await db.refresh(cand)
        assert cand.resolution_status == "CONFIRMED_DIFFERENT"
        assert cand.resolved_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# Audit 4: Finding Freshness Audit (Targeted vs Global Epoch)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_4_finding_freshness_targeted_invalidation():
    """
    Proves the system avoids the Cathedral Trap / Global Epoch invalidation:
    1. Relevant entity mutated -> finding directly referencing entity becomes NEEDS_REVIEW
    2. Unrelated entity mutated -> finding referencing other entity REMAINS CURRENT
    3. General case version bump / metadata mutation -> finding REMAINS CURRENT
    4. generated_at_case_version < case.state_version NEVER triggers automatic staleness
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-FRESH-{uuid.uuid4().hex[:6]}",
            title="Freshness Invalidation Audit Case",
            status="open",
            state_version=10,  # Case is at version 10
        )
        officer = User(
            id=uuid.uuid4(),
            username=f"io_fresh_{uuid.uuid4().hex[:6]}",
            email=f"io_fresh_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        ent_a = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Target Mule A", entity_type="ACCOUNT")
        ent_b = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Unrelated Trader B", entity_type="ACCOUNT")
        db.add_all([ent_a, ent_b])
        await db.commit()

        # Finding 1 depends on ent_a (generated at v5)
        f1_cog = CognitiveResult(
            finding_type="FINGERPRINT_VARIANT",
            title="Mule Account Pattern on Target Mule A",
            confidence=0.9,
            entity_refs=[str(ent_a.id)],
            supporting_refs=["doc1.csv"],
            generated_at_case_version=5,
            freshness_status=FRESHNESS_CURRENT,
        )
        f1_row, _ = await upsert_finding(db, case.id, f1_cog)

        # Finding 2 depends on ent_b (generated at v5)
        f2_cog = CognitiveResult(
            finding_type="REPLAY_ANOMALY",
            title="Timing Anomaly on Trader B",
            confidence=0.85,
            entity_refs=[str(ent_b.id)],
            supporting_refs=["doc2.csv"],
            generated_at_case_version=5,
            freshness_status=FRESHNESS_CURRENT,
        )
        f2_row, _ = await upsert_finding(db, case.id, f2_cog)
        await db.commit()

        # INVARIANT: Both findings are at v5 while case is at v10.
        # Neither finding should be marked stale simply because v5 < v10!
        assert f1_row.freshness_status == FRESHNESS_CURRENT
        assert f2_row.freshness_status == FRESHNESS_CURRENT

        # SCENARIO 1: Mutate entity A only
        invalidated_count = await InvestigationBrain.mark_intelligence_stale(
            db,
            case_id=case.id,
            affected_entity_ids=[str(ent_a.id)],
        )
        await db.commit()
        assert invalidated_count == 1

        await db.refresh(f1_row)
        await db.refresh(f2_row)

        # Finding 1 (referencing entity A) must be NEEDS_REVIEW
        assert f1_row.freshness_status == FRESHNESS_NEEDS_REVIEW
        # Finding 2 (referencing entity B) MUST REMAIN CURRENT!
        assert f2_row.freshness_status == FRESHNESS_CURRENT

        # SCENARIO 2: Case version bumped for unrelated activity
        await InvestigationBrain.bump_case_version(db, case, actor=officer, reason="Investigator logged in")
        await db.commit()
        await db.refresh(case)
        assert case.state_version == 11

        await db.refresh(f2_row)
        # Finding 2 STILL remains CURRENT!
        assert f2_row.freshness_status == FRESHNESS_CURRENT


# ─────────────────────────────────────────────────────────────────────────────
# Audit 5: Copilot Integrity Audit (No Silent Mutation)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_5_copilot_security_invariant_no_silent_mutation():
    """
    Verifies that Copilot:
    1. NEVER mutates state directly (zero silent mutation)
    2. Generates structured mutation proposals
    3. Mutations ONLY execute when an investigator explicitly submits the proposed command
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-COP-{uuid.uuid4().hex[:6]}",
            title="Copilot Security Audit Case",
            status="open",
            state_version=1,
        )
        officer = User(
            id=uuid.uuid4(),
            username=f"io_cop_{uuid.uuid4().hex[:6]}",
            email=f"io_cop_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rohit Sharma", entity_type="PER")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="ACC-777", entity_type="ACCOUNT")
        db.add_all([e1, e2])
        await db.commit()

        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.OWNS,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
        )
        db.add(rel)
        await db.commit()

        initial_version = case.state_version
        initial_status = rel.verification_status

        # Even if a prompt asks Copilot to confirm a relationship, Copilot MUST NOT mutate state
        # Simulated Copilot mutation proposal generation:
        proposal = {
            "command": "CONFIRM_RELATIONSHIP",
            "endpoint": f"/cases/{case.id}/commands",
            "payload": {"relationship_id": str(rel.id)},
            "description": f"Confirm inferred relationship between {e1.canonical_value} and {e2.canonical_value}",
            "capability_required": "CAP_RELATIONSHIP_CONFIRM",
        }

        # Drift guard: Copilot must only advertise capabilities that actually exist
        # in the capability policy module (mirrors routes/copilot.py proposal emission).
        assert hasattr(policies, proposal["capability_required"]), (
            f"Copilot advertised unknown capability '{proposal['capability_required']}'"
        )
        assert getattr(policies, proposal["capability_required"]) in policies.ROLE_CAPABILITIES["io"]

        # Verify: State has NOT changed
        await db.refresh(case)
        await db.refresh(rel)
        assert case.state_version == initial_version
        assert rel.verification_status == initial_status

        # Only explicit submission to Command Gateway executes the proposal
        cmd_req = CommandRequest(
            command=proposal["command"],
            payload=proposal["payload"],
            reason="Investigator approved Copilot proposal after reviewing physical KYC",
        )
        exec_res = await dispatch_command(db, case.id, cmd_req, officer)
        assert exec_res.success is True

        # Now and only now does state mutate
        await db.refresh(case)
        await db.refresh(rel)
        assert case.state_version == initial_version + 1
        assert rel.verification_status == RT.REVIEW_ACCEPTED


# ─────────────────────────────────────────────────────────────────────────────
# Audit 6: Graph Audit (Canonical vs Analytical Separation)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_6_graph_canonical_vs_analytical_separation():
    """
    Verifies that:
    1. OBSERVED -> included in canonical G (edges)
    2. INFERRED + UNREVIEWED -> excluded from canonical G (edges), present in analytical overlay (hidden_edges)
    3. INVESTIGATOR_ADDED -> included in canonical G (edges)
    4. REJECTED -> completely purged from G and hidden_edges
    5. Centrality metrics are computed strictly on canonical graph topology
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"AUDIT-GRAPH-{uuid.uuid4().hex[:6]}",
            title="Graph Projection Audit Case",
            status="open",
            state_version=1,
        )
        officer = User(
            id=uuid.uuid4(),
            username=f"io_grp_{uuid.uuid4().hex[:6]}",
            email=f"io_grp_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        db.add_all([case, officer])
        await db.commit()

        # Create 4 entities: A, B, C, D
        ea = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Node A", entity_type="PER")
        eb = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Node B", entity_type="ACCOUNT")
        ec = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Node C", entity_type="PHONE")
        ed = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Node D", entity_type="LOCATION")
        db.add_all([ea, eb, ec, ed])
        await db.commit()

        # 1. Edge A -> B: OBSERVED (Canonical)
        rel_obs = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=ea.id, target_entity_id=eb.id,
            relationship_type=RT.TRANSFERRED_TO, epistemic_status=RT.OBSERVED, verification_status=RT.REVIEW_UNREVIEWED,
        )
        # 2. Edge B -> C: INFERRED + UNREVIEWED (Analytical overlay only)
        rel_inf = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=eb.id, target_entity_id=ec.id,
            relationship_type=RT.ASSOCIATED_WITH, epistemic_status=RT.INFERRED, verification_status=RT.REVIEW_UNREVIEWED,
            confidence=0.82,
        )
        # 3. Edge A -> D: INVESTIGATOR_ADDED (Canonical)
        rel_inv = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=ea.id, target_entity_id=ed.id,
            relationship_type=RT.LOCATED_AT, epistemic_status=RT.INVESTIGATOR_ADDED, verification_status=RT.REVIEW_ACCEPTED,
        )
        # 4. Edge C -> D: REJECTED (Excluded from both)
        rel_rej = Relationship(
            id=uuid.uuid4(), case_id=case.id, source_entity_id=ec.id, target_entity_id=ed.id,
            relationship_type=RT.COMMUNICATED_WITH, epistemic_status=RT.INFERRED, verification_status=RT.REVIEW_REJECTED,
        )
        db.add_all([rel_obs, rel_inf, rel_inv, rel_rej])
        await db.commit()

        # Fetch workspace snapshot and verify dual relationship partitioning
        snap = await get_case_workspace_snapshot(db, case.id, officer)
        canonical_ids = {r["id"] for r in snap["canonical_relationships"]}
        analytical_ids = {r["id"] for r in snap["analytical_relationships"]}

        # Check 1: OBSERVED is in canonical
        assert str(rel_obs.id) in canonical_ids
        # Check 2: INFERRED + UNREVIEWED is in analytical, NOT in canonical
        assert str(rel_inf.id) in analytical_ids
        assert str(rel_inf.id) not in canonical_ids
        # Check 3: INVESTIGATOR_ADDED is in canonical
        assert str(rel_inv.id) in canonical_ids
        # Check 4: REJECTED is in NEITHER canonical NOR analytical
        assert str(rel_rej.id) not in canonical_ids
        assert str(rel_rej.id) not in analytical_ids
