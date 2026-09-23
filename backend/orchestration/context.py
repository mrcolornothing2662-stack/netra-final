from __future__ import annotations

"""
CyberDrishti AI — Case Context Loader

Builds the read-only CaseContext snapshot the orchestrator hands to every
engine. Loaded once per run so all engines reason over identical case state.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, Entity, EvidenceEvent, EvidenceFile, IdentityCandidate, InvestigationFinding, Relationship
from orchestration.contracts import CaseContext
from orchestration.finding_service import serialize_finding
from orchestration.intelligence_state import compute_state


def _iso(value) -> str | None:
    return value.isoformat() if value else None


async def load_case_context(db: AsyncSession, case_id) -> CaseContext:
    case = await db.get(Case, case_id) if not isinstance(case_id, Case) else case_id
    if case is None:
        raise ValueError(f"case not found: {case_id}")
    cid = case.id

    evidence_files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == cid)
    )).scalars().all()

    entities = (await db.execute(
        select(Entity).where(Entity.case_id == cid)
    )).scalars().all()

    events = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.case_id == cid)
        .order_by(EvidenceEvent.event_timestamp, EvidenceEvent.id)
    )).scalars().all()

    relationships = (await db.execute(
        select(Relationship).where(Relationship.case_id == cid)
    )).scalars().all()

    candidates = (await db.execute(
        select(IdentityCandidate).where(IdentityCandidate.case_id == cid)
    )).scalars().all()

    findings = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == cid)
    )).scalars().all()

    entity_by_id = {e.id: e for e in entities}

    evidence_types: set[str] = set()
    evidence_payload: list[dict[str, Any]] = []
    for f in evidence_files:
        for value in (f.file_type, f.source_type):
            if value:
                evidence_types.add(str(value).lower())
        evidence_payload.append({
            "id":                 str(f.id),
            "filename":           f.original_name,
            "original_name":      f.original_name,
            "file_type":          f.file_type,
            "source_type":        f.source_type,
            "upload_status":      f.upload_status,
            "sha256_hash":        f.sha256_hash,
            "parse_error":        f.parse_error,
            "processed_at":       _iso(f.processed_at),
            "uploaded_at":        _iso(f.uploaded_at),
            "parent_evidence_id": str(f.parent_evidence_id) if f.parent_evidence_id else None,
            "version_number":     f.version_number or 1,
            "version_status":     f.version_status or "original",
            "variant_details":    f.variant_details or {},
        })

    event_payload = [{
        "id":              str(ev.id),
        "event_type":      ev.event_type,
        "event_timestamp": _iso(ev.event_timestamp),
        "text_content":    ev.text_content or "",
        "source_line":     ev.source_line,
        "source_page":     ev.source_page,
        "event_metadata":  ev.event_metadata or {},
        "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
    } for ev in events]

    entity_payload = [{
        "id":               str(e.id),
        "canonical_value":  e.canonical_value,
        "entity_type":      e.entity_type,
        "degree_centrality": e.degree_centrality or 0.0,
        "community_id":     e.community_id,
        "bridge_score":     e.bridge_score or 0.0,
        "first_seen":       _iso(e.first_seen),
        "last_seen":        _iso(e.last_seen),
    } for e in entities]

    relationship_payload = []
    for rel in relationships:
        source = entity_by_id.get(rel.source_entity_id)
        target = entity_by_id.get(rel.target_entity_id)
        relationship_payload.append({
            "id":                str(rel.id),
            "source_entity_id":  str(rel.source_entity_id),
            "target_entity_id":  str(rel.target_entity_id),
            "source_value":      source.canonical_value if source else None,
            "target_value":      target.canonical_value if target else None,
            "source_type":       source.entity_type if source else None,
            "target_type":       target.entity_type if target else None,
            "relationship_type":   rel.relationship_type,
            "direction":           rel.direction,
            "epistemic_status":    rel.epistemic_status,
            "verification_status": rel.verification_status,
            "is_canonical":        bool(rel.is_canonical),
            "confidence":          rel.confidence,
            "amount":              rel.amount,
            "evidence_refs":       rel.evidence_refs or [],
            "event_refs":          rel.event_refs or [],
            "component_scores":    rel.component_scores or {},
            "reason_codes":        rel.reason_codes or [],
            "source_engine":       rel.source_engine,
            "engine_version":      rel.engine_version,
            "observation_count":   rel.observation_count,
        })

    candidate_payload = [{
        "id":                  str(c.id),
        "canonical_entity_id": str(c.canonical_entity_id) if c.canonical_entity_id else None,
        "candidate_value":     c.candidate_value,
        "candidate_type":      c.candidate_type,
        "resolution_status":   c.resolution_status,
        "source_refs":         c.source_refs or [],
    } for c in candidates]

    counts = await compute_state(db, cid)

    return CaseContext(
        case_id=str(cid),
        case_number=case.case_number,
        case_fir_number=case.fir_number,
        case_created_at=_iso(case.created_at),
        case_state_version=case.state_version or 1,
        evidence_files=evidence_payload,
        evidence_types=evidence_types,
        events=event_payload,
        entities=entity_payload,
        relationships=relationship_payload,
        identity_candidates=candidate_payload,
        findings=[serialize_finding(f) for f in findings],
        counts=counts,
    )
