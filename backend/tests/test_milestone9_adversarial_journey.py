from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Adversarial Security Journey Acceptance Test

Executes the complete end-to-end security progression:
1. Investigator logs in with registered device context
2. Opens authorized case workspace -> 200 OK
3. Attempts unauthorized cross-case access -> non-leaking 404
4. Denial audited in tamper-evident ledger (CASE_ACCESS_DENIED)
5. Accesses original evidence with Section 63 BSA reason + device trust
6. Access audited in ledger (EVIDENCE_ACCESS_GRANTED)
7. Submits command via Server-Authoritative Command Gateway
8. Case state version increments (1 -> 2)
9. Tamper-evident audit chain consecutively updated
10. Offline device sync attempts identical mutation -> Server rechecks authorization and handles idempotency
11. Supervisor 1 generates formal dossier snapshot and submits for review
12. Supervisor 1 self-approval attempt blocked by Four-Eyes Policy (403 Forbidden)
13. Supervisor 2 approves formal dossier -> 200 OK
14. Certified dossier export audited and delivered
15. AuditVerifier confirms entire cryptographic ledger is unbroken
"""

import hashlib
import pathlib
import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    AuditLog,
    Case,
    CaseCollaborator,
    Entity,
    EvidenceFile,
    IdentityCandidate,
    ReportSnapshot,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token
from security.audit_verifier import AuditVerifier


@pytest.mark.asyncio
async def test_milestone9_complete_adversarial_journey():
    unique_run = uuid.uuid4().hex[:8]
    upload_dir = pathlib.Path(__file__).parent.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        # ── 1. Seed Actors ───────────────────────────────────────────────────
        # Investigator A (Case Alpha Lead)
        inv_a = User(
            id=uuid.uuid4(),
            username=f"io_alpha_{unique_run}",
            email=f"io_alpha_{unique_run}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Inspector",
            is_active=True,
        )
        # Investigator B (Case Beta Lead)
        inv_b = User(
            id=uuid.uuid4(),
            username=f"io_beta_{unique_run}",
            email=f"io_beta_{unique_run}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Sub-Inspector",
            is_active=True,
        )
        # Supervisor 1 (Manager)
        sup_1 = User(
            id=uuid.uuid4(),
            username=f"dsp_one_{unique_run}",
            email=f"dsp_one_{unique_run}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="DSP",
            is_active=True,
        )
        # Supervisor 2 (Manager - distinct for Four-Eyes)
        sup_2 = User(
            id=uuid.uuid4(),
            username=f"sp_two_{unique_run}",
            email=f"sp_two_{unique_run}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="Superintendent",
            is_active=True,
        )
        db.add_all([inv_a, inv_b, sup_1, sup_2])
        await db.flush()

        # ── 2. Seed Cases ────────────────────────────────────────────────────
        case_alpha = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-ALPHA-{unique_run.upper()}",
            title=f"Operation Cyber Citadel {unique_run}",
            assigned_officer_id=inv_a.id,
            status="open",
            state_version=1,
        )
        case_beta = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-BETA-{unique_run.upper()}",
            title=f"Classified State Operation {unique_run}",
            assigned_officer_id=inv_b.id,
            status="open",
            state_version=1,
        )
        db.add_all([case_alpha, case_beta])
        await db.flush()

        # Add Supervisors to Case Alpha
        db.add_all([
            CaseCollaborator(case_id=case_alpha.id, user_id=sup_1.id, role="supervisor"),
            CaseCollaborator(case_id=case_alpha.id, user_id=sup_2.id, role="supervisor"),
        ])

        # ── 3. Seed Original Seized Evidence in Case Alpha ───────────────────
        ev_content = b"CRITICAL FORENSIC BITSTREAM: SEIZED BANKING API ACCESS LOGS"
        ev_hash = hashlib.sha256(ev_content).hexdigest()
        file_path = upload_dir / f"ev_journey_{unique_run}_{ev_hash[:8]}.bin"
        with open(file_path, "wb") as f:
            f.write(ev_content)

        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_alpha.id,
            filename=f"seized_logs_{unique_run}.bin",
            original_name=f"seized_logs_{unique_run}.bin",
            file_type="binary",
            file_size_bytes=len(ev_content),
            sha256_hash=ev_hash,
            storage_path=str(file_path),
            upload_status="processed",
            integrity_status="verified",
            original_immutable=True,
            version_status="original",
            uploaded_by=inv_a.id,
        )
        db.add(ev_file)

        # ── 4. Seed Identity Candidate for Command Gateway ──────────────────
        ent = Entity(
            id=uuid.uuid4(),
            case_id=case_alpha.id,
            canonical_value="Vikramaditya Mule",
            entity_type="PERSON",
        )
        db.add(ent)
        await db.flush()

        candidate = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case_alpha.id,
            canonical_entity_id=ent.id,
            candidate_value="Vikramaditya Sharma",
            candidate_type="PERSON",
            resolution_status="UNRESOLVED",
        )
        db.add(candidate)
        await db.commit()

        # ── 5. Issue Device-Bound Session Tokens ─────────────────────────────
        device_alpha = "device-terminal-alpha-01"
        token_a, _, _ = _create_access_token(
            user_id=str(inv_a.id),
            role=inv_a.role,
            device_id=device_alpha,
            authentication_level="standard",
        )
        headers_a = {
            "Authorization": f"Bearer {token_a}",
            "X-Device-ID": device_alpha,
        }

        token_sup1, _, _ = _create_access_token(
            user_id=str(sup_1.id),
            role=sup_1.role,
            device_id="supervisor-workstation-01",
        )
        headers_sup1 = {"Authorization": f"Bearer {token_sup1}"}

        token_sup2, _, _ = _create_access_token(
            user_id=str(sup_2.id),
            role=sup_2.role,
            device_id="supervisor-workstation-02",
        )
        headers_sup2 = {"Authorization": f"Bearer {token_sup2}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ─────────────────────────────────────────────────────────────────────
        # STEP 1 & 2: Investigator A logs in and opens authorized Case Alpha
        # ─────────────────────────────────────────────────────────────────────
        resp_workspace = await client.get(
            f"/api/v1/cases/{case_alpha.id}/workspace",
            headers=headers_a,
        )
        assert resp_workspace.status_code == 200
        workspace_data = resp_workspace.json()
        assert workspace_data["case_id"] == str(case_alpha.id)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3 & 4: Attempts unauthorized access to Case Beta -> 404 (audited)
        # ─────────────────────────────────────────────────────────────────────
        resp_unauth = await client.get(
            f"/api/v1/cases/{case_beta.id}/workspace",
            headers=headers_a,
        )
        assert resp_unauth.status_code == 404

        # Verify CASE_ACCESS_DENIED entry in audit trail
        async with AsyncSessionLocal() as db:
            audit_denied = (
                await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.action == "CASE_ACCESS_DENIED",
                        AuditLog.resource_id == str(case_beta.id),
                    )
                    .order_by(AuditLog.id.desc())
                )
            ).scalars().first()
            assert audit_denied is not None
            assert audit_denied.details_json.get("reason") == "unassigned_user"

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5 & 6: Access original evidence with Section 63 BSA reason + device
        # ─────────────────────────────────────────────────────────────────────
        # Unjustified access attempt -> 403
        resp_no_reason = await client.get(
            f"/api/v1/evidence/{case_alpha.id}/files/{ev_file.id}/download",
            headers=headers_a,
        )
        assert resp_no_reason.status_code == 403
        assert "justification" in resp_no_reason.json()["detail"].lower()

        # Justified access with registered device -> 200 OK
        resp_download = await client.get(
            f"/api/v1/evidence/{case_alpha.id}/files/{ev_file.id}/download?reason=Court+Exemption+Order+Section+63",
            headers=headers_a,
        )
        assert resp_download.status_code == 200
        assert resp_download.content == ev_content
        assert resp_download.headers.get("x-bsa-section") == "63"
        assert resp_download.headers.get("x-evidence-sha256") == ev_hash

        # Verify EVIDENCE_ACCESS_GRANTED in audit trail
        async with AsyncSessionLocal() as db:
            ev_audit = (
                await db.execute(
                    select(AuditLog)
                    .where(
                        AuditLog.action == "EVIDENCE_ACCESS_GRANTED",
                        AuditLog.resource_id == str(ev_file.id),
                    )
                    .order_by(AuditLog.id.desc())
                )
            ).scalars().first()
            assert ev_audit is not None
            assert ev_audit.details_json["device_id"] == device_alpha
            assert "Section 63" in ev_audit.details_json["reason"]

        # ─────────────────────────────────────────────────────────────────────
        # STEP 7, 8, 9: Review identity candidate via Command Gateway
        # ─────────────────────────────────────────────────────────────────────
        resp_cmd = await client.post(
            f"/api/v1/cases/{case_alpha.id}/commands",
            headers=headers_a,
            json={
                "command": "RESOLVE_IDENTITY_CANDIDATE",
                "payload": {
                    "candidate_id": str(candidate.id),
                    "decision": "CONFIRMED_SAME",
                    "reason": "Biometric match verified via state records",
                },
                "reason": "Forensic biometric validation",
            },
        )
        assert resp_cmd.status_code == 200
        cmd_result = resp_cmd.json()
        assert cmd_result["success"] is True
        assert cmd_result["new_state_version"] >= 2

        # ─────────────────────────────────────────────────────────────────────
        # STEP 10: Offline device sync re-checks authorization and idempotency
        # ─────────────────────────────────────────────────────────────────────
        offline_mut_id = f"mut_journey_{unique_run}"
        resp_sync = await client.post(
            f"/api/v1/cases/{case_alpha.id}/sync",
            headers=headers_a,
            json={
                "device_id": device_alpha,
                "client_state_version": 1,
                "mutations": [
                    {
                        "mutation_id": offline_mut_id,
                        "device_id": device_alpha,
                        "actor_id": str(inv_a.id),
                        "case_id": str(case_alpha.id),
                        "command_type": "RESOLVE_IDENTITY_CANDIDATE",
                        "payload": {
                            "candidate_id": str(candidate.id),
                            "decision": "CONFIRMED_SAME",
                            "reason": "Offline replay verification",
                        },
                        "base_state_version": 1,
                        "client_created_at": datetime.now(timezone.utc).isoformat(),
                        "local_sequence": 1,
                    }
                ],
            },
        )
        assert resp_sync.status_code == 200
        sync_data = resp_sync.json()
        # Candidate already resolved -> mutation accepted or rebased safely without crashing
        assert len(sync_data["rejected"]) == 0 or offline_mut_id in sync_data["rebased"] or offline_mut_id in sync_data["accepted"]

        # ─────────────────────────────────────────────────────────────────────
        # STEP 11, 12: Supervisor 1 generates dossier; Four-Eyes prevents self-approval
        # ─────────────────────────────────────────────────────────────────────
        resp_gen = await client.post(
            f"/api/v1/cases/{case_alpha.id}/reports/generate",
            headers=headers_sup1,
            json={
                "report_type": "formal_dossier",
                "title": "Comprehensive Cyber Investigation Dossier",
                "summary": "Forensic evidence package with verified entity relationships",
            },
        )
        assert resp_gen.status_code == 201
        snapshot_id = resp_gen.json()["metadata"]["report_id"]

        # Submit for review
        resp_sub = await client.post(
            f"/api/v1/cases/{case_alpha.id}/reports/snapshots/{snapshot_id}/submit-review",
            headers=headers_sup1,
        )
        assert resp_sub.status_code == 200

        # Supervisor 1 tries to approve own report -> MUST BE REJECTED (Four-Eyes violation)
        resp_self = await client.post(
            f"/api/v1/cases/{case_alpha.id}/reports/snapshots/{snapshot_id}/review",
            headers=headers_sup1,
            json={"action": "APPROVE"},
        )
        assert resp_self.status_code == 403
        assert "Four-Eyes" in resp_self.json()["detail"]

        # ─────────────────────────────────────────────────────────────────────
        # STEP 13 & 14: Supervisor 2 approves; Export certified dossier
        # ─────────────────────────────────────────────────────────────────────
        resp_appr = await client.post(
            f"/api/v1/cases/{case_alpha.id}/reports/snapshots/{snapshot_id}/review",
            headers=headers_sup2,
            json={"action": "APPROVE"},
        )
        assert resp_appr.status_code == 200
        assert resp_appr.json()["new_status"] == "APPROVED"

        resp_export = await client.post(
            f"/api/v1/cases/{case_alpha.id}/reports/snapshots/{snapshot_id}/export?export_format=json",
            headers=headers_sup2,
        )
        assert resp_export.status_code == 200
        export_data = resp_export.json()
        assert export_data["metadata"]["status"] == "EXPORTED"
        assert export_data["metadata"]["exported_by"] == str(sup_2.id)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 15: Cryptographic Audit Trail Verification
        # ─────────────────────────────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            ledger_audit = await AuditVerifier.verify_ledger(db)
            assert ledger_audit["intact"] is True
            assert ledger_audit["status"] == "VERIFIED"
            assert ledger_audit["global_entry_count"] > 0
