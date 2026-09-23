from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 5: Original Evidence Immutability
Verifies:
- Original evidence cannot be deleted (returns 403 Forbidden)
- Original SHA-256, filename, and acquisition metadata cannot be altered
- Allowed operations create analysis derivatives instead
- Derivatives are modifiable and deletable
"""

import hashlib
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, EvidenceFile, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_original_evidence_immutability_guarantees():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        officer = User(
            id=uuid.uuid4(),
            username=f"immut_io_{unique_id}",
            email=f"immut_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(officer)
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-IMMUT-{unique_id.upper()}",
            title="Operation Stone Seal",
            assigned_officer_id=officer.id,
            status="open",
        )
        db.add(case)
        await db.flush()

        # Original seized evidence
        orig_hash = hashlib.sha256(b"ORIGINAL ACQUIRED BITSTREAM").hexdigest()
        orig_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="seized_harddrive_image.dd",
            original_name="seized_harddrive_image.dd",
            file_type="forensic_image",
            file_size_bytes=1024,
            sha256_hash=orig_hash,
            storage_path=f"evidence/{case.id}/{orig_hash}.dd",
            upload_status="processed",
            integrity_status="verified",
            original_immutable=True,
            version_status="original",
            uploaded_by=officer.id,
        )
        db.add(orig_file)
        await db.commit()

        token, _, _ = _create_access_token(user_id=str(officer.id), role=officer.role)
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. ATTEMPT TO DELETE ORIGINAL EVIDENCE -> MUST BE REJECTED (403 Forbidden)
            resp_del = await client.delete(
                f"/api/v1/evidence/{case.id}/files/{orig_file.id}",
                headers=headers,
            )
            assert resp_del.status_code == 403
            assert "immutable under Section 63 BSA" in resp_del.json()["detail"]

            # 2. ATTEMPT TO OVERWRITE PROTECTED FORENSIC METADATA -> MUST BE REJECTED (403 Forbidden)
            resp_patch_hash = await client.patch(
                f"/api/v1/evidence/{case.id}/files/{orig_file.id}",
                json={"sha256_hash": "0000000000000000000000000000000000000000000000000000000000000000"},
                headers=headers,
            )
            assert resp_patch_hash.status_code == 403
            assert "Cannot modify protected forensic fields" in resp_patch_hash.json()["detail"]

            resp_patch_name = await client.patch(
                f"/api/v1/evidence/{case.id}/files/{orig_file.id}",
                json={"original_name": "tampered_name.dd"},
                headers=headers,
            )
            assert resp_patch_name.status_code == 403

            # 3. CREATE DERIVATIVE ARTIFACT -> PERMITTED (200 OK)
            resp_deriv = await client.post(
                f"/api/v1/evidence/{case.id}/files/{orig_file.id}/derivatives",
                json={
                    "name": "redacted_carved_documents.zip",
                    "details": {"operation": "PII_REDACTION", "officer": officer.username},
                },
                headers=headers,
            )
            assert resp_deriv.status_code == 200
            deriv_data = resp_deriv.json()
            deriv_id = deriv_data["derivative_id"]
            assert deriv_data["parent_evidence_id"] == str(orig_file.id)
            assert deriv_data["version_status"] == "variant"

            # 4. DERIVATIVE ARTIFACT CAN BE DELETED IF SUPERSEDED -> PERMITTED (200 OK)
            resp_del_deriv = await client.delete(
                f"/api/v1/evidence/{case.id}/files/{deriv_id}",
                headers=headers,
            )
            assert resp_del_deriv.status_code == 200
            assert "Evidence variant deleted" in resp_del_deriv.json()["message"]
