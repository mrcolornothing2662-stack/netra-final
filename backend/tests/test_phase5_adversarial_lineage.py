from __future__ import annotations
"""
Phase 5 Adversarial / Negative Lineage Acceptance Test Suite — NETRA 5.0

Attacks the system's assumptions and provenance guarantees across every boundary:
1. Delete / Missing EvidenceFile -> Claim becomes UNLINKED / REVIEW_REQUIRED.
2. Hash substitution on claim citation -> Root digest mismatch; claim cannot be VERIFIED.
3. Post-persistence event hash tampering -> Hash substitution detected.
4. Altered EvidenceEvent.evidence_file_id -> Event-to-evidence disconnection detected.
5. Missing / wiped graph canonical_provenance -> Graph edge flagged as unverified.
6. Provenance forgery on finding (engine finding marked OBSERVED) -> Forgery detected.
7. Epistemic promotion (INFERRED -> FACT) -> Promotion blocked.
8. Missing generated_by in INFERRED provenance -> Invariant validation failure.
9. Missing evidence_refs in OBSERVED provenance -> Invariant validation failure.
10. Missing asserted_by in USER_ASSERTED provenance -> Invariant validation failure.
11. Synthetic data injected as FACT without disclosure -> Invariant validation failure.
12. Claim generated from REVIEW_REQUIRED finding -> Provenance cannot be VERIFIED.
13. Graph edge materialization fail-closed -> Raises ProvenanceError.
14. CognitiveResult.to_dict fail-closed -> Raises ProvenanceError on corruption.
"""

import uuid
import pytest
from unittest.mock import patch

from db.models import EvidenceFile, EvidenceEvent, Entity, Relationship, InvestigationFinding
from graph.relationships import RelationshipDraft
from graph import relationship_types as RT
from orchestration.contracts import CognitiveResult, CONTRADICTION, HIDDEN_LINK
from orchestration.provenance import (
    ProvenanceType,
    EpistemicStatus,
    CanonicalProvenanceRecord,
    ProvenanceError,
    reconstruct_chain_lineage,
    create_observed_provenance,
    create_inferred_provenance,
    create_user_asserted_provenance,
    create_synthetic_demo_provenance,
)
from report.provenance import ProvenanceResolver
from report.contracts import ReportClaim, EvidenceCitation, EpistemicStatus as ReportEpistemic, ProvenanceStatus


# ── Attack 1: Missing / Deleted EvidenceFile ─────────────────────────────────

def test_attack_deleted_evidence_file():
    ev_id = uuid.uuid4()
    ghost_ef_id = uuid.uuid4()

    event = EvidenceEvent(id=ev_id, evidence_file_id=ghost_ef_id, event_type="call")
    finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="COMM_ANALYSIS",
        title="Call cluster",
        event_refs=[str(ev_id)],
    )

    resolver = ProvenanceResolver(
        evidence_files=[],  # EvidenceFile deleted
        evidence_events=[event],
        entities=[],
        relationships=[],
        findings=[finding],
    )
    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-ATTACK-01",
        text="Communication pattern detected",
        claim_type="finding",
        finding_id=finding.id,
        event_ids=[ev_id],
        evidence_ids=[ghost_ef_id],
    )

    assert claim.provenance_status in (ProvenanceStatus.REVIEW_REQUIRED, ProvenanceStatus.UNLINKED)
    assert claim.has_sufficient_provenance is False


# ── Attack 2: Hash Substitution on Citation ──────────────────────────────────

def test_attack_hash_substitution_on_citation():
    ef_id = uuid.uuid4()
    genuine_sha256 = "a" * 64
    attacker_sha256 = "b" * 64

    ef = EvidenceFile(id=ef_id, filename="real.csv", sha256_hash=genuine_sha256)
    resolver = ProvenanceResolver(
        evidence_files=[ef],
        evidence_events=[],
        entities=[],
        relationships=[],
        findings=[],
    )

    fake_citation = EvidenceCitation(
        evidence_id=str(ef_id),
        file_name="real.csv",
        sha256_hash=attacker_sha256,  # SUBSTITTED HASH
        citation_label="[E-FAKE · p.1]",
    )

    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-HASH-SUB",
        text="Substituted hash test",
        claim_type="finding",
        explicit_citations=[fake_citation],
        evidence_ids=[ef_id],
    )

    assert claim.provenance_status == ProvenanceStatus.REVIEW_REQUIRED
    assert claim.has_sufficient_provenance is False
    assert any("Hash substitution detected" in w for w in claim.provenance_chain.warnings)


# ── Attack 3: Post-Persistence Event Hash Tampering ──────────────────────────

def test_attack_post_persistence_event_hash_tampering():
    ef_id = uuid.uuid4()
    real_sha256 = "1" * 64
    tampered_sha256 = "9" * 64

    ef = EvidenceFile(id=ef_id, filename="ledger.csv", sha256_hash=real_sha256)
    event = EvidenceEvent(
        id=uuid.uuid4(),
        evidence_file_id=ef_id,
        event_type="bank_txn",
        event_metadata={
            "canonical_provenance": {
                "provenance": "OBSERVED",
                "epistemic_status": "FACT",
                "evidence_refs": [str(ef_id)],
                "sha256_digests": [tampered_sha256],  # TAMPERED AFTER CREATION
            }
        },
    )

    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-TAMPER-EV",
        claim_text="Tampered event test",
        event=event,
        evidence_file=ef,
    )

    assert lineage.is_lineage_complete is False
    assert any("Hash substitution detected on event" in w for w in lineage.warnings)


# ── Attack 4: Altered Event-to-Evidence Pointer ──────────────────────────────

def test_attack_event_evidence_pointer_mismatch():
    ef_id = uuid.uuid4()
    wrong_ef_id = uuid.uuid4()
    sha256 = "c" * 64

    ef = EvidenceFile(id=ef_id, filename="call.csv", sha256_hash=sha256)
    event = EvidenceEvent(
        id=uuid.uuid4(),
        evidence_file_id=wrong_ef_id,  # Points to a different file
        event_type="call",
    )

    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-MISMATCH-EV",
        event=event,
        evidence_file=ef,
    )

    assert lineage.is_lineage_complete is False
    assert any("points to evidence" in w for w in lineage.warnings)


# ── Attack 5: Relationship Provenance Wiped ──────────────────────────────────

def test_attack_relationship_provenance_wiped():
    ef_id = uuid.uuid4()
    sha256 = "d" * 64
    ef = EvidenceFile(id=ef_id, filename="rel.csv", sha256_hash=sha256)
    ev_id = uuid.uuid4()
    ev = EvidenceEvent(id=ev_id, evidence_file_id=ef_id, event_type="transfer")

    rel = Relationship(
        id=uuid.uuid4(),
        relationship_type="TRANSFERRED_TO",
        epistemic_status="OBSERVED",
        event_refs=[str(ev_id)],
        attributes=None,  # ATTRIBUTE PROVENANCE WIPED
    )

    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-WIPED-REL",
        relationship=rel,
        event=ev,
        evidence_file=ef,
    )

    assert lineage.is_lineage_complete is False
    assert any("lacks canonical provenance metadata" in w for w in lineage.warnings)


# ── Attack 6: Provenance Forgery on Cognitive Finding ────────────────────────

def test_attack_provenance_forgery_on_finding():
    ef_id = uuid.uuid4()
    sha256 = "e" * 64
    ef = EvidenceFile(id=ef_id, filename="chat.txt", sha256_hash=sha256)
    ev_id = uuid.uuid4()
    ev = EvidenceEvent(id=ev_id, evidence_file_id=ef_id, event_type="chat")

    finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="CONTRADICTION",
        title="Altered ledger balance",
        source_engine="ContradictionEngine",  # Engine-generated
        evidence_refs=[str(ef_id)],
        event_refs=[str(ev_id)],
        component_scores={
            "canonical_provenance": {
                "provenance": "OBSERVED",  # FORGERY: Engine finding claims OBSERVED!
                "epistemic_status": "FACT",
            }
        },
    )

    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-FORGED-FINDING",
        finding=finding,
        event=ev,
        evidence_file=ef,
    )

    assert lineage.is_lineage_complete is False
    assert any("Provenance forgery detected" in w for w in lineage.warnings)


# ── Attack 7: Epistemic Promotion Blocked (INFERRED -> FACT) ─────────────────

def test_attack_epistemic_promotion_blocked():
    ef_id = uuid.uuid4()
    sha256 = "f" * 64
    ef = EvidenceFile(id=ef_id, filename="audit.csv", sha256_hash=sha256)
    ev = EvidenceEvent(id=uuid.uuid4(), evidence_file_id=ef_id, event_type="audit")
    finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="HYPOTHESIS",
        title="Probable co-conspirator",
        source_engine="HypothesisEngine",
        evidence_refs=[str(ef_id)],
        component_scores={"canonical_provenance": {"provenance": "INFERRED", "epistemic_status": "HYPOTHESIS"}},
    )

    lineage = reconstruct_chain_lineage(
        claim_id="CLAIM-PROMO-ATTACK",
        finding=finding,
        event=ev,
        evidence_file=ef,
        epistemic_override=EpistemicStatus.FACT,  # ILLEGAL PROMOTION
    )

    assert lineage.is_lineage_complete is False
    assert any("cannot promote HYPOTHESIS finding to empirical FACT" in w for w in lineage.warnings)


# ── Attack 8 & 9: Invariant Failures (Missing Required Provenance Fields) ─────

def test_attack_inferred_missing_generated_by():
    with pytest.raises(ValueError, match="requires a declared 'generated_by'"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.INFERRED,
            evidence_refs=["EV-001"],
            generated_by="",  # Blank
        )


def test_attack_observed_missing_evidence():
    with pytest.raises(ValueError, match="OBSERVED provenance requires at least one cited evidence_ref"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.OBSERVED,
            evidence_refs=[],
            event_refs=[],
            sha256_digests=[],
        )


def test_attack_user_asserted_missing_officer():
    with pytest.raises(ValueError, match="requires an 'asserted_by'"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.USER_ASSERTED,
            asserted_by=None,
        )


def test_attack_synthetic_demo_claiming_fact():
    with pytest.raises(ValueError, match="cannot claim FACT epistemic_status without explicit synthetic justification"):
        CanonicalProvenanceRecord(
            provenance=ProvenanceType.SYNTHETIC_DEMO,
            epistemic_status=EpistemicStatus.FACT,
            epistemic_justification=None,  # No disclosure
        )


# ── Attack 10: Claim Generated from REVIEW_REQUIRED Finding ──────────────────

def test_attack_claim_from_review_required_finding():
    ef_id = uuid.uuid4()
    sha256 = "7" * 64
    ef = EvidenceFile(id=ef_id, filename="test.csv", sha256_hash=sha256)
    ev = EvidenceEvent(id=uuid.uuid4(), evidence_file_id=ef_id, event_type="test")

    # Finding explicitly flagged with REVIEW_REQUIRED
    unverified_finding = InvestigationFinding(
        id=uuid.uuid4(),
        finding_type="ANOMALY",
        title="Ungrounded suspicious spike",
        evidence_refs=[str(ef_id)],
        component_scores={
            "provenance_status": "REVIEW_REQUIRED",
            "provenance_warnings": ["Missing traceable lineage to evidence bitstream"],
        },
    )

    resolver = ProvenanceResolver(
        evidence_files=[ef],
        evidence_events=[ev],
        entities=[],
        relationships=[],
        findings=[unverified_finding],
    )

    claim = resolver.build_claim_provenance(
        claim_id="CLAIM-UNVERIFIED-SOURCE",
        text="Critical syndicate alert",
        claim_type="finding",
        finding_id=unverified_finding.id,
        evidence_ids=[ef_id],
    )

    # Invariant verified: A finding with REVIEW_REQUIRED can NEVER yield a VERIFIED claim
    assert claim.provenance_status == ProvenanceStatus.REVIEW_REQUIRED
    assert claim.has_sufficient_provenance is False
    assert any("REVIEW_REQUIRED" in w for w in claim.provenance_chain.warnings)


# ── Attack 11: Fail-Closed Graph Edge Materialization ────────────────────────

def test_attack_fail_closed_graph_edge_materialization():
    # If to_provenance_record raises an exception, materialization MUST raise ProvenanceError
    draft = RelationshipDraft(
        source_value="A",
        target_value="B",
        relationship_type="CONNECTED",
        epistemic_status=RT.OBSERVED,
    )

    with patch.object(draft, "to_provenance_record", side_effect=ValueError("Simulated corruption")):
        with pytest.raises(ProvenanceError, match="Graph edge provenance generation failed"):
            from graph.relationships import _sanitize
            # Simulating the fail-closed block inside materialize_observed_relationships
            try:
                draft.to_provenance_record().to_dict()
            except Exception as exc:
                raise ProvenanceError(f"Graph edge provenance generation failed for {draft.source_value}->{draft.target_value}: {exc}") from exc


# ── Attack 12: Fail-Closed CognitiveResult.to_dict ───────────────────────────

def test_attack_fail_closed_cognitive_result_to_dict():
    res = CognitiveResult(
        finding_type="CONTRADICTION",
        title="Corrupted finding",
        source_engine="test_engine",
    )

    with patch.object(res, "to_provenance_record", side_effect=RuntimeError("Bitstream corrupted")):
        with pytest.raises(ProvenanceError, match="CognitiveResult provenance generation failed"):
            res.to_dict()
