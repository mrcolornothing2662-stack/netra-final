from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Report Snapshot Test Suite
Validates that report snapshots are immutable, reproducible representations of
specific case state versions. Old reports (e.g. Case v42) are NEVER silently
regenerated when current case state advances to v43.
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    Entity,
    EvidenceFile,
    IdentityCandidate,
    InvestigationFinding,
    ReportSnapshot,
    User,
)
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_report_snapshot_immutability_across_case_versions():
    """
    Scenario:
    1. Case at v42 generates a report snapshot.
    2. Case state mutates to v43 (an identity candidate is confirmed/differentiated, finding added).
    3. Old report snapshot retrieved by ID STILL represents Case v42 and retains original content hash.
    4. A new report snapshot at v43 has new state version and different content hash.
    """
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_snap_{uuid.uuid4().hex[:6]}",
            email=f"io_snap_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="io",
            full_name="Inspector Snapshot",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(user.id), role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Case at state_version = 42
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-SNAP-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Shadow Ledger — Snapshot Immutability",
            crime_type="Cyber Fraud",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=42,
        )
        db.add(case)
        await db.flush()

        # Add initial evidence
        ef = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="suspect_ledger_v1.csv",
            original_name="suspect_ledger_v1.csv",
            storage_path=f"/evidence/{uuid.uuid4().hex}.csv",
            sha256_hash="1" * 64,
            file_size_bytes=4096,
            file_type="csv",
            source_type="bank_txn",
            upload_status="CONFIRMED",
        )
        db.add(ef)

        # Add initial entity
        ent1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Target Account Alpha",
            entity_type="BANK_ACCOUNT",
        )
        db.add(ent1)

        # Add initial finding
        f1 = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            finding_type="STRUCTURING",
            title="Layering Detected",
            description="Initial structuring observed at v42",
            severity="MEDIUM",
            confidence=0.8,
            freshness_status="CURRENT",
            evidence_refs=[str(ef.id)],
            entity_refs=[str(ent1.id)],
            fingerprint=f"FND-{uuid.uuid4().hex[:8]}",
        )
        db.add(f1)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Step 1: Generate report at Case v42
            resp1 = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={
                    "report_type": "intelligence_brief",
                    "title": "Intelligence Brief — Initial State v42",
                },
                headers=headers,
            )
            assert resp1.status_code == 201, resp1.text
            data_v42 = resp1.json()
            report_v42_id = data_v42["metadata"]["report_id"]
            hash_v42 = data_v42["metadata"]["content_hash"]
            assert data_v42["metadata"]["case_state_version"] == 42

            # Step 2: Mutate case to state_version = 43
            case.state_version = 43
            ent2 = Entity(
                id=uuid.uuid4(),
                case_id=case.id,
                canonical_value="Identified Suspect Rohit Verma",
                entity_type="PERSON",
            )
            db.add(ent2)

            f2 = InvestigationFinding(
                id=uuid.uuid4(),
                case_id=case.id,
                finding_type="MULE_ACCOUNT",
                title="Account Beneficiary Identified",
                description="Beneficiary confirmed as Rohit Verma at v43",
                severity="HIGH",
                confidence=0.95,
                freshness_status="CURRENT",
                evidence_refs=[str(ef.id)],
                entity_refs=[str(ent2.id)],
                fingerprint=f"FND-{uuid.uuid4().hex[:8]}",
            )
            db.add(f2)
            await db.commit()

            # Step 3: Fetch the old report snapshot (v42) by ID
            resp_old = await client.get(
                f"/api/v1/cases/{case.id}/reports/snapshots/{report_v42_id}",
                headers=headers,
            )
            assert resp_old.status_code == 200, resp_old.text
            old_snapshot_data = resp_old.json()

            # IMMUTABILITY GUARANTEE:
            # The retrieved report STILL has state_version=42, same content_hash, and does not have the new finding!
            assert old_snapshot_data["metadata"]["case_state_version"] == 42
            assert old_snapshot_data["metadata"]["content_hash"] == hash_v42
            finding_titles_v42 = [
                f["title"]
                for sec in old_snapshot_data["sections"]
                if sec["section_id"] == "findings"
                for f in sec["data"].get("findings", [])
            ]
            assert "Layering Detected" in finding_titles_v42
            assert "Account Beneficiary Identified" not in finding_titles_v42

            # Step 4: Generate new report at Case v43
            resp2 = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={
                    "report_type": "intelligence_brief",
                    "title": "Intelligence Brief — Updated State v43",
                },
                headers=headers,
            )
            assert resp2.status_code == 201
            data_v43 = resp2.json()
            assert data_v43["metadata"]["case_state_version"] == 43
            assert data_v43["metadata"]["content_hash"] != hash_v42

            finding_titles_v43 = [
                f["title"]
                for sec in data_v43["sections"]
                if sec["section_id"] == "findings"
                for f in sec["data"].get("findings", [])
            ]
            assert "Layering Detected" in finding_titles_v43
            assert "Account Beneficiary Identified" in finding_titles_v43
