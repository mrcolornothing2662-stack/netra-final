from __future__ import annotations
"""
NETRA 5.0 — Canonical Provenance & Epistemic Contract Test Suite (Phase 2)

Verifies:
1. Canonical Vocabulary:
   - ProvenanceType: OBSERVED, INFERRED, USER_ASSERTED, SYNTHETIC_DEMO
   - EpistemicStatus: FACT, DERIVED_ANALYSIS, HYPOTHESIS, ALLEGED, DISPUTED, UNRESOLVED
2. Strict Negative Invariants:
   - Rejection of ungrounded OBSERVED records
   - Rejection of INFERRED without declared generator engine
   - Rejection of USER_ASSERTED without officer ID
   - Rejection of SYNTHETIC_DEMO masquerading as empirical FACT
3. Target Chain Traceability:
   EvidenceFile (SHA-256) -> EvidenceEvent -> Entity/Relationship -> Finding -> Claim
4. Serialization and Integration:
   - NormalizedEvent.to_provenance_record()
   - CognitiveResult.to_provenance_record()
   - ReportClaim.to_canonical_provenance()
"""

import pytest
from orchestration.provenance import (
    ProvenanceType,
    EpistemicStatus,
    ChainTier,
    CanonicalProvenanceRecord,
    EvidenceChainLink,
    ChainLineageTrace,
    create_observed_provenance,
    create_inferred_provenance,
    create_user_asserted_provenance,
    create_synthetic_demo_provenance,
)
from orchestration.contracts import NormalizedEvent, CognitiveResult
from report.contracts import ReportClaim, EvidenceCitation, EpistemicStatus as ReportEpistemic, ProvenanceStatus


# ── 1. Canonical Vocabulary & Invariants ─────────────────────────────────────

def test_canonical_vocabulary_constants():
    assert ProvenanceType.OBSERVED.value == "OBSERVED"
    assert ProvenanceType.INFERRED.value == "INFERRED"
    assert ProvenanceType.USER_ASSERTED.value == "USER_ASSERTED"
    assert ProvenanceType.SYNTHETIC_DEMO.value == "SYNTHETIC_DEMO"

    assert EpistemicStatus.FACT.value == "FACT"
    assert EpistemicStatus.DERIVED_ANALYSIS.value == "DERIVED_ANALYSIS"
    assert EpistemicStatus.HYPOTHESIS.value == "HYPOTHESIS"
    assert EpistemicStatus.ALLEGED.value == "ALLEGED"
    assert EpistemicStatus.DISPUTED.value == "DISPUTED"
    assert EpistemicStatus.UNRESOLVED.value == "UNRESOLVED"


def test_observed_provenance_requires_evidence():
    # Valid OBSERVED
    rec = create_observed_provenance(evidence_id="EV-FILE-001", sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert rec.provenance == ProvenanceType.OBSERVED
    assert rec.epistemic_status == EpistemicStatus.FACT
    assert rec.has_evidence_lineage() is True
    ok, warnings = rec.validate_chain_integrity()
    assert ok is True
    assert len(warnings) == 0

    # Negative Guarantee: OBSERVED with zero evidence references MUST fail
    with pytest.raises(ValueError, match="OBSERVED provenance requires at least one cited evidence_ref"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.OBSERVED,
            epistemic_status=EpistemicStatus.FACT,
            evidence_refs=[],
            event_refs=[],
            sha256_digests=[],
        )


def test_inferred_provenance_requires_engine_and_references():
    # Valid INFERRED
    rec = create_inferred_provenance(
        engine_name="hidden_link_engine",
        confidence=0.88,
        evidence_refs=["EV-FILE-001"],
        event_refs=["EVENT-042"],
        epistemic_status=EpistemicStatus.DERIVED_ANALYSIS,
    )
    assert rec.provenance == ProvenanceType.INFERRED
    assert rec.epistemic_status == EpistemicStatus.DERIVED_ANALYSIS
    assert rec.generated_by == "hidden_link_engine"
    assert rec.confidence == 0.88
    ok, warnings = rec.validate_chain_integrity()
    assert ok is True

    # Negative Guarantee 1: Missing generated_by
    with pytest.raises(ValueError, match="requires a declared 'generated_by'"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.INFERRED,
            evidence_refs=["EV-FILE-001"],
            generated_by=None,
        )

    # Negative Guarantee 2: Missing source references without justification
    with pytest.raises(ValueError, match="must cite underlying source references"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.INFERRED,
            generated_by="hidden_link_engine",
            evidence_refs=[],
            event_refs=[],
            entity_refs=[],
            finding_refs=[],
            epistemic_justification=None,
        )


def test_user_asserted_provenance_requires_investigator():
    # Valid USER_ASSERTED
    rec = create_user_asserted_provenance(officer_id="IO_SHARMA_2026")
    assert rec.provenance == ProvenanceType.USER_ASSERTED
    assert rec.asserted_by == "IO_SHARMA_2026"
    ok, warnings = rec.validate_chain_integrity()
    assert ok is True

    # Negative Guarantee: Missing asserted_by
    with pytest.raises(ValueError, match="requires an 'asserted_by'"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.USER_ASSERTED,
            asserted_by=None,
        )


def test_synthetic_demo_cannot_claim_empirical_fact():
    # Valid SYNTHETIC_DEMO with disclaimer
    rec = create_synthetic_demo_provenance(generator_name="mule_ring_generator", scenario="bank_fraud_demo")
    assert rec.provenance == ProvenanceType.SYNTHETIC_DEMO
    assert "Synthetic demonstration" in rec.epistemic_justification

    # Negative Guarantee: Claiming FACT without synthetic explanation
    with pytest.raises(ValueError, match="cannot claim FACT epistemic_status without explicit synthetic justification"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.SYNTHETIC_DEMO,
            epistemic_status=EpistemicStatus.FACT,
            epistemic_justification=None,
        )


# ── 2. Full Evidentiary Chain Verification ───────────────────────────────────

def test_full_chain_traceability():
    """
    Verifies that the canonical chain:
    EvidenceFile (SHA-256) -> EvidenceEvent -> Relationship -> Finding -> Claim
    is completely modeled and inspectable without gaps.
    """
    sha256 = "a1b2c3d4e5f67890123456789abcdef0123456789abcdef0123456789abcdef0"

    # Tier 0: EvidenceFile
    link_file = EvidenceChainLink(
        tier=ChainTier.EVIDENCE_FILE,
        identifier="EF-001",
        label="bank_statement.pdf",
        sha256=sha256,
        provenance=ProvenanceType.OBSERVED,
        epistemic_status=EpistemicStatus.FACT,
    )

    # Tier 1: EvidenceEvent
    link_event = EvidenceChainLink(
        tier=ChainTier.EVIDENCE_EVENT,
        identifier="EV-104",
        label="Transaction TX-104 on 2026-08-12",
        sha256=sha256,
        provenance=ProvenanceType.OBSERVED,
        epistemic_status=EpistemicStatus.FACT,
        parent_tier=ChainTier.EVIDENCE_FILE,
        parent_refs=["EF-001"],
    )

    # Tier 2: Graph Relationship
    link_rel = EvidenceChainLink(
        tier=ChainTier.GRAPH_ELEMENT,
        identifier="REL-88",
        label="Account_A -> Transferred_To -> Account_B",
        provenance=ProvenanceType.OBSERVED,
        epistemic_status=EpistemicStatus.FACT,
        parent_tier=ChainTier.EVIDENCE_EVENT,
        parent_refs=["EV-104"],
    )

    # Tier 3: Analytical Finding
    link_finding = EvidenceChainLink(
        tier=ChainTier.FINDING,
        identifier="FIND-019",
        label="Entity A and B share common mule intermediary",
        provenance=ProvenanceType.INFERRED,
        epistemic_status=EpistemicStatus.DERIVED_ANALYSIS,
        parent_tier=ChainTier.GRAPH_ELEMENT,
        parent_refs=["REL-88"],
    )

    # Tier 4: Report Claim
    link_claim = EvidenceChainLink(
        tier=ChainTier.CLAIM,
        identifier="CLAIM-003",
        label="Entity A is connected to Syndicate X via mule Account B",
        provenance=ProvenanceType.INFERRED,
        epistemic_status=EpistemicStatus.DERIVED_ANALYSIS,
        parent_tier=ChainTier.FINDING,
        parent_refs=["FIND-019"],
    )

    trace = ChainLineageTrace(
        target_id="CLAIM-003",
        target_tier=ChainTier.CLAIM,
        is_lineage_complete=True,
        root_evidence_files=["EF-001"],
        root_sha256_digests=[sha256],
        links=[link_file, link_event, link_rel, link_finding, link_claim],
        epistemic_summary="Chain verified from claim down to raw bitstream SHA-256 digest.",
    )

    assert trace.is_lineage_complete is True
    assert len(trace.links) == 5
    assert trace.root_evidence_files == ["EF-001"]
    assert trace.root_sha256_digests == [sha256]


# ── 3. Integration with Contracts ────────────────────────────────────────────

def test_normalized_event_provenance_integration():
    event = NormalizedEvent(
        event_id="EV-441",
        event_type="phone_call",
        timestamp="2026-09-01T10:00:00Z",
        text="Incoming call from +91-9876543210",
        source_doc="cdr_dump.csv",
        evidence_id="EF-CDR-09",
        extraction_method="cdr_parser",
    )
    rec = event.to_provenance_record()
    assert rec.provenance == ProvenanceType.OBSERVED
    assert rec.epistemic_status == EpistemicStatus.FACT
    assert rec.evidence_refs == ["EF-CDR-09"]
    assert rec.event_refs == ["EV-441"]
    assert rec.method == "cdr_parser"

    d = event.to_dict()
    assert d["canonical_provenance"]["provenance"] == "OBSERVED"


def test_cognitive_result_provenance_integration():
    finding = CognitiveResult(
        finding_type="HIDDEN_LINK",
        title="Co-travel between Suspect 1 and Suspect 2",
        source_engine="cross_case_engine",
        engine_version="2.1.0",
        confidence=0.92,
        evidence_refs=["EF-TRAVEL-01"],
        event_refs=["EV-FLIGHT-01", "EV-FLIGHT-02"],
        entity_refs=["Suspect-1", "Suspect-2"],
        reasoning="Both suspects booked identical PNR on flight AI-102.",
    )
    rec = finding.to_provenance_record()
    assert rec.provenance == ProvenanceType.INFERRED
    assert rec.epistemic_status == EpistemicStatus.DERIVED_ANALYSIS
    assert rec.generated_by == "cross_case_engine"
    assert rec.confidence == 0.92
    assert rec.entity_refs == ["Suspect-1", "Suspect-2"]
    assert rec.epistemic_justification == "Both suspects booked identical PNR on flight AI-102."

    d = finding.to_dict()
    assert d["canonical_provenance"]["generated_by"] == "cross_case_engine"


def test_report_claim_provenance_integration():
    citation = EvidenceCitation(
        evidence_id="EF-BANK-01",
        file_name="axis_statement.pdf",
        sha256_hash="7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
        citation_label="[E-01 · p.2 · line 15]",
    )
    claim = ReportClaim(
        claim_id="CLAIM-101",
        text="Victim transferred ₹2,50,000 to Mule Account on 2026-08-15",
        claim_type="finding",
        epistemic_status=ReportEpistemic.INFERRED,
        evidence_refs=[citation],
        finding_refs=["FIND-901"],
        generated_from="financial_intel_engine",
        provenance_status=ProvenanceStatus.VERIFIED,
    )
    rec = claim.to_canonical_provenance()
    assert rec.provenance == ProvenanceType.INFERRED
    assert rec.claim_refs == ["CLAIM-101"]
    assert rec.evidence_refs == ["EF-BANK-01"]
    assert rec.finding_refs == ["FIND-901"]
    assert "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069" in rec.sha256_digests
