from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Report Contracts
Defines explicit evidentiary claim models, provenance chains, report sections,
and immutable snapshot schemas for Investigation Intelligence Briefs and Formal Dossiers.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class EpistemicStatus(str, Enum):
    CONFIRMED    = "confirmed"
    INFERRED     = "inferred"
    ALLEGED      = "alleged"
    DISPUTED     = "disputed"
    CONTRADICTED = "contradicted"


class ConfidenceStatus(str, Enum):
    HIGH       = "high"
    MEDIUM     = "medium"
    LOW        = "low"
    UNVERIFIED = "unverified"


class ProvenanceStatus(str, Enum):
    VERIFIED        = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNLINKED        = "UNLINKED"


class ReportType(str, Enum):
    INTELLIGENCE_BRIEF = "intelligence_brief"
    FORMAL_DOSSIER     = "formal_dossier"


class ReportLifecycleStatus(str, Enum):
    DRAFT            = "DRAFT"
    REVIEW           = "REVIEW"
    READY_FOR_EXPORT = "READY_FOR_EXPORT"
    APPROVED         = "APPROVED"
    EXPORTED         = "EXPORTED"
    REJECTED         = "REJECTED"


class EvidenceCitation(BaseModel):
    """
    Direct granular reference to a piece of seized evidence, including
    exact source page, line number, and cryptographic bitstream digest.
    """
    evidence_id: str = Field(..., description="UUID of EvidenceFile")
    file_name: str = Field(..., description="Original filename of the evidence artifact")
    sha256_hash: str = Field(..., description="Section 63 BSA / 65B SHA-256 digest")
    source_page: Optional[int] = Field(None, description="Physical/logical page number in source document")
    source_line: Optional[int] = Field(None, description="Line number or transcript row index")
    event_id: Optional[str] = Field(None, description="UUID of EvidenceEvent if linked")
    citation_label: str = Field(..., description="Human-readable citation label, e.g. [E-017 · p.4 · line 23]")
    source_type: Optional[str] = Field(None, description="E.g. cdr, whatsapp, bank_txn, document_text, cctv")

    class Config:
        frozen = True


class ProvenanceChain(BaseModel):
    """
    End-to-end provenance trajectory tracing from claim to underlying bitstream.
    Claim -> Finding -> Relationship -> EvidenceEvent -> EvidenceFile -> SHA-256
    """
    claim_id: str
    finding_ref: Optional[Dict[str, Any]] = None
    relationship_ref: Optional[Dict[str, Any]] = None
    entity_refs: List[Dict[str, Any]] = Field(default_factory=list)
    event_refs: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_files: List[Dict[str, Any]] = Field(default_factory=list)
    provenance_status: ProvenanceStatus = ProvenanceStatus.UNLINKED
    trace_steps: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    class Config:
        frozen = True


class ReportClaim(BaseModel):
    """
    Explicit atomic claim contract.
    No analytical statement in NETRA is rendered without an underlying claim contract.
    If provenance is missing or ambiguous, it is visibly flagged as REVIEW_REQUIRED.
    """
    claim_id: str = Field(..., description="Unique claim identifier, e.g. CLAIM-001")
    text: str = Field(..., description="Analytical claim text")
    claim_type: str = Field(
        ...,
        description="E.g. finding, relationship, financial_signal, communication_signal, geographic_signal, identity, hypothesis, limitation, investigator_action"
    )
    epistemic_status: EpistemicStatus = EpistemicStatus.INFERRED
    confidence_status: ConfidenceStatus = ConfidenceStatus.MEDIUM
    entity_refs: List[str] = Field(default_factory=list, description="List of canonical entity IDs or labels")
    relationship_refs: List[str] = Field(default_factory=list, description="List of relationship IDs")
    event_refs: List[str] = Field(default_factory=list, description="List of event IDs")
    finding_refs: List[str] = Field(default_factory=list, description="List of finding IDs")
    evidence_refs: List[EvidenceCitation] = Field(default_factory=list, description="List of granular evidence citations")
    limitations: List[str] = Field(default_factory=list, description="Known technical or investigative limitations")
    generated_from: str = Field("investigation_brain", description="Component or engine that produced the claim")
    provenance_chain: Optional[ProvenanceChain] = None
    provenance_status: ProvenanceStatus = ProvenanceStatus.UNLINKED

    @property
    def has_sufficient_provenance(self) -> bool:
        return self.provenance_status == ProvenanceStatus.VERIFIED and len(self.evidence_refs) > 0

    def to_canonical_provenance(self):
        from orchestration.provenance import (
            CanonicalProvenanceRecord,
            EpistemicStatus as CanonicalEpistemicStatus,
            ProvenanceType,
        )
        ev_ids = [c.evidence_id for c in self.evidence_refs if c.evidence_id]
        hashes = [c.sha256_hash for c in self.evidence_refs if c.sha256_hash]

        if self.claim_type in ("evidence_inventory", "direct_observation") and len(ev_ids) > 0:
            prov_type = ProvenanceType.OBSERVED
            epistemic = CanonicalEpistemicStatus.FACT
        else:
            prov_type = ProvenanceType.INFERRED
            raw_ep = self.epistemic_status.value if hasattr(self.epistemic_status, 'value') else str(self.epistemic_status)
            epistemic = CanonicalEpistemicStatus.from_str(raw_ep)

        return CanonicalProvenanceRecord(
            provenance=prov_type,
            epistemic_status=epistemic,
            evidence_refs=ev_ids,
            event_refs=list(self.event_refs),
            entity_refs=list(self.entity_refs),
            finding_refs=list(self.finding_refs),
            claim_refs=[self.claim_id],
            generated_by=self.generated_from or "report_builder",
            sha256_digests=hashes,
            method=self.claim_type,
        )


class ReportSection(BaseModel):
    """
    Reusable, modular section of an Investigation Intelligence Brief or Formal Dossier.
    """
    section_id: str = Field(..., description="Unique section key, e.g. case_summary, chronology, findings")
    title: str = Field(..., description="Display title of the section")
    order: int = Field(..., description="Sort order within the document")
    summary: Optional[str] = Field(None, description="High-level narrative or takeaway")
    claims: List[ReportClaim] = Field(default_factory=list, description="Atomic claims in this section")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured tabular data payload")
    limitations: List[str] = Field(default_factory=list, description="Section-specific constraints or disclaimers")


class ReportSnapshotMetadata(BaseModel):
    """
    Cryptographically verifiable metadata for reproducible report snapshots.
    """
    report_id: str
    case_id: str
    case_number: str
    case_title: str
    report_type: ReportType
    status: ReportLifecycleStatus = ReportLifecycleStatus.DRAFT
    case_state_version: int
    template_version: str = "v1.0"
    content_hash: str
    title: str
    summary: Optional[str] = None
    generated_by: Optional[str] = None
    generated_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    claims_count: int = 0
    linked_claims_count: int = 0
    review_required_claims_count: int = 0
    export_approval_id: Optional[str] = None


class ReportPayload(BaseModel):
    """
    Full serializable report tree stored in ReportSnapshot.payload.
    """
    metadata: ReportSnapshotMetadata
    sections: List[ReportSection]
    statutory_provisions: Dict[str, str] = Field(default_factory=dict)
    provenance_summary: Dict[str, Any] = Field(default_factory=dict)

    def get_section(self, section_id: str) -> Optional[ReportSection]:
        """Find a report section by section_id."""
        return next((s for s in self.sections if s.section_id == section_id), None)


# API Request/Response DTOs

class ReportGenerateRequest(BaseModel):
    report_type: ReportType = Field(ReportType.INTELLIGENCE_BRIEF, description="Report type")
    title: Optional[str] = Field(None, description="Optional custom report title")
    include_draft_findings: bool = Field(True, description="Whether to include unconfirmed hypotheses")
    section_keys: Optional[List[str]] = Field(None, description="Subset of section keys to include")


class ReportReviewBody(BaseModel):
    action: str = Field(..., description="'APPROVE' or 'REJECT'")
    rejection_reason: Optional[str] = Field(None, description="Mandatory when rejecting a report")


class EvidenceUsageFinding(BaseModel):
    id: str
    title: str
    severity: str
    freshness_status: str


class EvidenceUsageClaim(BaseModel):
    claim_id: str
    text: str
    report_type: str
    report_id: str


class EvidenceUsageRelationship(BaseModel):
    id: str
    rel_type: str
    source_name: str
    target_name: str
    status: str


class EvidenceUsageResponse(BaseModel):
    evidence_id: str
    case_id: str
    filename: str
    sha256_hash: str
    file_size_bytes: Optional[int] = None
    upload_status: str
    findings: List[EvidenceUsageFinding] = Field(default_factory=list)
    claims: List[EvidenceUsageClaim] = Field(default_factory=list)
    relationships: List[EvidenceUsageRelationship] = Field(default_factory=list)
    total_usages: int = 0
