from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Bidirectional Evidence Links Test Suite
Tests:
1. Bidirectional linking: Report claim -> Evidence citation and Evidence -> Report/Finding usages.
2. Querying evidence usage returns all linked findings, relationships, and claims.
3. Nonexistent evidence handling and negative guarantees.
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import (
    Case,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_bidirectional_evidence_links_and_usage_query():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_ev_{uuid.uuid4().hex[:6]}",
            email=f"io_ev_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="io",
            full_name="Inspector Evidence Trace",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(user.id), role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-EVLINK-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Trace Matrix — Bidirectional Verification",
            crime_type="Financial Fraud",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=5,
        )
        db.add(case)
        await db.flush()

        # Seed Evidence File
        ef_id = uuid.uuid4()
        sha_val = "4" * 64
        ef = EvidenceFile(
            id=ef_id,
            case_id=case.id,
            filename="account_statement_hdfc.csv",
            original_name="HDFC_Account_Statement_Sept2026.csv",
            storage_path=f"/evidence/{uuid.uuid4().hex}.csv",
            sha256_hash=sha_val,
            file_size_bytes=8192,
            file_type="csv",
            source_type="bank_txn",
            upload_status="CONFIRMED",
        )
        db.add(ef)

        # Seed Event
        ev = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef_id,
            event_timestamp=datetime(2026, 9, 3, 11, 0, 0, tzinfo=timezone.utc),
            event_type="transfer",
            text_content="IMPS Transfer of ₹2,50,000 to Beneficiary Rohit",
            source_page=2,
            source_line=45,
        )
        db.add(ev)

        # Seed Entities
        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Sender Account", entity_type="BANK_ACCOUNT")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Rohit Verma", entity_type="PERSON")
        db.add_all([e1, e2])
        await db.flush()

        # Seed Relationship citing evidence
        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type="TRANSFERRED_FUNDS",
            verification_status="ACCEPTED",
            epistemic_status="OBSERVED",
            confidence=0.98,
            evidence_refs=[str(ef_id)],
        )
        db.add(rel)

        # Seed Finding citing evidence
        finding = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            finding_type="STRUCTURING",
            title="Rapid Funneling Transfer",
            description="Immediate withdrawal after ₹2,50,000 credit",
            severity="HIGH",
            confidence=0.9,
            freshness_status="CURRENT",
            evidence_refs=[str(ef_id)],
            entity_refs=[str(e1.id), str(e2.id)],
            fingerprint=f"FND-{uuid.uuid4().hex[:8]}",
        )
        db.add(finding)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Generate Report Snapshot
            gen_resp = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={"report_type": "formal_dossier", "title": "Evidentiary Dossier"},
                headers=headers,
            )
            assert gen_resp.status_code == 201, gen_resp.text
            payload = gen_resp.json()

            # Verify that Report Claims contain exact citations back to ef
            citations_found = []
            for sec in payload["sections"]:
                for claim in sec["claims"]:
                    for cit in claim["evidence_refs"]:
                        if cit["evidence_id"] == str(ef_id):
                            citations_found.append(cit)

            assert len(citations_found) > 0
            first_cit = citations_found[0]
            assert first_cit["file_name"] == "HDFC_Account_Statement_Sept2026.csv"
            assert first_cit["sha256_hash"] == sha_val

            # 2. Query Evidence Usage via bidirectional route
            usage_resp = await client.get(
                f"/api/v1/cases/{case.id}/reports/evidence/{ef_id}/usage",
                headers=headers,
            )
            assert usage_resp.status_code == 200, usage_resp.text
            usage = usage_resp.json()

            assert usage["evidence_id"] == str(ef_id)
            assert usage["filename"] == "HDFC_Account_Statement_Sept2026.csv"
            assert usage["sha256_hash"] == sha_val

            # Verify findings using this evidence
            f_titles = [f["title"] for f in usage["findings"]]
            assert "Rapid Funneling Transfer" in f_titles

            # Verify relationships using this evidence
            r_types = [r["rel_type"] for r in usage["relationships"]]
            assert "TRANSFERRED_FUNDS" in r_types

            # Verify claims using this evidence
            assert len(usage["claims"]) > 0
            assert usage["total_usages"] >= 3

            # 3. Also verify the case-level alias endpoint
            alias_resp = await client.get(
                f"/api/v1/cases/{case.id}/evidence/{ef_id}/usage",
                headers=headers,
            )
            assert alias_resp.status_code == 200
            assert alias_resp.json()["total_usages"] == usage["total_usages"]

            # 4. Negative guarantee: Nonexistent evidence ID returns 404
            bad_id = uuid.uuid4()
            bad_resp = await client.get(
                f"/api/v1/cases/{case.id}/evidence/{bad_id}/usage",
                headers=headers,
            )
            assert bad_resp.status_code == 404
