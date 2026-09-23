from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Command Center Contract Test Suite
Validates that GET /cases/{case_id}/command-center returns a complete,
well-typed projection where all 10 widgets match authoritative database state.
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    Relationship,
    SyncConflictRecord,
    User,
)
from db.session import AsyncSessionLocal
import graph.relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_command_center_contract_and_metrics():
    async with AsyncSessionLocal() as db:
        io_user = User(
            id=uuid.uuid4(),
            username=f"io_cmd_{uuid.uuid4().hex[:6]}",
            email=f"io_cmd_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Inspector Command Center",
            rank="Inspector",
            is_active=True,
        )
        db.add(io_user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(io_user.id), role=io_user.role)
        headers = {"Authorization": f"Bearer {token}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-CMD-{uuid.uuid4().hex[:8].upper()}",
            title="Operation EaglePulse — Command Center Validation",
            crime_type="Financial Fraud",
            priority="high",
            status="open",
            assigned_officer_id=io_user.id,
            state_version=3,
            created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            last_activity_at=datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.add(case)
        await db.flush()

        # Seed Evidence Files (1 processed, 1 pending)
        ef1 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="cdr_batch_sept.csv",
            original_name="cdr_batch_sept.csv",
            file_type="CSV",
            storage_path=f"/tmp/cdr_{uuid.uuid4().hex[:6]}.csv",
            sha256_hash="1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
            upload_status="processed",
            uploaded_by=io_user.id,
            uploaded_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        )
        ef2 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="forensic_disk.raw",
            original_name="forensic_disk.raw",
            file_type="IMAGE",
            storage_path=f"/tmp/disk_{uuid.uuid4().hex[:6]}.raw",
            sha256_hash="aaaabbbbccccddddeeeeffff1111222233334444555566667777888899990000",
            upload_status="processing",
            uploaded_by=io_user.id,
            uploaded_at=datetime(2026, 9, 1, 10, 6, 0, tzinfo=timezone.utc),
        )
        db.add_all([ef1, ef2])

        # Seed Entities
        e1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9988776655",
            entity_type="PHONE",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        e2 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9988776644",
            entity_type="PHONE",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        e3 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="HDFC-MULE-9988",
            entity_type="ACCOUNT",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        db.add_all([e1, e2, e3])

        # Seed Relationships: 1 Canonical, 2 Inferred Unreviewed
        r1 = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type="CALLED",
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_ACCEPTED,
            evidence_refs=["cdr_batch_sept.csv:row_42"],
            confidence=1.0,
            created_at=datetime(2026, 9, 1, 10, 15, 0, tzinfo=timezone.utc),
        )
        r2 = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e2.id,
            target_entity_id=e3.id,
            relationship_type="TRANSFERRED_TO",
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            evidence_refs=["cdr_batch_sept.csv:row_88"],
            confidence=0.82,
            created_at=datetime(2026, 9, 1, 10, 16, 0, tzinfo=timezone.utc),
        )
        db.add_all([r1, r2])

        # Seed Identity Candidate (Unresolved)
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=e1.id,
            candidate_value="+91-9988776644",
            candidate_type="PHONE",
            resolution_status="UNRESOLVED",
            source_refs=["cdr_batch_sept.csv"],
            supporting_refs=["Shared Cell Tower Sector"],
            contradicting_refs=["Different Subscriber Name in CAF"],
            created_at=datetime(2026, 9, 1, 10, 20, 0, tzinfo=timezone.utc),
        )
        db.add(cand)

        # Seed Findings (1 Current, 1 Stale)
        f1 = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fp_{uuid.uuid4().hex[:12]}",
            finding_type="BURST_COMMUNICATION",
            title="Rapid communication sequence preceding withdrawal",
            description="3 calls within 12 minutes between suspect and mule operator.",
            severity="HIGH",
            confidence=0.88,
            status="OPEN",
            freshness_status="CURRENT",
            supporting_refs=["cdr_batch_sept.csv"],
            created_at=datetime(2026, 9, 1, 10, 25, 0, tzinfo=timezone.utc),
        )
        f2 = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fp_{uuid.uuid4().hex[:12]}",
            finding_type="MULE_ACCOUNT_SYNDICATE",
            title="Layering network node",
            description="Account flagged as high-velocity hop.",
            severity="CRITICAL",
            confidence=0.91,
            status="OPEN",
            freshness_status="STALE",  # Stale finding!
            supporting_refs=["cdr_batch_sept.csv"],
            created_at=datetime(2026, 9, 1, 10, 26, 0, tzinfo=timezone.utc),
        )
        db.add_all([f1, f2])

        # Seed Sync Conflict Record
        sync_conf = SyncConflictRecord(
            id=uuid.uuid4(),
            mutation_id=f"mut_conf_{uuid.uuid4().hex[:6]}",
            device_id="FIELD-TAB-01",
            actor_id=io_user.id,
            case_id=case.id,
            command_type="RESOLVE_IDENTITY_CANDIDATE",
            client_payload={"candidate_id": str(cand.id), "decision": "CONFIRMED_DIFFERENT"},
            base_state_version=1,
            server_state_version=3,
            conflict_type="IDENTITY_DECISION_CONFLICT",
            server_current_state={"status": "CONFIRMED_SAME"},
            status="PENDING_REVIEW",
            created_at=datetime(2026, 9, 1, 11, 0, 0, tzinfo=timezone.utc),
        )
        db.add(sync_conf)

        # Seed Activity
        act = InvestigationActivity(
            id=uuid.uuid4(),
            case_id=case.id,
            activity_type="EVIDENCE_INGESTED",
            actor_id=io_user.id,
            reason="Uploaded CDR batch for initial triage",
            created_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        )
        db.add(act)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        # Core Case Metadata
        assert data["case_id"] == str(case.id)
        assert data["case_number"] == case.case_number
        assert data["state_version"] == 3

        # Verify all 10 widgets exist
        required_widgets = [
            "attention_queue",
            "investigation_health",
            "recent_activity",
            "findings_requiring_review",
            "identity_conflicts",
            "relationship_review",
            "evidence_status",
            "sync_status",
            "lens_summary",
            "mini_network",
        ]
        for w_name in required_widgets:
            assert w_name in data, f"Missing widget: {w_name}"
            w = data[w_name]
            assert "header" in w, f"Widget {w_name} missing header"
            assert "title" in w["header"]
            assert "status" in w["header"]
            assert "click_action" in w["header"]

        # Validate Metrics Consistency against Database
        assert data["identity_conflicts"]["total_unresolved"] == 1
        assert len(data["identity_conflicts"]["items"]) == 1
        assert data["identity_conflicts"]["items"][0]["id"] == str(cand.id)

        assert data["relationship_review"]["total_unreviewed"] == 1
        assert len(data["relationship_review"]["items"]) == 1
        assert data["relationship_review"]["items"][0]["id"] == str(r2.id)

        assert data["findings_requiring_review"]["stale_count"] == 1
        assert data["findings_requiring_review"]["total_findings"] == 2

        assert data["evidence_status"]["total_files"] == 2
        assert data["evidence_status"]["processed_files"] == 1
        assert data["evidence_status"]["pending_files"] == 1

        assert data["sync_status"]["pending_conflicts_count"] == 1
        assert data["sync_status"]["server_state_version"] == 3

        # Attention queue should prioritize urgent action items
        assert data["attention_queue"]["header"]["status"] == "URGENT_ACTION"
        assert len(data["attention_queue"]["items"]) >= 2
