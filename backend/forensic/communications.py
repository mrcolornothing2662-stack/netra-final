from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Communications Lens Builder
Projects CDR, call logs, WhatsApp, and SMS communications into participant graphs,
burst detection signals, and 24-hour temporal distributions.
"""
from collections import defaultdict
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


DEFAULT_BURST_WINDOW_MINUTES: int = 30
DEFAULT_BURST_MIN_EVENTS: int = 3


async def build_communications_lens(
    db: AsyncSession,
    case: Case,
    entity_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    cutoff_timestamp: Optional[datetime] = None,
    burst_window_minutes: int = DEFAULT_BURST_WINDOW_MINUTES,
    burst_min_events: int = DEFAULT_BURST_MIN_EVENTS,
) -> dict[str, Any]:
    """
    Build the Communications Lens projection.
    Strictly read-only; no database rows are mutated.
    """
    case_id = case.id

    # 1. Fetch communication evidence events
    query = (
        select(EvidenceEvent)
        .where(
            EvidenceEvent.case_id == case_id,
            EvidenceEvent.event_type.in_(["call", "cdr", "whatsapp_msg", "sms", "communication"]),
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

    # 3. Analyze communications
    call_pairs: dict[tuple[str, str], dict[str, Any]] = {}
    whatsapp_senders: dict[str, dict[str, Any]] = {}
    hourly_distribution: dict[int, int] = defaultdict(int)
    all_timestamps: list[tuple[datetime, EvidenceEvent]] = []
    night_events: list[EvidenceEvent] = []
    evidence_file_ids: set[uuid.UUID] = set()

    comms_events: list[LensEvent] = []
    timeline_events: list[LensTimelineEvent] = []
    signals: list[LensSignal] = []

    total_calls = 0
    total_messages = 0
    total_duration_sec = 0

    for ev in events_filtered:
        if ev.evidence_file_id:
            evidence_file_ids.add(ev.evidence_file_id)

        meta = ev.event_metadata or {}
        caller = (meta.get("caller") or meta.get("sender") or "").strip()
        callee = (meta.get("callee") or meta.get("receiver") or meta.get("recipient") or "").strip()
        duration = meta.get("duration_sec") or meta.get("duration") or 0
        try:
            dur_sec = int(duration) if str(duration).isdigit() else 0
        except (ValueError, TypeError):
            dur_sec = 0

        source_doc = meta.get("source_doc") or ""
        source_page = ev.source_page
        source_line = ev.source_line
        ev_time_iso = ev.event_timestamp.isoformat() if ev.event_timestamp else None

        # Entity filtering
        ev_text = f"{caller} {callee} {ev.text_content or ''}".lower()
        if entity_id:
            if entity_id.lower() not in ev_text and str(ev.id) != entity_id:
                continue

        # Classify by event type
        is_msg = ev.event_type in ["whatsapp_msg", "sms"]
        if is_msg:
            total_messages += 1
            if caller:
                if caller not in whatsapp_senders:
                    whatsapp_senders[caller] = {
                        "sender": caller,
                        "message_count": 0,
                        "first_message": ev_time_iso,
                        "last_message": ev_time_iso,
                    }
                whatsapp_senders[caller]["message_count"] += 1
                whatsapp_senders[caller]["last_message"] = ev_time_iso
            summary_label = f"Message from {caller or 'Unknown'}: {(ev.text_content or '')[:60]}"
        else:
            total_calls += 1
            total_duration_sec += dur_sec
            if caller and callee:
                pair_key = tuple(sorted([caller, callee]))
                if pair_key not in call_pairs:
                    call_pairs[pair_key] = {
                        "caller": pair_key[0],
                        "callee": pair_key[1],
                        "call_count": 0,
                        "total_duration_sec": 0,
                        "first_call": ev_time_iso,
                        "last_call": ev_time_iso,
                        "evidence_refs": set(),
                        "event_refs": [],
                    }
                entry = call_pairs[pair_key]
                entry["call_count"] += 1
                entry["total_duration_sec"] += dur_sec
                entry["last_call"] = ev_time_iso
                if ev.evidence_file_id:
                    entry["evidence_refs"].add(str(ev.evidence_file_id))
                entry["event_refs"].append(str(ev.id))

            summary_label = f"Call: {caller or 'Unknown'} ➔ {callee or 'Unknown'} ({dur_sec}s)"

        if ev.event_timestamp:
            all_timestamps.append((ev.event_timestamp, ev))
            hourly_distribution[ev.event_timestamp.hour] += 1
            # Check for night activity (between 23:00 and 05:00)
            if ev.event_timestamp.hour >= 23 or ev.event_timestamp.hour < 5:
                night_events.append(ev)

        # Build LensEvent
        comms_events.append(
            LensEvent(
                id=str(ev.id),
                event_type=ev.event_type or "communication",
                event_time=ev_time_iso,
                recorded_at=ev.created_at.isoformat() if ev.created_at else datetime.now(timezone.utc).isoformat(),
                time_confidence="CONFIRMED" if ev.event_timestamp else "RECORDED_ONLY",
                summary=summary_label,
                details={
                    "caller": caller,
                    "callee": callee,
                    "duration_sec": dur_sec,
                    "text_preview": (ev.text_content or "")[:120],
                    "channel": ev.event_type,
                },
                evidence_file_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
                provenance_confidence=meta.get("confidence", 0.95),
            )
        )

        timeline_events.append(
            LensTimelineEvent(
                id=str(ev.id),
                timestamp=ev_time_iso,
                label=summary_label,
                category="COMMUNICATION",
                entities=[p for p in [caller, callee] if p],
                evidence_id=str(ev.evidence_file_id) if ev.evidence_file_id else None,
                source_doc=source_doc,
                source_page=source_page,
                source_line=source_line,
            )
        )

    # 4. Burst Detection (configurable burst_window_minutes and burst_min_events)
    all_timestamps.sort(key=lambda x: x[0])
    burst_window_sec = burst_window_minutes * 60
    i = 0
    while i < len(all_timestamps):
        j = i
        while j < len(all_timestamps) and (all_timestamps[j][0] - all_timestamps[i][0]).total_seconds() <= burst_window_sec:
            j += 1
        count = j - i
        if count >= burst_min_events:
            t_start = all_timestamps[i][0]
            t_end = all_timestamps[j - 1][0]
            burst_evs = [all_timestamps[k][1] for k in range(i, j)]
            dur_min = round((t_end - t_start).total_seconds() / 60, 1)

            participants = set()
            for bev in burst_evs:
                bmeta = bev.event_metadata or {}
                if bmeta.get("caller"):
                    participants.add(bmeta["caller"])
                if bmeta.get("callee"):
                    participants.add(bmeta["callee"])
                if bmeta.get("sender"):
                    participants.add(bmeta["sender"])

            signals.append(
                LensSignal(
                    id=str(uuid.uuid4()),
                    signal_type="COMMUNICATION_BURST",
                    severity="HIGH" if count >= 5 else "MEDIUM",
                    title=f"Heuristic Pattern Signal: Communication Burst ({count} events in {dur_min} min)",
                    description=(
                        f"Analytical heuristic: High-frequency burst of {count} communications observed between "
                        f"{t_start.strftime('%H:%M')} and {t_end.strftime('%H:%M')} (window <= {burst_window_minutes} min)."
                    ),
                    timestamp=t_start.isoformat(),
                    entities_involved=list(participants),
                    evidence_refs=[str(bev.evidence_file_id) for bev in burst_evs if bev.evidence_file_id],
                    event_refs=[str(bev.id) for bev in burst_evs],
                    metrics={
                        "event_count": count,
                        "duration_minutes": dur_min,
                        "start_time": t_start.isoformat(),
                        "end_time": t_end.isoformat(),
                    },
                )
            )
            i = j  # advance past burst window
        else:
            i += 1

    # 5. Night Activity Signal
    if len(night_events) >= 2:
        signals.append(
            LensSignal(
                id=str(uuid.uuid4()),
                signal_type="NIGHT_ACTIVITY",
                severity="LOW",
                title=f"Night Communications: {len(night_events)} events (23:00 - 05:00)",
                description=f"{len(night_events)} communication events occurred during late-night off-hours.",
                timestamp=night_events[0].event_timestamp.isoformat() if night_events[0].event_timestamp else None,
                entities_involved=list({
                    (ne.event_metadata or {}).get("caller") or (ne.event_metadata or {}).get("sender")
                    for ne in night_events
                    if (ne.event_metadata or {}).get("caller") or (ne.event_metadata or {}).get("sender")
                }),
                evidence_refs=[str(ne.evidence_file_id) for ne in night_events if ne.evidence_file_id],
                event_refs=[str(ne.id) for ne in night_events],
                metrics={"night_event_count": len(night_events)},
            )
        )

    # 6. Fetch Canonical Entities from DB
    ent_q = select(Entity).where(Entity.case_id == case_id)
    if cutoff_timestamp:
        ent_q = ent_q.where(Entity.created_at < cutoff_timestamp)
    db_entities = list((await db.execute(ent_q)).scalars().all())

    lens_entities: list[LensEntity] = []
    for e in db_entities:
        if e.entity_type in ["PHONE", "PER", "ORG"]:
            lens_entities.append(
                LensEntity(
                    id=str(e.id),
                    canonical_value=e.canonical_value,
                    entity_type=e.entity_type,
                    role="PARTICIPANT",
                    degree_centrality=e.degree_centrality or 0.0,
                    bridge_score=e.bridge_score or 0.0,
                    mention_count=0,
                    node_metadata=e.node_metadata or {},
                )
            )

    # Add dynamic phone participants from call pairs if not yet in entities
    existing_phones = {le.canonical_value.lower() for le in lens_entities}
    for pair_key, pair_data in call_pairs.items():
        for p_val in pair_key:
            if p_val and p_val.lower() not in existing_phones:
                lens_entities.append(
                    LensEntity(
                        id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{case_id}:{p_val}")),
                        canonical_value=p_val,
                        entity_type="PHONE",
                        role="PARTICIPANT",
                        mention_count=pair_data["call_count"],
                        node_metadata={},
                    )
                )
                existing_phones.add(p_val.lower())

    # 7. Fetch Relationships
    rel_q = select(Relationship).where(Relationship.case_id == case_id)
    if cutoff_timestamp:
        rel_q = rel_q.where(Relationship.created_at < cutoff_timestamp)
    db_rels = list((await db.execute(rel_q)).scalars().all())

    lens_relationships: list[LensRelationship] = []
    for r in db_rels:
        is_canon = RT.is_canonical_eligible(r.epistemic_status, r.verification_status)
        if r.verification_status == RT.REVIEW_REJECTED:
            is_canon = False

        if r.relationship_type in ["COMMUNICATED_WITH", "CALLED", "MESSAGED", "REGISTERED_TO", "SAME_AS"]:
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

    # 8. Fetch Findings relevant to communication domain
    find_q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
    if cutoff_timestamp:
        find_q = find_q.where(InvestigationFinding.created_at < cutoff_timestamp)
    db_findings = list((await db.execute(find_q)).scalars().all())

    lens_findings: list[LensFinding] = []
    for f in db_findings:
        if f.finding_type in ["COMMUNICATION_BURST", "SUSPICIOUS_CALL_PATTERN", "CDR_ANOMALY", "WHATSAPP_COORDINATION"] or "call" in f.title.lower() or "burst" in f.title.lower() or "cdr" in f.title.lower():
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

    # 9. Evidence File References
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

    # Clean up call pairs serialization
    serializable_call_pairs = []
    for pair_data in sorted(call_pairs.values(), key=lambda x: x["call_count"], reverse=True):
        serializable_call_pairs.append({
            "caller": pair_data["caller"],
            "callee": pair_data["callee"],
            "call_count": pair_data["call_count"],
            "total_duration_sec": pair_data["total_duration_sec"],
            "first_call": pair_data["first_call"],
            "last_call": pair_data["last_call"],
        })

    summary = {
        "total_calls": total_calls,
        "total_messages": total_messages,
        "total_duration_seconds": total_duration_sec,
        "total_duration_minutes": round(total_duration_sec / 60, 1),
        "unique_call_pairs": len(call_pairs),
        "bursts_count": len([s for s in signals if s.signal_type == "COMMUNICATION_BURST"]),
        "night_events_count": len(night_events),
        "call_pairs": serializable_call_pairs[:15],
        "whatsapp_senders": sorted(whatsapp_senders.values(), key=lambda x: x["message_count"], reverse=True)[:10],
        "hourly_distribution": {str(h): hourly_distribution[h] for h in range(24)},
    }

    return {
        "summary": summary,
        "entities": lens_entities,
        "events": comms_events,
        "relationships": lens_relationships,
        "signals": signals,
        "findings": lens_findings,
        "evidence_refs": evidence_refs,
        "timeline": timeline_events,
    }
