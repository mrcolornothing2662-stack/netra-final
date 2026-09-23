from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Final Adversarial Security Attack Suite (Milestone 10)
Verifies 14 deliberate adversarial security attacks:
  1. Tampered JWT signature rejection (HTTP 401).
  2. Revoked session token reuse rejection (HTTP 401).
  3. Expired token rejection (HTTP 401).
  4. Privilege escalation: Investigator role cannot execute CASE_CLOSE (HTTP 403).
  5. Privilege escalation: Investigator role cannot approve formal dossier reports (HTTP 403).
  6. Four-Eyes violation: Supervisor cannot approve their own report snapshot (HTTP 403).
  7. Cross-case data boundary: Officer on Case Alpha cannot read Case Beta (non-leaking HTTP 404).
  8. Cross-case data boundary: Officer on Case Alpha cannot mutate Case Beta (non-leaking HTTP 404).
  9. Cross-case entity relationship forgery: Cannot link entities across distinct cases (HTTP 400/404).
 10. Insufficient operational justification (< 5 chars) denies evidence download & audits EVIDENCE_ACCESS_DENIED.
 11. Cryptographic audit chain tamper detection: modifying an audit row breaks the hash chain (BROKEN_HASH_CHAIN).
 12. Stale concurrency conflict: concurrent conflicting relationship review creates an explicit conflict.
 13. Duplicate sync packet replay attack: identical mutation ID processed idempotently without double-mutation.
 14. Unapproved formal dossier export rejection: unapproved draft cannot be exported (HTTP 403).
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import select

from config import settings
from db.models import (
    AuditLog,
    Case,
    CaseCollaborator,
    Entity,
    EvidenceFile,
    InvestigationState,
    Relationship,
    ReportSnapshot,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token
from security.audit_verifier import AuditVerifier


@pytest.fixture
def run_suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest.mark.asyncio
async def test_attack_1_tampered_jwt_signature(run_suffix: str):
    """Attack 1: Tampered JWT signature is rejected with HTTP 401."""
    tok, _, _ = _create_access_token(
        user_id=str(uuid.uuid4()),
        role="INVESTIGATOR",
        session_id=uuid.uuid4().hex,
        device_id="dev-tamper-1",
    )
    tampered_tok = tok[:-4] + ("AAAA" if tok[-4:] != "AAAA" else "BBBB")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tampered_tok}"},
        )
        assert resp.status_code == 401, f"Expected 401 Unauthorized for tampered token, got {resp.status_code}"


@pytest.mark.asyncio
async def test_attack_2_revoked_session_reuse(run_suffix: str):
    """Attack 2: Revoked session token reuse is rejected with HTTP 401."""
    sess_id = uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"rev_user_{run_suffix}",
            email=f"rev_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        sess = UserSession(
            id=sess_id,
            user_id=user.id,
            device_id="dev-revoked",
            ip_address="127.0.0.1",
            user_agent="AdversarialTest/1.0",
            authentication_level="standard",
            revoked=True,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        db.add(sess)
        await db.commit()
        user_id = str(user.id)

    tok, _, _ = _create_access_token(
        user_id=user_id,
        role="INVESTIGATOR",
        session_id=sess_id,
        device_id="dev-revoked",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_attack_3_expired_jwt_token(run_suffix: str):
    """Attack 3: Expired access token is rejected with HTTP 401."""
    expired_payload = {
        "sub": str(uuid.uuid4()),
        "role": "INVESTIGATOR",
        "type": "access",
        "jti": uuid.uuid4().hex,
        "sid": uuid.uuid4().hex,
        "did": "dev-expired",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_tok = jwt.encode(expired_payload, settings.secret_key, algorithm=settings.algorithm)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_tok}"},
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_attack_4_analyst_cannot_close_case(run_suffix: str):
    """Attack 4: Investigator role cannot execute CASE_CLOSE command (HTTP 403)."""
    async with AsyncSessionLocal() as db:
        io_user = User(
            id=uuid.uuid4(),
            username=f"io_close_{run_suffix}",
            email=f"io_close_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Sub-Inspector",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ATTACK-4-{run_suffix.upper()}",
            title="Privilege Escalation Test Case",
            status="open",
            assigned_officer_id=io_user.id,
            state_version=1,
        )
        db.add_all([io_user, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=io_user.id, role="lead"))
        await db.commit()
        io_id = str(io_user.id)
        case_id = str(case.id)

    tok, _, _ = _create_access_token(user_id=io_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-io")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_id}/commands",
            json={
                "command": "CLOSE_CASE",
                "payload": {"reason": "Investigator trying to close case unilaterally"},
                "base_case_version": 1,
            },
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-io"},
        )
        assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_attack_5_analyst_cannot_approve_dossier(run_suffix: str):
    """Attack 5: Investigator role cannot approve formal dossier report snapshots (HTTP 403)."""
    async with AsyncSessionLocal() as db:
        inv = User(
            id=uuid.uuid4(),
            username=f"inv_app_{run_suffix}",
            email=f"inv_app_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        sup = User(
            id=uuid.uuid4(),
            username=f"sup_creator_{run_suffix}",
            email=f"sup_creator_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="DSP",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ATTACK-5-{run_suffix.upper()}",
            title="Dossier Approval RBAC Test Case",
            status="open",
            assigned_officer_id=sup.id,
            state_version=1,
        )
        db.add_all([inv, sup, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=inv.id, role="lead"))
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=sup.id, role="lead"))
        await db.flush()

        snap = ReportSnapshot(
            id=uuid.uuid4(),
            case_id=case.id,
            report_type="formal_dossier",
            case_state_version=1,
            title="Dossier Investigation Snapshot",
            generated_by=sup.id,
            status="REVIEW",
            content_hash="f" * 64,
            payload={"metadata": {}, "sections": []},
        )
        db.add(snap)
        await db.commit()
        inv_id = str(inv.id)
        case_id = str(case.id)
        snap_id = str(snap.id)

    tok, _, _ = _create_access_token(user_id=inv_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-inv")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_id}/reports/snapshots/{snap_id}/review",
            json={"action": "APPROVE", "comments": "Investigator unauthorized approval"},
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-inv"},
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_attack_6_four_eyes_self_approval_blocked(run_suffix: str):
    """Attack 6: Supervisor cannot approve their own report snapshot (HTTP 403)."""
    async with AsyncSessionLocal() as db:
        sup = User(
            id=uuid.uuid4(),
            username=f"sup_self_{run_suffix}",
            email=f"sup_self_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="DSP",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ATTACK-6-{run_suffix.upper()}",
            title="Four-Eyes Self Approval Test Case",
            status="open",
            assigned_officer_id=sup.id,
            state_version=1,
        )
        db.add_all([sup, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=sup.id, role="lead"))
        await db.flush()

        snap = ReportSnapshot(
            id=uuid.uuid4(),
            case_id=case.id,
            report_type="formal_dossier",
            case_state_version=1,
            title="Four-Eyes Formal Dossier",
            generated_by=sup.id,  # Generated by sup
            status="REVIEW",
            content_hash="f" * 64,
            payload={"metadata": {}, "sections": []},
        )
        db.add(snap)
        await db.commit()
        sup_id = str(sup.id)
        case_id = str(case.id)
        snap_id = str(snap.id)

    tok, _, _ = _create_access_token(user_id=sup_id, role="MANAGER", session_id=uuid.uuid4().hex, device_id="dev-dsp")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_id}/reports/snapshots/{snap_id}/review",
            json={"action": "APPROVE", "comments": "Self-approval attempt"},
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-dsp"},
        )
        assert resp.status_code == 403
        assert "Four-Eyes Policy Violation" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_attack_7_cross_case_isolation_query(run_suffix: str):
    """Attack 7: Officer on Case Alpha cannot read Case Beta (returns non-leaking HTTP 404)."""
    async with AsyncSessionLocal() as db:
        io_alpha = User(
            id=uuid.uuid4(),
            username=f"io_a_{run_suffix}",
            email=f"io_a_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        io_beta = User(
            id=uuid.uuid4(),
            username=f"io_b_{run_suffix}",
            email=f"io_b_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case_alpha = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ALPHA-{run_suffix.upper()}",
            title="Alpha Case",
            status="open",
            assigned_officer_id=io_alpha.id,
            state_version=1,
        )
        case_beta = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-BETA-{run_suffix.upper()}",
            title="Beta Sensitive Case",
            status="open",
            assigned_officer_id=io_beta.id,
            state_version=1,
        )
        db.add_all([io_alpha, io_beta, case_alpha, case_beta])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case_alpha.id, user_id=io_alpha.id, role="lead"))
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case_beta.id, user_id=io_beta.id, role="lead"))
        await db.commit()
        io_a_id = str(io_alpha.id)
        beta_id = str(case_beta.id)

    tok, _, _ = _create_access_token(user_id=io_a_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-a")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/cases/{beta_id}/command-center",
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-a"},
        )
        assert resp.status_code == 404, f"Expected non-leaking 404, got {resp.status_code}"


@pytest.mark.asyncio
async def test_attack_8_cross_case_isolation_mutation(run_suffix: str):
    """Attack 8: Officer on Case Alpha cannot execute mutations on Case Beta (HTTP 404)."""
    async with AsyncSessionLocal() as db:
        io_alpha = User(
            id=uuid.uuid4(),
            username=f"io_a_mut_{run_suffix}",
            email=f"io_a_mut_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        io_beta = User(
            id=uuid.uuid4(),
            username=f"io_b_mut_{run_suffix}",
            email=f"io_b_mut_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case_beta = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-BETA-MUT-{run_suffix.upper()}",
            title="Beta Sensitive Case",
            status="open",
            assigned_officer_id=io_beta.id,
            state_version=1,
        )
        db.add_all([io_alpha, io_beta, case_beta])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case_beta.id, user_id=io_beta.id, role="lead"))
        await db.commit()
        io_a_id = str(io_alpha.id)
        beta_id = str(case_beta.id)

    tok, _, _ = _create_access_token(user_id=io_a_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-a")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{beta_id}/commands",
            json={
                "command": "CREATE_HYPOTHESIS",
                "payload": {"title": "Hostile Injected Hypothesis"},
                "base_case_version": 1,
            },
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-a"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_attack_9_cross_case_relationship_forgery(run_suffix: str):
    """Attack 9: Cannot link an entity in Case Alpha to an entity in Case Beta."""
    async with AsyncSessionLocal() as db:
        io_alpha = User(
            id=uuid.uuid4(),
            username=f"io_rel_{run_suffix}",
            email=f"io_rel_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case_a = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-A-REL-{run_suffix.upper()}",
            title="Case A",
            status="open",
            assigned_officer_id=io_alpha.id,
            state_version=1,
        )
        case_b = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-B-REL-{run_suffix.upper()}",
            title="Case B",
            status="open",
            assigned_officer_id=io_alpha.id,
            state_version=1,
        )
        db.add_all([io_alpha, case_a, case_b])
        await db.flush()

        ent_a = Entity(id=uuid.uuid4(), case_id=case_a.id, canonical_value=f"+9198111{run_suffix[:5]}", entity_type="phone")
        ent_b = Entity(id=uuid.uuid4(), case_id=case_b.id, canonical_value=f"+9198222{run_suffix[:5]}", entity_type="phone")
        db.add_all([ent_a, ent_b])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case_a.id, user_id=io_alpha.id, role="lead"))
        await db.commit()
        io_a_id = str(io_alpha.id)
        case_a_id = str(case_a.id)
        ent_a_id = str(ent_a.id)
        ent_b_id = str(ent_b.id)

    tok, _, _ = _create_access_token(user_id=io_a_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-a")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_a_id}/commands",
            json={
                "command": "ADD_INVESTIGATOR_RELATIONSHIP",
                "payload": {
                    "source_entity_id": ent_a_id,
                    "target_entity_id": ent_b_id,
                    "relationship_type": RT.ASSOCIATED_WITH,
                },
                "base_case_version": 1,
            },
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-a"},
        )
        assert resp.status_code in (400, 404), f"Expected 400/404 for cross-case entity link, got {resp.status_code}"


@pytest.mark.asyncio
async def test_attack_10_evidence_access_denied_insufficient_justification(run_suffix: str):
    """Attack 10: Evidence download without >= 5 chars justification is denied and audited."""
    async with AsyncSessionLocal() as db:
        io = User(
            id=uuid.uuid4(),
            username=f"io_ev_{run_suffix}",
            email=f"io_ev_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-EV-DENY-{run_suffix.upper()}",
            title="Evidence Access Justification Test",
            status="open",
            assigned_officer_id=io.id,
            state_version=1,
        )
        db.add_all([io, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=io.id, role="lead"))
        await db.flush()

        ev = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"confidential_{run_suffix}.csv",
            original_name=f"confidential_{run_suffix}.csv",
            file_type="telecom_cdr",
            sha256_hash="e" * 64,
            storage_path=f"/uploads/conf_{run_suffix}.csv",
            file_size_bytes=1024,
        )
        db.add(ev)
        await db.commit()
        io_id = str(io.id)
        case_id = str(case.id)
        ev_id = str(ev.id)

    tok, _, _ = _create_access_token(user_id=io_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-io")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/evidence/{case_id}/files/{ev_id}/download?reason=why",
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-io"},
        )
        assert resp.status_code in (400, 403), f"Expected 400 or 403 for trivial reason, got {resp.status_code}"

    # Verify that EVIDENCE_ACCESS_DENIED was logged in the tamper-evident audit ledger
    async with AsyncSessionLocal() as db:
        audit_res = await db.execute(
            select(AuditLog).where(
                AuditLog.action == "EVIDENCE_ACCESS_DENIED",
                AuditLog.resource_id == ev_id,
            )
        )
        entry = audit_res.scalar_one_or_none()
        assert entry is not None, "EVIDENCE_ACCESS_DENIED must be audited in the ledger"


@pytest.mark.asyncio
async def test_attack_11_audit_log_tamper_detection(run_suffix: str):
    """Attack 11: Modifying an audit log entry in the database triggers BROKEN_HASH_CHAIN."""
    async with AsyncSessionLocal() as db:
        res_before = await AuditVerifier.verify_ledger(db)
        assert res_before["intact"] is True, f"Audit ledger should be intact initially: {res_before}"

        stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(1)
        last_entry = (await db.execute(stmt)).scalar_one_or_none()
        assert last_entry is not None

        original_action = last_entry.action
        last_entry.action = "TAMPERED_MALICIOUS_ACTION"
        await db.commit()

        res_tampered = await AuditVerifier.verify_ledger(db)
        assert res_tampered["intact"] is False, "Tampered audit ledger must fail verification"
        assert res_tampered["status"] == "BROKEN_HASH_CHAIN"

        last_entry.action = original_action
        await db.commit()

        res_restored = await AuditVerifier.verify_ledger(db)
        assert res_restored["intact"] is True


@pytest.mark.asyncio
async def test_attack_12_stale_concurrency_conflict(run_suffix: str):
    """Attack 12: Stale concurrent conflicting decision creates an explicit conflict."""
    async with AsyncSessionLocal() as db:
        io = User(
            id=uuid.uuid4(),
            username=f"io_conf_{run_suffix}",
            email=f"io_conf_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-CONF-{run_suffix.upper()}",
            title="Conflict Concurrency Test",
            status="open",
            assigned_officer_id=io.id,
            state_version=2,
        )
        db.add_all([io, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=io.id, role="lead"))
        await db.flush()

        ev = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"ev_conf_{run_suffix}.csv",
            original_name=f"ev_conf_{run_suffix}.csv",
            file_type="telecom_cdr",
            sha256_hash="c" * 64,
            storage_path=f"/uploads/conf_{run_suffix}.csv",
            file_size_bytes=1024,
        )
        ent_a = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value=f"+9198111{run_suffix[:5]}", entity_type="phone")
        ent_b = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value=f"+9198222{run_suffix[:5]}", entity_type="phone")
        db.add_all([ev, ent_a, ent_b])
        await db.flush()

        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=ent_a.id,
            target_entity_id=ent_b.id,
            relationship_type=RT.COMMUNICATED_WITH,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_ACCEPTED,
            is_canonical=True,
            confidence=0.9,
            evidence_refs=[str(ev.id)],
        )
        db.add(rel)
        db.add(InvestigationState(id=uuid.uuid4(), case_id=case.id, version=1, created_by=io.id))
        db.add(InvestigationState(id=uuid.uuid4(), case_id=case.id, version=2, created_by=io.id))
        await db.commit()
        io_id = str(io.id)
        case_id = str(case.id)
        rel_id = str(rel.id)

    tok, _, _ = _create_access_token(user_id=io_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-field")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_id}/sync",
            json={
                "device_id": "dev-field",
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": str(uuid.uuid4()),
                        "device_id": "dev-field",
                        "actor_id": io_id,
                        "case_id": case_id,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "command_type": "REJECT_RELATIONSHIP",
                        "payload": {"relationship_id": rel_id},
                        "base_state_version": 1,
                    }
                ],
            },
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-field"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["conflict_type"] == "RELATIONSHIP_REVIEW_CONFLICT"


@pytest.mark.asyncio
async def test_attack_13_duplicate_sync_packet_replay(run_suffix: str):
    """Attack 13: Duplicate sync packet replay is handled idempotently without double-incrementing version."""
    async with AsyncSessionLocal() as db:
        io = User(
            id=uuid.uuid4(),
            username=f"io_replay_{run_suffix}",
            email=f"io_replay_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-REPLAY-{run_suffix.upper()}",
            title="Packet Replay Test",
            status="open",
            assigned_officer_id=io.id,
            state_version=1,
        )
        db.add_all([io, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=io.id, role="lead"))
        db.add(InvestigationState(id=uuid.uuid4(), case_id=case.id, version=1, created_by=io.id))
        await db.commit()
        io_id = str(io.id)
        case_id = str(case.id)

    tok, _, _ = _create_access_token(user_id=io_id, role="INVESTIGATOR", session_id=uuid.uuid4().hex, device_id="dev-rep")

    mutation_id = str(uuid.uuid4())
    sync_packet = {
        "device_id": "dev-rep",
        "client_state_version": 1,
        "mutations": [
            {
                "mutation_id": mutation_id,
                "device_id": "dev-rep",
                "actor_id": io_id,
                "case_id": case_id,
                "client_created_at": datetime.now(timezone.utc).isoformat(),
                "command_type": "CREATE_HYPOTHESIS",
                "payload": {"title": "Idempotent Field Hypothesis"},
                "base_state_version": 1,
            }
        ],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(f"/api/v1/cases/{case_id}/sync", json=sync_packet, headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-rep"})
        assert r1.status_code == 200
        d1 = r1.json()
        assert len(d1["accepted"]) == 1
        v1 = d1["server_state_version"]

        r2 = await client.post(f"/api/v1/cases/{case_id}/sync", json=sync_packet, headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-rep"})
        assert r2.status_code == 200
        d2 = r2.json()
        assert len(d2["accepted"]) == 1
        assert d2["server_state_version"] == v1


@pytest.mark.asyncio
async def test_attack_14_unapproved_formal_dossier_export_blocked(run_suffix: str):
    """Attack 14: Unapproved draft formal dossier export is rejected with HTTP 403."""
    async with AsyncSessionLocal() as db:
        sup = User(
            id=uuid.uuid4(),
            username=f"sup_exp_{run_suffix}",
            email=f"sup_exp_{run_suffix}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="DSP",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-EXP-UNAPP-{run_suffix.upper()}",
            title="Unapproved Export Test Case",
            status="open",
            assigned_officer_id=sup.id,
            state_version=1,
        )
        db.add_all([sup, case])
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=sup.id, role="lead"))
        await db.flush()

        snap = ReportSnapshot(
            id=uuid.uuid4(),
            case_id=case.id,
            report_type="formal_dossier",
            case_state_version=1,
            title="Draft Formal Dossier",
            generated_by=sup.id,
            status="DRAFT",
            content_hash="f" * 64,
            payload={"metadata": {}, "sections": []},
        )
        db.add(snap)
        await db.commit()
        sup_id = str(sup.id)
        case_id = str(case.id)
        snap_id = str(snap.id)

    tok, _, _ = _create_access_token(user_id=sup_id, role="MANAGER", session_id=uuid.uuid4().hex, device_id="dev-dsp")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/cases/{case_id}/reports/snapshots/{snap_id}/export?format=json",
            headers={"Authorization": f"Bearer {tok}", "X-Device-ID": "dev-dsp"},
        )
        assert resp.status_code == 403
        assert "Dual-authorization required" in resp.json()["detail"]
