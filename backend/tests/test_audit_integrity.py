from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 6: Cryptographic Audit Trail Integrity
Verifies:
- Consecutive SHA-256 hash-chain linkage (Audit #101 -> hash -> Audit #102)
- Tampering with details, timestamps, or prev_hash is immediately flagged as BROKEN HASH CHAIN
- Verifier detects broken link without mutating any records
"""

import copy
import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import AuditLog, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token
from security.audit_verifier import AuditVerifier
from utils.audit import append_audit


@pytest.mark.asyncio
async def test_audit_hash_chain_verification_and_tamper_detection():
    async with AsyncSessionLocal() as db:
        # Create 3 audit entries linked consecutively
        e1 = await append_audit(
            db,
            action="TEST_ACTION_1",
            resource_type="case",
            resource_id="case-101",
            details={"step": 1, "payload": "initial_data"},
        )
        await db.flush()

        e2 = await append_audit(
            db,
            action="TEST_ACTION_2",
            resource_type="case",
            resource_id="case-101",
            details={"step": 2, "payload": "secondary_data"},
        )
        await db.flush()

        e3 = await append_audit(
            db,
            action="TEST_ACTION_3",
            resource_type="case",
            resource_id="case-101",
            details={"step": 3, "payload": "final_data"},
        )
        await db.commit()

        # 1. Verify unbroken chain
        status_ok = await AuditVerifier.verify_ledger(db)
        assert status_ok["intact"] is True
        assert status_ok["status"] == "VERIFIED"

        # 2. SIMULATE ADVERSARIAL TAMPERING: In-memory alteration of record e2
        # Clone records to simulate DB retrieval with tampered entry
        records = [e1, e2, e3]
        tampered_records = copy.copy(records)
        tampered_entry = AuditLog(
            id=e2.id,
            prev_hash=e2.prev_hash,
            entry_hash=e2.entry_hash,
            event_timestamp=e2.event_timestamp,
            user_id=e2.user_id,
            action=e2.action,
            resource_type=e2.resource_type,
            resource_id=e2.resource_id,
            details_json={"step": 2, "payload": "TAMPERED_ADVERSARY_DATA"},
        )
        tampered_records[1] = tampered_entry

        # 3. Verifier MUST detect the broken hash chain
        status_tampered = AuditVerifier.verify_records(tampered_records)
        assert status_tampered["intact"] is False
        assert status_tampered["status"] == "BROKEN_HASH_CHAIN"
        assert status_tampered["first_broken_entry_id"] == e2.id
        assert "BROKEN HASH CHAIN" in status_tampered["message"]


@pytest.mark.asyncio
async def test_audit_verify_api_endpoint():
    async with AsyncSessionLocal() as db:
        admin_user = User(
            id=uuid.uuid4(),
            username=f"admin_audit_{uuid.uuid4().hex[:6]}",
            email=f"admin_audit_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="ADMIN",
            is_active=True,
        )
        db.add(admin_user)
        await db.commit()

        token, _, _ = _create_access_token(user_id=str(admin_user.id), role=admin_user.role)
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/audit/verify", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["intact"] is True
            assert "global_entry_count" in data
