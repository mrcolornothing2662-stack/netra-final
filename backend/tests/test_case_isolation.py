from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 3: Multi-Case Tenant Isolation
Verifies:
- Complete isolation between Case A and Case B
- Unauthorized case access returns non-leaking 404
- Injecting an object ID from Case B into Case A command returns 404
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, Entity, Relationship, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_strict_multi_case_tenant_isolation():
    async with AsyncSessionLocal() as db:
        # User A assigned to Case A
        user_a = User(
            id=uuid.uuid4(),
            username=f"investigator_a_{uuid.uuid4().hex[:6]}",
            email=f"io_a_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        # User B assigned to Case B
        user_b = User(
            id=uuid.uuid4(),
            username=f"investigator_b_{uuid.uuid4().hex[:6]}",
            email=f"io_b_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add_all([user_a, user_b])
        await db.flush()

        case_a = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-A-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Alpha (Confidential)",
            assigned_officer_id=user_a.id,
            status="open",
        )
        case_b = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-B-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Bravo (Classified)",
            assigned_officer_id=user_b.id,
            status="open",
        )
        db.add_all([case_a, case_b])
        await db.flush()

        # Entity and Relationship in Case B
        ent_b1 = Entity(id=uuid.uuid4(), case_id=case_b.id, canonical_value="B1_Target", entity_type="PERSON")
        ent_b2 = Entity(id=uuid.uuid4(), case_id=case_b.id, canonical_value="B2_Mule", entity_type="BANK_ACCOUNT")
        rel_b = Relationship(
            id=uuid.uuid4(),
            case_id=case_b.id,
            source_entity_id=ent_b1.id,
            target_entity_id=ent_b2.id,
            relationship_type="TRANSFERS_TO",
            verification_status="UNREVIEWED",
        )
        db.add_all([ent_b1, ent_b2, rel_b])
        await db.commit()

        token_a, _, _ = _create_access_token(user_id=str(user_a.id), role=user_a.role)
        headers_a = {"Authorization": f"Bearer {token_a}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. User A accesses Case A -> 200 OK
            resp_a = await client.get(f"/api/v1/cases/{case_a.id}/workspace", headers=headers_a)
            assert resp_a.status_code == 200

            # 2. User A attempts to access Case B workspace -> 404 (non-leaking)
            resp_b_workspace = await client.get(f"/api/v1/cases/{case_b.id}/workspace", headers=headers_a)
            assert resp_b_workspace.status_code == 404

            # 3. User A attempts to access Case B entities -> 404
            resp_b_entities = await client.get(f"/api/v1/cases/{case_b.id}/entities", headers=headers_a)
            assert resp_b_entities.status_code == 404

            # 4. User A attempts to access Case B replay index -> 404
            resp_b_replay = await client.get(f"/api/v1/cases/{case_b.id}/replay", headers=headers_a)
            assert resp_b_replay.status_code == 404

            # 5. User A attempts to download Case B offline bundle -> 404
            resp_b_bundle = await client.get(f"/api/v1/cases/{case_b.id}/offline-bundle", headers=headers_a)
            assert resp_b_bundle.status_code == 404

            # 6. INJECTION ATTACK: User A targets Case A endpoint, but submits Relationship ID from Case B
            resp_cross_command = await client.post(
                f"/api/v1/cases/{case_a.id}/commands",
                json={
                    "command": "CONFIRM_RELATIONSHIP",
                    "payload": {"relationship_id": str(rel_b.id)},
                    "reason": "Attempting cross-case relationship confirmation",
                },
                headers=headers_a,
            )
            # Must fail with 404 because rel_b is not in Case A
            assert resp_cross_command.status_code == 404
            assert "Relationship not found in this case" in resp_cross_command.json()["detail"]
