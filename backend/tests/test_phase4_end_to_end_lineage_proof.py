from __future__ import annotations
"""
Phase 4 End-to-End Lineage Proof Acceptance Test Suite — NETRA 5.0

Proves that forensic provenance survives unbroken across the entire trajectory:
Synthetic Evidence File
       ↓ SHA-256
EvidenceEvent (page/line)
       ↓
Entity + Relationship
       ↓
Cognitive Engine Finding
       ↓
Report Claim
       ↓
Report Citation

Asserts:
1. Exact preservation of originating EvidenceFile.id and SHA-256 digest across all 5 tiers.
2. Correct propagation of EvidenceEvent.id, entity/rel refs, finding refs, and claim refs.
3. Invariant maintenance: OBSERVED remains OBSERVED, INFERRED remains INFERRED.
4. Negative guarantee: Epistemic status cannot silently promote an INFERRED finding to empirical FACT.
5. Negative guarantee: Severed or tampered lineage renders claim UNVERIFIED / REVIEW_REQUIRED.
6. Citation navigability: Final claim citation backtracks cleanly to exact line, page, and bitstream.
"""

import hashlib
import pathlib
import tempfile
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Base, Case, EvidenceFile, EvidenceEvent, Entity, Relationship, InvestigationFinding
from graph.relationships import RelationshipDraft, materialize_observed_relationships
from graph import relationship_types as RT
from orchestration.contracts import CognitiveResult, CONTRADICTION, HIDDEN_LINK, SEVERITY_CRITICAL
from orchestration.finding_service import upsert_finding
from orchestration.provenance import (
    ProvenanceType,
    EpistemicStatus,
    ChainTier,
    reconstruct_chain_lineage,
    create_observed_provenance,
)
from report.provenance import ProvenanceResolver
from report.contracts import ReportClaim, EvidenceCitation, EpistemicStatus as ReportEpistemic, ProvenanceStatus

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="p4_lineage_test_"))
_DB_PATH = _TMP / "p4_lineage.db"
_ENGINE = create_async_engine(f"sqlite+aiosqlite:///{_DB_PATH}", echo=False)
_SessionLocal = async_sessionmaker(_ENGINE, expire_on_commit=False)


async def _ensure_db():
    async with _ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── 1. Canonical End-to-End Lineage Journey ──────────────────────────────────

@pytest.mark.asyncio
async def test_unbroken_end_to_end_forensic_lineage_pipeline():
    await _ensure_db()
    async with _SessionLocal() as db:
        case = Case(
            case_number="CYB-2026-E2E-001",
            title="Synthetic Mule Ring Investigation",
            priority="high",
            status="in_progress",
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        # ── Tier 0: Synthetic Evidence File + SHA-256 ────────────────────────
        raw_csv_content = b"date,account,type,amount,narration,balance\n2026-08-15,ACCT-MULE-88,CR,500000,RTGS FROM VICTIM,500000\n2026-08-15,ACCT-MULE-88,DR,480000,ATM WITHDRAWAL CONTRADICTION,20000\n"
        computed_sha256 = hashlib.sha256(raw_csv_content).hexdigest()

        evidence_file = EvidenceFile(
            case_id=case.id,
            filename="mule_transactions.csv",
            original_name="axis_statement_aug2026.csv",
            storage_path="/tmp/mule_transactions.csv",
            sha256_hash=computed_sha256,
            file_size_bytes=len(raw_csv_content),
            file_type="csv",
            source_type="bank_statement",
            upload_status="processed",
        )
        db.add(evidence_file)
        await db.commit()
        await db.refresh(evidence_file)

        # ── Tier 1: EvidenceEvent ────────────────────────────────────────────
        event_id = uuid.uuid4()
        prov_obs = create_observed_provenance(
            evidence_id=str(evidence_file.id),
            event_id=str(event_id),
            sha256=computed_sha256,
            method="parser:bank_csv",
        )

        event = EvidenceEvent(
            id=event_id,
            case_id=case.id,
            evidence_file_id=evidence_file.id,
            event_timestamp=datetime(2026, 8, 15, 10, 30, tzinfo=timezone.utc),
            event_type="bank_txn",
            text_content="RTGS FROM VICTIM to ACCT-MULE-88 INR 500,000",
            source_line=2,
            source_page=1,
            event_metadata={
                "canonical_provenance": prov_obs.to_dict(),
                "amount": 500000,
                "from_account": "VICTIM_ACC",
                "to_account": "ACCT-MULE-88",
            },
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)

        # ── Tier 2: Entity & Relationship ────────────────────────────────────
        ent_victim = Entity(case_id=case.id, canonical_value="VICTIM_ACC", entity_type="ACCOUNT")
        ent_mule = Entity(case_id=case.id, canonical_value="ACCT-MULE-88", entity_type="ACCOUNT")
        db.add_all([ent_victim, ent_mule])
        await db.commit()
        await db.refresh(ent_victim)
        await db.refresh(ent_mule)

        draft = RelationshipDraft(
            source_value="VICTIM_ACC",
            target_value="ACCT-MULE-88",
            relationship_type="TRANSFERRED_TO",
            epistemic_status=RT.OBSERVED,
            confidence=1.0,
            amount=500000,
            timestamp=event.event_timestamp,
            evidence_refs=[str(evidence_file.id)],
            event_refs=[str(event.id)],
        )

        rel = Relationship(
            case_id=case.id,
            source_entity_id=ent_victim.id,
            target_entity_id=ent_mule.id,
            relationship_type=draft.relationship_type,
            direction=draft.direction,
            epistemic_status=draft.epistemic_status,
            confidence=1.0,
            amount=500000,
            event_timestamp=event.event_timestamp,
            attributes={"canonical_provenance": draft.to_provenance_record().to_dict()},
            evidence_refs=[str(evidence_file.id)],
            event_refs=[str(event.id)],
        )
        db.add(rel)
        await db.commit()
        await db.refresh(rel)

        # ── Tier 3: Cognitive Finding ────────────────────────────────────────
        cog_result = CognitiveResult(
            finding_type=CONTRADICTION,
            title="High velocity dissipation through mule account",
            description="₹4,80,000 withdrawn within 30 minutes of ₹5,00,000 victim deposit",
            confidence=0.96,
            severity=SEVERITY_CRITICAL,
            source_engine="ContradictionEngine",
            engine_version="2.0",
            evidence_refs=[str(evidence_file.id)],
            event_refs=[str(event.id)],
            entity_refs=["ACCT-MULE-88"],
            reasoning="Temporal co-occurrence and rapid debit balance change.",
        )

        finding_row, created = await upsert_finding(db, case.id, cog_result)
        await db.commit()
        await db.refresh(finding_row)
        assert created is True

        # ── Tier 4: Report Claim & Citation Resolution ───────────────────────
        resolver = ProvenanceResolver(
            evidence_files=[evidence_file],
            evidence_events=[event],
            entities=[ent_victim, ent_mule],
            relationships=[rel],
            findings=[finding_row],
        )

        claim = resolver.build_claim_provenance(
            claim_id="CLAIM-P4-001",
            text="₹4,80,000 was dissipated from mule account ACCT-MULE-88 immediately after victim deposit.",
            claim_type="finding",
            finding_id=finding_row.id,
            relationship_id=rel.id,
            event_ids=[event.id],
            evidence_ids=[evidence_file.id],
        )

        assert claim.provenance_status == ProvenanceStatus.VERIFIED
        assert len(claim.evidence_refs) >= 1
        citation = claim.evidence_refs[0]

        # ── Lineage Invariant Verification Across All Tiers ──────────────────
        lineage = reconstruct_chain_lineage(
            claim_id=claim.claim_id,
            claim_text=claim.text,
            finding=finding_row,
            relationship=rel,
            event=event,
            evidence_file=evidence_file,
        )

        assert lineage.is_lineage_complete is True
        assert len(lineage.links) == 5
        assert lineage.root_evidence_files == [str(evidence_file.id)]
        assert lineage.root_sha256_digests == [computed_sha256]

        # Tier 0 (EvidenceFile): OBSERVED + FACT + SHA-256
        t0 = lineage.links[0]
        assert t0.tier == ChainTier.EVIDENCE_FILE
        assert t0.identifier == str(evidence_file.id)
        assert t0.sha256 == computed_sha256
        assert t0.provenance == ProvenanceType.OBSERVED
        assert t0.epistemic_status == EpistemicStatus.FACT

        # Tier 1 (EvidenceEvent): OBSERVED + FACT + same SHA-256
        t1 = lineage.links[1]
        assert t1.tier == ChainTier.EVIDENCE_EVENT
        assert t1.identifier == str(event.id)
        assert t1.sha256 == computed_sha256
        assert t1.parent_refs == [str(evidence_file.id)]

        # Tier 2 (Relationship): OBSERVED
        t2 = lineage.links[2]
        assert t2.tier == ChainTier.GRAPH_ELEMENT
        assert t2.identifier == str(rel.id)
        assert t2.provenance == ProvenanceType.OBSERVED

        # Tier 3 (Finding): INFERRED + DERIVED_ANALYSIS
        t3 = lineage.links[3]
        assert t3.tier == ChainTier.FINDING
        assert t3.provenance == ProvenanceType.INFERRED
        assert t3.epistemic_status == EpistemicStatus.DERIVED_ANALYSIS

        # Tier 4 (Claim): INFERRED (inherits analytical nature of finding)
        t4 = lineage.links[4]
        assert t4.tier == ChainTier.CLAIM
        assert t4.provenance == ProvenanceType.INFERRED
        assert t4.epistemic_status == EpistemicStatus.DERIVED_ANALYSIS

        # Citation Backtrack Navigation Proof
        assert citation.evidence_id == str(evidence_file.id)
        assert citation.sha256_hash == computed_sha256
        assert citation.source_line == 2
        assert citation.source_page == 1
        assert citation.event_id == str(event.id)


# ── 2. Negative Guarantee: Epistemic Promotion Blocked ───────────────────────

def test_negative_guarantee_epistemic_promotion_blocked():
    ef_id = uuid.uuid4()
    sha256 = "a" * 64

    ef = EvidenceFile(id=ef_id, filename="log.csv", sha256_hash=sha256)
    ev = EvidenceEvent(id=uuid.uuid4(), evidence_file_id=ef_id, event_type="log")
    finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="HYPOTHESIS",
        title="Syndicate kingpin hypothesis",
        evidence_refs=[str(ef_id)],
        component_scores={"canonical_provenance": {"provenance": "INFERRED", "epistemic_status": "HYPOTHESIS"}},
    )

    # Attempting to declare claim as FACT when based on a HYPOTHESIS finding
    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-PROMO-001",
        claim_text="Target is the confirmed kingpin.",
        finding=finding,
        event=ev,
        evidence_file=ef,
        epistemic_override=EpistemicStatus.FACT,  # ILLEGAL PROMOTION
    )

    assert lineage.is_lineage_complete is False
    assert any("cannot promote HYPOTHESIS finding to empirical FACT" in w for w in lineage.warnings)


# ── 3. Negative Guarantee: Severed Lineage Becomes Unverified ────────────────

def test_negative_guarantee_severed_lineage_becomes_unverified():
    ev_id = uuid.uuid4()
    ghost_ef_id = uuid.uuid4()

    event = EvidenceEvent(
        id=ev_id,
        evidence_file_id=ghost_ef_id,  # Points to nonexistent file
        event_type="call",
    )

    finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="COMM_ANALYSIS",
        title="Call cluster",
        event_refs=[str(ev_id)],
    )

    # Reconstruct with missing root EvidenceFile
    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-SEVERED-001",
        claim_text="Communication established with suspect",
        finding=finding,
        event=event,
        evidence_file=None,  # SEVERED ROOT
    )

    assert lineage.is_lineage_complete is False
    assert any("No root EvidenceFile attached" in w for w in lineage.warnings)

    # Also verify ProvenanceResolver marks claim as UNLINKED / REVIEW_REQUIRED
    resolver = ProvenanceResolver(
        evidence_files=[],
        evidence_events=[event],
        entities=[],
        relationships=[],
        findings=[finding],
    )
    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-RESOLVER-SEVERED",
        text="Ungrounded statement",
        claim_type="finding",
        finding_id=finding.id,
        event_ids=[ev_id],
        evidence_ids=[ghost_ef_id],
    )

    assert claim.provenance_status in (ProvenanceStatus.REVIEW_REQUIRED, ProvenanceStatus.UNLINKED)
    assert not claim.has_sufficient_provenance
