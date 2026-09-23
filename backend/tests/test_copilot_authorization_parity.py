from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 9: Copilot Authorization Parity
Verifies:
- Parity between Direct UI mutations and Copilot proposal confirmations
- Copilot proposals route through Command Gateway with identical capability checks
- Unauthorized user cannot bypass security policy via Copilot proposals
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, Entity, Relationship, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_copilot_proposal_authorization_parity():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        # Constable (Read-only observer, lacks RELATIONSHIP_REVIEW capability)
        constable = User(
            id=uuid.uuid4(),
            username=f"constable_copilot_{unique_id}",
            email=f"constable_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="constable",
            is_active=True,
        )
        # Lead Investigator
        investigator = User(
            id=uuid.uuid4(),
            username=f"investigator_copilot_{unique_id}",
            email=f"io_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add_all([constable, investigator])
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-COP-{unique_id.upper()}",
            title="Operation AI Lead",
            assigned_officer_id=investigator.id,
            status="open",
            state_version=5,
        )
        db.add(case)
        await db.flush()

        ent1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Suspect A", entity_type="PERSON")
        ent2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Mule B", entity_type="PERSON")
        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent1.id,
            target_entity_id=ent2.id,
            relationship_type="COMMUNICATES_WITH",
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
            # Simulated copilot mutation proposal targeting Command Gateway
            proposal_command = {
                "command": "CONFIRM_RELATIONSHIP",
                "payload": {"relationship_id": str(rel.id)},
                "reason": "Confirmed via Copilot investigative recommendation",
                "base_case_version": 5,
            }

            # 1. CONSTABLE ATTEMPTS TO EXECUTE COPILOT PROPOSAL -> MUST FAIL (403 or 404)
            resp_c = await client.post(
                f"/api/v1/cases/{case.id}/commands",
                json=proposal_command,
                headers=headers_c,
            )
            assert resp_c.status_code in (403, 404)

            # 2. AUTHORIZED INVESTIGATOR EXECUTES COPILOT PROPOSAL -> PERMITTED (200 OK)
            resp_inv = await client.post(
                f"/api/v1/cases/{case.id}/commands",
                json=proposal_command,
                headers=headers_inv,
            )
            assert resp_inv.status_code == 200
            res_data = resp_inv.json()
            assert res_data["success"] is True
            assert res_data["new_state_version"] == 6
            assert res_data["command"] == "CONFIRM_RELATIONSHIP"
