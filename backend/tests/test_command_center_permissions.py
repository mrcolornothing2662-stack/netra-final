from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Command Center Permissions & Multi-Tenant Scoping Test Suite
Verifies that GET /cases/{case_id}/command-center strictly enforces case authorization boundaries:
- Unauthorized users receive 404 (preventing investigation enumeration)
- Authorized lead officers and collaborators receive the projection
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, CaseCollaborator, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_command_center_case_authorization_boundaries():
    async with AsyncSessionLocal() as db:
        assigned_user = User(
            id=uuid.uuid4(),
            username=f"io_auth_{uuid.uuid4().hex[:6]}",
            email=f"io_auth_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Assigned Lead IO",
            rank="Inspector",
            is_active=True,
        )
        collab_user = User(
            id=uuid.uuid4(),
            username=f"collab_{uuid.uuid4().hex[:6]}",
            email=f"collab_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="constable",
            full_name="Collaborator Officer",
            rank="Constable",
            is_active=True,
        )
        outsider_user = User(
            id=uuid.uuid4(),
            username=f"outsider_{uuid.uuid4().hex[:6]}",
            email=f"outsider_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Outsider Officer",
            rank="Inspector",
            is_active=True,
        )
        db.add_all([assigned_user, collab_user, outsider_user])
        await db.flush()

        assigned_token, _, _ = _create_access_token(user_id=str(assigned_user.id), role=assigned_user.role)
        assigned_headers = {"Authorization": f"Bearer {assigned_token}"}

        collab_token, _, _ = _create_access_token(user_id=str(collab_user.id), role=collab_user.role)
        collab_headers = {"Authorization": f"Bearer {collab_token}"}

        outsider_token, _, _ = _create_access_token(user_id=str(outsider_user.id), role=outsider_user.role)
        outsider_headers = {"Authorization": f"Bearer {outsider_token}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-PERM-{uuid.uuid4().hex[:8].upper()}",
            title="Operation Firewall Guard",
            crime_type="Cyber Intrusions",
            priority="medium",
            status="open",
            assigned_officer_id=assigned_user.id,
            state_version=1,
            created_at=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        )
        db.add(case)
        await db.flush()

        # Add collaborator
        collab = CaseCollaborator(
            id=uuid.uuid4(),
            case_id=case.id,
            user_id=collab_user.id,
            role="observer",
            assigned_by=assigned_user.id,
        )
        db.add(collab)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Assigned Lead IO can read Command Center
        resp_io = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=assigned_headers)
        assert resp_io.status_code == 200
        assert resp_io.json()["case_id"] == str(case.id)

        # 2. Case Collaborator (Observer) can read Command Center
        resp_collab = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=collab_headers)
        assert resp_collab.status_code == 200
        assert resp_collab.json()["case_id"] == str(case.id)

        # 3. Unassigned outsider is denied (HTTP 404 to avoid leaking case existence)
        resp_outsider = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=outsider_headers)
        assert resp_outsider.status_code == 404
