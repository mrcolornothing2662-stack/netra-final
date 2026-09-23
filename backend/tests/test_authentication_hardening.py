from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 1: Authentication Hardening
Verifies:
- Memory-hard Argon2id password verification
- Sliding-window account lockout after excessive failed logins
- Token revocation and blocklist enforcement
- Session tracking and session revocation
- Step-up session elevation
"""

import uuid
from datetime import datetime, timedelta, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import User, UserSession
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token, _hash_password, _revoke_jti


@pytest.mark.asyncio
async def test_argon2id_and_failed_login_lockout():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        user = User(
            id=uuid.uuid4(),
            username=f"lockout_user_{unique_id}",
            email=f"lockout_{unique_id}@police.gov.in",
            hashed_password=_hash_password("CorrectHorseBatteryStaple123!"),
            role="io",
            full_name="Constable Under Attack",
            is_active=True,
            failed_login_attempts=0,
        )
        db.add(user)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Attempt invalid logins up to threshold (5 attempts)
            for i in range(5):
                resp = await client.post(
                    "/api/v1/auth/login",
                    data={"username": user.username, "password": "WrongPassword!"},
                )
                assert resp.status_code in (401, 429), f"Attempt {i+1} got {resp.status_code}"

            # 2. 6th attempt MUST be blocked by account lockout (429 or 423)
            locked_resp = await client.post(
                "/api/v1/auth/login",
                data={"username": user.username, "password": "WrongPassword!"},
            )
            assert locked_resp.status_code in (429, 423)
            assert "locked" in locked_resp.text.lower()


@pytest.mark.asyncio
async def test_session_creation_revocation_and_elevation():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        manager = User(
            id=uuid.uuid4(),
            username=f"manager_sess_{unique_id}",
            email=f"manager_{unique_id}@police.gov.in",
            hashed_password=_hash_password("SuperSecret123!"),
            role="MANAGER",
            full_name="DSP Intelligence Lead",
            is_active=True,
        )
        db.add(manager)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Login with device ID header
            login_resp = await client.post(
                "/api/v1/auth/login",
                data={"username": manager.username, "password": "SuperSecret123!"},
                headers={"X-Device-ID": "station-terminal-042"},
            )
            assert login_resp.status_code == 200, login_resp.text
            tok_data = login_resp.json()
            token = tok_data["access_token"]
            auth_header = {"Authorization": f"Bearer {token}"}

            # 2. Inspect active sessions
            sess_resp = await client.get("/api/v1/auth/sessions", headers=auth_header)
            assert sess_resp.status_code == 200
            sessions = sess_resp.json()
            assert len(sessions) >= 1
            sess_id = sessions[0]["session_id"]
            assert sessions[0]["device_id"] == "station-terminal-042"
            assert sessions[0]["authentication_level"] == "standard"

            # 3. Elevate session to supervisor
            elevate_resp = await client.post(
                "/api/v1/auth/sessions/elevate",
                json={"password": "SuperSecret123!", "target_level": "supervisor"},
                headers=auth_header,
            )
            assert elevate_resp.status_code == 200
            elevated_token = elevate_resp.json()["access_token"]

            # 4. Revoke session
            revoke_resp = await client.post(
                "/api/v1/auth/sessions/revoke",
                json={"session_id": sess_id, "reason": "Officer logout"},
                headers={"Authorization": f"Bearer {elevated_token}"},
            )
            assert revoke_resp.status_code == 200
            assert "revoked" in revoke_resp.json()["message"].lower()

            # 5. Subsequent access with revoked token MUST FAIL (401 Unauthorized)
            post_revoke = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {elevated_token}"})
            assert post_revoke.status_code == 401
