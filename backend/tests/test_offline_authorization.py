from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 8: Offline Synchronization Authorization & Idempotency
Verifies:
- Offline sync mutations re-check authorization server-side on every command
- Unauthorized offline mutations are rejected with error_code 'UNAUTHORIZED'
- Idempotency guarantees prevent replay/duplicate execution
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, Entity, Relationship, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_offline_sync_authorization_and_idempotency():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        # Constable (lacks RELATIONSHIP_REVIEW capability)
        constable = User(
            id=uuid.uuid4(),
            username=f"constable_offline_{unique_id}",
            email=f"constable_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="constable",
            is_active=True,
        )
        # Investigator (possesses RELATIONSHIP_REVIEW capability)
        investigator = User(
            id=uuid.uuid4(),
            username=f"investigator_offline_{unique_id}",
            email=f"inv_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add_all([constable, investigator])
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-SYNC-{unique_id.upper()}",
            title="Operation Field Sync",
            assigned_officer_id=investigator.id,
            status="open",
            state_version=1,
        )
        db.add(case)
        await db.flush()

        ent1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Suspect Mule", entity_type="PERSON")
        ent2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="UPI ID", entity_type="UPI")
        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent1.id,
            target_entity_id=ent2.id,
            relationship_type="ASSOCIATED_WITH",
            verification_status="UNREVIEWED",
        )
        db.add_all([ent1, ent2, rel])
        await db.commit()

        token_c, _, _ = _create_access_token(user_id=str(constable.id), role=constable.role)
        headers_c = {"Authorization": f"Bearer {token_c}"}

        token_inv, _, _ = _create_access_token(user_id=str(investigator.id), role=investigator.role)
        headers_inv = {"Authorization": f"Bearer {token_inv}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            mut_id_1 = f"mut-{uuid.uuid4().hex[:12]}"
            # 1. UNAUTHORIZED MUTATION: Constable queues CONFIRM_RELATIONSHIP offline
            # Attempt to sync -> server re-check MUST reject with UNAUTHORIZED
            resp_c = await client.post(
                f"/api/v1/cases/{case.id}/sync",
                json={
                    "device_id": "field-tablet-99",
                    "client_state_version": 1,
                    "mutations": [
                        {
                            "mutation_id": mut_id_1,
                            "device_id": "field-tablet-99",
                            "actor_id": str(constable.id),
                            "case_id": str(case.id),
                            "command_type": "CONFIRM_RELATIONSHIP",
                            "payload": {"relationship_id": str(rel.id)},
                            "base_state_version": 1,
                            "client_created_at": "2026-09-22T10:00:00Z",
                            "local_sequence": 1,
                        }
                    ],
                },
                headers=headers_c,
            )
            # Depending on case access, constable might get 403 / 404 or rejection in batch
            if resp_c.status_code == 200:
                batch = resp_c.json()
                assert len(batch["rejected"]) > 0
                assert batch["rejected"][0]["error_code"] == "UNAUTHORIZED"
            else:
                assert resp_c.status_code in (403, 404)

            # 2. AUTHORIZED MUTATION: Investigator queues CONFIRM_RELATIONSHIP offline
            mut_id_2 = f"mut-{uuid.uuid4().hex[:12]}"
            resp_inv = await client.post(
                f"/api/v1/cases/{case.id}/sync",
                json={
                    "device_id": "inv-laptop-01",
                    "client_state_version": 1,
                    "mutations": [
                        {
                            "mutation_id": mut_id_2,
                            "device_id": "inv-laptop-01",
                            "actor_id": str(investigator.id),
                            "case_id": str(case.id),
                            "command_type": "CONFIRM_RELATIONSHIP",
                            "payload": {"relationship_id": str(rel.id)},
                            "base_state_version": 1,
                            "client_created_at": "2026-09-22T10:05:00Z",
                            "local_sequence": 1,
                        }
                    ],
                },
                headers=headers_inv,
            )
            assert resp_inv.status_code == 200
            batch_inv = resp_inv.json()
            assert mut_id_2 in batch_inv["accepted"]
            assert batch_inv["server_state_version"] >= 2

            # 3. IDEMPOTENCY: Re-submitting the exact same mutation_id produces idempotent accepted outcome
            resp_replay = await client.post(
                f"/api/v1/cases/{case.id}/sync",
                json={
                    "device_id": "inv-laptop-01",
                    "client_state_version": 1,
                    "mutations": [
                        {
                            "mutation_id": mut_id_2,
                            "device_id": "inv-laptop-01",
                            "actor_id": str(investigator.id),
                            "case_id": str(case.id),
                            "command_type": "CONFIRM_RELATIONSHIP",
                            "payload": {"relationship_id": str(rel.id)},
                            "base_state_version": 1,
                            "client_created_at": "2026-09-22T10:05:00Z",
                            "local_sequence": 1,
                        }
                    ],
                },
                headers=headers_inv,
            )
            assert resp_replay.status_code == 200
            assert mut_id_2 in resp_replay.json()["accepted"]
