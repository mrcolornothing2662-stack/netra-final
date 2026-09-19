"""
CyberDrishti AI — SQLAlchemy ORM Models
Mirrors init_db.sql exactly; used for queries and type-safe access.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime,
    Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, JSON, Uuid
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY, JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, relationship, backref
from sqlalchemy.sql import func

# Cross-dialect type wrappers supporting both PostgreSQL and SQLite
def ARRAY(item_type):
    return PG_ARRAY(item_type).with_variant(JSON, "sqlite")

JSONB = PG_JSONB().with_variant(JSON, "sqlite")
UUID = lambda as_uuid=True: PG_UUID(as_uuid=as_uuid).with_variant(Uuid(as_uuid=as_uuid), "sqlite")


class Base(DeclarativeBase):
    pass


# ── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username       = Column(String(64), nullable=False, unique=True)
    email          = Column(String(256), nullable=False, unique=True)
    hashed_password = Column(String(256), nullable=False)
    full_name      = Column(String(128))
    rank           = Column(String(64))
    unit           = Column(String(128))
    role           = Column(String(32), nullable=False, default="constable")
    is_active      = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=False)
    totp_secret    = Column(String(64), nullable=True)
    totp_enabled   = Column(Boolean, nullable=False, default=False)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until   = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # relationships
    cases           = relationship("Case", back_populates="assigned_officer", foreign_keys="Case.assigned_officer_id")
    uploaded_files  = relationship("EvidenceFile", back_populates="uploader")
    audit_entries   = relationship("AuditLog", back_populates="user")
    verified_links  = relationship("Correlation", back_populates="verifier")

    __table_args__ = (
        CheckConstraint("role IN ('constable','io','fiu_analyst','admin')", name="ck_users_role"),
    )


# ── Cases ────────────────────────────────────────────────────────────────────

class Case(Base):
    __tablename__ = "cases"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_number         = Column(String(64), nullable=False, unique=True)
    title               = Column(String(256), nullable=False)
    description         = Column(Text)
    crime_type          = Column(String(64))
    fir_number          = Column(String(64))
    police_station      = Column(String(128))
    priority            = Column(String(16), nullable=False, default="medium")
    status              = Column(String(32), nullable=False, default="open")
    assigned_officer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    tags                = Column(ARRAY(Text))
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at           = Column(DateTime(timezone=True))

    # relationships
    assigned_officer = relationship("User", back_populates="cases", foreign_keys=[assigned_officer_id])
    evidence_files   = relationship("EvidenceFile", back_populates="case", cascade="all, delete-orphan")
    evidence_events  = relationship("EvidenceEvent", back_populates="case", cascade="all, delete-orphan")
    entities         = relationship("Entity", back_populates="case", cascade="all, delete-orphan")
    correlations     = relationship("Correlation", back_populates="case", cascade="all, delete-orphan")
    relationships    = relationship("Relationship", back_populates="case", cascade="all, delete-orphan")
    findings         = relationship("InvestigationFinding", back_populates="case", cascade="all, delete-orphan")
    analysis_runs    = relationship("AnalysisRun", back_populates="case", cascade="all, delete-orphan")
    intelligence_state = relationship("CaseIntelligenceState", back_populates="case", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("priority IN ('high','medium','low')", name="ck_cases_priority"),
        CheckConstraint("status IN ('open','in_progress','under_review','closed','on_hold')", name="ck_cases_status"),
        Index("idx_cases_status", "status"),
        Index("idx_cases_priority", "priority"),
    )


# ── Evidence Files ───────────────────────────────────────────────────────────

class EvidenceFile(Base):
    __tablename__ = "evidence_files"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id         = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    filename        = Column(String(512), nullable=False)
    original_name   = Column(String(512), nullable=False)
    file_type       = Column(String(32), nullable=False)
    source_type     = Column(String(32))
    file_size_bytes = Column(BigInteger)
    sha256_hash     = Column(String(64), nullable=False)
    storage_path    = Column(Text, nullable=False)
    upload_status   = Column(String(32), nullable=False, default="pending")
    parse_error     = Column(Text)
    uploaded_by     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at     = Column(DateTime(timezone=True), server_default=func.now())
    processed_at    = Column(DateTime(timezone=True))

    # Document Version Timeline (F01) lineage fields
    parent_evidence_id = Column(UUID(as_uuid=True), ForeignKey("evidence_files.id", ondelete="SET NULL"), nullable=True)
    version_number     = Column(Integer, default=1, nullable=False)
    version_status     = Column(String(32), default="original", nullable=False)  # "original" | "variant" | "superseded"
    fingerprint_hash   = Column(String(64))
    variant_details    = Column(JSONB, default=dict)

    # Source Device & Forensic Integrity
    source_device_hash  = Column(String(64), nullable=True)
    acquisition_tool    = Column(String(128), nullable=True)
    acquisition_timestamp = Column(DateTime(timezone=True), nullable=True)
    officer_notes       = Column(Text, nullable=True)

    # Envelope Encryption at Rest
    is_encrypted        = Column(Boolean, nullable=False, default=False)
    encrypted_dek       = Column(Text, nullable=True)
    encryption_iv       = Column(String(64), nullable=True)

    case     = relationship("Case", back_populates="evidence_files")
    uploader = relationship("User", back_populates="uploaded_files")
    events   = relationship("EvidenceEvent", back_populates="evidence_file")
    variants = relationship("EvidenceFile", backref=backref("parent_evidence", remote_side=[id], lazy="selectin"), lazy="selectin")

    __table_args__ = (
        UniqueConstraint("case_id", "sha256_hash", name="uq_evidence_case_sha256"),
        UniqueConstraint("storage_path", name="uq_evidence_storage_path"),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="ck_evidence_size"),
    )


# ── Case Collaborators ───────────────────────────────────────────────────────

class CaseCollaborator(Base):
    __tablename__ = "case_collaborators"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id     = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role        = Column(String(32), nullable=False, default="io")
    assigned_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    case     = relationship("Case")
    user     = relationship("User", foreign_keys=[user_id])
    assigner = relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (
        UniqueConstraint("case_id", "user_id", name="uq_case_collaborators_case_user"),
        Index("idx_case_collaborators_case_id", "case_id"),
        Index("idx_case_collaborators_user_id", "user_id"),
    )


# ── Dossier Export Approvals ─────────────────────────────────────────────────

class DossierExportApproval(Base):
    __tablename__ = "dossier_export_approvals"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id          = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    report_type      = Column(String(64), nullable=False)
    requested_by     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    approved_by      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status           = Column(String(32), nullable=False, default="PENDING")
    rejection_reason = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at      = Column(DateTime(timezone=True), nullable=True)

    case      = relationship("Case")
    requester = relationship("User", foreign_keys=[requested_by])
    approver  = relationship("User", foreign_keys=[approved_by])

    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_dossier_export_status"),
        Index("idx_dossier_export_case_status", "case_id", "status"),
    )



# ── Evidence Events ──────────────────────────────────────────────────────────

class EvidenceEvent(Base):
    __tablename__ = "evidence_events"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id           = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    evidence_file_id  = Column(UUID(as_uuid=True), ForeignKey("evidence_files.id", ondelete="SET NULL"))
    event_timestamp   = Column(DateTime(timezone=True))
    event_type        = Column(String(32))
    text_content      = Column(Text)
    source_line       = Column(Integer)
    source_page       = Column(Integer)
    event_metadata    = Column("metadata", JSONB, default=dict)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    case          = relationship("Case", back_populates="evidence_events")
    evidence_file = relationship("EvidenceFile", back_populates="events")
    mentions      = relationship("EntityMention", back_populates="event")


# ── Entities ─────────────────────────────────────────────────────────────────

class Entity(Base):
    __tablename__ = "entities"

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id            = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    canonical_value    = Column(String(512), nullable=False)
    entity_type        = Column(String(32), nullable=False)
    node_metadata      = Column(JSONB, default=dict)
    degree_centrality  = Column(Float)
    community_id       = Column(Integer)
    bridge_score       = Column(Float, default=0.0)
    first_seen         = Column(DateTime(timezone=True))
    last_seen          = Column(DateTime(timezone=True))
    created_at         = Column(DateTime(timezone=True), server_default=func.now())

    case     = relationship("Case", back_populates="entities")
    mentions = relationship("EntityMention", back_populates="entity")


# ── Entity Mentions ──────────────────────────────────────────────────────────

class EntityMention(Base):
    __tablename__ = "entity_mentions"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id         = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"))
    evidence_event_id = Column(UUID(as_uuid=True), ForeignKey("evidence_events.id", ondelete="CASCADE"))
    raw_value         = Column(String(512), nullable=False)
    entity_type       = Column(String(32), nullable=False)
    confidence        = Column(Float, default=1.0)
    extractor         = Column(String(32))
    span_start        = Column(Integer)
    span_end          = Column(Integer)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())

    entity = relationship("Entity", back_populates="mentions")
    event  = relationship("EvidenceEvent", back_populates="mentions")


# ── Correlations ─────────────────────────────────────────────────────────────

class Correlation(Base):
    __tablename__ = "correlations"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id          = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    entity_a_id      = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    entity_b_id      = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    link_type        = Column(String(32), default="hidden_link")
    final_score      = Column(Float, nullable=False)
    threshold        = Column(Float, nullable=False)
    decision         = Column(String(16), nullable=False)
    component_scores = Column(JSONB, nullable=False, default=dict)
    model_weights    = Column(JSONB, nullable=False, default=dict)
    source_citations = Column(JSONB, default=list)
    verified_by      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    verified_at      = Column(DateTime(timezone=True))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    case     = relationship("Case", back_populates="correlations")
    verifier = relationship("User", back_populates="verified_links")

    __table_args__ = (
        UniqueConstraint("case_id", "entity_a_id", "entity_b_id", name="uq_correlations_pair"),
        CheckConstraint("decision IN ('flagged','not_flagged')", name="ck_correlations_decision"),
    )


# ── Relationships (Unified Case Graph Edges) ──────────────────────────────────

class Relationship(Base):
    """
    A persisted, semantically typed edge of the unified case graph.

    Unlike a raw co-occurrence projection, every row carries:
      • a semantic relationship_type (TRANSFERRED_TO, CALLED, MESSAGED, …)
      • an epistemic_status — OBSERVED (evidence-backed) or INFERRED (cognitive)
      • evidence_refs / event_refs provenance for forensic traceability
      • confidence plus engine/component metadata for inferred links

    Observed edges are materialised at ingestion; inferred edges are written by
    cognitive engines. They share this table so one graph can express both.
    """
    __tablename__ = "relationships"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id           = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    source_entity_id  = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    target_entity_id  = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    relationship_type = Column(String(32), nullable=False)
    direction         = Column(String(16), nullable=False, default="OUTBOUND")
    epistemic_status  = Column(String(16), nullable=False, default="OBSERVED")
    confidence        = Column(Float, nullable=False, default=1.0)
    amount            = Column(Float)
    event_timestamp   = Column(DateTime(timezone=True))
    first_seen        = Column(DateTime(timezone=True))
    last_seen         = Column(DateTime(timezone=True))
    observation_count = Column(Integer, nullable=False, default=1)
    attributes        = Column(JSONB, default=dict)
    evidence_refs     = Column(JSONB, default=list)
    event_refs        = Column(JSONB, default=list)
    source_engine     = Column(String(64))
    engine_version    = Column(String(32))
    component_scores  = Column(JSONB, default=dict)
    reason_codes      = Column(JSONB, default=list)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case          = relationship("Case", back_populates="relationships")
    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    target_entity = relationship("Entity", foreign_keys=[target_entity_id])

    __table_args__ = (
        UniqueConstraint(
            "case_id", "source_entity_id", "target_entity_id",
            "relationship_type", "epistemic_status",
            name="uq_relationships_edge",
        ),
        CheckConstraint(
            "epistemic_status IN ('OBSERVED','INFERRED')",
            name="ck_relationships_epistemic_status",
        ),
        CheckConstraint(
            "direction IN ('OUTBOUND','INBOUND','BIDIRECTIONAL')",
            name="ck_relationships_direction",
        ),
        Index("idx_relationships_case_id", "case_id"),
        Index("idx_relationships_epistemic_status", "epistemic_status"),
        Index("idx_relationships_source", "source_entity_id"),
        Index("idx_relationships_target", "target_entity_id"),
    )


# ── Investigation Findings (unified intelligence output) ──────────────────────

class InvestigationFinding(Base):
    """
    One traceable intelligence finding, whatever engine produced it.

    Findings are the contract between the cognitive layer and every consumer
    (Cognitive tab, graph overlays, copilot, reports). `fingerprint` is a stable
    identity so re-running analysis updates the same finding instead of
    duplicating it.
    """
    __tablename__ = "findings"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id          = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    fingerprint      = Column(String(64), nullable=False)
    finding_type     = Column(String(48), nullable=False)
    title            = Column(String(512), nullable=False)
    description      = Column(Text)
    confidence       = Column(Float)
    severity         = Column(String(16), nullable=False, default="MEDIUM")
    status           = Column(String(24), nullable=False, default="OPEN")
    source_engine    = Column(String(64))
    engine_version   = Column(String(32))
    entity_refs      = Column(JSONB, default=list)
    event_refs       = Column(JSONB, default=list)
    evidence_refs    = Column(JSONB, default=list)
    component_scores = Column(JSONB, default=dict)
    reason_codes     = Column(JSONB, default=list)
    reasoning        = Column(Text)
    citations        = Column(JSONB, default=list)
    observed_at      = Column(DateTime(timezone=True))
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case = relationship("Case", back_populates="findings")

    __table_args__ = (
        UniqueConstraint("case_id", "fingerprint", name="uq_findings_case_fingerprint"),
        CheckConstraint(
            "severity IN ('LOW','MEDIUM','HIGH','CRITICAL')",
            name="ck_findings_severity",
        ),
        CheckConstraint(
            "status IN ('OPEN','CONFIRMED','DISMISSED','SUPERSEDED')",
            name="ck_findings_status",
        ),
        Index("idx_findings_case_id", "case_id"),
        Index("idx_findings_type", "finding_type"),
        Index("idx_findings_severity", "severity"),
        Index("idx_findings_status", "status"),
    )


# ── Analysis Runs (orchestrator execution log) ────────────────────────────────

class AnalysisRun(Base):
    """One execution of the cognitive orchestrator over a case's case state."""
    __tablename__ = "analysis_runs"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id           = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    trigger           = Column(String(32), nullable=False, default="manual")
    status            = Column(String(16), nullable=False, default="running")
    engines_requested = Column(JSONB, default=list)
    engines_run       = Column(JSONB, default=list)
    engines_skipped   = Column(JSONB, default=list)
    findings_created  = Column(Integer, nullable=False, default=0)
    findings_updated  = Column(Integer, nullable=False, default=0)
    started_at        = Column(DateTime(timezone=True), server_default=func.now())
    completed_at      = Column(DateTime(timezone=True))
    duration_ms       = Column(Integer)
    error             = Column(Text)
    summary           = Column(JSONB, default=dict)

    case = relationship("Case", back_populates="analysis_runs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed')",
            name="ck_analysis_runs_status",
        ),
        Index("idx_analysis_runs_case_id", "case_id"),
        Index("idx_analysis_runs_status", "status"),
    )


# ── Case Intelligence State (latest per-case intelligence snapshot) ───────────

class CaseIntelligenceState(Base):
    """
    Materialised snapshot of what NETRA currently knows about a case. It powers
    the Cognitive tab header ("47 Evidence · 83 Entities · 12 Findings …") and
    lets the UI render intelligence without recomputing every engine.
    """
    __tablename__ = "case_intelligence_state"

    id                           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id                      = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    evidence_count               = Column(Integer, nullable=False, default=0)
    processed_evidence_count     = Column(Integer, nullable=False, default=0)
    entity_count                 = Column(Integer, nullable=False, default=0)
    event_count                  = Column(Integer, nullable=False, default=0)
    relationship_count           = Column(Integer, nullable=False, default=0)
    observed_relationship_count  = Column(Integer, nullable=False, default=0)
    inferred_relationship_count  = Column(Integer, nullable=False, default=0)
    finding_count                = Column(Integer, nullable=False, default=0)
    high_priority_count          = Column(Integer, nullable=False, default=0)
    findings_by_type             = Column(JSONB, default=dict)
    engine_status                = Column(JSONB, default=dict)
    last_run_id                  = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="SET NULL"))
    last_run_at                  = Column(DateTime(timezone=True))
    updated_at                   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    case = relationship("Case", back_populates="intelligence_state")

    __table_args__ = (
        UniqueConstraint("case_id", name="uq_case_intelligence_state_case"),
    )


# ── Audit Log ────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_log"

    id              = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    prev_hash       = Column(String(64), nullable=False)
    entry_hash      = Column(String(64), nullable=False, unique=True)
    event_timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    action          = Column(String(64), nullable=False)
    resource_type   = Column(String(64))
    resource_id     = Column(Text)
    details_json    = Column(JSONB, default=dict)

    user = relationship("User", back_populates="audit_entries")


# ── ArmorIQ Agent Session ─────────────────────────────────────────────────────

class AgentSession(Base):
    """Tracks one autonomous investigation session per case."""
    __tablename__ = "agent_sessions"

    id              = Column(String(64), primary_key=True)  # UUID string
    case_id         = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    status          = Column(String(32), nullable=False, default="idle")
    triggered_by    = Column(String(128))   # username or 'system'
    started_at      = Column(DateTime(timezone=True), server_default=func.now())
    completed_at    = Column(DateTime(timezone=True))
    actions_json    = Column(JSONB, default=list)   # full action list snapshot

    __table_args__ = (
        CheckConstraint(
            "status IN ('idle','investigating','analyzing','executing',"
            "'blocked','awaiting_approval','completed','failed')",
            name="ck_agent_sessions_status"
        ),
        Index("idx_agent_sessions_case_id", "case_id"),
    )


# ── ArmorIQ Agent Action ──────────────────────────────────────────────────────

class AgentAction(Base):
    """Individual action record with ArmorIQ enforcement state."""
    __tablename__ = "agent_actions"

    id              = Column(String(64), primary_key=True)
    session_id      = Column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False)
    case_id         = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    action_type     = Column(String(64), nullable=False)
    description     = Column(Text)
    status          = Column(String(32), nullable=False)
    details_json    = Column(JSONB, default=dict)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_agent_actions_session_id", "session_id"),
        Index("idx_agent_actions_case_id", "case_id"),
    )


# ── ArmorIQ Hold (BLOCK awaiting human approval) ──────────────────────────────

class AgentHold(Base):
    """ArmorIQ-blocked actions awaiting human approval or rejection."""
    __tablename__ = "agent_holds"

    id                      = Column(String(64), primary_key=True)   # hold_id
    session_id              = Column(String(64), ForeignKey("agent_sessions.id", ondelete="CASCADE"))
    case_id                 = Column(UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"))
    action                  = Column(String(128), nullable=False)
    description             = Column(Text)
    ai_reasoning            = Column(Text)         # AI explanation for why it wanted this action
    authorization_boundary  = Column(Text)         # Why ArmorIQ blocked it
    risk_level              = Column(String(16), default="HIGH")
    affected_resource_json  = Column(JSONB, default=dict)
    tool_params_json        = Column(JSONB, default=dict)
    armoriq_reason          = Column(Text)         # Raw IntentMismatchException message
    status                  = Column(String(32), nullable=False, default="awaiting_approval")
    approved_by             = Column(String(128))
    rejected_by             = Column(String(128))
    rejection_reason        = Column(Text)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at             = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_approval','approved','rejected','expired')",
            name="ck_agent_holds_status"
        ),
        Index("idx_agent_holds_case_id", "case_id"),
        Index("idx_agent_holds_status", "status"),
    )


# ── Sandbox Firewall Rules (protected test resource for boundary demo) ────────

class SandboxFirewallRule(Base):
    """Protected sandbox network-control config — the out-of-scope resource."""
    __tablename__ = "sandbox_firewall_rules"

    id               = Column(String(32), primary_key=True)
    rule_name        = Column(String(128), nullable=False)
    description      = Column(Text)
    rule_type        = Column(String(32))
    target_cidr      = Column(String(64))
    port_range       = Column(String(128))
    priority         = Column(Integer, default=100)
    status           = Column(String(16), default="active")
    protected        = Column(Boolean, default=True)   # protected = requires ArmorIQ approval
    owner_team       = Column(String(64))
    last_modified_by = Column(String(128))
    last_modified_at = Column(DateTime(timezone=True), server_default=func.now())
