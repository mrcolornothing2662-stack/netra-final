from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 4: Stricter Evidence Access Control
Verifies:
- Case access alone does not grant raw original evidence access
- Missing or insufficient operational justification returns 403
- Legitimate request produces verified download + Section 63 BSA audit record
"""

import hashlib
import os
import pathlib
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from config import settings
from db.models import AuditLog, Case, EvidenceFile, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_evidence_stricter_access_and_audit():
    upload_dir = pathlib.Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        officer = User(
            id=uuid.uuid4(),
            username=f"evidence_io_{unique_id}",
            email=f"ev_io_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(officer)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-EV-{unique_id.upper()}",
            title="Operation Digital Vault",
            assigned_officer_id=officer.id,
            status="open",
        )
        db.add(case)
        await db.flush()

        # Create physical test file
        content = b"CRITICAL FORENSIC EVIDENCE: MULE TRANSACTIONS DOCKET 2026"
        content_hash = hashlib.sha256(content).hexdigest()
        file_path = upload_dir / f"test_ev_{unique_id}_{content_hash[:8]}.bin"
        with open(file_path, "wb") as f:
            f.write(content)

        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="mule_ledger.bin",
            original_name="mule_ledger.bin",
            file_type="binary",
            file_size_bytes=len(content),
            sha256_hash=content_hash,
            storage_path=str(file_path),
            upload_status="processed",
            integrity_status="verified",
            original_immutable=True,
            version_status="original",
            uploaded_by=officer.id,
        )
        db.add(ev_file)
        await db.commit()

        token, _, _ = _create_access_token(user_id=str(officer.id), role=officer.role)
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. ATTEMPT WITHOUT JUSTIFICATION -> MUST FAIL (403 Forbidden)
            resp_no_reason = await client.get(
                f"/api/v1/evidence/{case.id}/files/{ev_file.id}/download",
                headers=headers,
            )
            assert resp_no_reason.status_code == 403
            assert "explicit operational justification" in resp_no_reason.json()["detail"]

            # 2. ATTEMPT WITH SHORT / EMPTY REASON -> MUST FAIL (403 Forbidden)
            resp_short_reason = await client.get(
                f"/api/v1/evidence/{case.id}/files/{ev_file.id}/download?reason=hi",
                headers=headers,
            )
            assert resp_short_reason.status_code == 403

            # 3. LEGITIMATE ACCESS WITH JUSTIFICATION + DEVICE CONTEXT -> 200 OK
            justification = "Forensic hash verification for court chargesheet submission under Section 63 BSA"
            resp_ok = await client.get(
                f"/api/v1/evidence/{case.id}/files/{ev_file.id}/download?reason={justification}",
                headers={**headers, "X-Device-ID": "forensic-lab-workstation-09"},
            )
            assert resp_ok.status_code == 200
            assert resp_ok.content == content
            assert resp_ok.headers["X-Evidence-SHA256"] == content_hash

    # 4. VERIFY AUDIT TRAIL RECORD IN DATABASE
    async with AsyncSessionLocal() as db:
        audit_res = await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_id == str(ev_file.id))
            .order_by(AuditLog.id.desc())
        )
        logs = audit_res.scalars().all()
        actions = [l.action for l in logs]
        assert "EVIDENCE_ACCESS_DENIED" in actions
        assert "EVIDENCE_ACCESS_GRANTED" in actions

        granted_log = next(l for l in logs if l.action == "EVIDENCE_ACCESS_GRANTED")
        assert granted_log.details_json["reason"] == justification
        assert granted_log.details_json["device_id"] == "forensic-lab-workstation-09"
        assert granted_log.details_json["result"] == "AUTHORIZED"
