from __future__ import annotations
"""
NETRA 5.0 — Canonical Provenance & Epistemic Contract (Phase 2)

Establishes a single authoritative provenance vocabulary and chain-of-custody
contract across the backend:

1. ProvenanceType:
   - OBSERVED:       Directly present in supplied evidence (parsed files/events).
   - INFERRED:       Derived by NETRA's analytical / cognitive / graph engines.
   - USER_ASSERTED:  Entered, tagged, or explicitly confirmed by an investigator.
   - SYNTHETIC_DEMO: Generated test/demo data (strictly isolated from real evidence).

2. EpistemicStatus:
   - FACT:             Directly evidenced empirical fact.
   - DERIVED_ANALYSIS: Deterministically or probabilistically calculated from evidence.
   - HYPOTHESIS:       Tentative analytical proposal or potential scenario.
   - ALLEGED:          Stated in complaints, FIR, or witness statements without proof.
   - DISPUTED:         Conflicted by contradictory evidence or counter-findings.
   - UNRESOLVED:       Ambiguous candidate identity or discrepancy needing adjudication.

3. Target Evidentiary Chain:
   EvidenceFile (SHA-256)
        │
        ↓
   EvidenceEvent (page/line)
        │
        ↓
   Entity / Relationship
        │
        ↓
   Finding (CognitiveResult / InvestigationFinding)
        │
        ↓
   Claim (ReportClaim / Copilot Claim)
        │
        ↓
   Report / Output (Section 65B Dossier / Copilot RAG)

Negative Guarantees:
- OBSERVED records MUST cite at least one evidence_ref or event_ref.
- INFERRED records MUST declare generated_by and link to underlying inputs.
- USER_ASSERTED records MUST declare asserted_by.
- SYNTHETIC_DEMO records can never claim unflagged FACT status.
- No object may jump over the chain without explicitly declaring why.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field, model_validator


class ProvenanceType(str, Enum):
    """Canonical vocabulary for origin of any forensic object in NETRA."""
    OBSERVED       = "OBSERVED"
    INFERRED       = "INFERRED"
    USER_ASSERTED  = "USER_ASSERTED"
    SYNTHETIC_DEMO = "SYNTHETIC_DEMO"

    @classmethod
    def from_str(cls, value: str | None) -> ProvenanceType:
        if not value:
            return cls.INFERRED
        norm = str(value).strip().upper()
        if norm in cls.__members__:
            return cls[norm]
        if norm in ("CONFIRMED", "DIRECT", "EMPIRICAL"):
            return cls.OBSERVED
        if norm in ("DERIVED", "COMPUTED", "AI", "ALGORITHMIC"):
            return cls.INFERRED
        if norm in ("USER", "MANUAL", "INVESTIGATOR"):
            return cls.USER_ASSERTED
        if norm in ("SYNTHETIC", "DEMO", "MOCK", "TEST"):
            return cls.SYNTHETIC_DEMO
        return cls.INFERRED


class EpistemicStatus(str, Enum):
    """Epistemic dimension describing evidentiary certainty / modality."""
    FACT             = "FACT"
    DERIVED_ANALYSIS = "DERIVED_ANALYSIS"
    HYPOTHESIS       = "HYPOTHESIS"
    ALLEGED          = "ALLEGED"
    DISPUTED         = "DISPUTED"
    UNRESOLVED       = "UNRESOLVED"

    @classmethod
    def from_str(cls, value: str | None) -> EpistemicStatus:
        if not value:
            return cls.DERIVED_ANALYSIS
        norm = str(value).strip().upper()
        if norm in cls.__members__:
            return cls[norm]
        if norm in ("CONFIRMED", "ESTABLISHED"):
            return cls.FACT
        if norm in ("INFERRED", "DERIVED", "COMPUTED"):
            return cls.DERIVED_ANALYSIS
        if norm in ("THEORY", "POTENTIAL", "SPECULATION"):
            return cls.HYPOTHESIS
        if norm in ("COMPLAINT", "REPORTED"):
            return cls.ALLEGED
        if norm in ("CONTRADICTED", "CONFLICTING"):
            return cls.DISPUTED
        if norm in ("PENDING", "AMBIGUOUS", "CANDIDATE"):
            return cls.UNRESOLVED
        return cls.DERIVED_ANALYSIS


class ChainTier(str, Enum):
    """Levels in the canonical evidence-to-output chain."""
    EVIDENCE_FILE  = "EVIDENCE_FILE"   # Tier 0: Bitstream with SHA-256
    EVIDENCE_EVENT = "EVIDENCE_EVENT"  # Tier 1: Parsed timestamped/located event
    GRAPH_ELEMENT  = "GRAPH_ELEMENT"   # Tier 2: Entity / Relationship
    FINDING        = "FINDING"         # Tier 3: InvestigationFinding / CognitiveResult
    CLAIM          = "CLAIM"           # Tier 4: Explicit claim in brief/dossier
    OUTPUT         = "OUTPUT"          # Tier 5: Report / Copilot RAG / Section 65B


class CanonicalProvenanceRecord(BaseModel):
    """
    Canonical, tamper-evident provenance record attached to any NETRA object.
    """
    provenance: ProvenanceType = ProvenanceType.INFERRED
    epistemic_status: EpistemicStatus = EpistemicStatus.DERIVED_ANALYSIS
    evidence_refs: List[str] = Field(default_factory=list, description="UUIDs of underlying EvidenceFiles")
    event_refs: List[str] = Field(default_factory=list, description="UUIDs of underlying EvidenceEvents")
    entity_refs: List[str] = Field(default_factory=list, description="UUIDs or canonical values of Entities")
    finding_refs: List[str] = Field(default_factory=list, description="UUIDs of InvestigationFindings")
    claim_refs: List[str] = Field(default_factory=list, description="UUIDs of ReportClaims")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    generated_by: Optional[str] = Field(default=None, description="Analytical engine or parser ID")
    asserted_by: Optional[str] = Field(default=None, description="Investigator username/ID if USER_ASSERTED")
    method: Optional[str] = Field(default=None, description="Methodology or rule used")
    sha256_digests: List[str] = Field(default_factory=list, description="SHA-256 digests of cited evidence files")
    epistemic_justification: Optional[str] = Field(default=None, description="Explanation if jumping chain tiers")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def validate_canonical_invariants(self) -> CanonicalProvenanceRecord:
        """
        Enforce strict negative guarantees on creation.
        """
        # 1. OBSERVED must cite physical evidence or events
        if self.provenance == ProvenanceType.OBSERVED:
            if not self.evidence_refs and not self.event_refs and not self.sha256_digests:
                raise ValueError(
                    "OBSERVED provenance requires at least one cited evidence_ref, event_ref, or sha256_digest."
                )

        # 2. INFERRED must declare engine/method and source references
        elif self.provenance == ProvenanceType.INFERRED:
            if not self.generated_by:
                raise ValueError(
                    "INFERRED provenance requires a declared 'generated_by' analytical engine or module."
                )
            if not (self.evidence_refs or self.event_refs or self.entity_refs or self.finding_refs):
                if not self.epistemic_justification:
                    raise ValueError(
                        "INFERRED provenance must cite underlying source references (evidence, events, entities, or findings) "
                        "or provide an explicit 'epistemic_justification'."
                    )

        # 3. USER_ASSERTED must declare investigator identity
        elif self.provenance == ProvenanceType.USER_ASSERTED:
            if not self.asserted_by:
                raise ValueError(
                    "USER_ASSERTED provenance requires an 'asserted_by' investigator identifier."
                )

        # 4. SYNTHETIC_DEMO cannot masquerade as unflagged empirical FACT
        elif self.provenance == ProvenanceType.SYNTHETIC_DEMO:
            if self.epistemic_status == EpistemicStatus.FACT:
                if not self.epistemic_justification or "synthetic" not in self.epistemic_justification.lower():
                    raise ValueError(
                        "SYNTHETIC_DEMO data cannot claim FACT epistemic_status without explicit synthetic justification."
                    )

        return self

    def has_evidence_lineage(self) -> bool:
        """True if directly or transitively anchored in raw evidence bitstreams."""
        return bool(self.evidence_refs or self.event_refs or self.sha256_digests)

    def validate_chain_integrity(self) -> Tuple[bool, List[str]]:
        """
        Audits chain integrity and returns (is_intact, list_of_violations_or_warnings).
        """
        issues: List[str] = []

        if self.provenance == ProvenanceType.OBSERVED:
            if not self.has_evidence_lineage():
                issues.append("Missing root evidence file or event reference for OBSERVED object.")
            if self.epistemic_status not in (EpistemicStatus.FACT, EpistemicStatus.ALLEGED):
                issues.append(f"Unusual epistemic status '{self.epistemic_status}' for OBSERVED evidence.")

        elif self.provenance == ProvenanceType.INFERRED:
            if not self.generated_by:
                issues.append("Missing 'generated_by' engine for INFERRED object.")
            if not self.has_evidence_lineage() and not self.finding_refs:
                issues.append("INFERRED object lacks traceable lineage back to evidence or intermediate findings.")
            if self.epistemic_status == EpistemicStatus.FACT and not self.epistemic_justification:
                issues.append("INFERRED object cannot claim FACT status without documented deterministic justification.")

        elif self.provenance == ProvenanceType.USER_ASSERTED:
            if not self.asserted_by:
                issues.append("Missing 'asserted_by' for USER_ASSERTED object.")

        elif self.provenance == ProvenanceType.SYNTHETIC_DEMO:
            if self.epistemic_status == EpistemicStatus.FACT:
                issues.append("SYNTHETIC_DEMO objects cannot claim FACT status in legal proceedings.")

        return (len(issues) == 0, issues)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class EvidenceChainLink(BaseModel):
    """
    Represents a single verified link in the chain:
    EvidenceFile -> Event -> Entity/Rel -> Finding -> Claim -> Report
    """
    tier: ChainTier
    identifier: str
    label: str
    sha256: Optional[str] = None
    provenance: ProvenanceType
    epistemic_status: EpistemicStatus
    parent_tier: Optional[ChainTier] = None
    parent_refs: List[str] = Field(default_factory=list)
    is_anchored: bool = True
    gap_reason: Optional[str] = None


class ChainLineageTrace(BaseModel):
    """
    Full audit trail tracing an object back through all chain tiers to root evidence bitstreams.
    """
    target_id: str
    target_tier: ChainTier
    is_lineage_complete: bool = True
    root_evidence_files: List[str] = Field(default_factory=list)
    root_sha256_digests: List[str] = Field(default_factory=list)
    links: List[EvidenceChainLink] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    epistemic_summary: str = ""


def create_observed_provenance(
    evidence_id: str,
    event_id: Optional[str] = None,
    sha256: Optional[str] = None,
    method: str = "direct_ingestion",
) -> CanonicalProvenanceRecord:
    """Helper to create a validated OBSERVED provenance record for raw evidence."""
    return CanonicalProvenanceRecord(
        provenance=ProvenanceType.OBSERVED,
        epistemic_status=EpistemicStatus.FACT,
        evidence_refs=[evidence_id] if evidence_id else [],
        event_refs=[event_id] if event_id else [],
        sha256_digests=[sha256] if sha256 else [],
        confidence=1.0,
        method=method,
    )


def create_inferred_provenance(
    engine_name: str,
    confidence: float,
    evidence_refs: Optional[List[str]] = None,
    event_refs: Optional[List[str]] = None,
    entity_refs: Optional[List[str]] = None,
    finding_refs: Optional[List[str]] = None,
    epistemic_status: EpistemicStatus = EpistemicStatus.DERIVED_ANALYSIS,
    method: Optional[str] = None,
) -> CanonicalProvenanceRecord:
    """Helper to create a validated INFERRED provenance record for analytical engines."""
    return CanonicalProvenanceRecord(
        provenance=ProvenanceType.INFERRED,
        epistemic_status=epistemic_status,
        generated_by=engine_name,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        event_refs=event_refs or [],
        entity_refs=entity_refs or [],
        finding_refs=finding_refs or [],
        method=method,
    )


def create_user_asserted_provenance(
    officer_id: str,
    epistemic_status: EpistemicStatus = EpistemicStatus.ALLEGED,
    notes: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
) -> CanonicalProvenanceRecord:
    """Helper to create a validated USER_ASSERTED provenance record for investigator input."""
    return CanonicalProvenanceRecord(
        provenance=ProvenanceType.USER_ASSERTED,
        epistemic_status=epistemic_status,
        asserted_by=officer_id,
        evidence_refs=evidence_refs or [],
        epistemic_justification=notes,
    )


def create_synthetic_demo_provenance(
    generator_name: str = "demo_generator",
    scenario: str = "sih_demo_scenario",
) -> CanonicalProvenanceRecord:
    """Helper to create a validated SYNTHETIC_DEMO provenance record for test/demo data."""
    return CanonicalProvenanceRecord(
        provenance=ProvenanceType.SYNTHETIC_DEMO,
        epistemic_status=EpistemicStatus.DERIVED_ANALYSIS,
        generated_by=generator_name,
        confidence=0.99,
        epistemic_justification=f"Synthetic demonstration data for {scenario}",
    )
