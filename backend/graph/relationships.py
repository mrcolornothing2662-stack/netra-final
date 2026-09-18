from __future__ import annotations

"""
CyberDrishti AI — Unified Case Graph Relationship Service

Turns structured evidence events into persisted, semantically typed edges.

Two layers live here:

  • derive_observed_relationships()      — pure, deterministic, DB-free
  • materialize_observed_relationships() — loads events/mentions, derives and
                                           upserts Relationship rows with full
                                           evidence + event provenance.

Observed edges carry evidence_refs/event_refs so the investigator can always
answer "why is this relationship here?". Inferred edges are written through the
same upsert path by cognitive engines (see routes/correlations.py) so a single
table expresses both observed and inferred relationships.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from graph import relationship_types as RT


# ── Draft produced by pure derivation ─────────────────────────────────────────

@dataclass
class RelationshipDraft:
    source_value: str
    target_value: str
    relationship_type: str
    epistemic_status: str = RT.OBSERVED
    direction: str = RT.OUTBOUND
    confidence: float = 1.0
    amount: float | None = None
    timestamp: datetime | None = None
    evidence_refs: list[str] = field(default_factory=list)
    event_refs: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    source_engine: str | None = None
    engine_version: str | None = None
    component_scores: dict = field(default_factory=dict)
    reason_codes: list = field(default_factory=list)
    observation_count: int = 1


# ── Normalisation helpers ─────────────────────────────────────────────────────

_WS_RE = re.compile(r"[\s\-\(\)\.]+")
_NON_DIGIT_RE = re.compile(r"\D+")


def _norm(value: Any) -> str:
    """Case/space/punctuation-insensitive key for entity matching."""
    return _WS_RE.sub("", str(value or "")).strip().lower()


def _phone_key(value: Any) -> str | None:
    digits = _NON_DIGIT_RE.sub("", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else None


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise for comparison — SQLite drops tzinfo, so treat naive as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sanitize(value: Any) -> Any:
    """Keep JSON payloads free of characters that break legacy text columns."""
    if isinstance(value, str):
        return value.replace("\u20b9", "Rs.")
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("\u20b9", "").strip())
    except (ValueError, TypeError):
        return None


class _MentionIndex:
    """Resolve a raw metadata value (account/phone) to an event entity mention."""

    def __init__(self, mentions: Sequence[dict]):
        self._by_value: dict[str, dict] = {}
        self._by_phone: dict[str, dict] = {}
        for mention in mentions:
            value = mention.get("canonical_value")
            if not value:
                continue
            self._by_value.setdefault(_norm(value), mention)
            pk = _phone_key(value)
            if pk:
                self._by_phone.setdefault(pk, mention)

    def find(self, value: Any) -> dict | None:
        if value is None:
            return None
        hit = self._by_value.get(_norm(value))
        if hit:
            return hit
        pk = _phone_key(value)
        if pk:
            return self._by_phone.get(pk)
        return None


def _pair_key(draft: RelationshipDraft) -> tuple[str, str, str]:
    return (
        _norm(draft.source_value),
        _norm(draft.target_value),
        draft.relationship_type,
    )


# ── Per-event-type derivation ─────────────────────────────────────────────────

def _event_common(event: dict) -> tuple[str | None, dict, list[dict], datetime | None, list[str], list[str]]:
    event_id = event.get("id")
    metadata = event.get("event_metadata") or event.get("metadata") or {}
    mentions = event.get("entity_mentions") or []
    timestamp = _coerce_dt(event.get("event_timestamp") or event.get("timestamp"))
    event_refs = [str(event_id)] if event_id else []
    evidence_file_id = event.get("evidence_file_id")
    evidence_refs = [str(evidence_file_id)] if evidence_file_id else []
    return event_id, metadata, mentions, timestamp, event_refs, evidence_refs


def _typed_bank(event: dict, index: _MentionIndex) -> list[RelationshipDraft]:
    _, meta, _, ts, event_refs, evidence_refs = _event_common(event)
    from_raw = meta.get("from_account")
    to_raw = meta.get("to_account") or meta.get("upi_id")
    source = index.find(from_raw)
    target = index.find(to_raw)
    if not source or not target or source is target:
        return []
    return [RelationshipDraft(
        source_value=source["canonical_value"],
        target_value=target["canonical_value"],
        relationship_type=RT.TRANSFERRED_TO,
        direction=RT.OUTBOUND,
        confidence=1.0,
        amount=_to_float(meta.get("amount") or meta.get("debit") or meta.get("credit")),
        timestamp=ts,
        evidence_refs=evidence_refs,
        event_refs=event_refs,
        attributes=_sanitize({
            "channel": meta.get("channel"),
            "ref_no": meta.get("ref_no"),
            "status": meta.get("status"),
            "narration": meta.get("narration"),
            "source_doc": meta.get("source_doc") or event.get("source_doc"),
        }),
    )]


def _typed_call(event: dict, index: _MentionIndex) -> list[RelationshipDraft]:
    _, meta, _, ts, event_refs, evidence_refs = _event_common(event)
    source = index.find(meta.get("caller"))
    target = index.find(meta.get("callee"))
    if not source or not target or source is target:
        return []
    return [RelationshipDraft(
        source_value=source["canonical_value"],
        target_value=target["canonical_value"],
        relationship_type=RT.CALLED,
        direction=RT.OUTBOUND,
        confidence=1.0,
        timestamp=ts,
        evidence_refs=evidence_refs,
        event_refs=event_refs,
        attributes=_sanitize({
            "duration_sec": meta.get("duration_sec"),
            "call_type": meta.get("call_type"),
            "cell_id": meta.get("cell_id"),
            "imei": meta.get("imei"),
            "location": meta.get("location"),
        }),
    )]


def _typed_message(event: dict, index: _MentionIndex, mentions: list[dict]) -> list[RelationshipDraft]:
    _, meta, _, ts, event_refs, evidence_refs = _event_common(event)
    sender = index.find(meta.get("sender"))
    if not sender or meta.get("is_system"):
        return []
    drafts: list[RelationshipDraft] = []
    for mention in mentions:
        if mention is sender:
            continue
        other = index.find(mention.get("canonical_value"))
        if not other or other is sender:
            continue
        drafts.append(RelationshipDraft(
            source_value=sender["canonical_value"],
            target_value=other["canonical_value"],
            relationship_type=RT.MESSAGED,
            direction=RT.OUTBOUND,
            confidence=1.0,
            timestamp=ts,
            evidence_refs=evidence_refs,
            event_refs=event_refs,
            attributes=_sanitize({"media_omitted": meta.get("media_omitted")}),
        ))
    return drafts


def _typed_network(event: dict, index: _MentionIndex) -> list[RelationshipDraft]:
    _, meta, _, ts, event_refs, evidence_refs = _event_common(event)
    dev_raw = meta.get("device")
    ip_raw = meta.get("ip")
    source = index.find(dev_raw)
    target = index.find(ip_raw)
    if not source or not target or source is target:
        return []
    return [RelationshipDraft(
        source_value=source["canonical_value"],
        target_value=target["canonical_value"],
        relationship_type=RT.CONNECTED_TO,
        direction=RT.OUTBOUND,
        epistemic_status=RT.OBSERVED,
        confidence=1.0,
        amount=None,
        timestamp=ts,
        evidence_refs=evidence_refs,
        event_refs=event_refs,
        attributes=_sanitize({
            "port": meta.get("port"),
            "action": meta.get("action"),
            "destination": meta.get("destination"),
            "source_doc": meta.get("source_doc") or event.get("source_doc"),
        }),
    )]


def _typed_location_timeline(event: dict, index: _MentionIndex) -> list[RelationshipDraft]:
    _, meta, _, ts, event_refs, evidence_refs = _event_common(event)
    phone_raw = meta.get("phone")
    tower_raw = meta.get("cell_tower")
    source = index.find(phone_raw)
    target = index.find(tower_raw)
    if not source or not target or source is target:
        return []
    return [RelationshipDraft(
        source_value=source["canonical_value"],
        target_value=target["canonical_value"],
        relationship_type=RT.LOCATED_AT,
        direction=RT.OUTBOUND,
        epistemic_status=RT.OBSERVED,
        confidence=1.0,
        amount=None,
        timestamp=ts,
        evidence_refs=evidence_refs,
        event_refs=event_refs,
        attributes=_sanitize({
            "city": meta.get("city"),
            "observation": meta.get("observation"),
            "limitation": meta.get("limitation"),
            "source_doc": meta.get("source_doc") or event.get("source_doc"),
        }),
    )]


_NON_RELATIONAL_TYPES = frozenset({"AMOUNT", "KEYWORD", "TRANSACTION", "TXN", "DATE", "TIME", "TIMESTAMP"})


def _cooccurrence(event: dict, mentions: list[dict]) -> list[RelationshipDraft]:
    _, _, _, ts, event_refs, evidence_refs = _event_common(event)
    drafts: list[RelationshipDraft] = []
    rel_mentions = [
        m for m in mentions
        if (m.get("entity_type") or "").upper() not in _NON_RELATIONAL_TYPES
    ]
    if len(rel_mentions) > 20:
        rel_mentions = rel_mentions[:20]
    for i in range(len(rel_mentions)):
        for j in range(i + 1, len(rel_mentions)):
            a, b = rel_mentions[i], rel_mentions[j]
            av, bv = a.get("canonical_value"), b.get("canonical_value")
            if not av or not bv or _norm(av) == _norm(bv):
                continue
            drafts.append(RelationshipDraft(
                source_value=av,
                target_value=bv,
                relationship_type=RT.CO_OCCURRENCE,
                direction=RT.BIDIRECTIONAL,
                confidence=1.0,
                timestamp=ts,
                evidence_refs=evidence_refs,
                event_refs=event_refs,
                attributes=_sanitize({"event_type": event.get("event_type")}),
            ))
    return drafts


# ── Public pure derivation ────────────────────────────────────────────────────

def derive_observed_relationships(events: Iterable[dict]) -> list[RelationshipDraft]:
    """
    Derive observed relationships from structured events.

    Each event expects: id, event_type, event_timestamp, event_metadata,
    evidence_file_id and entity_mentions [{canonical_value, entity_type, ...}].

    Typed edges (TRANSFERRED_TO / CALLED / MESSAGED) are emitted where the
    evidence supports them; every remaining co-located pair yields a
    CO_OCCURRENCE edge. Results are de-duplicated per (source, target, type).
    """
    aggregated: dict[tuple[str, str, str], RelationshipDraft] = {}

    def _add(draft: RelationshipDraft) -> None:
        key = _pair_key(draft)
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = draft
            return
        existing.observation_count += 1
        existing.event_refs = list(dict.fromkeys(existing.event_refs + draft.event_refs))
        existing.evidence_refs = list(dict.fromkeys(existing.evidence_refs + draft.evidence_refs))
        if draft.amount is not None:
            existing.amount = draft.amount
        if draft.timestamp is not None:
            incoming_ts = _as_utc(draft.timestamp)
            existing_ts = _as_utc(existing.timestamp)
            if existing_ts is None or incoming_ts > existing_ts:
                existing.timestamp = draft.timestamp

    for event in events:
        mentions = event.get("entity_mentions") or []
        index = _MentionIndex(mentions)
        event_type = event.get("event_type")
        if event_type == "seizure_memo":
            # File 10 is an inventory/custody memo.
            # Never generate arbitrary CO_OCCURRENCE edges from table columns.
            continue

        typed: list[RelationshipDraft] = []
        if event_type == "bank_txn":
            typed = _typed_bank(event, index)
        elif event_type == "call":
            typed = _typed_call(event, index)
        elif event_type == "whatsapp_msg":
            typed = _typed_message(event, index, mentions)
        elif event_type == "network_log":
            typed = _typed_network(event, index)
        elif event_type == "location_timeline":
            typed = _typed_location_timeline(event, index)

        for draft in typed:
            _add(draft)

        # For location timeline observations, the typed LOCATED_AT edge
        # fully represents the observation with city in attributes;
        # do not emit redundant arbitrary co-occurrence edges.
        if event_type == "location_timeline" and typed:
            continue

        # Typed pairs already captured — suppress their duplicate co-occurrence
        # edge regardless of the typed relationship's direction/type.
        typed_pairs = {
            frozenset((_norm(d.source_value), _norm(d.target_value))) for d in typed
        }
        for draft in _cooccurrence(event, mentions):
            pair = frozenset((_norm(draft.source_value), _norm(draft.target_value)))
            if pair in typed_pairs:
                continue
            _add(draft)

    return list(aggregated.values())


# ── Persistence ───────────────────────────────────────────────────────────────

def _merge_unique(existing: Any, incoming: Sequence[str]) -> list[str]:
    base = list(existing) if isinstance(existing, (list, tuple)) else []
    return list(dict.fromkeys(base + [str(x) for x in incoming]))


async def upsert_relationship(
    db: AsyncSession,
    *,
    case_id,
    source_entity_id,
    target_entity_id,
    relationship_type: str,
    epistemic_status: str = RT.OBSERVED,
    direction: str = RT.OUTBOUND,
    confidence: float = 1.0,
    amount: float | None = None,
    timestamp: datetime | None = None,
    evidence_refs: Sequence[str] = (),
    event_refs: Sequence[str] = (),
    attributes: dict | None = None,
    source_engine: str | None = None,
    engine_version: str | None = None,
    component_scores: dict | None = None,
    reason_codes: Sequence[str] = (),
    observation_increment: int = 1,
):
    """
    Idempotently upsert one case-graph edge.

    The uniqueness key is (case_id, source, target, relationship_type,
    epistemic_status), so re-processing evidence aggregates provenance onto the
    same edge instead of creating duplicates, while observed and inferred edges
    between the same entities remain distinct rows.
    """
    from db.models import Relationship

    def _find():
        return db.execute(
            select(Relationship).where(
                Relationship.case_id == case_id,
                Relationship.source_entity_id == source_entity_id,
                Relationship.target_entity_id == target_entity_id,
                Relationship.relationship_type == relationship_type,
                Relationship.epistemic_status == epistemic_status,
            )
        )

    existing = (await _find()).scalars().first()

    if existing is None:
        row = Relationship(
            case_id=case_id,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relationship_type=relationship_type,
            direction=direction,
            epistemic_status=epistemic_status,
            confidence=confidence,
            amount=amount,
            event_timestamp=timestamp,
            first_seen=timestamp,
            last_seen=timestamp,
            observation_count=observation_increment,
            attributes=_sanitize(attributes or {}),
            evidence_refs=_merge_unique([], evidence_refs),
            event_refs=_merge_unique([], event_refs),
            source_engine=source_engine,
            engine_version=engine_version,
            component_scores=_sanitize(component_scores or {}),
            reason_codes=_sanitize(list(reason_codes)),
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
            return row, True
        except IntegrityError:
            # Concurrent writer won the race — fall through to the update path.
            existing = (await _find()).scalars().first()
            if existing is None:
                raise

    existing.evidence_refs = _merge_unique(existing.evidence_refs, evidence_refs)
    existing.event_refs = _merge_unique(existing.event_refs, event_refs)
    existing.observation_count = (existing.observation_count or 0) + observation_increment
    if amount is not None:
        existing.amount = amount
    incoming_ts = _as_utc(timestamp)
    if incoming_ts is not None:
        existing_ts = _as_utc(existing.event_timestamp)
        if existing_ts is None or incoming_ts > existing_ts:
            existing.event_timestamp = timestamp
        first_seen = _as_utc(existing.first_seen)
        if first_seen is None or incoming_ts < first_seen:
            existing.first_seen = timestamp
        last_seen = _as_utc(existing.last_seen)
        if last_seen is None or incoming_ts > last_seen:
            existing.last_seen = timestamp
    if attributes:
        merged = dict(existing.attributes or {})
        merged.update(_sanitize(attributes))
        existing.attributes = merged
    if component_scores:
        existing.component_scores = _sanitize(component_scores)
    if reason_codes:
        existing.reason_codes = _sanitize(list(reason_codes))
    if source_engine:
        existing.source_engine = source_engine
    if engine_version:
        existing.engine_version = engine_version
    if epistemic_status == RT.INFERRED and confidence is not None:
        existing.confidence = confidence
    await db.flush()
    return existing, False


async def materialize_observed_relationships(
    db: AsyncSession,
    case_id,
    *,
    evidence_file_id=None,
) -> dict[str, int]:
    """
    Derive and persist OBSERVED relationships for a case (or a single evidence
    file). Returns {"drafts", "created", "updated", "skipped"} counts.
    """
    from db.models import Entity, EntityMention, EvidenceEvent, Relationship

    entities = (await db.execute(
        select(Entity).where(Entity.case_id == case_id)
    )).scalars().all()
    if not entities:
        return {"drafts": 0, "created": 0, "updated": 0, "skipped": 0}

    entity_lookup: dict[str, Entity] = {}
    for entity in entities:
        entity_lookup.setdefault(_norm(entity.canonical_value), entity)
        pk = _phone_key(entity.canonical_value)
        if pk:
            entity_lookup.setdefault("phone:" + pk, entity)

    event_q = select(EvidenceEvent).where(EvidenceEvent.case_id == case_id)
    if evidence_file_id is not None:
        event_q = event_q.where(EvidenceEvent.evidence_file_id == evidence_file_id)
    events = (await db.execute(event_q)).scalars().all()
    if not events:
        return {"drafts": 0, "created": 0, "updated": 0, "skipped": 0}

    if evidence_file_id is not None:
        mention_rows = (await db.execute(
            select(EntityMention)
            .join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
            .where(EvidenceEvent.evidence_file_id == evidence_file_id)
        )).scalars().all()
    else:
        mention_rows = (await db.execute(
            select(EntityMention)
            .join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id)
            .where(EvidenceEvent.case_id == case_id)
        )).scalars().all()

    entity_id_to_value = {e.id: e.canonical_value for e in entities}
    mentions_by_event: dict[Any, list[dict]] = {}
    for mention in mention_rows:
        value = entity_id_to_value.get(mention.entity_id)
        if not value:
            continue
        mentions_by_event.setdefault(mention.evidence_event_id, []).append({
            "canonical_value": value,
            "entity_type": mention.entity_type,
            "entity_id": mention.entity_id,
        })

    event_dicts = [
        {
            "id": str(ev.id),
            "event_type": ev.event_type,
            "event_timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            "event_metadata": ev.event_metadata or {},
            "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
            "entity_mentions": mentions_by_event.get(ev.id, []),
        }
        for ev in events
    ]

    drafts = derive_observed_relationships(event_dicts)

    # High-throughput batch materialization: pre-fetch existing case relationships
    existing_rels = (await db.execute(
        select(Relationship).where(Relationship.case_id == case_id)
    )).scalars().all()
    rel_map = {
        (r.source_entity_id, r.target_entity_id, r.relationship_type, r.epistemic_status): r
        for r in existing_rels
    }

    created = updated = skipped = 0
    for draft in drafts:
        source = entity_lookup.get(_norm(draft.source_value))
        target = entity_lookup.get(_norm(draft.target_value))
        if source is None or target is None or source.id == target.id:
            skipped += 1
            continue

        key = (source.id, target.id, draft.relationship_type, draft.epistemic_status)
        existing = rel_map.get(key)
        if existing is None:
            row = Relationship(
                case_id=case_id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relationship_type=draft.relationship_type,
                direction=draft.direction,
                epistemic_status=draft.epistemic_status,
                confidence=draft.confidence,
                amount=draft.amount,
                event_timestamp=draft.timestamp,
                first_seen=draft.timestamp,
                last_seen=draft.timestamp,
                observation_count=draft.observation_count,
                attributes=_sanitize(draft.attributes or {}),
                evidence_refs=_merge_unique([], draft.evidence_refs),
                event_refs=_merge_unique([], draft.event_refs),
                source_engine=draft.source_engine,
                engine_version=draft.engine_version,
                component_scores=_sanitize(draft.component_scores or {}),
                reason_codes=_sanitize(list(draft.reason_codes)),
            )
            db.add(row)
            rel_map[key] = row
            created += 1
        else:
            existing.evidence_refs = _merge_unique(existing.evidence_refs, draft.evidence_refs)
            existing.event_refs = _merge_unique(existing.event_refs, draft.event_refs)
            existing.observation_count = (existing.observation_count or 0) + draft.observation_count
            if draft.amount is not None:
                existing.amount = draft.amount
            incoming_ts = _as_utc(draft.timestamp)
            if incoming_ts is not None:
                existing_ts = _as_utc(existing.event_timestamp)
                if existing_ts is None or incoming_ts > existing_ts:
                    existing.event_timestamp = draft.timestamp
                first_seen = _as_utc(existing.first_seen)
                if first_seen is None or incoming_ts < first_seen:
                    existing.first_seen = draft.timestamp
                last_seen = _as_utc(existing.last_seen)
                if last_seen is None or incoming_ts > last_seen:
                    existing.last_seen = draft.timestamp
            if draft.attributes:
                merged = dict(existing.attributes or {})
                merged.update(_sanitize(draft.attributes))
                existing.attributes = merged
            if draft.component_scores:
                existing.component_scores = _sanitize(draft.component_scores)
            if draft.reason_codes:
                existing.reason_codes = _sanitize(list(draft.reason_codes))
            if draft.source_engine:
                existing.source_engine = draft.source_engine
            if draft.engine_version:
                existing.engine_version = draft.engine_version
            if draft.epistemic_status == RT.INFERRED and draft.confidence is not None:
                existing.confidence = draft.confidence
            updated += 1

    await db.flush()
    return {"drafts": len(drafts), "created": created, "updated": updated, "skipped": skipped}
