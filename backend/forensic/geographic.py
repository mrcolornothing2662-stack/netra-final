from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Travel / Geographic Lens Builder
Projects cell-site observations and location references into temporal tower hops
while strictly enforcing non-GPS disclaimers and timestamp integrity.
"""
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, EvidenceEvent, Entity, Relationship, InvestigationFinding, EvidenceFile
from forensic.contracts import (
    LensEntity,
    LensEvent,
    LensRelationship,
    LensSignal,
    LensFinding,
    EvidenceRef,
    LensTimelineEvent,
)
import graph.relationship_types as RT

LOCATION_DISCLAIMER = (
    "TECHNICAL LIMITATION: Observed cell-site association — NOT exact physical location. "
    "Telemetry reflects base transceiver station registration and radio propagation, "
    "NOT an exact physical GPS fix. Sector antenna registration cannot determine exact coordinates or physical presence."
)


async def build_geographic_lens(
    db: AsyncSession,
    case: Case,
    entity_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    cutoff_timestamp: Optional[datetime] = None,
) -> dict[str, Any]:
    """
    Build the Travel / Geographic Lens projection.
    Strictly read-only; no database rows are mutated.
    """
    case_id = case.id

    # 1. Fetch location evidence events
    query = (
        select(EvidenceEvent)
        .where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type.in_(["location_timeline", "location", "cell_site", "cdr_location"]),
        )
        .order_by(EvidenceEvent.event_timestamp.asc().nulls_last())
    )
    if cutoff_timestamp:
        query = query.where(EvidenceEvent.created_at < cutoff_timestamp)

    events_raw = list((await db.execute(query)).scalars().all())

    # 2. Filter events by time range
    events_filtered = []
    for ev in events_raw:
        if ev.event_timestamp:
            if start_time and ev.event_timestamp < start_time:
                continue
            if end_time and ev.event_timestamp > end_time:
                continue
        events_filtered.append(ev)

    # 3. Process observations and tower hops
    geo_events: list[LensEvent] = []
    timeline_events: list[LensTimelineEvent] = []
    signals: list[LensSignal] = []

    unique_towers: set[str] = set()
    unique_cities: set[str] = set()
    associated_phones: set[str] = set()
    evidence_file_ids: set[uuid.UUID] = set()

    # Chronological observations per phone
    phone_observations: dict[str, list[dict[str, Any]]] = {}

    for ev in events_filtered:
        if ev.evidence_file_id:
            evidence_file_ids.add(ev.evidence_file_id)

        meta = ev.event_metadata or {}
        phone = (meta.get("phone") or meta.get("caller") or meta.get("mobile") or "").strip()
        cell_tower = (meta.get("cell_tower") or meta.get("tower_id") or meta.get("cell_site") or "").strip()
        city = (meta.get("city") or meta.get("location_ref") or "").strip()
        obs_note = (meta.get("observation") or meta.get("note") or "Cell-site association").strip()

        source_doc = meta.get("source_doc") or ""
        source_page = ev.source_page
        source_line = ev.source_line

        # Entity filtering
        ev_text = f"{phone} {cell_tower} {city} {ev.text_content or ''}".lower()
        if entity_id:
            if entity_id.lower() not in ev_text and str(ev.id) != entity_id:
                continue

        if cell_tower:
            unique_towers.add(cell_tower)
        if city:
            unique_cities.add(city)
        if phone:
            associated_phones.add(phone)

        # Handle timestamps strictly (Invariant 5 & 6)
        ev_time_iso = ev.event_timestamp.isoformat() if ev.event_timestamp else None
        time_confidence = "CONFIRMED" if ev.event_timestamp else "RECORDED_ONLY"
        time_warning = None if ev.event_timestamp else "No verified source timestamp; cell association record only"

        # Forensic phrasing
        summary_text = (
            f"Phone identifier '{phone}' associated with cell site '{cell_tower or city}'"
            if phone
            else f"Cell site association: '{cell_tower or city}'"
        )

        geo_events.append(
            LensEvent(
                id=str(ev.id),
                event_type=ev.event_type or "location_timeline",
                event_time=ev_time_iso,
                recorded_at=ev.created_at.isoformat() if ev.created_at else datetime.now(timezone.utc).isoformat(),
                time_confidence=time_confidence,
                summary=summary_text,
                details={
                    "phone": phone,
                    "cell_tower": cell_tower,
                    "city": city,
                    "observation_note": obs_note,
                    "disclaimer": LOCATION_DISCLAIMER,
                },
                evidence_file_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
                provenance_confidence=meta.get("confidence", 0.95),
                time_warning=time_warning,
            )
        )

        timeline_events.append(
            LensTimelineEvent(
                id=str(ev.id),
                timestamp=ev_time_iso,
                label=f"{cell_tower or city} (Tower observation)",
                category="GEOGRAPHIC",
                entities=[p for p in [phone, cell_tower, city] if p],
                evidence_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
                disclaimer=LOCATION_DISCLAIMER,
            )
        )

        if phone and ev.event_timestamp:
            if phone not in phone_observations:
                phone_observations[phone] = []
            phone_observations[phone].append({
                "timestamp": ev.event_timestamp,
                "cell_tower": cell_tower,
                "city": city,
                "event_id": str(ev.id),
                "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
                "source_doc": source_doc,
                "source_page": source_page,
                "source_line": source_line,
            })

    # 4. Generate Tower Movement Hops & Signals
    tower_hops_list: list[dict[str, Any]] = []

    for ph, obs_list in phone_observations.items():
        obs_list.sort(key=lambda x: x["timestamp"])
        for i in range(len(obs_list) - 1):
            o1 = obs_list[i]
            o2 = obs_list[i + 1]
            diff_sec = (o2["timestamp"] - o1["timestamp"]).total_seconds()
            diff_min = round(diff_sec / 60, 1)

            # Record hop
            hop_data = {
                "phone": ph,
                "from_tower": o1["cell_tower"] or o1["city"],
                "to_tower": o2["cell_tower"] or o2["city"],
                "from_time": o1["timestamp"].isoformat(),
                "to_time": o2["timestamp"].isoformat(),
                "gap_minutes": diff_min,
                "from_city": o1["city"],
                "to_city": o2["city"],
            }
            tower_hops_list.append(hop_data)

            # Rapid transit signal between different cities/towers
            if o1["cell_tower"] != o2["cell_tower"] and 0 < diff_min <= 120:
                signals.append(
                    LensSignal(
                        id=str(uuid.uuid4()),
                        signal_type="TOWER_HOPPING",
                        severity="MEDIUM" if o1["city"] != o2["city"] else "LOW",
                        title=f"Cell Site Transition: {o1['cell_tower']} ➔ {o2['cell_tower']} ({diff_min} min)",
                        description=(
                            f"Phone identifier '{ph}' was associated with cell site '{o1['cell_tower']}' "
                            f"at {o1['timestamp'].strftime('%H:%M')} and subsequently with '{o2['cell_tower']}' "
                            f"at {o2['timestamp'].strftime('%H:%M')} ({diff_min} min delta). "
                            f"Note: {LOCATION_DISCLAIMER}"
                        ),
                        timestamp=o2["timestamp"].isoformat(),
                        entities_involved=[ph, o1["cell_tower"], o2["cell_tower"]],
                        evidence_refs=[ref for ref in [o1["evidence_file_id"], o2["evidence_file_id"]] if ref],
                        event_refs=[o1["event_id"], o2["event_id"]],
                        metrics={
                            "gap_minutes": diff_min,
                            "from_tower": o1["cell_tower"],
                            "to_tower": o2["cell_tower"],
                            "disclaimer": LOCATION_DISCLAIMER,
                        },
                    )
                )

    # 5. Fetch Canonical Entities
    ent_q = select(Entity).where(Entity.case_id == case_id)
    if cutoff_timestamp:
        ent_q = ent_q.where(Entity.created_at < cutoff_timestamp)
    db_entities = list((await db.execute(ent_q)).scalars().all())

    lens_entities: list[LensEntity] = []
    for e in db_entities:
        if e.entity_type in ["PHONE", "LOCATION", "DEVICE", "PER"]:
            lens_entities.append(
                LensEntity(
                    id=str(e.id),
                    canonical_value=e.canonical_value,
                    entity_type=e.entity_type,
                    role="LOCATION" if e.entity_type == "LOCATION" else "PHONE",
                    degree_centrality=e.degree_centrality or 0.0,
                    bridge_score=e.bridge_score or 0.0,
                    mention_count=0,
                    node_metadata=e.node_metadata or {},
                )
            )

    # Add dynamic tower / phone nodes if not in DB entities
    existing_vals = {le.canonical_value.lower() for le in lens_entities}
    for tower_id in unique_towers:
        if tower_id.lower() not in existing_vals:
            lens_entities.append(
                LensEntity(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{case_id}:{tower_id}")),
                    canonical_value=tower_id,
                    entity_type="LOCATION",
                    role="CELL_TOWER",
                    node_metadata={"disclaimer": LOCATION_DISCLAIMER},
                )
            )
            existing_vals.add(tower_id.lower())

    for ph_val in associated_phones:
        if ph_val.lower() not in existing_vals:
            lens_entities.append(
                LensEntity(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{case_id}:{ph_val}")),
                    canonical_value=ph_val,
                    entity_type="PHONE",
                    role="PHONE",
                    node_metadata={},
                )
            )
            existing_vals.add(ph_val.lower())

    # 6. Fetch Relationships
    rel_q = select(Relationship).where(Relationship.case_id == case_id)
    if cutoff_timestamp:
        rel_q = rel_q.where(Relationship.created_at < cutoff_timestamp)
    db_rels = list((await db.execute(rel_q)).scalars().all())

    lens_relationships: list[LensRelationship] = []
    for r in db_rels:
        is_canon = RT.is_canonical_eligible(r.epistemic_status, r.verification_status)
        if r.verification_status == RT.REVIEW_REJECTED:
            is_canon = False

        if r.relationship_type in ["LOCATED_AT", "ASSOCIATED_WITH", "REGISTERED_TO", "SAME_AS"]:
            lens_relationships.append(
                LensRelationship(
                    id=str(r.id),
                    source_entity_id=str(r.source_entity_id),
                    target_entity_id=str(r.target_entity_id),
                    relationship_type=r.relationship_type,
                    direction=r.direction,
                    epistemic_status=r.epistemic_status,
                    verification_status=r.verification_status,
                    is_canonical=is_canon,
                    confidence=r.confidence or 1.0,
                    evidence_refs=[str(ref) for ref in (r.evidence_refs or [])],
                    event_refs=[str(ref) for ref in (r.event_refs or [])],
                    created_by=str(r.created_by) if r.created_by else None,
                )
            )

    # 7. Fetch Findings relevant to geographic domain
    find_q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
    if cutoff_timestamp:
        find_q = find_q.where(InvestigationFinding.created_at < cutoff_timestamp)
    db_findings = list((await db.execute(find_q)).scalars().all())

    lens_findings: list[LensFinding] = []
    for f in db_findings:
        if f.finding_type in ["LOCATION_CO_OCCURRENCE", "TOWER_HOPPING", "TRAVEL_ANOMALY"] or "location" in f.title.lower() or "tower" in f.title.lower() or "cell" in f.title.lower():
            lens_findings.append(
                LensFinding(
                    id=str(f.id),
                    finding_type=f.finding_type,
                    title=f.title,
                    severity=f.severity,
                    confidence=float(f.confidence) if f.confidence is not None else 0.8,
                    status=f.status,
                    freshness_status=getattr(f, "freshness_status", "CURRENT") or "CURRENT",
                    generated_at_case_version=getattr(f, "generated_at_case_version", 1) or 1,
                    evidence_refs=[str(ref) for ref in (f.evidence_refs or [])],
                    entity_refs=[str(ref) for ref in (f.entity_refs or [])],
                    event_refs=[str(ref) for ref in (f.event_refs or [])],
                )
            )

    # 8. Evidence File References
    evidence_refs: list[EvidenceRef] = []
    if evidence_file_ids:
        file_q = select(EvidenceFile).where(EvidenceFile.id.in_(list(evidence_file_ids)))
        db_files = list((await db.execute(file_q)).scalars().all())
        for fl in db_files:
            evidence_refs.append(
                EvidenceRef(
                    id=str(fl.id),
                    file_name=fl.filename,
                    file_type=fl.file_type,
                    sha256=fl.sha256_hash,
                    uploaded_at=fl.uploaded_at.isoformat() if fl.uploaded_at else None,
                )
            )

    summary = {
        "total_observations": len(geo_events),
        "unique_cell_towers": len(unique_towers),
        "unique_cities": len(unique_cities),
        "associated_phones": len(associated_phones),
        "tower_hops_count": len(tower_hops_list),
        "tower_hops": tower_hops_list[:15],
        "disclaimer": LOCATION_DISCLAIMER,
    }

    return {
        "disclaimer": LOCATION_DISCLAIMER,
        "summary": summary,
        "entities": lens_entities,
        "events": geo_events,
        "relationships": lens_relationships,
        "signals": signals,
        "findings": lens_findings,
        "evidence_refs": evidence_refs,
        "timeline": timeline_events,
    }
