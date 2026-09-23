from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Provenance Test Suite
Verifies end-to-end provenance preservation across the full evidentiary chain:
EvidenceFile -> EvidenceEvent -> Entity -> Relationship -> Finding -> ReportClaim
and enforces negative guarantees against ungrounded, nonexistent, or rejected assertions.
"""
from datetime import datetime, timezone
import uuid
import pytest

from db.models import (
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationFinding,
    Relationship,
)
from report.contracts import EpistemicStatus, ProvenanceStatus
from report.provenance import ProvenanceResolver


def test_complete_provenance_chain_preservation():
    """
    Constructs a complete multi-tier case graph:
    EvidenceFile -> EvidenceEvent -> Entity -> Relationship -> Finding -> ReportClaim
    and validates that every node in the chain is resolved with exact page, line, and SHA-256.
    """
    case_id = uuid.uuid4()
    ev_file_id = uuid.uuid4()
    event_id = uuid.uuid4()
    entity_a_id = uuid.uuid4()
    entity_b_id = uuid.uuid4()
    rel_id = uuid.uuid4()
    finding_id = uuid.uuid4()

    sha256 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"

    # 1. Evidence File
    ef = EvidenceFile(
        id=ev_file_id,
        case_id=case_id,
        filename="whatsapp_dump_sept2026.txt",
        original_name="WhatsApp Chat - Vikram Patel.txt",
        sha256_hash=sha256,
        file_size_bytes=1048576,
        file_type="txt",
        source_type="whatsapp",
        upload_status="CONFIRMED",
    )

    # 2. Evidence Event (page 4, line 23)
    ev = EvidenceEvent(
        id=event_id,
        case_id=case_id,
        evidence_file_id=ev_file_id,
        event_timestamp=datetime(2026, 9, 2, 14, 30, 0, tzinfo=timezone.utc),
        event_type="comm",
        text_content="Vikram: I sent the ₹4,80,000 to Account B via RTGS",
        source_page=4,
        source_line=23,
    )

    # 3. Entities
    ent_a = Entity(
        id=entity_a_id,
        case_id=case_id,
        canonical_value="Vikram Patel",
        entity_type="PERSON",
    )
    ent_b = Entity(
        id=entity_b_id,
        case_id=case_id,
        canonical_value="Account 9876543210",
        entity_type="BANK_ACCOUNT",
    )

    # 4. Relationship
    rel = Relationship(
        id=rel_id,
        case_id=case_id,
        source_entity_id=entity_a_id,
        target_entity_id=entity_b_id,
        relationship_type="TRANSFERRED_FUNDS",
        verification_status="ACCEPTED",
        epistemic_status="OBSERVED",
        confidence=0.95,
        evidence_refs=[str(ev_file_id)],
    )

    # 5. Finding
    finding = InvestigationFinding(
        id=finding_id,
        case_id=case_id,
        title="Fund Transfer to Mule Node",
        description="Vikram Patel transferred ₹4,80,000 to Account 9876543210 during critical window",
        severity="HIGH",
        confidence=0.95,
        freshness_status="CURRENT",
        evidence_refs=[str(ev_file_id)],
        entity_refs=[str(entity_a_id), str(entity_b_id)],
        fingerprint="FND-TRANSFER-480K",
    )

    resolver = ProvenanceResolver(
        evidence_files=[ef],
        evidence_events=[ev],
        entities=[ent_a, ent_b],
        relationships=[rel],
        findings=[finding],
    )

    # 6. Build Claim with complete provenance
    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-014",
        text="Vikram Patel transferred ₹4,80,000 to Account 9876543210 during the relevant period.",
        claim_type="financial_transfer",
        finding_id=str(finding_id),
        relationship_id=str(rel_id),
        entity_ids=[str(entity_a_id), str(entity_b_id)],
        event_ids=[str(event_id)],
        evidence_ids=[str(ev_file_id)],
        epistemic_status=EpistemicStatus.CONFIRMED,
    )

    assert claim.has_sufficient_provenance is True
    assert claim.provenance_status == ProvenanceStatus.VERIFIED

    # Check granular citation
    assert len(claim.evidence_refs) >= 1
    cit = claim.evidence_refs[0]
    assert cit.evidence_id == str(ev_file_id)
    assert cit.sha256_hash == sha256
    assert cit.source_page == 4
    assert cit.source_line == 23
    assert "[E-9F86D0 · p.4 · line 23]" in cit.citation_label

    # Check full provenance chain steps
    chain = claim.provenance_chain
    assert chain is not None
    assert chain.finding_ref["title"] == "Fund Transfer to Mule Node"
    assert chain.relationship_ref["rel_type"] == "TRANSFERRED_FUNDS"
    assert chain.relationship_ref["source_value"] == "Vikram Patel"
    assert chain.relationship_ref["target_value"] == "Account 9876543210"
    assert any("WhatsApp Chat" in step or "Evidence" in step for step in chain.trace_steps)


def test_missing_provenance_triggers_review_required():
    """
    Negative Guarantee: A claim with nonexistent evidence references or zero citations
    must NEVER be silently approved; it must be flagged with PROVENANCE REVIEW REQUIRED.
    """
    resolver = ProvenanceResolver(
        evidence_files=[],
        evidence_events=[],
        entities=[],
        relationships=[],
        findings=[],
    )

    # 1. Zero citations claim
    claim_empty = resolver.build_claim_provenance(
        claim_id="CLAIM-UNLINKED-001",
        text="Suspect operates three additional unmonitored drop points.",
        claim_type="finding",
    )
    assert claim_empty.provenance_status == ProvenanceStatus.UNLINKED
    assert claim_empty.has_sufficient_provenance is False
    assert any("PROVENANCE REVIEW REQUIRED" in w for w in claim_empty.provenance_chain.warnings)

    # 2. Nonexistent evidence reference
    nonexistent_id = str(uuid.uuid4())
    claim_nonexistent = resolver.build_claim_provenance(
        claim_id="CLAIM-GHOST-002",
        text="Cryptocurrency hardware key seized from suspect residence.",
        claim_type="evidence_inventory",
        evidence_ids=[nonexistent_id],
    )
    assert claim_nonexistent.provenance_status in (ProvenanceStatus.UNLINKED, ProvenanceStatus.REVIEW_REQUIRED)
    assert claim_nonexistent.has_sufficient_provenance is False
    assert any("Nonexistent evidence artifact" in w for w in claim_nonexistent.provenance_chain.warnings)


def test_rejected_relationship_is_never_presented_as_established_fact():
    """
    Negative Guarantee: A relationship marked as REJECTED by investigator adjudication
    must have its epistemic status set to CONTRADICTED and trigger a provenance warning.
    """
    case_id = uuid.uuid4()
    ent_a = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="Alice", entity_type="PERSON")
    ent_b = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="Bob", entity_type="PERSON")

    rejected_rel = Relationship(
        id=uuid.uuid4(),
        case_id=case_id,
        source_entity_id=ent_a.id,
        target_entity_id=ent_b.id,
        relationship_type="CO_CONSPIRATOR",
        verification_status="REJECTED",
        epistemic_status="INFERRED",
        confidence=0.1,
    )

    resolver = ProvenanceResolver(
        evidence_files=[],
        evidence_events=[],
        entities=[ent_a, ent_b],
        relationships=[rejected_rel],
        findings=[],
    )

    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-REJ-001",
        text="Alice is a co-conspirator of Bob.",
        claim_type="relationship",
        relationship_id=str(rejected_rel.id),
        entity_ids=[str(ent_a.id), str(ent_b.id)],
    )

    assert claim.epistemic_status == EpistemicStatus.CONTRADICTED
    assert any("REJECTED by investigator adjudication" in w for w in claim.provenance_chain.warnings)
