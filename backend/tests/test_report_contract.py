from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Report Contract Test Suite
Validates ReportClaim, EvidenceCitation, ProvenanceChain, ReportSection,
and ReportPayload contracts and serialization semantics.
"""
import uuid
import pytest
from pydantic import ValidationError

from report.contracts import (
    ConfidenceStatus,
    EpistemicStatus,
    EvidenceCitation,
    ProvenanceChain,
    ProvenanceStatus,
    ReportClaim,
    ReportPayload,
    ReportSection,
    ReportSnapshotMetadata,
    ReportType,
    ReportLifecycleStatus,
)


def test_evidence_citation_contract():
    cit = EvidenceCitation(
        evidence_id=str(uuid.uuid4()),
        file_name="bank_statement_sept2026.pdf",
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        source_page=4,
        source_line=23,
        citation_label="[E-E3B0C4 · p.4 · line 23]",
        source_type="bank_txn",
    )
    assert cit.file_name == "bank_statement_sept2026.pdf"
    assert cit.source_page == 4
    assert cit.source_line == 23
    assert "[E-E3B0C4 · p.4 · line 23]" in cit.citation_label

    # Immutability
    with pytest.raises(ValidationError):
        cit.source_page = 5  # Citations are frozen


def test_report_claim_provenance_flag_contract():
    cit = EvidenceCitation(
        evidence_id=str(uuid.uuid4()),
        file_name="whatsapp_chat.txt",
        sha256_hash="7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
        source_page=1,
        source_line=10,
        citation_label="[E-7F83B1 · line 10]",
    )

    # 1. Verified claim with evidence citation
    verified_claim = ReportClaim(
        claim_id="CLAIM-001",
        text="Entity A communicated with Entity B on Sept 2, 2026.",
        claim_type="communication",
        epistemic_status=EpistemicStatus.CONFIRMED,
        confidence_status=ConfidenceStatus.HIGH,
        evidence_refs=[cit],
        provenance_status=ProvenanceStatus.VERIFIED,
    )
    assert verified_claim.has_sufficient_provenance is True
    assert verified_claim.provenance_status == ProvenanceStatus.VERIFIED

    # 2. Unlinked claim without evidence citation
    unlinked_claim = ReportClaim(
        claim_id="CLAIM-002",
        text="Suspect transferred undisclosed sum to offshore node.",
        claim_type="financial_signal",
        epistemic_status=EpistemicStatus.ALLEGED,
        confidence_status=ConfidenceStatus.LOW,
        evidence_refs=[],
        provenance_status=ProvenanceStatus.UNLINKED,
    )
    assert unlinked_claim.has_sufficient_provenance is False
    assert unlinked_claim.provenance_status == ProvenanceStatus.UNLINKED

    # 3. Review required claim (e.g. invalid hash or missing artifact)
    review_claim = ReportClaim(
        claim_id="CLAIM-003",
        text="Suspect vehicle seen near cell tower sector 4.",
        claim_type="geographic_signal",
        epistemic_status=EpistemicStatus.INFERRED,
        confidence_status=ConfidenceStatus.MEDIUM,
        evidence_refs=[],
        limitations=["Cell tower triangulation technical limitation (approximate 800m sector)"],
        provenance_status=ProvenanceStatus.REVIEW_REQUIRED,
    )
    assert review_claim.has_sufficient_provenance is False
    assert review_claim.provenance_status == ProvenanceStatus.REVIEW_REQUIRED
    assert len(review_claim.limitations) == 1


def test_report_payload_full_structure():
    meta = ReportSnapshotMetadata(
        report_id=str(uuid.uuid4()),
        case_id=str(uuid.uuid4()),
        case_number="FIR-2026-TEST",
        case_title="Operation Falcon Strike",
        report_type=ReportType.FORMAL_DOSSIER,
        status=ReportLifecycleStatus.DRAFT,
        case_state_version=42,
        content_hash="a" * 64,
        title="Formal Investigation Dossier — FIR-2026-TEST",
        generated_at="2026-09-22T23:00:00Z",
        claims_count=1,
        linked_claims_count=1,
        review_required_claims_count=0,
    )

    section = ReportSection(
        section_id="case_summary",
        title="1. Case Scope",
        order=1,
        summary="Summary of case",
        claims=[],
        data={"priority": "HIGH"},
        limitations=[],
    )

    payload = ReportPayload(
        metadata=meta,
        sections=[section],
        statutory_provisions={"statutory_act": "Section 63 BSA"},
        provenance_summary={"total_claims": 1, "verified_claims": 1, "review_required_claims": 0},
    )

    serialized = payload.model_dump()
    assert serialized["metadata"]["case_state_version"] == 42
    assert serialized["sections"][0]["section_id"] == "case_summary"
    assert serialized["statutory_provisions"]["statutory_act"] == "Section 63 BSA"

    # Reconstruct from dict
    restored = ReportPayload.model_validate(serialized)
    assert restored.metadata.report_type == ReportType.FORMAL_DOSSIER
    assert restored.metadata.case_number == "FIR-2026-TEST"
