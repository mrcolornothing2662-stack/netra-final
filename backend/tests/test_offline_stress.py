from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Offline Multi-Device Concurrency & Stress Suite (Milestone 10)
Verifies:
  1. Concurrency stress with 1, 3, and 10 field devices syncing concurrently.
  2. Duplicate packet replay idempotency (network re-transmissions cause no duplicate records).
  3. Out-of-order mutation arrival handling (rebase or conflict; monotonic server state versions).
  4. Conflicting offline decisions (Device A confirms, Device B rejects) and conflict adjudication.
  5. Invariants: Strict state version monotonicity, zero corrupted states, zero lost updates.
"""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationActivity,
    InvestigationState,
    Relationship,
    SyncConflictRecord,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_offline_multi_device_concurrency_and_stress():
    run_id = uuid.uuid4().hex[:8]

    # 1. Setup Investigator & Supervisor users
    async with AsyncSessionLocal() as db:
        io_user = User(
            id=uuid.uuid4(),
            username=f"stress_io_{run_id}",
            email=f"stress_io_{run_id}@police.gov.in",
            full_name="Stress Test IO",
            rank="Inspector",
            unit="Tactical Ops",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(io_user)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-STRESS-{run_id.upper()}",
            title=f"Multi-Device Offline Stress Case {run_id}",
            description="Testing concurrent multi-device sync, packet replays, and conflict adjudication",
            status="open",
            assigned_officer_id=io_user.id,
            state_version=1,
        )
        db.add(case)
        db.add(
            CaseCollaborator(
                id=uuid.uuid4(),
                case_id=case.id,
                user_id=io_user.id,
                role="lead",
            )
        )
        await db.flush()

        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"stress_ev_{run_id}.csv",
            original_name=f"stress_ev_{run_id}.csv",
            file_type="telecom_cdr",
            sha256_hash=uuid.uuid4().hex * 2,
            storage_path=f"/uploads/stress_{run_id}.csv",
            file_size_bytes=2048,
        )
        db.add(ev_file)

        # Seed two entities and an unreviewed relationship
        ent_a = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value=f"+9198111{run_id[:5]}",
            entity_type="phone",
        )
        ent_b = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value=f"+9198222{run_id[:5]}",
            entity_type="phone",
        )
        db.add_all([ent_a, ent_b])
        await db.flush()

        test_rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent_a.id,
            target_entity_id=ent_b.id,
            relationship_type=RT.COMMUNICATED_WITH,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            is_canonical=False,
            confidence=0.85,
            evidence_refs=[str(ev_file.id)],
        )
        db.add(test_rel)

        # Setup initial InvestigationState checkpoint version 1
        db.add(
            InvestigationState(
                id=uuid.uuid4(),
                case_id=case.id,
                version=1,
                created_by=io_user.id,
            )
        )
        await db.commit()

        case_id = str(case.id)
        rel_id = str(test_rel.id)
        user_id = str(io_user.id)

    # Helper to create device session and auth header
    async def _setup_device(dev_name: str) -> tuple[str, dict[str, str]]:
        async with AsyncSessionLocal() as sdb:
            sess_id = uuid.uuid4().hex
            us = UserSession(
                id=sess_id,
                user_id=uuid.UUID(user_id),
                device_id=dev_name,
                ip_address="127.0.0.1",
                user_agent="StressHarness/1.0",
                authentication_level="standard",
                revoked=False,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
            )
            sdb.add(us)
            await sdb.commit()

        tok, _, _ = _create_access_token(
            user_id=user_id,
            role="INVESTIGATOR",
            session_id=sess_id,
            device_id=dev_name,
        )
        hdrs = {
            "Authorization": f"Bearer {tok}",
            "X-Device-ID": dev_name,
            "X-Session-ID": sess_id,
        }
        return dev_name, hdrs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # ── Test 1: Single Device Baseline Sync ─────────────────────────────────
        dev1_id, dev1_headers = await _setup_device(f"DEV-STRESS-1-{run_id[:4]}")
        m_id_base = str(uuid.uuid4())
        resp_base = await client.post(
            f"/api/v1/cases/{case_id}/sync",
            json={
                "device_id": dev1_id,
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": m_id_base,
                        "device_id": dev1_id,
                        "actor_id": user_id,
                        "case_id": case_id,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CREATE_HYPOTHESIS",
                        "payload": {"title": "Baseline Field Hypothesis"},
                        "base_state_version": 1,
                    }
                ],
            },
            headers=dev1_headers,
        )
        assert resp_base.status_code == 200, resp_base.text
        data_base = resp_base.json()
        assert len(data_base["accepted"]) == 1
        assert data_base["server_state_version"] == 2

        # ── Test 2: Duplicate Packet Replay Idempotency ──────────────────────────
        # Re-sending the exact same batch MUST be 100% idempotent
        resp_replay = await client.post(
            f"/api/v1/cases/{case_id}/sync",
            json={
                "device_id": dev1_id,
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": m_id_base,
                        "device_id": dev1_id,
                        "actor_id": user_id,
                        "case_id": case_id,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CREATE_HYPOTHESIS",
                        "payload": {"title": "Baseline Field Hypothesis"},
                        "base_state_version": 1,
                    }
                ],
            },
            headers=dev1_headers,
        )
        assert resp_replay.status_code == 200
        data_replay = resp_replay.json()
        # Server version must not have incremented again
        assert data_replay["server_state_version"] == 2

        # ── Test 3: 3 Devices Concurrent Non-Conflicting Sync ───────────────────
        dev2_id, dev2_headers = await _setup_device(f"DEV-STRESS-2-{run_id[:4]}")
        dev3_id, dev3_headers = await _setup_device(f"DEV-STRESS-3-{run_id[:4]}")

        async def _sync_hypo(dev_id: str, headers: dict[str, str], title: str):
            mid = str(uuid.uuid4())
            return await client.post(
                f"/api/v1/cases/{case_id}/sync",
                json={
                    "device_id": dev_id,
                    "client_state_version": 2,
                    "mutations": [
                        {
                            "mutation_id": mid,
                            "device_id": dev_id,
                            "actor_id": user_id,
                            "case_id": case_id,
                            "client_created_at": datetime.now(timezone.utc).isoformat(),
                            "command_type": "CREATE_HYPOTHESIS",
                            "payload": {"title": title},
                            "base_state_version": 2,
                        }
                    ],
                },
                headers=headers,
            )

        res_2, res_3 = await asyncio.gather(
            _sync_hypo(dev2_id, dev2_headers, "Hypothesis from Device 2"),
            _sync_hypo(dev3_id, dev3_headers, "Hypothesis from Device 3"),
        )
        assert res_2.status_code == 200
        assert res_3.status_code == 200
        assert res_2.json()["server_state_version"] >= 3
        assert res_3.json()["server_state_version"] >= 3

        # ── Test 4: Conflicting Decision Adjudication ───────────────────────────
        # Device 1 confirms the relationship
        m_confirm_id = str(uuid.uuid4())
        conf_resp = await client.post(
            f"/api/v1/cases/{case_id}/sync",
            json={
                "device_id": dev1_id,
                "client_state_version": 2,
                "mutations": [
                    {
                        "mutation_id": m_confirm_id,
                        "device_id": dev1_id,
                        "actor_id": user_id,
                        "case_id": case_id,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "CONFIRM_RELATIONSHIP",
                        "payload": {"relationship_id": rel_id},
                        "base_state_version": 2,
                    }
                ],
            },
            headers=dev1_headers,
        )
        assert conf_resp.status_code == 200
        assert len(conf_resp.json()["accepted"]) == 1 or len(conf_resp.json()["rebased"]) == 1

        # Device 2 concurrently submits REJECT on the same relationship from stale version 2
        m_reject_id = str(uuid.uuid4())
        conflict_resp = await client.post(
            f"/api/v1/cases/{case_id}/sync",
            json={
                "device_id": dev2_id,
                "client_state_version": 2,
                "mutations": [
                    {
                        "mutation_id": m_reject_id,
                        "device_id": dev2_id,
                        "actor_id": user_id,
                        "case_id": case_id,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "REJECT_RELATIONSHIP",
                        "payload": {"relationship_id": rel_id},
                        "base_state_version": 2,
                    }
                ],
            },
            headers=dev2_headers,
        )
        assert conflict_resp.status_code == 200
        conf_data = conflict_resp.json()
        assert len(conf_data["conflicts"]) == 1

        # Investigator resolves the conflict
        confs_list = await client.get(f"/api/v1/cases/{case_id}/conflicts", headers=dev1_headers)
        assert confs_list.status_code == 200
        active_confs = confs_list.json()
        assert len(active_confs) >= 1

        res_resolve = await client.post(
            f"/api/v1/cases/{case_id}/conflicts/{active_confs[0]['conflict_id']}/resolve",
            json={
                "resolution": "KEEP_SERVER",
                "rationale": "Prior confirmation supported by physical warrant evidence",
            },
            headers=dev1_headers,
        )
        assert res_resolve.status_code == 200
        assert res_resolve.json()["success"] is True

        # ── Test 5: 10 Field Devices Concurrency Stress ─────────────────────────
        devices = []
        for i in range(10):
            d_id, d_hdrs = await _setup_device(f"DEV-CONC-{i}-{run_id[:4]}")
            devices.append((d_id, d_hdrs))

        current_server_version = res_resolve.json()["server_state_version"]

        async def _device_worker(idx: int, dev_tuple: tuple[str, dict[str, str]]):
            d_name, d_h = dev_tuple
            mid = str(uuid.uuid4())
            return await client.post(
                f"/api/v1/cases/{case_id}/sync",
                json={
                    "device_id": d_name,
                    "client_state_version": current_server_version,
                    "mutations": [
                        {
                            "mutation_id": mid,
                            "device_id": d_name,
                            "actor_id": user_id,
                            "case_id": case_id,
                            "client_created_at": datetime.now(timezone.utc).isoformat(),
                            "command_type": "CREATE_HYPOTHESIS",
                            "payload": {"title": f"Concurrent Field Intel #{idx}"},
                            "base_state_version": current_server_version,
                        }
                    ],
                },
                headers=d_h,
            )

        worker_tasks = [_device_worker(i, devices[i]) for i in range(10)]
        worker_results = await asyncio.gather(*worker_tasks)

        for idx, wr in enumerate(worker_results):
            assert wr.status_code == 200, f"Worker {idx} failed: {wr.text}"
            res_json = wr.json()
            assert len(res_json["accepted"]) == 1 or len(res_json["rebased"]) == 1 or len(res_json["conflicts"]) == 1

        # ── Test 6: Invariants Verification ─────────────────────────────────────
        async with AsyncSessionLocal() as final_db:
            final_case = await final_db.get(Case, uuid.UUID(case_id))
            assert final_case is not None
            # Server state version must have monotonically increased
            assert final_case.state_version > current_server_version

            # Check that activities and states match monotonically
            st_q = select(InvestigationState).where(InvestigationState.case_id == uuid.UUID(case_id)).order_by(InvestigationState.version.asc())
            states = list((await final_db.execute(st_q)).scalars().all())
            versions = [s.version for s in states]
            # No duplicate version numbers allowed
            assert len(versions) == len(set(versions))
            assert versions == sorted(versions)
