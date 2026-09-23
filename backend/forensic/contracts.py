from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Unified Forensic Lens Contracts
Strict Pydantic schemas enforcing identical structure across all lenses:
- Summary
- Entities
- Events
- Relationships
- Signals
- Findings
- Evidence
- Timeline
- Cross-Lens Signals
"""
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ForensicLensType(str, Enum):
    MONEY = "MONEY"
    COMMUNICATION = "COMMUNICATION"
    GEOGRAPHIC = "GEOGRAPHIC"


class LensEntity(BaseModel):
    id: str
    canonical_value: str
    entity_type: str
    role: Optional[str] = None
    degree_centrality: float = 0.0
    bridge_score: float = 0.0
    mention_count: int = 0
    node_metadata: dict[str, Any] = Field(default_factory=dict)


class LensEvent(BaseModel):
    id: str
    event_type: str
    event_time: Optional[str] = None
    recorded_at: str
    time_confidence: str = "CONFIRMED"  # CONFIRMED | APPROXIMATE | NORMALIZED | RECORDED_ONLY
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_file_id: Optional[str] = None
    source_doc: Optional[str] = None
    source_page: Optional[int] = None
    source_line: Optional[int] = None
    provenance_confidence: Optional[float] = None
    time_warning: Optional[str] = None


class LensRelationship(BaseModel):
    id: str
    source_entity_id: str
    source_entity_value: Optional[str] = None
    target_entity_id: str
    target_entity_value: Optional[str] = None
    relationship_type: str
    direction: str = "OUTBOUND"
    epistemic_status: str = "OBSERVED"
    verification_status: str = "UNREVIEWED"
    is_canonical: bool = False
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    created_by: Optional[str] = None


class LensSignal(BaseModel):
    id: str
    signal_type: str  # RAPID_TRANSFER | ROUND_NUMBER_TXN | COMMUNICATION_BURST | NIGHT_ACTIVITY | TOWER_HOPPING
    severity: str = "INFO"  # INFO | LOW | MEDIUM | HIGH | CRITICAL
    title: str
    description: str
    timestamp: Optional[str] = None
    entities_involved: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class LensFinding(BaseModel):
    id: str
    finding_type: str
    title: str
    severity: str
    confidence: float = 0.8
    status: str
    freshness_status: str = "CURRENT"
    generated_at_case_version: int = 1
    evidence_refs: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    event_refs: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    id: str
    file_name: str
    file_type: Optional[str] = None
    sha256: Optional[str] = None
    uploaded_at: Optional[str] = None


class LensTimelineEvent(BaseModel):
    id: str
    timestamp: Optional[str] = None
    label: str
    category: str
    entities: list[str] = Field(default_factory=list)
    evidence_id: Optional[str] = None
    source_doc: Optional[str] = None
    source_page: Optional[int] = None
    source_line: Optional[int] = None
    disclaimer: Optional[str] = None


class CrossLensSignal(BaseModel):
    id: str
    title: str
    description: str
    lenses_involved: list[str] = Field(default_factory=list)  # ["MONEY", "COMMUNICATION", "GEOGRAPHIC"]
    time_window: dict[str, Optional[str]] = Field(default_factory=dict)
    entities_involved: list[str] = Field(default_factory=list)
    events_involved: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.85


class ForensicLensResponse(BaseModel):
    id: str  # "MONEY" | "COMMUNICATION" | "GEOGRAPHIC"
    case_id: str
    case_number: str
    title: str
    state_version: int
    is_historical: bool
    disclaimer: Optional[str] = None
    summary: dict[str, Any]
    entities: list[LensEntity]
    events: list[LensEvent]
    relationships: list[LensRelationship]
    signals: list[LensSignal]
    findings: list[LensFinding]
    evidence_refs: list[EvidenceRef]
    timeline: list[LensTimelineEvent]
    cross_lens_signals: list[CrossLensSignal]


class LensOverviewResponse(BaseModel):
    case_id: str
    case_number: str
    title: str
    state_version: int
    money_summary: dict[str, Any]
    communications_summary: dict[str, Any]
    geographic_summary: dict[str, Any]
    cross_lens_coincidences_count: int
    active_lenses: list[str]
