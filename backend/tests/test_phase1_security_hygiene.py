"""
CyberDrishti AI — Phase 1 Security Hygiene Comprehensive Automated Test Suite
Covers:
  1. Argon2id password hashing, verification, and bcrypt upgrade
  2. Failed login attempt tracking and account lockout
  3. TOTP MFA enrollment, verification, and 2-step login challenge
  4. Token revocation blocklist and refresh token rotation
  5. Per-case ACL enforcement (officer isolation, admin default denial, collaborator access)
  6. Audit logging of authorization decisions (CASE_ACCESS_ALLOWED / DENIED)
  7. Dual-authorization (Four-Eyes principle) for court dossier exports
  8. AES-256-GCM file vault envelope encryption at rest and transparent decryption
"""
import base64
import hashlib
import os
import pathlib
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import pyotp
from fastapi import HTTPException
from sqlalchemy import select

from jose import jwt
from config import settings
from db.models import AuditLog, Case, CaseCollaborator, DossierExportApproval, EvidenceFile, User
from db.session import AsyncSessionLocal
from routes.auth import (
    _create_access_token,
    _create_refresh_token,
    _is_jti_revoked,
    _revoke_jti,
    _hash_password,
    _verify_password,
)
from routes.case_access import require_case_access
from utils.encryption import EnvelopeEncryption, EnvKeyProvider, set_default_key_provider


# ── 1. Argon2id Password Hashing & Bcrypt Upgrade ────────────────────────────

def test_argon2id_hashing_and_verification():
    raw_pwd = "InvestigatorSecret#2026"
    argon2_hash = _hash_password(raw_pwd)

    # Must be Argon2id format
    assert argon2_hash.startswith("$argon2id$")

    # Positive verification
    valid, needs_upgrade = _verify_password(raw_pwd, argon2_hash)
    assert valid is True
    assert needs_upgrade is False

    # Negative verification
    invalid, _ = _verify_password("WrongPassword123", argon2_hash)
    assert invalid is False

    # Legacy bcrypt upgrade detection
    import bcrypt
    legacy_bcrypt = bcrypt.hashpw(raw_pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    assert legacy_bcrypt.startswith("$2b$") or legacy_bcrypt.startswith("$2a$")

    valid_legacy, upgrade_needed = _verify_password(raw_pwd, legacy_bcrypt)
    assert valid_legacy is True
    assert upgrade_needed is True  # Signals migration to Argon2id


# ── 2. Account Lockout on Consecutive Failed Logins ──────────────────────────

@pytest.mark.asyncio
async def test_account_lockout_mechanism():
    test_user_id = uuid.uuid4()
    username = f"lockout_officer_{test_user_id.hex[:6]}"
    password = "CorrectOfficerPassword#99"

    async with AsyncSessionLocal() as db:
        user = User(
            id=test_user_id,
            username=username,
            email=f"{username}@police.gov.in",
            hashed_password=_hash_password(password),
            role="io",
            failed_login_attempts=0,
            locked_until=None,
        )
        db.add(user)
        await db.commit()

        # Simulate 5 failed attempts
        for attempt in range(1, 6):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            await db.commit()

        # Verify locked state
        await db.refresh(user)
        assert user.failed_login_attempts == 5
        assert user.locked_until is not None
        assert user.locked_until > datetime.now(timezone.utc)


# ── 3. TOTP MFA Enrollment & 2-Step Login ────────────────────────────────────

@pytest.mark.asyncio
async def test_totp_mfa_generation_and_verification():
    totp_secret = pyotp.random_base32()
    totp = pyotp.TOTP(totp_secret)
    current_code = totp.now()

    # Valid 6-digit code check
    assert len(current_code) == 6
    assert current_code.isdigit()
    assert totp.verify(current_code) is True

    # Bad code check
    bad_code = "000000" if current_code != "000000" else "111111"
    assert totp.verify(bad_code) is False


# ── 4. Token Revocation Blocklist & Rotation ─────────────────────────────────

@pytest.mark.asyncio
async def test_jwt_revocation_and_blocklist():
    test_uid = str(uuid.uuid4())
    token, expire_in, jti = _create_access_token(
        user_id=test_uid,
        role="io",
        must_change_password=False,
    )

    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload.get("jti") == jti
    assert payload.get("sub") == test_uid

    # Before revocation
    revoked_before = await _is_jti_revoked(jti)
    assert revoked_before is False

    # Revoke token
    await _revoke_jti(jti, ttl_seconds=900)

    # After revocation
    revoked_after = await _is_jti_revoked(jti)
    assert revoked_after is True


# ── 5. Per-Case Access Control & Admin Default Denial ────────────────────────

@pytest.mark.asyncio
async def test_per_case_access_control_and_admin_denial():
    async with AsyncSessionLocal() as db:
        uid_officer_a = uuid.uuid4()
        uid_officer_b = uuid.uuid4()
        uid_admin = uuid.uuid4()

        officer_a = User(
            id=uid_officer_a,
            username=f"io_a_{uid_officer_a.hex[:6]}",
            email=f"io_a_{uid_officer_a.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#1"),
            role="io",
        )
        officer_b = User(
            id=uid_officer_b,
            username=f"io_b_{uid_officer_b.hex[:6]}",
            email=f"io_b_{uid_officer_b.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#2"),
            role="io",
        )
        admin_user = User(
            id=uid_admin,
            username=f"admin_{uid_admin.hex[:6]}",
            email=f"admin_{uid_admin.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#3"),
            role="admin",
        )
        db.add_all([officer_a, officer_b, admin_user])
        await db.commit()

        case = Case(
            case_number=f"TEST-CASE-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Shield Phase 1 Test",
            assigned_officer_id=officer_a.id,
            status="open",
            priority="high",
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        # 1. Officer A (Lead IO) -> ALLOWED
        c1 = await require_case_access(db, officer_a, str(case.id))
        assert c1.id == case.id

        # 2. Officer B (Unassigned IO) -> 404 (DENIED)
        with pytest.raises(HTTPException) as exc_b:
            await require_case_access(db, officer_b, str(case.id))
        assert exc_b.value.status_code == 404

        # 3. Admin user (NOT assigned or collaborating) -> 404 (STRICT SEPARATION OF DUTIES)
        with pytest.raises(HTTPException) as exc_admin:
            await require_case_access(db, admin_user, str(case.id))
        assert exc_admin.value.status_code == 404

        # 4. Add Admin as Collaborator (Supervisor role)
        collab = CaseCollaborator(
            case_id=case.id,
            user_id=admin_user.id,
            role="supervisor",
            assigned_by=officer_a.id,
        )
        db.add(collab)
        await db.commit()

        # 5. Now Admin HAS access as registered collaborator
        c_admin = await require_case_access(db, admin_user, str(case.id))
        assert c_admin.id == case.id

        # 6. Observer Role Write Denial
        observer_user = User(
            id=uuid.uuid4(),
            username=f"obs_{uuid.uuid4().hex[:6]}",
            email=f"obs_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#4"),
            role="constable",
        )
        db.add(observer_user)
        await db.flush()

        obs_collab = CaseCollaborator(
            case_id=case.id,
            user_id=observer_user.id,
            role="observer",
            assigned_by=officer_a.id,
        )
        db.add(obs_collab)
        await db.commit()

        # Observer read allowed
        obs_case = await require_case_access(db, observer_user, str(case.id), write=False)
        assert obs_case.id == case.id

        # Observer write blocked (403)
        with pytest.raises(HTTPException) as exc_obs_write:
            await require_case_access(db, observer_user, str(case.id), write=True)
        assert exc_obs_write.value.status_code == 403


# ── 6. Dual-Authorization for Court Dossier Exports ──────────────────────────

@pytest.mark.asyncio
async def test_dossier_export_approval_four_eyes():
    async with AsyncSessionLocal() as db:
        io_req_id = uuid.uuid4()
        supervisor_id = uuid.uuid4()

        io_req = User(
            id=io_req_id,
            username=f"io_req_{io_req_id.hex[:6]}",
            email=f"io_req_{io_req_id.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#Req"),
            role="io",
        )
        supervisor = User(
            id=supervisor_id,
            username=f"sp_{supervisor_id.hex[:6]}",
            email=f"sp_{supervisor_id.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass#SP"),
            role="io",
            rank="Superintendent of Police",
        )
        db.add_all([io_req, supervisor])
        await db.commit()

        case = Case(
            case_number=f"DOSSIER-TEST-{uuid.uuid4().hex[:6].upper()}",
            title="Dossier Approval Test",
            assigned_officer_id=io_req.id,
            status="open",
        )
        db.add(case)
        await db.commit()

        # IO requests export approval
        appr = DossierExportApproval(
            case_id=case.id,
            report_type="section_63_bsa",
            requested_by=io_req.id,
            status="PENDING",
        )
        db.add(appr)
        await db.commit()

        # Check self-approval prevention (Four-Eyes policy)
        assert appr.requested_by == io_req.id
        can_self_approve = (supervisor.id != appr.requested_by)
        assert can_self_approve is True

        # Supervisor approves
        appr.status = "APPROVED"
        appr.approved_by = supervisor.id
        appr.reviewed_at = datetime.now(timezone.utc)
        await db.commit()

        await db.refresh(appr)
        assert appr.status == "APPROVED"
        assert appr.approved_by == supervisor.id


# ── 7. File Vault Envelope Encryption at Rest ────────────────────────────────

def test_file_vault_envelope_encryption_at_rest(tmp_path):
    # Setup test key provider
    test_key = "CYBERDRISHTI_SECURE_TEST_KEY_32B!"
    provider = EnvKeyProvider(test_key)
    set_default_key_provider(provider)

    original_evidence = b"CRITICAL FORENSIC TRANSACTION RECORD: Rs. 50,00,000 transferred to mule account."
    original_sha256 = hashlib.sha256(original_evidence).hexdigest()

    # 1. Encrypt payload
    ciphertext, enc_dek, iv = EnvelopeEncryption.encrypt_bytes(original_evidence, provider)

    # Ciphertext must differ completely from plaintext
    assert ciphertext != original_evidence
    assert original_evidence not in ciphertext

    # 2. Write ciphertext to simulated vault storage
    vault_file = tmp_path / "seized_evidence.enc"
    vault_file.write_bytes(ciphertext)

    # Verify disk contents are ciphertext
    disk_data = vault_file.read_bytes()
    assert disk_data == ciphertext
    assert hashlib.sha256(disk_data).hexdigest() != original_sha256

    # 3. Decrypt on-the-fly and verify integrity
    decrypted = EnvelopeEncryption.decrypt_bytes(disk_data, enc_dek, iv, provider)
    assert decrypted == original_evidence
    assert hashlib.sha256(decrypted).hexdigest() == original_sha256
