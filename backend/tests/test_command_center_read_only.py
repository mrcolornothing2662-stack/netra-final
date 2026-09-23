from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Command Center Read-Only Invariant Test Suite
Verifies that GET /cases/{case_id}/command-center is strictly read-only:
- Does not increment case state_version
- Does not mutate last_activity_at
- Does not create investigation_activity records
- Does not alter historical replay checkpoints
"""
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.models import (
    Case,
    InvestigationActivity,
    InvestigationState,
    User,
)
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_command_center_is_strictly_read_only():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_ro_{uuid.uuid4().hex[:6]}",
            email=f"io_ro_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="hashed_pw_test",
            role="io",
            full_name="Inspector Read Only",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(user.id), role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

        initial_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-RO-{uuid.uuid4().hex[:8].upper()}",
            title="Operation Read Only Guard",
            crime_type="Cyber Fraud",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
            state_version=4,
            created_at=initial_time,
            last_activity_at=initial_time,
        )
        db.add(case)
        await db.flush()

        # Seed initial state checkpoint at v4
        ckpt = InvestigationState(
            id=uuid.uuid4(),
            case_id=case.id,
            version=4,
            state_hash="hash_v4_baseline",
            created_at=initial_time,
            created_by=user.id,
        )
        db.add(ckpt)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Call Command Center endpoint 5 times in succession
        for _ in range(5):
            resp = await client.get(f"/api/v1/cases/{case.id}/command-center", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["state_version"] == 4

        # Verify DB state remained completely unmutated
        async with AsyncSessionLocal() as db_check:
            c_check = await db_check.get(Case, case.id)
            assert c_check.state_version == 4
            assert c_check.last_activity_at == initial_time

            # No investigation_activity entries created
            act_count = (await db_check.execute(
                select(func.count()).select_from(InvestigationActivity).where(InvestigationActivity.case_id == case.id)
            )).scalar() or 0
            assert act_count == 0

            # Replay checkpoints untouched
            ckpts = list((await db_check.execute(
                select(InvestigationState).where(InvestigationState.case_id == case.id)
            )).scalars().all())
            assert len(ckpts) == 1
            assert ckpts[0].version == 4
            assert ckpts[0].state_hash == "hash_v4_baseline"
