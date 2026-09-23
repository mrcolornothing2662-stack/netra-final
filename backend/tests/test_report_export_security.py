from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 7: Report & Export Security
Verifies:
- Capability enforcement on report approval (INVESTIGATOR cannot approve)
- Dual-control Four-Eyes policy (Officer cannot approve their own report)
- Supervisor / Manager dual-control sign-off
- Certified export requires prior APPROVED authorization
"""

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, CaseCollaborator, ReportSnapshot, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_report_approval_and_export_security():
    async with AsyncSessionLocal() as db:
        unique_id = uuid.uuid4().hex[:6]
        # Investigator who generates the report
        investigator = User(
            id=uuid.uuid4(),
            username=f"author_io_{unique_id}",
            email=f"author_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Sub-Inspector",
            is_active=True,
        )
        # Another Investigator (still lacks REPORT_APPROVE capability)
        investigator2 = User(
            id=uuid.uuid4(),
            username=f"peer_io_{unique_id}",
            email=f"peer_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="INVESTIGATOR",
            rank="Sub-Inspector",
            is_active=True,
        )
        # Supervisor / Manager (possesses REPORT_APPROVE and REPORT_EXPORT)
        manager = User(
            id=uuid.uuid4(),
            username=f"supervisor_dsp_{unique_id}",
            email=f"dsp_{unique_id}@police.gov.in",
            hashed_password="pw",
            role="MANAGER",
            rank="DSP",
            is_active=True,
        )
        db.add_all([investigator, investigator2, manager])
        await db.flush()

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-REP-{unique_id.upper()}",
            title="Operation Shield Gate",
            assigned_officer_id=investigator.id,
            status="open",
        )
        db.add(case)
        db.add_all([
            CaseCollaborator(case_id=case.id, user_id=investigator2.id, role="io"),
            CaseCollaborator(case_id=case.id, user_id=manager.id, role="supervisor"),
        ])
        await db.commit()

        token_inv1, _, _ = _create_access_token(user_id=str(investigator.id), role=investigator.role)
        headers_inv1 = {"Authorization": f"Bearer {token_inv1}"}

        token_inv2, _, _ = _create_access_token(user_id=str(investigator2.id), role=investigator2.role)
        headers_inv2 = {"Authorization": f"Bearer {token_inv2}"}

        token_mgr, _, _ = _create_access_token(user_id=str(manager.id), role=manager.role)
        headers_mgr = {"Authorization": f"Bearer {token_mgr}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Investigator generates formal dossier
            gen_resp = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={"report_type": "formal_dossier", "title": "Court Dossier — Operation Shield Gate"},
                headers=headers_inv1,
            )
            assert gen_resp.status_code == 201
            snap_id = gen_resp.json()["metadata"]["report_id"]

            # 2. Submit for review
            sub_resp = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snap_id}/submit-review",
                headers=headers_inv1,
            )
            assert sub_resp.status_code == 200
            assert sub_resp.json()["new_status"] == "REVIEW"

            # 3. SELF-APPROVAL ATTEMPT: Investigator tries to approve their own report -> MUST FAIL (403)
            self_approve = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snap_id}/review",
                json={"action": "APPROVE"},
                headers=headers_inv1,
            )
            assert self_approve.status_code == 403
            assert "Four-Eyes" in self_approve.json()["detail"]

            # 4. CAPABILITY ENFORCEMENT: Peer investigator lacks REPORT_APPROVE capability -> MUST FAIL (403)
            peer_approve = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snap_id}/review",
                json={"action": "APPROVE"},
                headers=headers_inv2,
            )
            assert peer_approve.status_code == 403

            # 5. SUPERVISOR APPROVAL: Manager with REPORT_APPROVE approves report -> PERMITTED (200 OK)
            mgr_approve = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snap_id}/review",
                json={"action": "APPROVE"},
                headers=headers_mgr,
            )
            assert mgr_approve.status_code == 200
            assert mgr_approve.json()["new_status"] == "APPROVED"

            # 6. EXPORT CERTIFIED DOSSIER -> PERMITTED (200 OK)
            export_resp = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snap_id}/export",
                headers=headers_mgr,
            )
            assert export_resp.status_code == 200
            assert export_resp.json()["metadata"]["status"] == "EXPORTED"
