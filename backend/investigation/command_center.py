from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Investigation Command Center Projection Service
Provides a consolidated, read-only projection answering:
"What requires my attention in this case right now?"

Adheres strictly to the architectural invariant:
Every widget is a projection of existing NETRA state.
Do not create dashboard-specific truth.
"""
from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InformationGap,
    InvestigationActivity,
    InvestigationFinding,
    Relationship,
    SyncConflictRecord,
    SyncProcessedMutation,
    User,
)
from graph import relationship_types as RT
from forensic.service import ForensicLensService


# ── Pydantic Contracts for Command Center Widgets ────────────────────────────

class WidgetHeader(BaseModel):
    title: str
    status: str  # e.g., "URGENT_ACTION", "REVIEW_REQUIRED", "HEALTHY", "SYNCED", "INFO"
    metric: Any
    last_updated: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    click_action: str


class AttentionItem(BaseModel):
    item_id: str
    priority: str  # "URGENT_ACTION" | "REVIEW_REQUIRED" | "NEW_INTELLIGENCE" | "INFORMATION"
    category: str  # "IDENTITY_CONFLICT" | "RELATIONSHIP_REVIEW" | "STALE_FINDING" | "SYNC_CONFLICT" | "INFORMATION_GAP"
    title: str
    description: str
    source_refs: List[str] = Field(default_factory=list)
    click_action: str


class AttentionQueueWidget(BaseModel):
    header: WidgetHeader
    items: List[AttentionItem] = Field(default_factory=list)
    counts_by_priority: Dict[str, int] = Field(default_factory=dict)


class InvestigationHealthWidget(BaseModel):
    header: WidgetHeader
    overall_score: int
    integrity_status: str
    state_version: int
    entities_count: int
    evidence_count: int
    processed_evidence_count: int
    relationships_count: int
    canonical_count: int
    inferred_count: int
    unreviewed_relationships_count: int
    findings_count: int
    stale_findings_count: int
    unresolved_identities_count: int


class ActivityItem(BaseModel):
    id: str
    activity_type: str
    actor: str
    reason: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    created_at: str


class RecentActivityWidget(BaseModel):
    header: WidgetHeader
    items: List[ActivityItem] = Field(default_factory=list)


class FindingReviewItem(BaseModel):
    id: str
    title: str
    finding_type: str
    severity: str
    confidence: Optional[float] = None
    freshness_status: str
    status: str
    supporting_refs: List[str] = Field(default_factory=list)
    suggested_actions: List[str] = Field(default_factory=list)
    click_action: str


class FindingsWidget(BaseModel):
    header: WidgetHeader
    items: List[FindingReviewItem] = Field(default_factory=list)
    total_findings: int
    stale_count: int


class IdentityConflictItem(BaseModel):
    id: str
    candidate_value: str
    candidate_type: str
    canonical_entity_id: Optional[str] = None
    resolution_status: str
    conflict_signals: List[str] = Field(default_factory=list)
    supporting_refs: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)
    click_action: str


class IdentityConflictsWidget(BaseModel):
    header: WidgetHeader
    items: List[IdentityConflictItem] = Field(default_factory=list)
    total_unresolved: int


class RelationshipReviewItem(BaseModel):
    id: str
    source_entity_id: str
    target_entity_id: str
    source_value: Optional[str] = None
    target_value: Optional[str] = None
    relationship_type: str
    epistemic_status: str
    verification_status: str
    confidence: Optional[float] = None
    source_refs: List[str] = Field(default_factory=list)
    click_action: str


class RelationshipReviewWidget(BaseModel):
    header: WidgetHeader
    items: List[RelationshipReviewItem] = Field(default_factory=list)
    total_unreviewed: int


class EvidenceStatusItem(BaseModel):
    id: str
    filename: str
    file_type: str
    upload_status: str
    sha256_hash: str
    uploaded_at: str
    click_action: str


class EvidenceStatusWidget(BaseModel):
    header: WidgetHeader
    items: List[EvidenceStatusItem] = Field(default_factory=list)
    total_files: int
    processed_files: int
    pending_files: int


class SyncWidget(BaseModel):
    header: WidgetHeader
    server_state_version: int
    pending_conflicts_count: int
    recent_synced_count: int
    last_synced_at: Optional[str] = None
    sync_status: str
    click_action: str


class LensSummaryWidget(BaseModel):
    header: WidgetHeader
    money_events_count: int
    comms_events_count: int
    geo_events_count: int
    cross_lens_signals_count: int
    disclaimer: str
    click_action: str


class MiniNetworkNode(BaseModel):
    id: str
    label: str
    entity_type: str


class MiniNetworkEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    is_canonical: bool


class MiniNetworkWidget(BaseModel):
    header: WidgetHeader
    nodes: List[MiniNetworkNode] = Field(default_factory=list)
    edges: List[MiniNetworkEdge] = Field(default_factory=list)
    click_action: str


class CommandCenterProjection(BaseModel):
    case_id: str
    case_number: str
    title: str
    crime_type: Optional[str] = None
    priority: str
    status: str
    state_version: int
    generated_at: str
    attention_queue: AttentionQueueWidget
    investigation_health: InvestigationHealthWidget
    recent_activity: RecentActivityWidget
    findings_requiring_review: FindingsWidget
    identity_conflicts: IdentityConflictsWidget
    relationship_review: RelationshipReviewWidget
    evidence_status: EvidenceStatusWidget
    sync_status: SyncWidget
    lens_summary: LensSummaryWidget
    mini_network: MiniNetworkWidget


# ── Projection Assembler ─────────────────────────────────────────────────────

async def build_command_center_projection(
    db: AsyncSession,
    case: Case,
    current_user: User,
) -> CommandCenterProjection:
    """
    Assemble the complete, read-only Command Center projection directly
    from authoritative PostgreSQL state.
    """
    case_uuid = case.id
    now_iso = datetime.now(timezone.utc).isoformat()
    state_version = case.state_version or 1

    # 1. Fetch Entities
    ent_res = await db.execute(select(Entity).where(Entity.case_id == case_uuid))
    entities = list(ent_res.scalars().all())
    entity_map = {str(e.id): e.canonical_value for e in entities}

    # 2. Fetch Relationships
    rel_res = await db.execute(select(Relationship).where(Relationship.case_id == case_uuid))
    relationships = list(rel_res.scalars().all())

    canonical_rels = [
        r for r in relationships if RT.is_canonical_eligible(r.epistemic_status, r.verification_status)
    ]
    inferred_rels = [
        r for r in relationships if r.epistemic_status == RT.INFERRED
    ]
    unreviewed_rels = [
        r for r in relationships if r.verification_status == RT.REVIEW_UNREVIEWED
    ]

    # 3. Fetch Identity Candidates
    cand_res = await db.execute(select(IdentityCandidate).where(IdentityCandidate.case_id == case_uuid))
    candidates = list(cand_res.scalars().all())
    unresolved_cands = [c for c in candidates if c.resolution_status == "UNRESOLVED"]

    # 4. Fetch Evidence Files
    ev_res = await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case_uuid).order_by(EvidenceFile.uploaded_at.desc())
    )
    evidence_files = list(ev_res.scalars().all())
    processed_files = [f for f in evidence_files if f.upload_status == "processed"]
    pending_files = [f for f in evidence_files if f.upload_status != "processed"]

    # 5. Fetch Findings
    find_res = await db.execute(
        select(InvestigationFinding)
        .where(InvestigationFinding.case_id == case_uuid)
        .order_by(InvestigationFinding.created_at.desc())
    )
    findings = list(find_res.scalars().all())
    stale_findings = [f for f in findings if getattr(f, "freshness_status", "CURRENT") == "STALE"]
    review_findings = [
        f for f in findings if getattr(f, "freshness_status", "CURRENT") == "STALE" or f.status in ["OPEN", "PENDING_REVIEW"]
    ]

    # 6. Fetch Sync Conflicts & Processed Mutations
    conf_res = await db.execute(select(SyncConflictRecord).where(SyncConflictRecord.case_id == case_uuid))
    sync_conflicts = list(conf_res.scalars().all())
    pending_sync_conflicts = [c for c in sync_conflicts if c.status == "PENDING_REVIEW"]

    mut_res = await db.execute(
        select(SyncProcessedMutation)
        .where(SyncProcessedMutation.case_id == case_uuid)
        .order_by(SyncProcessedMutation.applied_at.desc())
        .limit(10)
    )
    processed_mutations = list(mut_res.scalars().all())

    # 7. Fetch Recent Activity
    act_res = await db.execute(
        select(InvestigationActivity)
        .where(InvestigationActivity.case_id == case_uuid)
        .order_by(InvestigationActivity.created_at.desc())
        .limit(15)
    )
    activities = list(act_res.scalars().all())

    # 8. Forensic Lenses Overview
    lens_overview = await ForensicLensService.get_lenses_overview(db, case_uuid)

    # ── BUILD WIDGETS ────────────────────────────────────────────────────────

    # Widget 1: Attention Queue (Investigator-first Priority Ordering)
    attention_items: List[AttentionItem] = []

    # Priority A: URGENT ACTION - Identity conflicts & Sync conflicts
    for conf in pending_sync_conflicts:
        attention_items.append(
            AttentionItem(
                item_id=f"sync_conflict_{conf.id}",
                priority="URGENT_ACTION",
                category="SYNC_CONFLICT",
                title=f"Offline Conflict: {conf.command_type}",
                description=f"Device {conf.device_id} submitted diverged decision against server v{conf.server_state_version}.",
                source_refs=[conf.device_id] if conf.device_id else [],
                click_action=f"/investigations/{case_uuid}/overview?conflict={conf.id}",
            )
        )

    for cand in unresolved_cands:
        if cand.contradicting_refs or (cand.supporting_refs and len(cand.supporting_refs) > 0):
            attention_items.append(
                AttentionItem(
                    item_id=f"identity_cand_{cand.id}",
                    priority="URGENT_ACTION" if cand.contradicting_refs else "REVIEW_REQUIRED",
                    category="IDENTITY_CONFLICT",
                    title=f"Identity Candidate: {cand.candidate_value}",
                    description=f"{len(cand.contradicting_refs or [])} conflict signals detected across evidence.",
                    source_refs=list(cand.source_refs or []),
                    click_action=f"/investigations/{case_uuid}/entities?candidate={cand.id}",
                )
            )

    # Priority B: REVIEW REQUIRED - Unreviewed relationships & Stale findings
    for r in unreviewed_rels[:5]:
        s_val = entity_map.get(str(r.source_entity_id), str(r.source_entity_id)[:8])
        t_val = entity_map.get(str(r.target_entity_id), str(r.target_entity_id)[:8])
        attention_items.append(
            AttentionItem(
                item_id=f"rel_review_{r.id}",
                priority="REVIEW_REQUIRED",
                category="RELATIONSHIP_REVIEW",
                title=f"Unreviewed Link: {s_val} → {t_val}",
                description=f"Inferred {r.relationship_type} (Confidence: {int((r.confidence or 0.8) * 100)}%).",
                source_refs=list(r.evidence_refs or []),
                click_action=f"/investigations/{case_uuid}/network?relationship={r.id}",
            )
        )

    for sf in stale_findings[:5]:
        attention_items.append(
            AttentionItem(
                item_id=f"stale_finding_{sf.id}",
                priority="REVIEW_REQUIRED",
                category="STALE_FINDING",
                title=f"Stale Intelligence: {sf.title}",
                description=f"Finding generated at older case version requires review after topology changes.",
                source_refs=list(sf.evidence_refs or []),
                click_action=f"/investigations/{case_uuid}/analysis?finding={sf.id}",
            )
        )

    priority_counts: Dict[str, int] = {}
    for item in attention_items:
        priority_counts[item.priority] = priority_counts.get(item.priority, 0) + 1

    attention_queue = AttentionQueueWidget(
        header=WidgetHeader(
            title="Attention Required",
            status="URGENT_ACTION" if priority_counts.get("URGENT_ACTION", 0) > 0 else (
                "REVIEW_REQUIRED" if priority_counts.get("REVIEW_REQUIRED", 0) > 0 else "HEALTHY"
            ),
            metric=len(attention_items),
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/overview",
        ),
        items=attention_items,
        counts_by_priority=priority_counts,
    )

    # Widget 2: Investigation Health
    # Score calculation: 100 baseline, -10 per pending conflict, -5 per stale finding, -2 per unreviewed rel
    health_deductions = (
        (len(pending_sync_conflicts) * 15)
        + (len(unresolved_cands) * 5)
        + (len(stale_findings) * 5)
        + (min(len(unreviewed_rels), 10) * 2)
    )
    overall_health = max(10, 100 - health_deductions)
    health_status = "OPTIMAL" if overall_health >= 85 else ("DEGRADED" if overall_health >= 60 else "CRITICAL")

    investigation_health = InvestigationHealthWidget(
        header=WidgetHeader(
            title="Investigation Health",
            status=health_status,
            metric=f"{overall_health}%",
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/overview",
        ),
        overall_score=overall_health,
        integrity_status=health_status,
        state_version=state_version,
        entities_count=len(entities),
        evidence_count=len(evidence_files),
        processed_evidence_count=len(processed_files),
        relationships_count=len(relationships),
        canonical_count=len(canonical_rels),
        inferred_count=len(inferred_rels),
        unreviewed_relationships_count=len(unreviewed_rels),
        findings_count=len(findings),
        stale_findings_count=len(stale_findings),
        unresolved_identities_count=len(unresolved_cands),
    )

    # Widget 3: Recent Activity
    act_items = [
        ActivityItem(
            id=str(a.id),
            activity_type=a.activity_type,
            actor=str(a.actor_id) if a.actor_id else "SYSTEM",
            reason=a.reason,
            target_type=a.target_type,
            target_id=str(a.target_id) if a.target_id else None,
            created_at=a.created_at.isoformat() if a.created_at else now_iso,
        )
        for a in activities
    ]
    recent_activity = RecentActivityWidget(
        header=WidgetHeader(
            title="Recent Activity",
            status="INFO",
            metric=len(act_items),
            last_updated=act_items[0].created_at if act_items else now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/timeline",
        ),
        items=act_items,
    )

    # Widget 4: Findings Requiring Review
    finding_items = [
        FindingReviewItem(
            id=str(f.id),
            title=f.title,
            finding_type=f.finding_type,
            severity=f.severity,
            confidence=f.confidence,
            freshness_status=getattr(f, "freshness_status", "CURRENT"),
            status=f.status,
            supporting_refs=list(f.supporting_refs or []),
            suggested_actions=list(getattr(f, "suggested_actions", []) or []),
            click_action=f"/investigations/{case_uuid}/analysis?finding={f.id}",
        )
        for f in (review_findings if review_findings else findings[:5])
    ]
    findings_widget = FindingsWidget(
        header=WidgetHeader(
            title="Findings Requiring Review",
            status="REVIEW_REQUIRED" if len(stale_findings) > 0 else "HEALTHY",
            metric=len(review_findings),
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/analysis",
        ),
        items=finding_items,
        total_findings=len(findings),
        stale_count=len(stale_findings),
    )

    # Widget 5: Identity Conflicts
    identity_items = [
        IdentityConflictItem(
            id=str(c.id),
            candidate_value=c.candidate_value,
            candidate_type=c.candidate_type,
            canonical_entity_id=str(c.canonical_entity_id) if c.canonical_entity_id else None,
            resolution_status=c.resolution_status,
            conflict_signals=list(c.contradicting_refs or []),
            supporting_refs=list(c.supporting_refs or []),
            source_refs=list(c.source_refs or []),
            click_action=f"/investigations/{case_uuid}/entities?candidate={c.id}",
        )
        for c in unresolved_cands[:10]
    ]
    identity_widget = IdentityConflictsWidget(
        header=WidgetHeader(
            title="Identity Conflicts",
            status="URGENT_ACTION" if len(unresolved_cands) > 0 else "HEALTHY",
            metric=len(unresolved_cands),
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/entities",
        ),
        items=identity_items,
        total_unresolved=len(unresolved_cands),
    )

    # Widget 6: Relationship Review Queue
    rel_items = [
        RelationshipReviewItem(
            id=str(r.id),
            source_entity_id=str(r.source_entity_id),
            target_entity_id=str(r.target_entity_id),
            source_value=entity_map.get(str(r.source_entity_id)),
            target_value=entity_map.get(str(r.target_entity_id)),
            relationship_type=r.relationship_type,
            epistemic_status=r.epistemic_status,
            verification_status=r.verification_status,
            confidence=r.confidence,
            source_refs=list(r.evidence_refs or []),
            click_action=f"/investigations/{case_uuid}/network?relationship={r.id}",
        )
        for r in unreviewed_rels[:10]
    ]
    relationship_review = RelationshipReviewWidget(
        header=WidgetHeader(
            title="Relationship Review Queue",
            status="REVIEW_REQUIRED" if len(unreviewed_rels) > 0 else "HEALTHY",
            metric=len(unreviewed_rels),
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/network",
        ),
        items=rel_items,
        total_unreviewed=len(unreviewed_rels),
    )

    # Widget 7: Evidence Processing Status
    ev_items = [
        EvidenceStatusItem(
            id=str(ef.id),
            filename=ef.filename,
            file_type=ef.file_type or "DOCUMENT",
            upload_status=ef.upload_status or "processed",
            sha256_hash=ef.sha256_hash,
            uploaded_at=ef.uploaded_at.isoformat() if ef.uploaded_at else now_iso,
            click_action=f"/investigations/{case_uuid}/evidence?file={ef.id}",
        )
        for ef in evidence_files[:8]
    ]
    evidence_status = EvidenceStatusWidget(
        header=WidgetHeader(
            title="Evidence Processing Status",
            status="PROCESSING" if len(pending_files) > 0 else "HEALTHY",
            metric=f"{len(processed_files)} / {len(evidence_files)} Processed",
            last_updated=now_iso,
            source_refs=[ef.sha256_hash for ef in evidence_files[:3]],
            click_action=f"/investigations/{case_uuid}/evidence",
        ),
        items=ev_items,
        total_files=len(evidence_files),
        processed_files=len(processed_files),
        pending_files=len(pending_files),
    )

    # Widget 8: Offline Sync Status
    last_synced_dt = processed_mutations[0].applied_at.isoformat() if processed_mutations and processed_mutations[0].applied_at else None
    sync_status_val = "CONFLICT_PENDING" if len(pending_sync_conflicts) > 0 else "SYNCED"

    sync_widget = SyncWidget(
        header=WidgetHeader(
            title="Offline Sync Status",
            status=sync_status_val,
            metric=f"v{state_version} ({len(pending_sync_conflicts)} conflicts)",
            last_updated=last_synced_dt or now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/overview",
        ),
        server_state_version=state_version,
        pending_conflicts_count=len(pending_sync_conflicts),
        recent_synced_count=len(processed_mutations),
        last_synced_at=last_synced_dt,
        sync_status=sync_status_val,
        click_action=f"/investigations/{case_uuid}/overview",
    )

    # Widget 9: Forensic Lens Summary
    money_ev_count = (lens_overview.money_summary or {}).get("transaction_count", 0)
    comms_ev_count = (lens_overview.communications_summary or {}).get("communication_count", 0)
    geo_ev_count = (lens_overview.geographic_summary or {}).get("observation_count", 0)
    total_lens_events = money_ev_count + comms_ev_count + geo_ev_count
    geo_disclaimer = (lens_overview.geographic_summary or {}).get(
        "disclaimer", "Cell-site telemetry indicates general coverage; not exact physical GPS location."
    )

    lens_summary = LensSummaryWidget(
        header=WidgetHeader(
            title="Forensic Lens Summary",
            status="INFO",
            metric=f"{total_lens_events} events",
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/lenses",
        ),
        money_events_count=money_ev_count,
        comms_events_count=comms_ev_count,
        geo_events_count=geo_ev_count,
        cross_lens_signals_count=lens_overview.cross_lens_coincidences_count,
        disclaimer=geo_disclaimer,
        click_action=f"/investigations/{case_uuid}/lenses",
    )

    # Widget 10: Mini Network
    # Pick top entities by degree
    rel_degree: Dict[str, int] = {}
    for r in relationships:
        s_id = str(r.source_entity_id)
        t_id = str(r.target_entity_id)
        rel_degree[s_id] = rel_degree.get(s_id, 0) + 1
        rel_degree[t_id] = rel_degree.get(t_id, 0) + 1

    sorted_ent_ids = sorted(rel_degree.keys(), key=lambda eid: rel_degree[eid], reverse=True)[:10]
    sub_node_ids = set(sorted_ent_ids)
    if not sub_node_ids and entities:
        sub_node_ids = {str(e.id) for e in entities[:6]}

    sub_nodes = [
        MiniNetworkNode(
            id=str(e.id),
            label=e.canonical_value,
            entity_type=e.entity_type,
        )
        for e in entities if str(e.id) in sub_node_ids
    ]

    sub_edges = [
        MiniNetworkEdge(
            id=str(r.id),
            source=str(r.source_entity_id),
            target=str(r.target_entity_id),
            relationship_type=r.relationship_type,
            is_canonical=RT.is_canonical_eligible(r.epistemic_status, r.verification_status),
        )
        for r in relationships
        if str(r.source_entity_id) in sub_node_ids and str(r.target_entity_id) in sub_node_ids
    ][:15]

    mini_network = MiniNetworkWidget(
        header=WidgetHeader(
            title="Case Graph",
            status="INFO",
            metric=f"{len(sub_nodes)} nodes, {len(sub_edges)} links",
            last_updated=now_iso,
            source_refs=[],
            click_action=f"/investigations/{case_uuid}/network",
        ),
        nodes=sub_nodes,
        edges=sub_edges,
        click_action=f"/investigations/{case_uuid}/network",
    )

    return CommandCenterProjection(
        case_id=str(case.id),
        case_number=case.case_number,
        title=case.title,
        crime_type=case.crime_type,
        priority=case.priority,
        status=case.status,
        state_version=state_version,
        generated_at=now_iso,
        attention_queue=attention_queue,
        investigation_health=investigation_health,
        recent_activity=recent_activity,
        findings_requiring_review=findings_widget,
        identity_conflicts=identity_widget,
        relationship_review=relationship_review,
        evidence_status=evidence_status,
        sync_status=sync_widget,
        lens_summary=lens_summary,
        mini_network=mini_network,
    )
