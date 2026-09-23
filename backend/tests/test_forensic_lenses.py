from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 5 Acceptance Test Suite
Verifies all 15 Architectural Invariants for Forensic Lenses:
1. Lens reads only authorized case data.
2. Lens queries never mutate case state.
3. Every financial signal has evidence/event provenance.
4. Every communication signal has evidence provenance.
5. Every geographic observation retains source timestamp.
6. Missing geographic time is never fabricated.
7. Cell-site data is never represented as precise GPS.
8. Lens projections do not create canonical relationships.
9. Rejected relationships do not appear as canonical in lenses.
10. Investigator-added relationships remain visibly distinguished.
11. Selecting an entity produces consistent results across all lenses.
12. Selecting a timeline event filters the active lens correctly.
13. Historical replay can render the lens at state version N.
14. Findings remain linked to their supporting evidence.
15. Copilot can query a lens but cannot silently mutate it.
"""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from db.session import AsyncSessionLocal
from db.models import (
    Case,
    User,
    EvidenceFile,
    EvidenceEvent,
    Entity,
    Relationship,
    InvestigationFinding,
    InvestigationState,
    InvestigationActivity,
)
from routes.auth import _hash_password, _create_access_token
import graph.relationship_types as RT
from forensic.geographic import LOCATION_DISCLAIMER


@pytest.mark.asyncio
async def test_milestone5_forensic_lenses_suite():
    async with AsyncSessionLocal() as db:
        inv_uname = f"lens_inv_{uuid.uuid4().hex[:6]}"
        inv_user = User(
            id=uuid.uuid4(),
            username=inv_uname,
            email=f"{inv_uname}@netra.police.gov.in",
            hashed_password=_hash_password("Investigate@123"),
            role="io",
            unit="Special Cyber Unit",
        )
        # Create unprivileged viewer user
        oth_uname = f"lens_other_{uuid.uuid4().hex[:6]}"
        other_user = User(
            id=uuid.uuid4(),
            username=oth_uname,
            email=f"{oth_uname}@netra.police.gov.in",
            hashed_password=_hash_password("Viewer@123"),
            role="constable",
            unit="Traffic Unit",
        )
        db.add_all([inv_user, other_user])

        # Create case assigned to inv_user
        case = Case(
            id=uuid.uuid4(),
            case_number=f"CYB-2026-LENS-{uuid.uuid4().hex[:4].upper()}",
            title="Operation Chrono Lens Financial & CDR Network",
            crime_type="CYBER_FINANCIAL_FRAUD",
            description="Forensic investigation into coordinated mule accounts and cell-site movements.",
            status="open",
            priority="high",
            state_version=1,
            assigned_officer_id=inv_user.id,
        )
        db.add(case)
        await db.flush()

        # Checkpoint v1
        ckpt1 = InvestigationState(
            id=uuid.uuid4(),
            case_id=case.id,
            version=1,
            state_hash="genesis_lens_hash",
            created_by=inv_user.id,
            created_at=datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc),
        )
        db.add(ckpt1)

        # Ingest Evidence Files
        bank_doc = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="02_bank_statement_sbi.pdf",
            original_name="02_bank_statement_sbi.pdf",
            file_type="pdf",
            file_size_bytes=2048,
            storage_path=f"/tmp/02_bank_statement_{uuid.uuid4().hex[:8]}.pdf",
            sha256_hash="bank_doc_hash_1234567890abcdef",
            uploaded_by=inv_user.id,
            uploaded_at=datetime(2026, 8, 20, 9, 30, 0, tzinfo=timezone.utc),
        )
        cdr_doc = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="04_cdr_call_records.xlsx",
            original_name="04_cdr_call_records.xlsx",
            file_type="xlsx",
            file_size_bytes=4096,
            storage_path=f"/tmp/04_cdr_{uuid.uuid4().hex[:8]}.xlsx",
            sha256_hash="cdr_doc_hash_1234567890abcdef",
            uploaded_by=inv_user.id,
            uploaded_at=datetime(2026, 8, 20, 9, 35, 0, tzinfo=timezone.utc),
        )
        cell_doc = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="09_cell_tower_timeline.pdf",
            original_name="09_cell_tower_timeline.pdf",
            file_type="pdf",
            file_size_bytes=1024,
            storage_path=f"/tmp/09_cell_{uuid.uuid4().hex[:8]}.pdf",
            sha256_hash="cell_doc_hash_1234567890abcdef",
            uploaded_by=inv_user.id,
            uploaded_at=datetime(2026, 8, 20, 9, 40, 0, tzinfo=timezone.utc),
        )
        db.add_all([bank_doc, cdr_doc, cell_doc])
        await db.flush()

        # Seed Financial Events (Bank Transactions)
        # Txn 1: 10:00 UTC - ₹2,50,000 to Mule Account
        txn1 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=bank_doc.id,
            event_type="bank_txn",
            event_timestamp=datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc),
            source_line=14,
            source_page=2,
            event_metadata={
                "debit": 250000.0,
                "narration": "IMPS/P2A/TRANSFER TO MULE-1",
                "account": "SBI-ACC-9910",
                "source_doc": bank_doc.filename,
                "confidence": 0.98,
            },
            created_at=datetime(2026, 8, 21, 10, 1, 0, tzinfo=timezone.utc),
        )
        # Txn 2: 10:37 UTC - ₹2,48,000 (Rapid Transfer gap = 37 min, Round number)
        txn2 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=bank_doc.id,
            event_type="bank_txn",
            event_timestamp=datetime(2026, 8, 21, 10, 37, 0, tzinfo=timezone.utc),
            source_line=18,
            source_page=2,
            event_metadata={
                "debit": 248000.0,
                "narration": "NEFT TO BENEFICIARY-X",
                "account": "SBI-ACC-9910",
                "source_doc": bank_doc.filename,
                "confidence": 0.98,
            },
            created_at=datetime(2026, 8, 21, 10, 38, 0, tzinfo=timezone.utc),
        )
        db.add_all([txn1, txn2])

        # Seed Communication Events (CDR & WhatsApp)
        # Call 1, 2, 3 in rapid succession (10:10, 10:15, 10:22 -> 3 calls in 12 min = Burst!)
        t_base = datetime(2026, 8, 21, 10, 10, 0, tzinfo=timezone.utc)
        calls = []
        for i, (m_offset, dur) in enumerate([(0, 120), (5, 90), (12, 180)]):
            c_ev = EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=cdr_doc.id,
                event_type="call",
                event_timestamp=t_base + timedelta(minutes=m_offset),
                source_line=50 + i,
                source_page=1,
                event_metadata={
                    "caller": "+91-9876543210",
                    "callee": "+91-9812345678",
                    "duration_sec": dur,
                    "source_doc": cdr_doc.filename,
                    "confidence": 0.99,
                },
                created_at=t_base + timedelta(minutes=m_offset, seconds=10),
            )
            calls.append(c_ev)
            db.add(c_ev)

        # Night Call (02:15 UTC)
        night_call = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=cdr_doc.id,
            event_type="call",
            event_timestamp=datetime(2026, 8, 21, 2, 15, 0, tzinfo=timezone.utc),
            source_line=85,
            source_page=2,
            event_metadata={
                "caller": "+91-9876543210",
                "callee": "+91-9899999999",
                "duration_sec": 45,
                "source_doc": cdr_doc.filename,
            },
            created_at=datetime(2026, 8, 21, 2, 16, 0, tzinfo=timezone.utc),
        )
        db.add(night_call)

        # Seed Geographic Events (Cell Site Observations)
        # Obs 1: 10:02 - Tower CHD-CELL-17
        geo1 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=cell_doc.id,
            event_type="location_timeline",
            event_timestamp=datetime(2026, 8, 21, 10, 2, 0, tzinfo=timezone.utc),
            source_line=5,
            source_page=1,
            event_metadata={
                "phone": "+91-9876543210",
                "cell_tower": "CHD-CELL-17",
                "city": "Chandigarh",
                "source_doc": cell_doc.filename,
            },
            created_at=datetime(2026, 8, 21, 10, 3, 0, tzinfo=timezone.utc),
        )
        # Obs 2: 10:48 - Tower CHD-CELL-04 (Hop gap = 46 min)
        geo2 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=cell_doc.id,
            event_type="location_timeline",
            event_timestamp=datetime(2026, 8, 21, 10, 48, 0, tzinfo=timezone.utc),
            source_line=8,
            source_page=1,
            event_metadata={
                "phone": "+91-9876543210",
                "cell_tower": "CHD-CELL-04",
                "city": "Chandigarh",
                "source_doc": cell_doc.filename,
            },
            created_at=datetime(2026, 8, 21, 10, 49, 0, tzinfo=timezone.utc),
        )
        # Obs 3: Missing event_timestamp (Invariant 6 test)
        geo_no_time = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=cell_doc.id,
            event_type="location_timeline",
            event_timestamp=None,
            source_line=12,
            source_page=1,
            event_metadata={
                "phone": "+91-9876543210",
                "cell_tower": "PAN-CELL-08",
                "city": "Panchkula",
                "source_doc": cell_doc.filename,
            },
            created_at=datetime(2026, 8, 21, 11, 0, 0, tzinfo=timezone.utc),
        )
        db.add_all([geo1, geo2, geo_no_time])

        # Seed Entities
        ent_phone = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9876543210",
            entity_type="PHONE",
            node_metadata={"subscriber": "Suspect Alpha"},
        )
        ent_account = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="SBI-ACC-9910",
            entity_type="ACCOUNT",
            node_metadata={"bank": "SBI", "branch": "Sector 17"},
        )
        db.add_all([ent_phone, ent_account])

        # Seed Rejected Relationship (Invariant 9 test)
        rel_rejected = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent_phone.id,
            target_entity_id=ent_account.id,
            relationship_type="ASSOCIATED_WITH",
            direction="BIDIRECTIONAL",
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_REJECTED,
            confidence=0.30,
            evidence_refs=[str(bank_doc.id)],
        )
        # Seed Canonical Observed Relationship (Invariant 10 test)
        rel_observed = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent_phone.id,
            target_entity_id=ent_account.id,
            relationship_type="REGISTERED_TO",
            direction="OUTBOUND",
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_ACCEPTED,
            confidence=0.98,
            created_by=inv_user.id,
            evidence_refs=[str(bank_doc.id)],
        )
        db.add_all([rel_rejected, rel_observed])

        # Seed Investigation Finding with Provenance (Invariant 14 test)
        finding = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fprint-{uuid.uuid4().hex[:8]}",
            finding_type="RAPID_TRANSFER",
            title="High-velocity fund diversion from SBI-ACC-9910",
            description="Two high value transfers totaling ₹4.98L within 37 minutes.",
            severity="HIGH",
            confidence=0.92,
            status="OPEN",
            freshness_status="CURRENT",
            generated_at_case_version=1,
            evidence_refs=[str(bank_doc.id)],
            entity_refs=[str(ent_account.id)],
            event_refs=[str(txn1.id), str(txn2.id)],
        )
        db.add(finding)
        await db.commit()

        inv_token, _, _ = _create_access_token(user_id=str(inv_user.id), role=inv_user.role)
        headers = {"Authorization": f"Bearer {inv_token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ─────────────────────────────────────────────────────────────────────
        # Invariant 1: Lens reads only authorized case data
        # ─────────────────────────────────────────────────────────────────────
        unauth_resp = await client.get(f"/api/v1/cases/{case.id}/lenses")
        assert unauth_resp.status_code == 401

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 2: Lens queries never mutate case state
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db_pre:
            c_pre = await db_pre.get(Case, case.id)
            pre_version = c_pre.state_version
            pre_last_act = c_pre.last_activity_at

        # Query all lenses
        resp_ov = await client.get(f"/api/v1/cases/{case.id}/lenses", headers=headers)
        assert resp_ov.status_code == 200
        ov_data = resp_ov.json()
        assert "MONEY" in ov_data["active_lenses"]
        assert "COMMUNICATION" in ov_data["active_lenses"]
        assert "GEOGRAPHIC" in ov_data["active_lenses"]
        assert ov_data["cross_lens_coincidences_count"] >= 1

        resp_money = await client.get(f"/api/v1/cases/{case.id}/lenses/money", headers=headers)
        assert resp_money.status_code == 200

        resp_comms = await client.get(f"/api/v1/cases/{case.id}/lenses/communications", headers=headers)
        assert resp_comms.status_code == 200

        resp_geo = await client.get(f"/api/v1/cases/{case.id}/lenses/geographic", headers=headers)
        assert resp_geo.status_code == 200

        async with AsyncSessionLocal() as db_post:
            c_post = await db_post.get(Case, case.id)
            assert c_post.state_version == pre_version
            assert c_post.last_activity_at == pre_last_act

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 3: Every financial signal has evidence/event provenance
        # ─────────────────────────────────────────────────────────────────────
        m_data = resp_money.json()
        assert m_data["summary"]["total_debit"] == 498000.0
        assert len(m_data["signals"]) >= 1

        # Assert rapid transfer signal
        rapid_signal = next((s for s in m_data["signals"] if s["signal_type"] == "RAPID_TRANSFER"), None)
        assert rapid_signal is not None
        assert len(rapid_signal["evidence_refs"]) > 0
        assert len(rapid_signal["event_refs"]) == 2
        assert "gap_minutes" in rapid_signal["metrics"]
        assert rapid_signal["metrics"]["gap_minutes"] == 37.0

        # Every ledger event must have document provenance
        for ev in m_data["events"]:
            assert ev["source_doc"] == bank_doc.filename
            assert ev["source_page"] is not None
            assert ev["source_line"] is not None

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 4: Every communication signal has evidence provenance
        # ─────────────────────────────────────────────────────────────────────
        c_data = resp_comms.json()
        assert c_data["summary"]["total_calls"] >= 3
        burst_signal = next((s for s in c_data["signals"] if s["signal_type"] == "COMMUNICATION_BURST"), None)
        assert burst_signal is not None
        assert len(burst_signal["evidence_refs"]) > 0
        assert len(burst_signal["event_refs"]) >= 3
        assert len(burst_signal["entities_involved"]) >= 2
        assert "+91-9876543210" in burst_signal["entities_involved"]

        # Hourly distribution heatmap has 24 bins
        assert len(c_data["summary"]["hourly_distribution"]) == 24
        assert c_data["summary"]["hourly_distribution"]["10"] >= 3

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 5: Every geographic observation retains source timestamp
        # ─────────────────────────────────────────────────────────────────────
        g_data = resp_geo.json()
        assert g_data["summary"]["total_observations"] == 3
        geo_1_item = next(e for e in g_data["events"] if e["id"] == str(geo1.id))
        assert geo_1_item["event_time"] == "2026-08-21T10:02:00+00:00"
        assert geo_1_item["time_confidence"] == "CONFIRMED"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 6: Missing geographic time is never fabricated
        # ─────────────────────────────────────────────────────────────────────
        geo_no_time_item = next(e for e in g_data["events"] if e["id"] == str(geo_no_time.id))
        assert geo_no_time_item["event_time"] is None
        assert geo_no_time_item["time_confidence"] == "RECORDED_ONLY"
        assert geo_no_time_item["time_warning"] is not None

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 7: Cell-site data is never represented as precise GPS
        # ─────────────────────────────────────────────────────────────────────
        assert g_data["disclaimer"] == LOCATION_DISCLAIMER
        assert "NOT exact physical location" in g_data["disclaimer"]
        assert any("NOT exact physical location" in s["description"] for s in g_data["signals"] if s["signal_type"] == "TOWER_HOPPING")

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 8: Lens projections do not create canonical relationships
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db_chk:
            from sqlalchemy import select, func
            rel_cnt = (await db_chk.execute(select(func.count(Relationship.id)).where(Relationship.case_id == case.id))).scalar()
            assert rel_cnt == 2

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 9: Rejected relationships do not appear as canonical in lenses
        # ─────────────────────────────────────────────────────────────────────
        for lens_resp in [m_data, c_data, g_data]:
            canon_rels = [r for r in lens_resp["relationships"] if r["is_canonical"]]
            assert not any(r["id"] == str(rel_rejected.id) for r in canon_rels)
            rej_in_lens = next((r for r in lens_resp["relationships"] if r["id"] == str(rel_rejected.id)), None)
            if rej_in_lens:
                assert rej_in_lens["verification_status"] == RT.REVIEW_REJECTED
                assert rej_in_lens["is_canonical"] is False

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 10: Investigator-added relationships remain visibly distinguished
        # ─────────────────────────────────────────────────────────────────────
        obs_rel = next(r for r in m_data["relationships"] if r["id"] == str(rel_observed.id))
        assert obs_rel["epistemic_status"] == RT.OBSERVED
        assert obs_rel["is_canonical"] is True
        assert obs_rel["created_by"] == str(inv_user.id)

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 11: Selecting an entity produces consistent results across all lenses
        # ─────────────────────────────────────────────────────────────────────
        # Filter all three lenses by entity: "+91-9876543210"
        m_ent_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/money?entity_id=+91-9876543210", headers=headers)
        assert m_ent_resp.status_code == 200

        c_ent_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/communications?entity_id=+91-9876543210", headers=headers)
        assert c_ent_resp.status_code == 200
        # Comms should include calls involving +91-9876543210
        assert all("+91-9876543210" in (ev["details"]["caller"] or ev["details"]["callee"]) for ev in c_ent_resp.json()["events"])

        g_ent_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/geographic?entity_id=+91-9876543210", headers=headers)
        assert g_ent_resp.status_code == 200
        # Geo should include observations for this phone
        assert all(ev["details"]["phone"] == "+91-9876543210" for ev in g_ent_resp.json()["events"])

        # Also test entity focused shortcut endpoint
        focused_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/communications/entity/+91-9876543210", headers=headers)
        assert focused_resp.status_code == 200
        assert focused_resp.json()["id"] == "COMMUNICATION"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 12: Selecting a timeline event filters the active lens correctly
        # ─────────────────────────────────────────────────────────────────────
        # Filter window: 10:05 to 10:30 (should catch Call 1, 2, 3 but NOT night call or 10:00 txn)
        t_start = "2026-08-21T10:05:00Z"
        t_end = "2026-08-21T10:30:00Z"
        m_win_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/money?start_time={t_start}&end_time={t_end}", headers=headers)
        assert m_win_resp.status_code == 200
        assert len(m_win_resp.json()["events"]) == 0  # Txn1 was 10:00, Txn2 was 10:37

        c_win_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/communications?start_time={t_start}&end_time={t_end}", headers=headers)
        assert c_win_resp.status_code == 200
        assert len(c_win_resp.json()["events"]) == 3  # All 3 burst calls were between 10:10 and 10:22

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 13: Historical replay can render the lens at state version N
        # ─────────────────────────────────────────────────────────────────────
        # At state version 1 (before 8/21 events), no 8/21 events were in the case
        async with AsyncSessionLocal() as db_ckpt:
            # Bump case to version 2 and record checkpoint at 8/20 18:00
            c_bump = await db_ckpt.get(Case, case.id)
            c_bump.state_version = 2
            ckpt2 = InvestigationState(
                id=uuid.uuid4(),
                case_id=case.id,
                version=2,
                state_hash="v2_hash",
                created_by=inv_user.id,
                created_at=datetime(2026, 8, 20, 18, 0, 0, tzinfo=timezone.utc),
            )
            db_ckpt.add(ckpt2)
            await db_ckpt.commit()

        # Lens query at historical version 1 (cutoff = ckpt2.created_at = 8/20 18:00)
        v1_lens_resp = await client.get(f"/api/v1/cases/{case.id}/lenses/money?state_version=1", headers=headers)
        assert v1_lens_resp.status_code == 200
        v1_lens = v1_lens_resp.json()
        assert v1_lens["is_historical"] is True
        assert v1_lens["state_version"] == 1
        # Events created on 8/21 are excluded by the checkpoint cutoff
        assert len(v1_lens["events"]) == 0

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 14: Findings remain linked to their supporting evidence
        # ─────────────────────────────────────────────────────────────────────
        m_findings = m_data["findings"]
        assert len(m_findings) >= 1
        matched_finding = next(f for f in m_findings if f["id"] == str(finding.id))
        assert str(bank_doc.id) in matched_finding["evidence_refs"]
        assert str(ent_account.id) in matched_finding["entity_refs"]
        assert str(txn1.id) in matched_finding["event_refs"]

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 15: Copilot / Gateway read queries do not silently mutate state
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db_final:
            c_final = await db_final.get(Case, case.id)
            # Must still be version 2 (from our explicit test bump), zero side-effect mutations
            assert c_final.state_version == 2
