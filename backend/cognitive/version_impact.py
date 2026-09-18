from __future__ import annotations
"""
CyberDrishti AI — Document Version Semantic Impact Analysis (F01)

Determines the investigative impact between an original evidence document
and its variant / appended version:
- Identifies newly introduced events (added rows)
- Identifies newly surfaced entities (accounts, phones, persons)
- Identifies newly formed or reinforced relationship edges (money flows, calls)
- Links version diffs directly to contradictions or ledger alterations
"""
from typing import Any, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cognitive.fingerprint import DiffResult, canonical_tuple, DEFAULT_CONFIG
from db.models import Entity, EntityMention, EvidenceEvent, Relationship, InvestigationFinding


async def compute_version_impact(
    db: AsyncSession,
    case_id: uuid.UUID,
    parent_file_id: uuid.UUID,
    variant_file_id: uuid.UUID,
    diff: DiffResult,
    tuple_fields: Sequence[str] | None = None,
) -> dict[str, Any]:
    """
    Compute semantic differences between parent and variant evidence files.

    Returns structured impact metadata suitable for storage in
    EvidenceFile.variant_details and InvestigationFinding.
    """
    fields = tuple_fields or DEFAULT_CONFIG["tuple_fields"]
    added_set = set(diff.added)

    # 1. Fetch all events for parent and variant
    parent_events = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.evidence_file_id == parent_file_id)
    )).scalars().all()

    variant_events = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.evidence_file_id == variant_file_id)
    )).scalars().all()

    # 2. Identify newly introduced events in variant
    added_event_ids: list[str] = []
    for ev in variant_events:
        c_tup = canonical_tuple({
            "event_type": ev.event_type,
            "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            "amount": (ev.event_metadata or {}).get("amount", ""),
            "reference": (ev.event_metadata or {}).get("reference", "") or (ev.text_content or "")[:40],
        }, fields)
        if c_tup in added_set:
            added_event_ids.append(str(ev.id))

    # 3. Query entities present in parent
    parent_entity_ids = set((await db.execute(
        select(EntityMention.entity_id)
        .join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
        .where(EvidenceEvent.evidence_file_id == parent_file_id)
    )).scalars().all())

    # 4. Query entities present in variant
    variant_mentions = (await db.execute(
        select(EntityMention.entity_id, Entity.canonical_value, Entity.entity_type, EntityMention.evidence_event_id)
        .join(Entity, EntityMention.entity_id == Entity.id)
        .join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
        .where(EvidenceEvent.evidence_file_id == variant_file_id)
    )).all()

    new_entities_dict: dict[uuid.UUID, dict[str, Any]] = {}
    for ent_id, canonical, etype, ev_id in variant_mentions:
        if ent_id not in parent_entity_ids:
            if ent_id not in new_entities_dict:
                new_entities_dict[ent_id] = {
                    "id": str(ent_id),
                    "canonical_value": canonical,
                    "entity_type": etype,
                    "introduced_in_added_row": str(ev_id) in added_event_ids,
                }

    new_entities = list(new_entities_dict.values())

    # 5. Query relationships formed or reinforced
    all_case_relationships = (await db.execute(
        select(Relationship).where(Relationship.case_id == case_id)
    )).scalars().all()

    new_relationships: list[dict[str, Any]] = []
    reinforced_relationships: list[dict[str, Any]] = []

    for rel in all_case_relationships:
        refs = rel.evidence_refs or []
        var_str = str(variant_file_id)
        par_str = str(parent_file_id)

        if var_str in refs:
            # Look up endpoint entity values
            source_ent = await db.get(Entity, rel.source_entity_id)
            target_ent = await db.get(Entity, rel.target_entity_id)
            rel_info = {
                "id": str(rel.id),
                "relationship_type": rel.relationship_type,
                "source": source_ent.canonical_value if source_ent else str(rel.source_entity_id),
                "target": target_ent.canonical_value if target_ent else str(rel.target_entity_id),
                "confidence": rel.confidence,
                "amount": rel.amount,
            }
            if par_str not in refs:
                new_relationships.append(rel_info)
            else:
                reinforced_relationships.append(rel_info)

    # 6. Check for contradiction findings associated with this variant
    contradictions = (await db.execute(
        select(InvestigationFinding).where(
            InvestigationFinding.case_id == case_id,
            InvestigationFinding.finding_type == "CONTRADICTION",
        )
    )).scalars().all()

    contradictions_triggered: list[dict[str, Any]] = []
    for c in contradictions:
        c_refs = c.evidence_refs or []
        if str(variant_file_id) in c_refs:
            contradictions_triggered.append({
                "id": str(c.id),
                "title": c.title,
                "severity": c.severity,
                "confidence": c.confidence,
            })

    return {
        "parent_id": str(parent_file_id),
        "variant_id": str(variant_file_id),
        "diff_summary": diff.summary,
        "added_events_count": len(added_event_ids),
        "new_entities": new_entities,
        "new_entity_count": len(new_entities),
        "new_relationships": new_relationships,
        "new_relationship_count": len(new_relationships),
        "reinforced_relationship_count": len(reinforced_relationships),
        "contradictions_triggered": contradictions_triggered,
    }
