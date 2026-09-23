from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Read-Only Guarantee Test Suite
Validates that generating reports and previewing intelligence briefs execute in
strictly read-only mode and NEVER mutate case state, findings, entities, or version numbers.
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from db.models import (
    Case,
    Entity,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from main import app
from report.builder import ReportBuilder
from report.contracts import ReportType
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_report_generation_is_strictly_read_only():
    async with AsyncSessionLocal() as db:
        user = User(
            id=uuid.uuid4(),
            username=f"io_ro_{uuid.uuid4().hex[:6]}",
            email=f"io_ro_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password="pw",
            role="io",
            full_name="Inspector Read Only",
            rank="Inspector",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        token, _, _ = _create_access_token(user_id=str(user.id), role=user.role)
        headers = {"Authorization": f"Bearer {token}"}

        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-RO-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Clean Horizon — Read-Only Guarantee",
            crime_type="Cyber Security Incident",
            priority="medium",
            status="open",
            assigned_officer_id=user.id,
            state_version=15,
        )
        db.add(case)
        await db.flush()

        ef = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="syslog.txt",
            original_name="syslog.txt",
            storage_path=f"/evidence/{uuid.uuid4().hex}.txt",
            sha256_hash="2" * 64,
            file_size_bytes=2048,
            file_type="txt",
            source_type="network_log",
            upload_status="CONFIRMED",
        )
        db.add(ef)

        ent = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="192.168.1.100",
            entity_type="IP_ADDRESS",
        )
        db.add(ent)

        f = InvestigationFinding(
            id=uuid.uuid4(),
            case_id=case.id,
            finding_type="INTRUSION",
            title="Port Scan Activity",
            description="Reconnaissance detected from internal IP",
            severity="LOW",
            confidence=0.7,
            freshness_status="CURRENT",
            evidence_refs=[str(ef.id)],
            entity_refs=[str(ent.id)],
            fingerprint=f"FND-{uuid.uuid4().hex[:8]}",
        )
        db.add(f)
        await db.commit()

        # 1. Take snapshot of baseline case metrics before report execution
        case_ver_before = case.state_version
        findings_count_before = (
            await db.execute(select(func.count(InvestigationFinding.id)).where(InvestigationFinding.case_id == case.id))
        ).scalar()
        entities_count_before = (
            await db.execute(select(func.count(Entity.id)).where(Entity.case_id == case.id))
        ).scalar()
        evidence_count_before = (
            await db.execute(select(func.count(EvidenceFile.id)).where(EvidenceFile.case_id == case.id))
        ).scalar()
        rel_count_before = (
            await db.execute(select(func.count(Relationship.id)).where(Relationship.case_id == case.id))
        ).scalar()

        # 2. Execute ReportBuilder directly (in-memory builder)
        payload_brief = await ReportBuilder.build_report(
            case_id=str(case.id),
            db=db,
            report_type=ReportType.INTELLIGENCE_BRIEF,
            user_id=str(user.id),
        )
        assert payload_brief.metadata.case_state_version == 15

        payload_dossier = await ReportBuilder.build_report(
            case_id=str(case.id),
            db=db,
            report_type=ReportType.FORMAL_DOSSIER,
            user_id=str(user.id),
        )
        assert payload_dossier.metadata.case_state_version == 15

        # 3. Call API generate endpoint
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/cases/{case.id}/reports/generate",
                json={"report_type": "formal_dossier"},
                headers=headers,
            )
            assert resp.status_code == 201

        # 4. Verify that case state and child entities remain 100% untouched
        await db.refresh(case)
        assert case.state_version == case_ver_before, "Report generation must not increment case state_version"

        findings_count_after = (
            await db.execute(select(func.count(InvestigationFinding.id)).where(InvestigationFinding.case_id == case.id))
        ).scalar()
        entities_count_after = (
            await db.execute(select(func.count(Entity.id)).where(Entity.case_id == case.id))
        ).scalar()
        evidence_count_after = (
            await db.execute(select(func.count(EvidenceFile.id)).where(EvidenceFile.case_id == case.id))
        ).scalar()
        rel_count_after = (
            await db.execute(select(func.count(Relationship.id)).where(Relationship.case_id == case.id))
        ).scalar()

        assert findings_count_after == findings_count_before
        assert entities_count_after == entities_count_before
        assert evidence_count_after == evidence_count_before
        assert rel_count_after == rel_count_before
