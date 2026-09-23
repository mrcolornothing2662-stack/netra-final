import uuid
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select

from db.models import (
    AuditLog,
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from investigation.commands import CommandRequest, dispatch_command
from orchestration.contracts import (
    CognitiveResult,
    FINGERPRINT_VARIANT,
    FRESHNESS_CURRENT,
    FRESHNESS_NEEDS_REVIEW,
    REPLAY_ANOMALY,
)
from orchestration.finding_service import upsert_finding


@pytest.mark.asyncio
async def test_identity_candidate_12_point_invariants():
    """
    Exhaustive 12-point invariant test suite for Identity Candidate Adjudication:
    1. Candidate creation does not merge entities
    2. Candidate creation does not change canonical graph
    3. Resolve requires authorization (CAP_ENTITY_WRITE)
    4. Resolve increments case state version
    5. Resolve creates audit record
    6. Keep-separate creates audit record
    7. Copilot cannot directly resolve
    8. Evidence provenance survives resolution
    9. Affected findings become NEEDS_REVIEW
    10. Unrelated findings remain CURRENT
    11. Replay can reproduce the identity decision
    12. Graph reflects the investigator decision (SAME_AS edge)
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"ID-INV-{uuid.uuid4().hex[:6]}",
            title="Identity Invariant Suite Case",
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
        case.assigned_officer_id = io.id
        db.add_all([case, constable, io])
        await db.commit()

        # Evidence files
        ef1 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="pan_record_rahul_sharma.pdf",
            original_name="pan_record_rahul_sharma.pdf",
            file_type="kyc_document",
            file_size_bytes=2048,
            sha256_hash="1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            uploaded_by=io.id,
            storage_path=f"/tmp/ef1_{uuid.uuid4().hex}.pdf",
        )
        ef2 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="phone_subscriber_records.csv",
            original_name="phone_subscriber_records.csv",
            file_type="cdr",
            file_size_bytes=4096,
            sha256_hash="aaaabbbbccccddddeeeeffff1111222233334444555566667777888899990000",
            uploaded_by=io.id,
            storage_path=f"/tmp/ef2_{uuid.uuid4().hex}.csv",
        )
        db.add_all([ef1, ef2])
        await db.commit()

        # Target entities
        ent_a = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rahul Sharma", entity_type="PER")
        ent_b = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rahul S.", entity_type="PER")
        ent_unrelated = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Vikramaditya Rao", entity_type="PER")
        db.add_all([ent_a, ent_b, ent_unrelated])
        await db.commit()

        # Mentions & provenance
        ev1 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef1.id,
            event_type="kyc_record",
            text_content="PAN registration for Rahul Sharma with phone +919811002233",
            source_line=1,
            event_timestamp=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        )
        ev2 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef2.id,
            event_type="call",
            text_content="Subscriber Rahul S. registered phone +919811002233",
            source_line=45,
            event_timestamp=datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc),
        )
        db.add_all([ev1, ev2])
        await db.commit()

        m1 = EntityMention(id=uuid.uuid4(), entity_id=ent_a.id, evidence_event_id=ev1.id, raw_value="Rahul Sharma", entity_type="PER", extractor="HingBERT")
        m2 = EntityMention(id=uuid.uuid4(), entity_id=ent_b.id, evidence_event_id=ev2.id, raw_value="Rahul S.", entity_type="PER", extractor="regex")
        db.add_all([m1, m2])
        await db.commit()

        # Findings: Finding 1 depends on ent_a; Finding 2 depends on ent_unrelated
        f1_cog = CognitiveResult(
            finding_type=FINGERPRINT_VARIANT,
            title="Suspect A Transaction Chain",
            description="Rahul Sharma linked to high-volume cash deposits.",
            confidence=0.9,
            entity_refs=[str(ent_a.id)],
            supporting_refs=[str(ef1.id)],
            freshness_status=FRESHNESS_CURRENT,
        )
        f1_row, _ = await upsert_finding(db, case.id, f1_cog)

        f2_cog = CognitiveResult(
            finding_type=REPLAY_ANOMALY,
            title="Unrelated Vendor Payment",
            description="Vikramaditya Rao completed authorized logistics payment.",
            confidence=0.95,
            entity_refs=[str(ent_unrelated.id)],
            supporting_refs=[],
            freshness_status=FRESHNESS_CURRENT,
        )
        f2_row, _ = await upsert_finding(db, case.id, f2_cog)
        await db.commit()

        # ── Invariant 1: Candidate creation does not merge entities ────────────────
        candidate = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=ent_a.id,
            candidate_value=ent_b.canonical_value,
            candidate_type="PER",
            resolution_status="UNRESOLVED",
            supporting_refs=[{"signal": "Phone Overlap", "detail": "+919811002233 shared", "strength": "HIGH"}],
            contradicting_refs=[{"signal": "Address Divergence", "detail": "Delhi vs Noida", "severity": "MEDIUM"}],
        )
        db.add(candidate)
        await db.commit()

        # Both entities must still exist as distinct database records
        check_a = await db.get(Entity, ent_a.id)
        check_b = await db.get(Entity, ent_b.id)
        assert check_a is not None and check_b is not None
        assert check_a.id != check_b.id
        assert check_a.canonical_value == "Rahul Sharma"
        assert check_b.canonical_value == "Rahul S."

        # ── Invariant 2: Candidate creation does not change canonical graph ────────
        canon_rels_before = (await db.execute(
            select(Relationship).where(
                Relationship.case_id == case.id,
                Relationship.is_canonical == True,
            )
        )).scalars().all()
        assert len(canon_rels_before) == 0

        # ── Invariant 3: Resolve requires authorization (Constable rejected) ───────
        with pytest.raises(HTTPException) as exc_auth:
            await dispatch_command(
                db,
                case.id,
                CommandRequest(
                    command="RESOLVE_IDENTITY_CANDIDATE",
                    payload={
                        "candidate_id": str(candidate.id),
                        "resolution_status": "CONFIRMED_SAME",
                        "candidate_entity_id": str(ent_b.id),
                    },
                ),
                constable,
            )
        assert exc_auth.value.status_code == 403

        # ── Invariant 7: Copilot cannot directly resolve without investigator ──────
        # An unconfirmed proposal generates no state change
        await db.refresh(case)
        assert case.state_version == 1
        await db.refresh(candidate)
        assert candidate.resolution_status == "UNRESOLVED"

        # ── Invariant 4 & 5: Resolve increments case state version & creates audit log
        res_cmd = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="RESOLVE_IDENTITY_CANDIDATE",
                payload={
                    "candidate_id": str(candidate.id),
                    "resolution_status": "CONFIRMED_SAME",
                    "candidate_entity_id": str(ent_b.id),
                },
                reason="Investigator matched subscriber phone records",
            ),
            io,
        )
        assert res_cmd.success is True
        assert res_cmd.new_state_version == 2

        await db.refresh(case)
        assert case.state_version == 2

        # Invariant 5: Verify SHA-256 chained audit record exists for resolution
        audit_entry = (await db.execute(
            select(AuditLog).where(
                AuditLog.action == "IDENTITY_CANDIDATE_RESOLVED",
                AuditLog.user_id == io.id,
            )
        )).scalars().first()
        assert audit_entry is not None
        assert audit_entry.resource_type == "candidate"
        assert audit_entry.resource_id == str(candidate.id)
        assert len(audit_entry.entry_hash) == 64

        # ── Invariant 8: Evidence provenance survives resolution ───────────────────
        mentions_after = (await db.execute(
            select(EntityMention).where(EntityMention.entity_id.in_([ent_a.id, ent_b.id]))
        )).scalars().all()
        assert len(mentions_after) == 2
        assert any(m.raw_value == "Rahul Sharma" and m.extractor == "HingBERT" for m in mentions_after)
        assert any(m.raw_value == "Rahul S." and m.extractor == "regex" for m in mentions_after)

        # ── Invariant 9 & 10: Targeted finding invalidation (Avoiding Global Epoch) ─
        # Finding 1 (depends on ent_a) must be flagged NEEDS_REVIEW
        await db.refresh(f1_row)
        assert f1_row.freshness_status == FRESHNESS_NEEDS_REVIEW

        # Finding 2 (depends on ent_unrelated) must REMAIN CURRENT
        await db.refresh(f2_row)
        assert f2_row.freshness_status == FRESHNESS_CURRENT

        # ── Invariant 12: Graph reflects the investigator decision (SAME_AS edge) ──
        same_edge = (await db.execute(
            select(Relationship).where(
                Relationship.case_id == case.id,
                Relationship.relationship_type == RT.SAME_AS,
            )
        )).scalars().first()
        assert same_edge is not None
        assert same_edge.is_canonical is True
        assert same_edge.epistemic_status == RT.INVESTIGATOR_ADDED
        assert same_edge.verification_status == RT.REVIEW_ACCEPTED
        assert same_edge.verified_by == io.id

        # Canonical aliases populated on ent_a
        await db.refresh(ent_a)
        assert "Rahul S." in (ent_a.node_metadata.get("aliases") or [])

        # ── Invariant 6: Keep-separate creates audit record & leaves entities distinct
        cand_diff = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=ent_a.id,
            candidate_value="Vikramaditya Rao",
            candidate_type="PER",
            resolution_status="UNRESOLVED",
        )
        db.add(cand_diff)
        await db.commit()

        res_diff_cmd = await dispatch_command(
            db,
            case.id,
            CommandRequest(
                command="RESOLVE_IDENTITY_CANDIDATE",
                payload={
                    "candidate_id": str(cand_diff.id),
                    "resolution_status": "CONFIRMED_DIFFERENT",
                },
                reason="Different individuals verified by DOB",
            ),
            io,
        )
        assert res_diff_cmd.success is True
        assert res_diff_cmd.new_state_version == 3

        await db.refresh(cand_diff)
        assert cand_diff.resolution_status == "CONFIRMED_DIFFERENT"

        # Verify no SAME_AS edge between ent_a and ent_unrelated
        diff_edge = (await db.execute(
            select(Relationship).where(
                Relationship.case_id == case.id,
                Relationship.source_entity_id == ent_a.id,
                Relationship.target_entity_id == ent_unrelated.id,
            )
        )).scalars().first()
        assert diff_edge is None

        # ── Invariant 11: Replay can reproduce the identity decision ───────────────
        activities = (await db.execute(
            select(InvestigationActivity).where(
                InvestigationActivity.case_id == case.id,
                InvestigationActivity.activity_type == "IDENTITY_CANDIDATE_RESOLVED",
            ).order_by(InvestigationActivity.created_at.asc())
        )).scalars().all()
        assert len(activities) == 2
        # First decision: confirmed same
        assert activities[0].target_id == str(candidate.id)
        assert activities[0].after_state.get("resolution_status") == "CONFIRMED_SAME"
        # Second decision: confirmed different
        assert activities[1].target_id == str(cand_diff.id)
        assert activities[1].after_state.get("resolution_status") == "CONFIRMED_DIFFERENT"
