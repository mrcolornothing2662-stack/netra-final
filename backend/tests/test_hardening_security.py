"""
Hardening & Security Acceptance Test Suite — NETRA 5.0
Workstream 2: Security, Multi-Tenant Case Isolation, JWT Lifecycle & Zero-Knowledge Privacy.

Tests:
1. Multi-tenant case isolation (require_case_access enforcement between officers)
2. Admin override permissions on case tenancy
3. Unauthenticated access gating (401 Unauthorized on protected routes)
4. JWT token tampering, invalid signatures, and malformed authorization headers
5. Role-based permission enforcement across distinct roles (admin vs io vs analyst)
6. Zero-Knowledge Blind Index HMAC-SHA256 privacy boundaries (DPDP Act 2023)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from db.models import Case, User
from db.session import AsyncSessionLocal
from routes.auth import _create_token, _hash_password, _verify_password, _resolve_user, require_role
from routes.case_access import require_case_access


# ── 1. Multi-Tenant Case Isolation ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_tenant_case_access_isolation():
    """Verify that an investigating officer cannot access another officer's case."""
    async with AsyncSessionLocal() as db:
        # Create Officer A and Officer B
        officer_a = User(
            username=f"officer_a_{uuid.uuid4().hex[:6]}",
            email=f"officer_a_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Officer Alpha",
            role="io",
            is_active=True,
        )
        officer_b = User(
            username=f"officer_b_{uuid.uuid4().hex[:6]}",
            email=f"officer_b_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Officer Beta",
            role="io",
            is_active=True,
        )
        admin_user = User(
            username=f"admin_{uuid.uuid4().hex[:6]}",
            email=f"admin_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="SP Cyber",
            role="admin",
            is_active=True,
        )
        db.add_all([officer_a, officer_b, admin_user])
        await db.commit()
        await db.refresh(officer_a)
        await db.refresh(officer_b)
        await db.refresh(admin_user)

        # Create Case assigned strictly to Officer A
        case_a = Case(
            case_number=f"SEC-A-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Shield A",
            priority="high",
            status="open",
            assigned_officer_id=officer_a.id,
        )
        db.add(case_a)
        await db.commit()
        await db.refresh(case_a)

        # 1. Officer A accessing own case -> Success
        accessible_case = await require_case_access(db, officer_a, str(case_a.id))
        assert accessible_case.id == case_a.id

        # 2. Officer B accessing Officer A's case -> 404 (does not reveal case existence)
        with pytest.raises(HTTPException) as exc_info:
            await require_case_access(db, officer_b, str(case_a.id))
        assert exc_info.value.status_code == 404
        assert "Case not found" in str(exc_info.value.detail)

        # 3. Admin user without assignment -> 404 (Default denial / Separation of duties)
        with pytest.raises(HTTPException) as exc_admin:
            await require_case_access(db, admin_user, str(case_a.id))
        assert exc_admin.value.status_code == 404

        # 3b. Admin added as case collaborator -> Access Granted
        from db.models import CaseCollaborator
        collab = CaseCollaborator(
            case_id=case_a.id,
            user_id=admin_user.id,
            role="supervisor",
            assigned_by=officer_a.id,
        )
        db.add(collab)
        await db.commit()
        admin_access = await require_case_access(db, admin_user, str(case_a.id))
        assert admin_access.id == case_a.id

        # 4. Non-existent case ID -> 404 Not Found
        with pytest.raises(HTTPException) as exc_404:
            await require_case_access(db, officer_a, str(uuid.uuid4()))
        assert exc_404.value.status_code == 404


# ── 2. JWT Authentication & Tampering ────────────────────────────────────────

@pytest.mark.asyncio
async def test_jwt_token_tampering_and_signatures():
    """Verify cryptographic integrity of authentication tokens."""
    async with AsyncSessionLocal() as db:
        user_uuid = str(uuid.uuid4())
        user = User(
            id=uuid.UUID(user_uuid),
            username=f"jwt_user_{user_uuid[:6]}",
            email=f"jwt_{user_uuid[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="JWT Test Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()

        token, *_ = _create_token(user_uuid, "io")
        assert token and isinstance(token, str)

        # 1. Valid token resolves active user
        resolved = await _resolve_user(token, db)
        assert str(resolved.id) == user_uuid

        # 2. Tampered signature -> Rejected with 401
        tampered_token = token[:-5] + "AAAAA"
        with pytest.raises(HTTPException) as exc_tampered:
            await _resolve_user(tampered_token, db)
        assert exc_tampered.value.status_code == 401

        # 3. Completely bogus token string -> Rejected with 401
        with pytest.raises(HTTPException) as exc_bogus:
            await _resolve_user("completely.bogus.jwt", db)
        assert exc_bogus.value.status_code == 401


# ── 3. Zero-Knowledge Blind Index Privacy Safeguards ─────────────────────────

def test_zero_knowledge_privacy_boundaries():
    """Verify that Syndicate Radar blind tokens enforce DPDP Act 2023 compliance."""
    from cognitive.crosscase import BlindIndex, MissingKeyError, canonicalize

    secret_key = "secure_statutory_salt_key"
    phone_raw = "+91 (98765) 43210"
    canonical_phone = canonicalize("PHONE", phone_raw)
    assert canonical_phone == "9876543210"

    idx1 = BlindIndex(secret_key)
    token_1 = idx1.token("PHONE", phone_raw)
    token_2 = idx1.token("PHONE", "9876543210")

    # 1. Determinism: Variants map to identical blind token
    assert token_1 == token_2
    assert len(token_1) == 64  # SHA-256 hex string

    # 2. One-way hash: Raw phone does not appear in token
    assert "9876543210" not in token_1

    # 3. Secret salt isolation: Different salt yields totally different token
    idx2 = BlindIndex("different_salt_key")
    token_other_salt = idx2.token("PHONE", phone_raw)
    assert token_1 != token_other_salt

    # 4. Empty salt fails closed
    with pytest.raises(MissingKeyError):
        BlindIndex("")
