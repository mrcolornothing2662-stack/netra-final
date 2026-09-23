import uuid
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from db.models import (
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_entity_explorer_and_identity_candidate_contract():
    """
    Validates the contract for Entity Explorer and Identity Candidate review:
    - GET /api/v1/cases/{case_id}/entities (filtering, pagination, counts)
    - GET /api/v1/cases/{case_id}/entities/{entity_id} (dossier, provenance, mentions, dual relationships)
    - GET /api/v1/cases/{case_id}/identity-candidates (match/conflict signals)
    - POST /api/v1/cases/{case_id}/identity-candidates/{cand_id}/resolve (adjudication dispatch)
    """
    async with AsyncSessionLocal() as db:
        case = Case(
            id=uuid.uuid4(),
            case_number=f"EXP-{uuid.uuid4().hex[:6]}",
            title="Entity Explorer Contract Test Case",
            status="open",
            state_version=1,
        )
        io = User(
            id=uuid.uuid4(),
            username=f"io_exp_{uuid.uuid4().hex[:6]}@police.gov.in",
            email=f"io_exp_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        case.assigned_officer_id = io.id
        db.add_all([case, io])
        await db.commit()

        # Evidence file
        ef = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="07_upi_transaction_report.pdf",
            original_name="07_upi_transaction_report.pdf",
            file_type="bank_statement",
            file_size_bytes=1024,
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            uploaded_by=io.id,
            storage_path=f"/tmp/test_{uuid.uuid4().hex}.pdf",
        )
        db.add(ef)
        await db.commit()

        # Entities
        e1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Rahul Sharma",
            entity_type="PER",
            node_metadata={"aliases": ["R. Sharma"], "epistemic_status": RT.OBSERVED, "risk": "HIGH"},
            degree_centrality=0.45,
            bridge_score=0.2,
        )
        e2 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+919876543210",
            entity_type="PHONE",
            node_metadata={"epistemic_status": RT.OBSERVED},
        )
        e3 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACC-9912",
            entity_type="ACCOUNT",
            node_metadata={"epistemic_status": RT.INFERRED},
        )
        db.add_all([e1, e2, e3])
        await db.commit()

        # Evidence Event
        ev = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef.id,
            event_type="bank_txn",
            text_content="IMPS transfer of Rs 50,000 from ACC-9912 to Rahul Sharma ref TXN8819",
            source_line=14,
            source_page=2,
            event_timestamp=datetime(2026, 8, 23, 10, 30, tzinfo=timezone.utc),
        )
        db.add(ev)
        await db.commit()

        # Mention
        mention = EntityMention(
            id=uuid.uuid4(),
            entity_id=e1.id,
            evidence_event_id=ev.id,
            raw_value="Rahul Sharma",
            entity_type="PER",
            confidence=0.98,
            extractor="HingBERT-NER",
            span_start=44,
            span_end=56,
        )
        db.add(mention)
        await db.commit()

        # Canonical relationship: e1 USES e2
        rel_canonical = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.USES,
            direction=RT.OUTBOUND,
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_ACCEPTED,
            is_canonical=True,
            confidence=1.0,
            evidence_refs=[str(ef.id)],
            event_refs=[str(ev.id)],
        )
        # Analytical inferred relationship: e1 CONNECTED_TO e3
        rel_inferred = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e3.id,
            relationship_type=RT.CONNECTED_TO,
            direction=RT.OUTBOUND,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            is_canonical=False,
            confidence=0.78,
            reason_codes=["SHARED_DEVICE_COOCCURRENCE"],
        )
        db.add_all([rel_canonical, rel_inferred])
        await db.commit()

        # Identity Candidate: Rahul S. vs Rahul Sharma
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=e1.id,
            candidate_value="Rahul S.",
            candidate_type="PER",
            resolution_status="UNRESOLVED",
            supporting_refs=[
                {"signal": "Exact Phone Match", "detail": "+919876543210 shared on both records", "strength": "HIGH"},
                {"signal": "Co-occurrence", "detail": "Both appear in transaction batch 07", "strength": "MEDIUM"},
            ],
            contradicting_refs=[
                {"signal": "Registered Address", "detail": "Sector 14 vs Connaught Place", "severity": "MEDIUM"},
            ],
        )
        db.add(cand)
        await db.commit()

        io_token, _, _ = _create_access_token(str(io.id), io.role)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test GET /api/v1/cases/{case_id}/entities
        res_list = await client.get(
            f"/api/v1/cases/{case.id}/entities?search=Rahul",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert data_list["total"] >= 1
        assert any(e["canonical_value"] == "Rahul Sharma" for e in data_list["entities"])
        rahul_summary = next(e for e in data_list["entities"] if e["canonical_value"] == "Rahul Sharma")
        assert rahul_summary["mention_count"] >= 1
        assert rahul_summary["relationship_count"] >= 2
        assert rahul_summary["has_candidate_conflict"] is True
        assert "R. Sharma" in rahul_summary["aliases"]

        # Filter by entity_type
        res_phone = await client.get(
            f"/api/v1/cases/{case.id}/entities?entity_type=PHONE",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_phone.status_code == 200
        assert all(e["entity_type"] == "PHONE" for e in res_phone.json()["entities"])

        # 2. Test GET /api/v1/cases/{case_id}/entities/{entity_id} (Dossier)
        res_dossier = await client.get(
            f"/api/v1/cases/{case.id}/entities/{e1.id}",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_dossier.status_code == 200
        dossier = res_dossier.json()
        assert dossier["entity"]["id"] == str(e1.id)
        assert dossier["entity"]["canonical_value"] == "Rahul Sharma"
        assert dossier["entity"]["degree_centrality"] == 0.45

        # Provenance verification
        assert len(dossier["provenance"]["source_evidence_files"]) == 1
        assert dossier["provenance"]["source_evidence_files"][0]["filename"] == "07_upi_transaction_report.pdf"
        assert "HingBERT-NER" in dossier["provenance"]["extractors"]

        # Mentions verification
        assert len(dossier["mentions"]) >= 1
        assert dossier["mentions"][0]["source_line"] == 14
        assert dossier["mentions"][0]["source_page"] == 2
        assert "IMPS transfer" in dossier["mentions"][0]["snippet"]

        # Related events verification
        assert len(dossier["related_events"]) >= 1
        assert dossier["related_events"][0]["event_type"] == "bank_txn"

        # Dual projection relationships verification
        assert dossier["relationships"]["canonical_count"] >= 1
        assert dossier["relationships"]["analytical_count"] >= 1
        assert any(r["relationship_type"] == RT.USES for r in dossier["relationships"]["canonical"])
        assert any(r["relationship_type"] == RT.CONNECTED_TO for r in dossier["relationships"]["analytical"])

        # Associated candidate conflicts
        assert len(dossier["identity_candidates"]) >= 1
        assert dossier["identity_candidates"][0]["candidate_value"] == "Rahul S."
        assert len(dossier["identity_candidates"][0]["match_signals"]) == 2
        assert len(dossier["identity_candidates"][0]["conflict_signals"]) == 1

        # 3. Test GET /api/v1/cases/{case_id}/identity-candidates
        res_cands = await client.get(
            f"/api/v1/cases/{case.id}/identity-candidates?resolution_status=UNRESOLVED",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_cands.status_code == 200
        cands_data = res_cands.json()
        assert cands_data["pending_count"] >= 1
        assert cands_data["capabilities"]["can_resolve"] is True
        cand_item = next(c for c in cands_data["candidates"] if c["id"] == str(cand.id))
        assert cand_item["canonical_entity"]["canonical_value"] == "Rahul Sharma"
        assert cand_item["candidate_value"] == "Rahul S."

        # 4. Test POST /api/v1/cases/{case_id}/identity-candidates/{candidate_id}/resolve
        res_resolve = await client.post(
            f"/api/v1/cases/{case.id}/identity-candidates/{cand.id}/resolve",
            json={
                "verdict": "confirm_same",
                "reason": "Investigator confirmed KYC identity match from bank records",
            },
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_resolve.status_code == 200
        cmd_result = res_resolve.json()
        assert cmd_result["success"] is True
        assert cmd_result["new_state_version"] == 2

    # Verify DB state after resolution
    async with AsyncSessionLocal() as db:
        updated_cand = await db.get(IdentityCandidate, cand.id)
        updated_case = await db.get(Case, case.id)
        updated_e1 = await db.get(Entity, e1.id)

        assert updated_cand.resolution_status == "CONFIRMED_SAME"
        assert updated_cand.resolved_at is not None
        assert updated_case.state_version == 2
        assert "Rahul S." in (updated_e1.node_metadata.get("aliases") or [])
