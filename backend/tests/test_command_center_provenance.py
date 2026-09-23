from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Command Center Provenance Test Suite
Verifies that all widgets expose honest evidence provenance, cryptographic hashes,
and source references, adhering to the zero-fabrication principle.
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import (
    Case,
    Entity,
    EvidenceFile,
    IdentityCandidate,
    InvestigationFinding,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
import graph.relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_command_center_provenance_and_evidence_integrity():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_prov_{uuid.uuid4().hex[:6]}",
            email=f"io_prov_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Inspector Provenance",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(user.id), role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-PROV-{uuid.uuid4().hex[:8].upper()}",
            title="Operation Provenance Guard",
            crime_type="Cyber Fraud",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=1,
            created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(case)
        await db.flush()

        # Seed Evidence with genuine SHA-256 hash
        file_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ef = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="mule_ledger_verified.csv",
            original_name="mule_ledger_verified.csv",
            file_type="CSV",
            storage_path=f"/tmp/mule_ledger_verified_{uuid.uuid4().hex[:8]}.csv",
            sha256_hash=file_hash,
            upload_status="processed",
            uploaded_by=user.id,
            uploaded_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        db.add(ef)

        e1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9876543210",
            entity_type="PHONE",
            created_at=datetime(2026, 9, 1, 10, 12, 0, tzinfo=timezone.utc),
        )
        e2 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="SBI-ACC-998877",
            entity_type="ACCOUNT",
            created_at=datetime(2026, 9, 1, 10, 12, 0, tzinfo=timezone.utc),
        )
        db.add_all([e1, e2])

        # Relationship with concrete source refs
        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type="TRANSFERRED_TO",
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            confidence=0.92,
            evidence_refs=["mule_ledger_verified.csv:line_155"],
            created_at=datetime(2026, 9, 1, 10, 15, 0, tzinfo=timezone.utc),
        )
        db.add(rel)

        # Candidate with concrete source refs and conflict signals
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=e1.id,
            candidate_value="+91-9876543211",
            candidate_type="PHONE",
            resolution_status="UNRESOLVED",
            source_refs=["mule_ledger_verified.csv:header_metadata"],
            supporting_refs=["Co-located IMEI: 354892019283741"],
            contradicting_refs=["CAF photo mismatch"],
            created_at=datetime(2026, 9, 1, 10, 18, 0, tzinfo=timezone.utc),
        )
        db.add(cand)

        # Finding with concrete supporting refs
        finding = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fp_{uuid.uuid4().hex[:12]}",
            finding_type="SUSPECT_ALIAS_COINCIDENCE",
            title="Co-located secondary handset detected",
            description="IMEI association correlates secondary SIM card with target suspect.",
            severity="HIGH",
            confidence=0.89,
            status="OPEN",
            freshness_status="CURRENT",
            supporting_refs=["mule_ledger_verified.csv:line_155", "IMEI-354892019283741"],
            created_at=datetime(2026, 9, 1, 10, 20, 0, tzinfo=timezone.utc),
        )
        db.add(finding)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        # 1. Evidence status exposes authentic hash
        ev_items = data["evidence_status"]["items"]
        assert len(ev_items) == 1
        assert ev_items[0]["sha256_hash"] == file_hash

        # 2. Relationship review exposes source refs
        rel_items = data["relationship_review"]["items"]
        assert len(rel_items) == 1
        assert "mule_ledger_verified.csv:line_155" in rel_items[0]["source_refs"]

        # 3. Identity conflicts exposes supporting and contradicting refs
        cand_items = data["identity_conflicts"]["items"]
        assert len(cand_items) == 1
        assert "Co-located IMEI: 354892019283741" in cand_items[0]["supporting_refs"]
        assert "CAF photo mismatch" in cand_items[0]["conflict_signals"]

        # 4. Findings review exposes supporting refs
        find_items = data["findings_requiring_review"]["items"]
        assert len(find_items) == 1
        assert "mule_ledger_verified.csv:line_155" in find_items[0]["supporting_refs"]
