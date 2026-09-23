from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 10: Security Event Center & Administrative Projections
Verifies:
- ADMIN_SECURITY capability guard on /api/v1/security endpoints
- Security overview telemetry projection
- Filtered security event stream projection
- Session listing and administrative kill switch revocation
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import User, UserSession
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_security_event_center_projections_and_admin_guard():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        # Regular Investigator (lacks ADMIN_SECURITY)
        investigator = User(
            id=uuid.uuid4(),
            username=f"sec_io_{unique_id}",
            email=f"io_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        # Security Administrator (possesses ADMIN_SECURITY)
        admin = User(
            id=uuid.uuid4(),
            username=f"sec_admin_{unique_id}",
            email=f"admin_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([investigator, admin])
        await db.flush()

        # Seed a test session
        target_session_id = uuid.uuid4().hex
        sess = UserSession(
            id=target_session_id,
            user_id=investigator.id,
            device_id="investigator-tablet-01",
            expires_at=admin.created_at,  # dummy
            authentication_level="standard",
        )
        db.add(sess)
        await db.commit()

        token_io, _, _ = _create_access_token(user_id=str(investigator.id), role=investigator.role)
        headers_io = {"Authorization": f"Bearer {token_io}"}

        token_admin, _, _ = _create_access_token(user_id=str(admin.id), role=admin.role)
        headers_admin = {"Authorization": f"Bearer {token_admin}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. INVESTIGATOR ATTEMPTS TO ACCESS SECURITY CENTER -> MUST FAIL (403 Forbidden)
            resp_io_overview = await client.get("/api/v1/security/overview", headers=headers_io)
            assert resp_io_overview.status_code == 403

            resp_io_events = await client.get("/api/v1/security/events", headers=headers_io)
            assert resp_io_events.status_code == 403

            # 2. ADMIN ACCESSES SECURITY OVERVIEW -> 200 OK
            resp_overview = await client.get("/api/v1/security/overview", headers=headers_admin)
            assert resp_overview.status_code == 200
            ov_data = resp_overview.json()
            assert "audit_chain" in ov_data
            assert "metrics" in ov_data
            assert ov_data["status"] in ("HEALTHY", "TAMPERING_DETECTED")

            # 3. ADMIN LISTS SECURITY EVENTS -> 200 OK
            resp_events = await client.get("/api/v1/security/events?category=all", headers=headers_admin)
            assert resp_events.status_code == 200
            events_data = resp_events.json()
            assert "items" in events_data
            assert "total" in events_data

            # 4. ADMIN LISTS SESSIONS -> 200 OK
            resp_sessions = await client.get("/api/v1/security/sessions", headers=headers_admin)
            assert resp_sessions.status_code == 200
            sess_list = resp_sessions.json()
            assert any(s["session_id"] == target_session_id for s in sess_list)

            # 5. ADMIN REVOKES TARGET SESSION VIA KILL SWITCH
            resp_kill = await client.post(
                f"/api/v1/security/sessions/{target_session_id}/revoke?reason=Adversarial+anomaly+detected",
                headers=headers_admin,
            )
            assert resp_kill.status_code == 200
            assert "revoked by administrator" in resp_kill.json()["message"]
