from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Authorization & Four-Eyes Test Suite
Enforces dual-authorization (four-eyes principle) on report approval and export:
1. An officer cannot approve their own report snapshot.
2. A second supervisor/officer is required for sign-off.
3. Formal dossier export strictly requires APPROVED status (blocks DRAFT / REVIEW exports with 403).
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import Case, ReportSnapshot, User
from db.session import AsyncSessionLocal
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_report_four_eyes_and_export_authorization():
    async with AsyncSessionLocal() as db:
        # Officer 1: Investigating Officer who generates the report
        officer1 = User(
            id=uuid.uuid4(),
            username=f"io_author_{uuid.uuid4().hex[:6]}",
            email=f"io_author_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="io",
            full_name="Investigating Officer One",
            rank="Inspector",
            is_active=True,
        )
        # Officer 2: Supervisor / Second IO who reviews the report
        officer2 = User(
            id=uuid.uuid4(),
            username=f"io_supervisor_{uuid.uuid4().hex[:6]}",
            email=f"io_supervisor_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="supervisor",
            full_name="Supervisor Officer Two",
            rank="DSP",
            is_active=True,
        )
        db.add_all([officer1, officer2])
        await db.flush()

        token1, _, _ = _create_access_token(user_id=str(officer1.id), role=officer1.role)
        headers1 = {"Authorization": f"Bearer {token1}"}

        token2, _, _ = _create_access_token(user_id=str(officer2.id), role=officer2.role)
        headers2 = {"Authorization": f"Bearer {token2}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-AUTH-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Double Shield — Four-Eyes Validation",
            crime_type="Syndicate Narcotics",
            priority="high",
            status="open",
            assigned_officer_id=officer1.id,
            state_version=10,
        )
        db.add(case)
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Officer 1 generates Formal Dossier
            resp_gen = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={
                    "report_type": "formal_dossier",
                    "title": "Formal Court Dossier — Initial Submission",
                },
                headers=headers1,
            )
            assert resp_gen.status_code == 201, resp_gen.text
            snap_data = resp_gen.json()
            snapshot_id = snap_data["metadata"]["report_id"]
            assert snap_data["metadata"]["status"] == "DRAFT"

            # 2. Try to export directly while in DRAFT -> MUST FAIL (403 Forbidden)
            resp_unauth_export = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snapshot_id}/export",
                headers=headers1,
            )
            assert resp_unauth_export.status_code == 403
            assert "Dual-authorization required" in resp_unauth_export.json()["detail"]

            # 3. Submit for Review
            resp_sub = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snapshot_id}/submit-review",
                headers=headers1,
            )
            assert resp_sub.status_code == 200
            assert resp_sub.json()["new_status"] == "REVIEW"

            # 4. FOUR-EYES VIOLATION: Officer 1 tries to approve their OWN report -> MUST FAIL (403)
            resp_self_approve = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snapshot_id}/review",
                json={"action": "APPROVE"},
                headers=headers1,
            )
            assert resp_self_approve.status_code == 403
            assert "Four-Eyes Policy Violation" in resp_self_approve.json()["detail"]

            # 5. Officer 2 (Supervisor) reviews and approves
            # Add officer2 as collaborator so they have case access
            from db.models import CaseCollaborator
            collab = CaseCollaborator(
                case_id=case.id,
                user_id=officer2.id,
                role="supervisor",
            )
            db.add(collab)
            await db.commit()

            resp_sup_approve = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snapshot_id}/review",
                json={"action": "APPROVE"},
                headers=headers2,
            )
            assert resp_sup_approve.status_code == 200
            assert resp_sup_approve.json()["new_status"] == "APPROVED"
            assert resp_sup_approve.json()["approved_by"] == str(officer2.id)

            # 6. Now export the approved report snapshot -> SUCCEEDS
            resp_export = await client.post(
                f"/api/v1/cases/{case.id}/reports/snapshots/{snapshot_id}/export?export_format=markdown",
                headers=headers2,
            )
            assert resp_export.status_code == 200
            assert "# Formal Court Dossier" in resp_export.text
