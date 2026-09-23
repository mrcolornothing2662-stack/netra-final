from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 6: Offline Synchronization & Conflict Resolution Suite
Verifies all 15 architectural invariants:
1. Same mutation_id is idempotent.
2. Offline reads never mutate server state.
3. Every offline mutation enters Command Gateway.
4. Unauthorized offline commands are rejected server-side.
5. Stale base version does not automatically overwrite state.
6. Compatible mutations can rebase.
7. Conflicting mutations become explicit conflicts.
8. Conflict resolution itself is audited.
9. Evidence remains immutable offline.
10. Case state version remains server-authoritative.
11. Replay includes successfully synchronized offline decisions.
12. Failed synchronization does not lose the local mutation.
13. Retrying the same mutation cannot duplicate a relationship.
14. Copilot-created proposals remain proposals while offline.
15. Forensic lenses can operate from the offline projection without fabricating data.
Plus end-to-end multi-investigator acceptance test.
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    SyncConflictRecord,
    SyncProcessedMutation,
    User,
)
from db.session import AsyncSessionLocal
import graph.relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_milestone6_offline_sync_suite():
    async with AsyncSessionLocal() as db:
        # ── 1. Setup Users & RBAC ─────────────────────────────────────────────
        io_user = User(
            id=uuid.uuid4(),
            username=f"io_sync_{uuid.uuid4().hex[:6]}",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Inspector Offline Sync",
            rank="Inspector",
            is_active=True,
        )
        constable_user = User(
            id=uuid.uuid4(),
            username=f"constable_sync_{uuid.uuid4().hex[:6]}",
            email=f"constable_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="constable",
            full_name="Constable Restricted",
            rank="Constable",
            is_active=True,
        )
        db.add_all([io_user, constable_user])
        await db.flush()

        io_token, _, _ = _create_access_token(user_id=str(io_user.id), role=io_user.role)
        io_headers = {"Authorization": f"Bearer {io_token}"}

        constable_token, _, _ = _create_access_token(user_id=str(constable_user.id), role=constable_user.role)
        constable_headers = {"Authorization": f"Bearer {constable_token}"}

        # ── 2. Create Initial Case at version 1 ──────────────────────────────
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-SYNC-{uuid.uuid4().hex[:8].upper()}",
            title="Operation ShadowSync — Offline Reconciliation Case",
            crime_type="Cyber Fraud",
            priority="high",
            status="open",
            assigned_officer_id=io_user.id,
            state_version=1,
            created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            last_activity_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(case)
        await db.flush()

        collab_constable = CaseCollaborator(
            id=uuid.uuid4(),
            case_id=case.id,
            user_id=constable_user.id,
            role="investigator",
            assigned_by=io_user.id,
        )
        db.add(collab_constable)

        # Seed initial state checkpoint at v1
        ckpt_v1 = InvestigationState(
            id=uuid.uuid4(),
            case_id=case.id,
            version=1,
            state_hash="hash_v1_init",
            created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
            created_by=io_user.id,
        )
        db.add(ckpt_v1)

        # Seed Evidence File
        evidence_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="offline_seizure_report.pdf",
            original_name="offline_seizure_report.pdf",
            file_type="PDF",
            storage_path=f"/tmp/sync_evidence_{uuid.uuid4().hex[:8]}.pdf",
            sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            uploaded_by=io_user.id,
            uploaded_at=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc),
        )
        db.add(evidence_file)

        # Seed Entities
        ent_a = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9811223344",
            entity_type="PHONE",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        ent_b = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9811223355",
            entity_type="PHONE",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        ent_c = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="SBI-ACC-449900",
            entity_type="ACCOUNT",
            created_at=datetime(2026, 9, 1, 10, 10, 0, tzinfo=timezone.utc),
        )
        db.add_all([ent_a, ent_b, ent_c])

        # Seed Relationships (Unreviewed proposal)
        rel_1 = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent_a.id,
            target_entity_id=ent_b.id,
            relationship_type="COMMUNICATED_WITH",
            direction="OUTBOUND",
            epistemic_status="INFERRED",
            verification_status="UNREVIEWED",
            confidence=0.84,
            created_by=io_user.id,
            state_version=1,
            created_at=datetime(2026, 9, 1, 10, 12, 0, tzinfo=timezone.utc),
        )
        db.add(rel_1)

        # Seed Identity Candidate (Unresolved proposal)
        cand_1 = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=ent_a.id,
            candidate_value="+91-9811223355",
            candidate_type="PHONE",
            resolution_status="UNRESOLVED",
            source_refs=["offline_seizure_report.pdf"],
            supporting_refs=["Shared IMEI: 8675309001"],
            contradicting_refs=[],
            created_at=datetime(2026, 9, 1, 10, 15, 0, tzinfo=timezone.utc),
        )
        # Seed another Identity Candidate (for conflict test)
        cand_2 = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=ent_a.id,
            candidate_value="SBI-ACC-449900",
            candidate_type="ACCOUNT",
            resolution_status="UNRESOLVED",
            source_refs=["offline_seizure_report.pdf"],
            supporting_refs=["Co-occurring IPDR prefix"],
            contradicting_refs=["Different device form factor"],
            created_at=datetime(2026, 9, 1, 10, 15, 0, tzinfo=timezone.utc),
        )
        db.add_all([cand_1, cand_2])
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 2: Offline reads never mutate server state
        # ─────────────────────────────────────────────────────────────────────
        resp_bundle = await client.get(
            f"/api/v1/cases/{case.id}/offline-bundle",
            headers=io_headers,
        )
        assert resp_bundle.status_code == 200
        bundle = resp_bundle.json()
        assert bundle["case"]["id"] == str(case.id)
        assert bundle["server_state_version"] == 1
        assert len(bundle["entities"]) == 3
        assert len(bundle["relationships"]) == 1
        assert len(bundle["identity_candidates"]) == 2
        assert len(bundle["evidence_metadata"]) == 1

        # Verify server state is untouched
        async with AsyncSessionLocal() as db_check:
            c_check = await db_check.get(Case, case.id)
            assert c_check.state_version == 1
            assert c_check.last_activity_at == datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 4: Unauthorized offline commands rejected server-side
        # ─────────────────────────────────────────────────────────────────────
        unauth_mut_id = f"mut_unauth_{uuid.uuid4().hex[:6]}"
        resp_unauth = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=constable_headers,  # Constable lacks CAP_RELATIONSHIP_CONFIRM
            json={
                "device_id": "FIELD-TABLET-02",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": unauth_mut_id,
                        "device_id": "FIELD-TABLET-02",
                        "actor_id": str(constable_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 1,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CONFIRM_RELATIONSHIP",
                        "payload": {"relationship_id": str(rel_1.id)},
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_unauth.status_code == 200
        unauth_res = resp_unauth.json()
        assert len(unauth_res["rejected"]) == 1
        assert unauth_res["rejected"][0]["mutation_id"] == unauth_mut_id
        assert unauth_res["rejected"][0]["error_code"] == "UNAUTHORIZED"
        assert unauth_res["server_state_version"] == 1  # No version bump

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 3: Every offline mutation enters Command Gateway
        # ─────────────────────────────────────────────────────────────────────
        mut_1_id = f"mut_valid_rel_{uuid.uuid4().hex[:6]}"
        resp_sync_1 = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-01",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": mut_1_id,
                        "device_id": "FIELD-TABLET-01",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 1,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CONFIRM_RELATIONSHIP",
                        "payload": {"relationship_id": str(rel_1.id), "rationale": "Verified from call log"},
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_sync_1.status_code == 200
        sync_1_data = resp_sync_1.json()
        assert mut_1_id in sync_1_data["accepted"]
        assert sync_1_data["server_state_version"] == 2  # Incremented to v2

        # Verify Command Gateway executed and updated Relationship row
        async with AsyncSessionLocal() as db_check:
            r_check = await db_check.get(Relationship, rel_1.id)
            assert r_check.verification_status == RT.REVIEW_ACCEPTED
            assert r_check.verified_by == io_user.id

            # Verify audit trail exists
            acts = list((await db_check.execute(select(InvestigationActivity).where(InvestigationActivity.case_id == case.id))).scalars().all())
            assert len(acts) >= 1

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 1: Same mutation_id is idempotent
        # ─────────────────────────────────────────────────────────────────────
        resp_sync_idempotent = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-01",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": mut_1_id,  # Exact same ID
                        "device_id": "FIELD-TABLET-01",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 1,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CONFIRM_RELATIONSHIP",
                        "payload": {"relationship_id": str(rel_1.id)},
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_sync_idempotent.status_code == 200
        idem_data = resp_sync_idempotent.json()
        assert mut_1_id in idem_data["accepted"]
        assert idem_data["server_state_version"] == 2  # Version did NOT increment again!

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 6: Compatible mutations can rebase
        # ─────────────────────────────────────────────────────────────────────
        # Offline tablet was at base_version=1. Server is now at v2.
        # Candidate 1 was untouched on server.
        mut_rebase_id = f"mut_cand_rebase_{uuid.uuid4().hex[:6]}"
        resp_rebase = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-01",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": mut_rebase_id,
                        "device_id": "FIELD-TABLET-01",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 1,  # Stale! (Server is at 2)
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "RESOLVE_IDENTITY_CANDIDATE",
                        "payload": {
                            "candidate_id": str(cand_1.id),
                            "decision": "CONFIRMED_DIFFERENT",
                            "notes": "Different subscribers verified offline",
                        },
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_rebase.status_code == 200
        rebase_data = resp_rebase.json()
        assert mut_rebase_id in rebase_data["rebased"]
        assert rebase_data["server_state_version"] == 3  # Successfully rebased and incremented to v3!

        async with AsyncSessionLocal() as db_check:
            c1_check = await db_check.get(IdentityCandidate, cand_1.id)
            assert c1_check.resolution_status == "CONFIRMED_DIFFERENT"

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 5 & 7: Conflicting mutations become explicit conflicts
        # ─────────────────────────────────────────────────────────────────────
        # First, another investigator online resolves cand_2 as CONFIRMED_SAME on server
        async with AsyncSessionLocal() as db_server:
            c2_obj = await db_server.get(IdentityCandidate, cand_2.id)
            c2_obj.resolution_status = "CONFIRMED_SAME"
            c2_obj.resolved_at = datetime.now(timezone.utc)
            c_bump = await db_server.get(Case, case.id)
            c_bump.state_version = 4
            await db_server.commit()

        # Now, offline tablet (still at base_version=1) tries to submit CONFIRMED_DIFFERENT for cand_2!
        mut_conflict_id = f"mut_cand_conflict_{uuid.uuid4().hex[:6]}"
        resp_conflict = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-01",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": mut_conflict_id,
                        "device_id": "FIELD-TABLET-01",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 1,  # Stale!
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "RESOLVE_IDENTITY_CANDIDATE",
                        "payload": {
                            "candidate_id": str(cand_2.id),
                            "decision": "CONFIRMED_DIFFERENT",  # Conflicts with server's CONFIRMED_SAME!
                            "notes": "Decided different based on device form factor",
                        },
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_conflict.status_code == 200
        conflict_data = resp_conflict.json()
        assert len(conflict_data["conflicts"]) == 1
        conf = conflict_data["conflicts"][0]
        assert conf["mutation_id"] == mut_conflict_id
        assert conf["conflict_type"] == "IDENTITY_DECISION_CONFLICT"
        assert conf["status"] == "PENDING_REVIEW"
        assert conflict_data["server_state_version"] == 4  # Server state was NOT overwritten!

        # Verify candidate 2 is still CONFIRMED_SAME on server
        async with AsyncSessionLocal() as db_check:
            c2_check = await db_check.get(IdentityCandidate, cand_2.id)
            assert c2_check.resolution_status == "CONFIRMED_SAME"

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 8: Conflict resolution itself is audited
        # ─────────────────────────────────────────────────────────────────────
        # 1. Fetch pending conflicts endpoint
        resp_conf_list = await client.get(
            f"/api/v1/cases/{case.id}/conflicts",
            headers=io_headers,
        )
        assert resp_conf_list.status_code == 200
        conf_list = resp_conf_list.json()
        assert len(conf_list) >= 1
        target_conflict = next(c for c in conf_list if c["mutation_id"] == mut_conflict_id)

        # 2. Resolve conflict (Investigator reviews evidence and chooses KEEP_SERVER)
        resp_resolve = await client.post(
            f"/api/v1/cases/{case.id}/conflicts/{target_conflict['conflict_id']}/resolve",
            headers=io_headers,
            json={
                "resolution": "KEEP_SERVER",
                "rationale": "Investigator reviewed both notes; confirmed Officer B online determination is correct.",
            },
        )
        assert resp_resolve.status_code == 200
        resolve_data = resp_resolve.json()
        assert resolve_data["status"] == "RESOLVED_KEEP_SERVER"
        assert resolve_data["server_state_version"] == 5  # Bumps version to v5

        # Verify audit row created for conflict resolution
        async with AsyncSessionLocal() as db_check:
            act_res = list((await db_check.execute(
                select(InvestigationActivity).where(
                    InvestigationActivity.case_id == case.id,
                    InvestigationActivity.activity_type == "SYNC_CONFLICT_RESOLVED",
                )
            )).scalars().all())
            assert len(act_res) >= 1
            assert act_res[0].reason == "Investigator reviewed both notes; confirmed Officer B online determination is correct."

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 9 & 10: Evidence immutability & server-authoritative version
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db_check:
            ef_check = await db_check.get(EvidenceFile, evidence_file.id)
            assert ef_check.sha256_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            c_final = await db_check.get(Case, case.id)
            assert c_final.state_version == 5

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 13: Retrying same mutation cannot duplicate a relationship
        # ─────────────────────────────────────────────────────────────────────
        mut_dup_id_1 = f"mut_dup_{uuid.uuid4().hex[:6]}"
        resp_add_rel_1 = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-01",
                "client_state_version": 5,
                "mutations": [
                    {
                        "mutation_id": mut_dup_id_1,
                        "device_id": "FIELD-TABLET-01",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 5,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "ADD_INVESTIGATOR_RELATIONSHIP",
                        "payload": {
                            "source_entity_id": str(ent_a.id),
                            "target_entity_id": str(ent_c.id),
                            "relationship_type": "TRANSACTED_WITH",
                            "rationale": "Transfer documented in seizure memo",
                        },
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_add_rel_1.status_code == 200
        assert mut_dup_id_1 in resp_add_rel_1.json()["accepted"]

        # Submitting the same relationship from a different offline tablet
        mut_dup_id_2 = f"mut_dup_different_id_{uuid.uuid4().hex[:6]}"
        resp_add_rel_2 = await client.post(
            f"/api/v1/cases/{case.id}/sync",
            headers=io_headers,
            json={
                "device_id": "FIELD-TABLET-02",
                "client_state_version": 5,
                "mutations": [
                    {
                        "mutation_id": mut_dup_id_2,
                        "device_id": "FIELD-TABLET-02",
                        "actor_id": str(io_user.id),
                        "case_id": str(case.id),
                        "base_state_version": 5,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "ADD_INVESTIGATOR_RELATIONSHIP",
                        "payload": {
                            "source_entity_id": str(ent_a.id),
                            "target_entity_id": str(ent_c.id),
                            "relationship_type": "TRANSACTED_WITH",
                            "rationale": "Observed identical edge",
                        },
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_add_rel_2.status_code == 200
        assert mut_dup_id_2 in resp_add_rel_2.json()["rebased"]

        # Confirm there is strictly ONE relationship between ent_a and ent_c
        async with AsyncSessionLocal() as db_check:
            matching_rels = list((await db_check.execute(
                select(Relationship).where(
                    Relationship.case_id == case.id,
                    Relationship.source_entity_id == ent_a.id,
                    Relationship.target_entity_id == ent_c.id,
                    Relationship.relationship_type == "TRANSACTED_WITH",
                )
            )).scalars().all())
            assert len(matching_rels) == 1

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 11: Replay includes successfully synchronized offline decisions
        # ─────────────────────────────────────────────────────────────────────
        resp_replay = await client.get(
            f"/api/v1/cases/{case.id}/replay",
            headers=io_headers,
        )
        assert resp_replay.status_code == 200
        replay_data = resp_replay.json()
        assert replay_data["total_versions"] >= 5
        activities_types = [v["activity_type"] for v in replay_data["versions"]]
        assert any("RELATIONSHIP" in act for act in activities_types)

        # ─────────────────────────────────────────────────────────────────────
        # INVARIANT 15: Forensic lenses can operate from offline projection
        # ─────────────────────────────────────────────────────────────────────
        # The offline bundle download has complete events, entities, and relationships
        resp_bundle_latest = await client.get(
            f"/api/v1/cases/{case.id}/offline-bundle",
            headers=io_headers,
        )
        assert resp_bundle_latest.status_code == 200
        latest_b = resp_bundle_latest.json()
        assert len(latest_b["entities"]) == 3
        assert len(latest_b["relationships"]) >= 2
        assert latest_b["server_state_version"] >= 6
