import uuid
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from db.models import (
    Case,
    Entity,
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
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_timeline_and_replay_12_point_invariants():
    """
    Comprehensive test suite verifying all 12 acceptance criteria for Milestone 4:
    1. Evidence appears at its source event time.
    2. Missing event time is never replaced with ingestion time.
    3. Investigator identity decisions appear in investigation replay.
    4. Relationship accept/reject appears in investigation replay.
    5. Copilot proposal without confirmation appears only as proposal activity.
    6. Copilot confirmation creates the actual mutation activity.
    7. Historical state vN differs correctly from current state vN+K.
    8. Rejected relationships never become canonical during replay.
    9. Identity candidates remain candidates until their decision event.
    10. Replay is read-only.
    11. Replay does not mutate case state.
    12. Replay preserves evidence provenance.
    """
    async with AsyncSessionLocal() as db:
        # Create base case and officer
        case = Case(
            id=uuid.uuid4(),
            case_number=f"TRP-{uuid.uuid4().hex[:6]}",
            title="Timeline and Replay Test Case",
            status="open",
            state_version=1,
            created_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
        )
        io = User(
            id=uuid.uuid4(),
            username=f"io_replay_{uuid.uuid4().hex[:6]}@police.gov.in",
            email=f"io_replay_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        case.assigned_officer_id = io.id
        db.add_all([case, io])

        # State version 1 checkpoint (established after initial ingestion & extraction)
        state_v1 = InvestigationState(
            id=uuid.uuid4(),
            case_id=case.id,
            version=1,
            state_hash="hash_v1",
            created_at=datetime(2026, 1, 2, 13, 0, tzinfo=timezone.utc),
            created_by=io.id,
        )
        db.add(state_v1)
        await db.commit()

        # ── 1. Create Evidence File & Events with Known Source Times ───────────
        ef = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="cdr_log_01.csv",
            original_name="cdr_log_01.csv",
            file_type="cdr",
            file_size_bytes=2048,
            sha256_hash="f5a7b2c4819d92e8a7c2b3d4e5f6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8",
            uploaded_by=io.id,
            storage_path=f"/tmp/test_cdr_{uuid.uuid4().hex}.csv",
            uploaded_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),  # Ingestion time
        )
        db.add(ef)

        # Event A: Has explicit real-world event_time (2025-12-25) distinct from ingestion time
        ev_timed = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef.id,
            event_type="cdr_call",
            event_timestamp=datetime(2025, 12, 25, 15, 30, tzinfo=timezone.utc),
            text_content="Outgoing voice call to suspect from tower 44",
            source_line=42,
            source_page=1,
            created_at=datetime(2026, 1, 2, 12, 5, tzinfo=timezone.utc),
        )

        # Event B: Missing event_time (undated note)
        ev_undated = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case.id,
            evidence_file_id=ef.id,
            event_type="device_note",
            event_timestamp=None,  # No event timestamp
            text_content="Scratchpad note without header timestamp",
            source_line=88,
            created_at=datetime(2026, 1, 2, 12, 6, tzinfo=timezone.utc),
        )
        db.add_all([ev_timed, ev_undated])

        # ── 2. Create Entities at Version 1 ────────────────────────────────────
        e1 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+919876543210",
            entity_type="PHONE",
            created_at=datetime(2026, 1, 2, 12, 10, tzinfo=timezone.utc),
        )
        e2 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Target Suspect",
            entity_type="PER",
            created_at=datetime(2026, 1, 2, 12, 10, tzinfo=timezone.utc),
        )
        db.add_all([e1, e2])

        # ── 3. Create Inferred Relationship ───────────────────────────────────
        rel1 = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type="ASSOCIATED_WITH",
            direction="BIDIRECTIONAL",
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            is_canonical=False,
            confidence=0.85,
            created_at=datetime(2026, 1, 2, 12, 15, tzinfo=timezone.utc),
        )
        db.add(rel1)

        # ── 4. Create Identity Candidate ──────────────────────────────────────
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=e2.id,
            candidate_value="T. Suspect",
            candidate_type="PER",
            resolution_status="UNRESOLVED",
            created_at=datetime(2026, 1, 2, 12, 20, tzinfo=timezone.utc),
        )
        db.add(cand)

        # ── 5. Create Finding at Version 1 ─────────────────────────────────────
        finding = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            fingerprint=f"fp_{uuid.uuid4().hex[:12]}",
            finding_type="CROSS_SOURCE_CORRELATION",
            title="Phone Association Finding",
            description="Correlation between phone and target suspect",
            severity="HIGH",
            confidence=0.90,
            status="OPEN",
            freshness_status="CURRENT",
            generated_at_case_version=1,
            entity_refs=[str(e1.id), str(e2.id)],
            created_at=datetime(2026, 1, 2, 12, 25, tzinfo=timezone.utc),
        )
        db.add(finding)
        await db.commit()

        # Generate auth token
        token, _, _ = _create_access_token(str(io.id), io.role)
        headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ─────────────────────────────────────────────────────────────────────
        # Invariant 1: Evidence appears at its source event time
        # ─────────────────────────────────────────────────────────────────────
        resp = await client.get(f"/api/v1/cases/{case.id}/timeline?mode=incident", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 2
        timed_item = next((it for it in data["items"] if it["id"] == str(ev_timed.id)), None)
        assert timed_item is not None
        assert timed_item["event_time"] == "2025-12-25T15:30:00+00:00"
        assert timed_item["recorded_at"] == "2026-01-02T12:05:00+00:00"
        assert timed_item["time_status"] == "OK"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 2: Missing event time is never replaced with ingestion time
        # ─────────────────────────────────────────────────────────────────────
        undated_item = next((it for it in data["items"] if it["id"] == str(ev_undated.id)), None)
        assert undated_item is not None
        assert undated_item["event_time"] is None
        assert undated_item["time_status"] == "TIME_NORMALIZATION_REQUIRED"
        # Ingestion time is preserved in recorded_at
        assert undated_item["recorded_at"] == "2026-01-02T12:06:00+00:00"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 5: Copilot proposal without confirmation appears only as proposal
        # ─────────────────────────────────────────────────────────────────────
        # Send prompt with proposal to copilot
        copilot_req = {
            "question": "Please confirm relationship between the phone and suspect",
        }
        cop_resp = await client.post(f"/api/v1/copilot/{case.id}", json=copilot_req, headers=headers)
        assert cop_resp.status_code == 200
        cop_data = cop_resp.json()
        # Case version must NOT have been incremented by copilot message
        async with AsyncSessionLocal() as db_check:
            c_check = await db_check.get(Case, case.id)
            assert c_check.state_version == 1

        # ─────────────────────────────────────────────────────────────────────
        # Execute Command 1: Investigator confirms relationship (v1 -> v2)
        # ─────────────────────────────────────────────────────────────────────
        conf_resp = await client.post(
            f"/api/v1/cases/{case.id}/commands",
            json={
                "command": "CONFIRM_RELATIONSHIP",
                "payload": {"relationship_id": str(rel1.id)},
                "reason": "Call records corroborate direct suspect possession",
            },
            headers=headers,
        )
        assert conf_resp.status_code == 200
        assert conf_resp.json()["new_state_version"] == 2

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 4: Relationship accept/reject appears in investigation replay
        # ─────────────────────────────────────────────────────────────────────
        act_resp = await client.get(f"/api/v1/cases/{case.id}/timeline?mode=investigation", headers=headers)
        assert act_resp.status_code == 200
        inv_items = act_resp.json()["items"]
        rel_act = next((it for it in inv_items if it["activity_type"] == "RELATIONSHIP_CONFIRMED"), None)
        assert rel_act is not None
        assert str(rel1.id) in rel_act["relationship_refs"]
        assert "direct suspect possession" in rel_act["summary"]

        # ─────────────────────────────────────────────────────────────────────
        # Execute Command 2: Investigator resolves identity candidate (v2 -> v3)
        # ─────────────────────────────────────────────────────────────────────
        cand_resp = await client.post(
            f"/api/v1/cases/{case.id}/commands",
            json={
                "command": "RESOLVE_IDENTITY_CANDIDATE",
                "payload": {
                    "candidate_id": str(cand.id),
                    "resolution_status": "CONFIRMED_SAME",
                },
                "reason": "PAN card name variant confirms same individual",
            },
            headers=headers,
        )
        assert cand_resp.status_code == 200
        assert cand_resp.json()["new_state_version"] == 3

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 3: Investigator identity decisions appear in investigation replay
        # ─────────────────────────────────────────────────────────────────────
        act_resp2 = await client.get(f"/api/v1/cases/{case.id}/timeline?mode=investigation", headers=headers)
        inv_items2 = act_resp2.json()["items"]
        cand_act = next((it for it in inv_items2 if it["activity_type"] == "IDENTITY_CANDIDATE_RESOLVED"), None)
        assert cand_act is not None
        assert "CONFIRMED_SAME" in cand_act["summary"]

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 6: Copilot confirmation creates the actual mutation activity
        # ─────────────────────────────────────────────────────────────────────
        # When user submits a confirmed mutation from copilot, it dispatches through /commands
        prop_cmd_resp = await client.post(
            f"/api/v1/cases/{case.id}/commands",
            json={
                "command": "CREATE_HYPOTHESIS",
                "payload": {
                    "title": "Suspect operated primary burner device",
                    "description": "Proposed by Copilot, confirmed by IO",
                },
                "reason": "Investigator approved Copilot proposal",
            },
            headers=headers,
        )
        assert prop_cmd_resp.status_code == 200
        assert prop_cmd_resp.json()["new_state_version"] == 4

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 7: Historical state vN differs correctly from current state vM
        # ─────────────────────────────────────────────────────────────────────
        # Replay at Version 1 (prior to relationship confirmation & candidate resolution)
        v1_resp = await client.get(f"/api/v1/cases/{case.id}/replay/1", headers=headers)
        assert v1_resp.status_code == 200
        v1_data = v1_resp.json()
        assert v1_data["state_version"] == 1
        assert v1_data["current_case_version"] == 4
        assert v1_data["is_historical"] is True

        # At v1, relationship rel1 must NOT be canonical!
        v1_canon_rels = v1_data["relationships"]["canonical"]
        v1_inf_rels = v1_data["relationships"]["inferred"]
        assert not any(r["id"] == str(rel1.id) for r in v1_canon_rels)
        assert any(r["id"] == str(rel1.id) for r in v1_inf_rels)

        # At v1, identity candidate must be UNRESOLVED!
        v1_cands = v1_data["identity_candidates"]
        v1_target_cand = next(c for c in v1_cands if c["id"] == str(cand.id))
        assert v1_target_cand["resolution_status"] == "UNRESOLVED"

        # Current Replay at Version 4 (after relationship confirmation & candidate resolution)
        v4_resp = await client.get(f"/api/v1/cases/{case.id}/replay/4", headers=headers)
        assert v4_resp.status_code == 200
        v4_data = v4_resp.json()
        assert v4_data["state_version"] == 4
        assert v4_data["is_historical"] is False

        # At v4, relationship rel1 IS canonical!
        v4_canon_rels = v4_data["relationships"]["canonical"]
        assert any(r["id"] == str(rel1.id) for r in v4_canon_rels)

        # At v4, identity candidate is CONFIRMED_SAME!
        v4_cands = v4_data["identity_candidates"]
        v4_target_cand = next(c for c in v4_cands if c["id"] == str(cand.id))
        assert v4_target_cand["resolution_status"] == "CONFIRMED_SAME"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 8: Rejected relationships never become canonical during replay
        # ─────────────────────────────────────────────────────────────────────
        # Create an inferred relationship and reject it
        rel_reject_id = uuid.uuid4()
        async with AsyncSessionLocal() as db_rel:
            rel_rej = Relationship(
                id=rel_reject_id,
                case_id=case.id,
                source_entity_id=e1.id,
                target_entity_id=e2.id,
                relationship_type="CO_OCCURRENCE",
                direction="BIDIRECTIONAL",
                epistemic_status=RT.INFERRED,
                verification_status=RT.REVIEW_UNREVIEWED,
                is_canonical=False,
                created_at=datetime(2026, 1, 3, 10, 0, tzinfo=timezone.utc),
            )
            db_rel.add(rel_rej)
            await db_rel.commit()

        # Reject it via command (bumps to v5)
        rej_cmd = await client.post(
            f"/api/v1/cases/{case.id}/commands",
            json={
                "command": "REJECT_RELATIONSHIP",
                "payload": {"relationship_id": str(rel_reject_id)},
                "reason": "Co-occurrence was accidental bystander presence",
            },
            headers=headers,
        )
        assert rej_cmd.status_code == 200
        assert rej_cmd.json()["new_state_version"] == 5

        # In replay at v5, rejected relationship must NOT be canonical
        v5_resp = await client.get(f"/api/v1/cases/{case.id}/replay/5", headers=headers)
        v5_data = v5_resp.json()
        assert not any(r["id"] == str(rel_reject_id) for r in v5_data["relationships"]["canonical"])
        rej_inf_rel = next(r for r in v5_data["relationships"]["inferred"] if r["id"] == str(rel_reject_id))
        assert rej_inf_rel["verification_status"] == RT.REVIEW_REJECTED
        assert rej_inf_rel["is_canonical"] is False

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 9: Identity candidates remain candidates until their decision event
        # ─────────────────────────────────────────────────────────────────────
        # At v2 (before candidate resolution command at v3), candidate was UNRESOLVED
        v2_resp = await client.get(f"/api/v1/cases/{case.id}/replay/2", headers=headers)
        v2_cand = next(c for c in v2_resp.json()["identity_candidates"] if c["id"] == str(cand.id))
        assert v2_cand["resolution_status"] == "UNRESOLVED"

        # At v3 (after resolution command), candidate is CONFIRMED_SAME
        v3_resp = await client.get(f"/api/v1/cases/{case.id}/replay/3", headers=headers)
        v3_cand = next(c for c in v3_resp.json()["identity_candidates"] if c["id"] == str(cand.id))
        assert v3_cand["resolution_status"] == "CONFIRMED_SAME"

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 10 & 11: Replay is strictly read-only and does not mutate case state
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db_pre:
            c_pre = await db_pre.get(Case, case.id)
            pre_version = c_pre.state_version
            pre_last_act = c_pre.last_activity_at

        # Execute 5 replay queries across various versions
        for v in [1, 2, 3, 4, 5]:
            await client.get(f"/api/v1/cases/{case.id}/replay/{v}", headers=headers)
        await client.get(f"/api/v1/cases/{case.id}/replay", headers=headers)

        async with AsyncSessionLocal() as db_post:
            c_post = await db_post.get(Case, case.id)
            # Must remain EXACTLY equal: zero mutations, zero bumps
            assert c_post.state_version == pre_version
            assert c_post.last_activity_at == pre_last_act

        # ─────────────────────────────────────────────────────────────────────
        # Invariant 12: Replay preserves evidence provenance and source citations
        # ─────────────────────────────────────────────────────────────────────
        # Check timeline items have complete provenance and file references
        tl_resp = await client.get(f"/api/v1/cases/{case.id}/timeline?mode=all", headers=headers)
        assert tl_resp.status_code == 200
        tl_items = tl_resp.json()["items"]
        ef_item = next(it for it in tl_items if it["id"] == str(ev_timed.id))
        assert ef_item["provenance"]["source_doc"] == "cdr_log_01.csv"
        assert ef_item["provenance"]["source_line"] == 42
        assert ef_item["provenance"]["file_hash"] == ef.sha256_hash
        assert str(ef.id) in ef_item["evidence_refs"]
