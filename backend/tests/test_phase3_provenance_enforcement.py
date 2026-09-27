from __future__ import annotations
"""
Phase 3 Provenance Enforcement Acceptance Test Suite — NETRA 5.0
Verifies that every producer in NETRA obeys the canonical provenance contract:
1. Ingestion / Parsers -> EvidenceEvent carries verified OBSERVED provenance with SHA-256 bitstream anchor.
2. Graph Edge Creation -> Relationship carries canonical provenance (OBSERVED for direct, INFERRED for derived).
3. Finding Service -> Upsert finding enforces provenance, tags ungrounded findings as REVIEW_REQUIRED.
4. Report & Copilot -> Claims and citations preserve end-to-end provenance with SHA-256 digests.
"""

import os
import pathlib
import tempfile
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, Case, EvidenceFile, EvidenceEvent, Entity, Relationship, InvestigationFinding
from graph.relationships import RelationshipDraft, materialize_observed_relationships
from graph import relationship_types as RT
from orchestration.contracts import CognitiveResult, CONTRADICTION, HIDDEN_LINK, SEVERITY_HIGH
from orchestration.finding_service import upsert_finding
from orchestration.provenance import ProvenanceType, EpistemicStatus, create_observed_provenance
from report.provenance import ProvenanceResolver
from report.contracts import ReportClaim, EvidenceCitation, EpistemicStatus as ReportEpistemic, ProvenanceStatus

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="p3_prov_test_"))
_DB_PATH = _TMP / "p3_test.db"
_ENGINE = create_async_engine(f"sqlite+aiosqlite:///{_DB_PATH}", echo=False)
_SessionLocal = async_sessionmaker(_ENGINE, expire_on_commit=False)


async def _ensure_db_tables():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── 1. Ingestion: EvidenceEvent Provenance Stamping ───────────────────────────

@pytest.mark.asyncio
async def test_evidence_event_canonical_provenance_stamping():
    await _ensure_db_tables()
    async with _SessionLocal() as db:
        case = Case(
            case_number=f"CASE-P3-{uuid.uuid4().hex[:6].upper()}",
            title="Phase 3 Ingestion Test Case",
            priority="medium",
            status="open",
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        sha256 = "d41d8cd98f00b204e9800998ecf8427e123456789abcdef0123456789abcdef0"
        ev_file = EvidenceFile(
            case_id=case.id,
            filename="bank_ledger.csv",
            original_name="HDFC_Account_Statement.csv",
            storage_path="/tmp/bank_ledger.csv",
            sha256_hash=sha256,
            file_size_bytes=2048,
            file_type="csv",
            source_type="bank_statement",
            upload_status="processed",
        )
        db.add(ev_file)
        await db.commit()
        await db.refresh(ev_file)

        event_id = uuid.uuid4()
        prov = create_observed_provenance(
            evidence_id=str(ev_file.id),
            event_id=str(event_id),
            sha256=ev_file.sha256_hash,
            method="parser:bank_statement",
        )

        event = EvidenceEvent(
            id=event_id,
            case_id=case.id,
            evidence_file_id=ev_file.id,
            event_timestamp=datetime.now(timezone.utc),
            event_type="bank_txn",
            text_content="IMPS P2A to Account 9876543210 Rs 50,000",
            source_line=14,
            source_page=1,
            event_metadata={"canonical_provenance": prov.to_dict(), "amount": 50000},
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)

        # Query back and verify provenance stamp
        loaded = await db.get(EvidenceEvent, event.id)
        assert loaded is not None
        meta = loaded.event_metadata or {}
        assert "canonical_provenance" in meta
        c_prov = meta["canonical_provenance"]
        assert c_prov["provenance"] == "OBSERVED"
        assert c_prov["epistemic_status"] == "FACT"
        assert str(ev_file.id) in c_prov["evidence_refs"]
        assert sha256 in c_prov["sha256_digests"]


# ── 2. Case Graph: Relationship Edge Provenance ──────────────────────────────

def test_relationship_draft_provenance_contract():
    # Observed Edge Draft
    obs_draft = RelationshipDraft(
        source_value="+919876540001",
        target_value="+919876540002",
        relationship_type="CALLED",
        epistemic_status=RT.OBSERVED,
        confidence=1.0,
        evidence_refs=["EV-FILE-01"],
        event_refs=["EVENT-01"],
    )
    obs_prov = obs_draft.to_provenance_record()
    assert obs_prov.provenance == ProvenanceType.OBSERVED
    assert obs_prov.epistemic_status == EpistemicStatus.FACT
    assert obs_prov.evidence_refs == ["EV-FILE-01"]

    # Inferred Edge Draft
    inf_draft = RelationshipDraft(
        source_value="Acc-1",
        target_value="Acc-9",
        relationship_type="HIDDEN_INTERMEDIARY",
        epistemic_status=RT.INFERRED,
        confidence=0.82,
        evidence_refs=["EV-FILE-01"],
        source_engine="mule_detection_engine",
    )
    inf_prov = inf_draft.to_provenance_record()
    assert inf_prov.provenance == ProvenanceType.INFERRED
    assert inf_prov.epistemic_status == EpistemicStatus.DERIVED_ANALYSIS
    assert inf_prov.generated_by == "mule_detection_engine"


# ── 3. Cognitive Findings: Finding Service Enforcement ───────────────────────

@pytest.mark.asyncio
async def test_finding_service_provenance_enforcement():
    await _ensure_db_tables()
    async with _SessionLocal() as db:
        case = Case(
            case_number=f"CASE-P3-FIND-{uuid.uuid4().hex[:6].upper()}",
            title="Phase 3 Finding Service Case",
            priority="high",
            status="open",
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        # 1. Valid Grounded Finding
        valid_res = CognitiveResult(
            finding_type=CONTRADICTION,
            title="Altered ledger balance detected",
            description="Credit of 100,000 does not match running balance shift of 40,000",
            confidence=0.98,
            source_engine="ContradictionEngine",
            engine_version="2.0",
            evidence_refs=["EV-FILE-LEDGER"],
            event_refs=["EVENT-ROW-42"],
            entity_refs=["Account-X"],
            reasoning="Mathematical discrepancy in running statement balance.",
        )

        row, created = await upsert_finding(db, case.id, valid_res)
        await db.commit()
        await db.refresh(row)

        assert created is True
        assert "canonical_provenance" in row.component_scores
        c_prov = row.component_scores["canonical_provenance"]
        assert c_prov["provenance"] == "INFERRED"
        assert c_prov["generated_by"] == "ContradictionEngine"
        assert row.component_scores.get("provenance_status") == "VERIFIED"
        assert "EV-FILE-LEDGER" in row.evidence_refs

        # 2. Ungrounded Finding (Missing engine and evidence lineage)
        ungrounded_res = CognitiveResult(
            finding_type=HIDDEN_LINK,
            title="Unsubstantiated connection claim",
            description="Suspect might know individual Y",
            source_engine="",  # Empty engine violates INFERRED invariant
            confidence=0.5,
            evidence_refs=[],
            event_refs=[],
            entity_refs=[],
            reasoning="",
        )

        bad_row, _ = await upsert_finding(db, case.id, ungrounded_res)
        await db.commit()
        await db.refresh(bad_row)

        # Negative guarantee verified: Finding is flagged as REVIEW_REQUIRED
        assert bad_row.component_scores.get("provenance_status") == "REVIEW_REQUIRED"
        assert len(bad_row.component_scores.get("provenance_warnings", [])) > 0


# ── 4. Claims: Lineage Chain Inspection ──────────────────────────────────────

def test_report_claim_provenance_chain_resolution():
    ev_file_id = uuid.uuid4()
    sha256 = "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"

    ef = EvidenceFile(
        id=ev_file_id,
        filename="call_data_record.csv",
        original_name="CDR_Target.csv",
        sha256_hash=sha256,
        upload_status="processed",
    )

    ev_id = uuid.uuid4()
    event = EvidenceEvent(
        id=ev_id,
        evidence_file_id=ev_file_id,
        event_type="call",
        text_content="Call to +91-9999900001 (duration: 340s)",
        source_page=1,
        source_line=88,
    )

    finding_id = uuid.uuid4()
    finding = InvestigationFinding(
        id=finding_id,
        finding_type="CO_CALL",
        title="Frequent communication with syndicate coordinator",
        evidence_refs=[str(ev_file_id)],
        event_refs=[str(ev_id)],
        component_scores={
            "canonical_provenance": {
                "provenance": "INFERRED",
                "epistemic_status": "DERIVED_ANALYSIS",
                "generated_by": "communication_intel",
            }
        },
    )

    resolver = ProvenanceResolver(
        evidence_files=[ef],
        evidence_events=[event],
        entities=[],
        relationships=[],
        findings=[finding],
    )

    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-108",
        text="Target maintained frequent communications with coordinator right before transaction.",
        claim_type="finding",
        finding_id=finding_id,
        event_ids=[ev_id],
        evidence_ids=[ev_file_id],
    )

    assert claim.provenance_status == ProvenanceStatus.VERIFIED
    assert len(claim.evidence_refs) >= 1
    assert claim.evidence_refs[0].sha256_hash == sha256
    assert claim.provenance_chain.finding_ref["canonical_provenance"]["generated_by"] == "communication_intel"
