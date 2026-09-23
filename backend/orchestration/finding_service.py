from __future__ import annotations

"""
CyberDrishti AI — Finding Service

The only place that reads/writes InvestigationFinding rows. Engines return
CognitiveResult objects; the orchestrator funnels them here. Deduplication is
by (case_id, fingerprint) so repeated analysis is idempotent.
"""
import copy
import uuid
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import InvestigationFinding
from orchestration.contracts import CognitiveResult, HUMAN_REVIEW_STATUSES, STATUS_OPEN


def _merge_unique(existing: Any, incoming: Sequence[str]) -> list[str]:
    base = list(existing) if isinstance(existing, (list, tuple)) else []
    return list(dict.fromkeys(base + [str(x) for x in incoming]))


# Revision bookkeeping is kept compact: at most this many prior snapshots,
# and nested component_scores never carry the revision bookkeeping itself.
REVISION_HISTORY_LIMIT = 5
_SNAPSHOT_TEXT_LIMIT = 2000


def _finding_snapshot(row: InvestigationFinding) -> dict[str, Any]:
    """Full description of the current finding, used as the 'previous' state.

    Never includes the revision bookkeeping keys, so snapshots do not nest or
    grow without bound. Values are deep-copied so a stored snapshot can never be
    mutated by (or alias) the live row or another snapshot.
    """
    scores = copy.deepcopy(dict(row.component_scores or {}))
    scores.pop("revision_history", None)
    scores.pop("previous", None)
    scores.pop("revision_count", None)
    return {
        "title": row.title,
        "description": (row.description or "")[:_SNAPSHOT_TEXT_LIMIT],
        "severity": row.severity,
        "confidence": row.confidence,
        "status": row.status,
        "reasoning": (row.reasoning or "")[:_SNAPSHOT_TEXT_LIMIT],
        "component_scores": scores,
        "citations": copy.deepcopy(list(row.citations or [])),
        "at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _materially_changed(previous: dict[str, Any], result: CognitiveResult) -> bool:
    return (
        previous["title"] != result.title[:512]
        or (previous["description"] or "") != (result.description or "")[:_SNAPSHOT_TEXT_LIMIT]
        or previous["severity"] != result.severity
        or previous["confidence"] != result.confidence
    )


def _revision_metadata(scores: dict[str, Any]) -> dict[str, Any]:
    """Preserve existing revision metadata across an in-place update (deep-copied
    so the carried metadata never aliases the prior component_scores object)."""
    carried: dict[str, Any] = {}
    for key in ("revision_count", "previous", "revision_history"):
        if scores.get(key) is not None:
            carried[key] = copy.deepcopy(scores[key])
    return carried



async def upsert_finding(
    db: AsyncSession,
    case_id,
    result: CognitiveResult,
) -> tuple[InvestigationFinding, bool]:
    """Create or refresh one finding. Human review status is never overwritten."""
    fingerprint = result.fingerprint()

    def _find():
        return db.execute(
            select(InvestigationFinding).where(
                InvestigationFinding.case_id == case_id,
                InvestigationFinding.fingerprint == fingerprint,
            )
        )

    existing = (await _find()).scalar_one_or_none()

    if existing is None:
        row = InvestigationFinding(
            case_id=case_id,
            fingerprint=fingerprint,
            finding_type=result.finding_type,
            title=result.title[:512],
            description=result.description,
            confidence=result.confidence,
            severity=result.severity,
            status=result.status,
            source_engine=result.source_engine,
            engine_version=result.engine_version,
            entity_refs=list(result.entity_refs),
            event_refs=list(result.event_refs),
            evidence_refs=list(result.evidence_refs),
            component_scores=dict(result.component_scores),
            reason_codes=list(result.reason_codes),
            reasoning=result.reasoning,
            citations=list(result.citations),
            supporting_refs=list(result.supporting_refs),
            contradicting_refs=list(result.contradicting_refs),
            missing_information=list(result.missing_information),
            suggested_actions=list(result.suggested_actions),
            generated_at_case_version=result.generated_at_case_version,
            freshness_status=result.freshness_status,
            observed_at=result.observed_at,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
            return row, True
        except IntegrityError:
            existing = (await _find()).scalar_one_or_none()
            if existing is None:
                raise

    # Capture the FULL prior state BEFORE any overwrite. Order matters: "previous"
    # must describe the prior finding, never the newly-overwritten one.
    prior_scores = dict(existing.component_scores or {})
    previous = _finding_snapshot(existing)
    materially_changed = _materially_changed(previous, result)
    prior_revision_count = int(prior_scores.get("revision_count") or 0)
    prior_history = list(prior_scores.get("revision_history") or [])

    existing.finding_type = result.finding_type
    existing.title = result.title[:512]
    existing.description = result.description
    existing.confidence = result.confidence
    existing.severity = result.severity
    existing.source_engine = result.source_engine
    existing.engine_version = result.engine_version
    existing.entity_refs = _merge_unique(existing.entity_refs, result.entity_refs)
    existing.event_refs = _merge_unique(existing.event_refs, result.event_refs)
    existing.evidence_refs = _merge_unique(existing.evidence_refs, result.evidence_refs)
    existing.supporting_refs = _merge_unique(existing.supporting_refs or [], result.supporting_refs)
    existing.contradicting_refs = _merge_unique(existing.contradicting_refs or [], result.contradicting_refs)
    existing.missing_information = _merge_unique(existing.missing_information or [], result.missing_information)
    existing.suggested_actions = _merge_unique(existing.suggested_actions or [], result.suggested_actions)
    existing.generated_at_case_version = result.generated_at_case_version
    existing.freshness_status = result.freshness_status

    new_scores: dict[str, Any] = dict(result.component_scores)
    if materially_changed:
        # Preserve the actual prior state and append to a bounded history chain so
        # A→B→C remains recoverable (not merely B→C). The history entry is an
        # independent copy so it never aliases `previous`.
        new_scores["revision_count"] = prior_revision_count + 1
        new_scores["previous"] = previous
        new_scores["revision_history"] = (
            copy.deepcopy(prior_history) + [copy.deepcopy(previous)]
        )[-REVISION_HISTORY_LIMIT:]
        existing.reason_codes = _merge_unique(existing.reason_codes, ["REVISED"])
    else:
        # No material change: carry any previously recorded revision metadata so
        # an ordinary re-run does not erase it.
        new_scores.update(_revision_metadata(prior_scores))
    existing.component_scores = new_scores
    existing.reason_codes = _merge_unique(existing.reason_codes, result.reason_codes)

    existing.reasoning = result.reasoning
    existing.citations = list(result.citations)
    existing.observed_at = result.observed_at or existing.observed_at
    # Re-analysis may re-open an automatically derived finding, but must never
    # erase an investigator's CONFIRMED/DISMISSED verdict.
    if existing.status not in HUMAN_REVIEW_STATUSES and result.status == STATUS_OPEN:
        existing.status = STATUS_OPEN
    await db.flush()
    return existing, False


async def supersede_stale_findings(
    db: AsyncSession,
    case_id,
    engine_name: str,
    emitted_fingerprints: set[str],
) -> int:
    """Mark a successfully-run engine's OPEN findings SUPERSEDED when the engine
    no longer produces them. Human-confirmed findings are never superseded."""
    rows = list((await db.execute(
        select(InvestigationFinding).where(
            InvestigationFinding.case_id == case_id,
            InvestigationFinding.source_engine == engine_name,
            InvestigationFinding.status == STATUS_OPEN,
        )
    )).scalars().all())
    superseded = 0
    for row in rows:
        if row.fingerprint in emitted_fingerprints:
            continue
        row.status = "SUPERSEDED"
        row.reason_codes = _merge_unique(row.reason_codes, ["SUPERSEDED_BY_REANALYSIS"])
        superseded += 1
    if superseded:
        await db.flush()
    return superseded


async def upsert_findings(
    db: AsyncSession,
    case_id,
    results: Sequence[CognitiveResult],
) -> dict[str, int]:
    if not results:
        return {"created": 0, "updated": 0, "total": 0}

    # Pre-fetch existing findings for this case in a single query
    existing_rows = (await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
    )).scalars().all()
    existing_map = {r.fingerprint: r for r in existing_rows}

    created = updated = 0
    for result in results:
        fingerprint = result.fingerprint()
        existing = existing_map.get(fingerprint)
        if existing is None:
            row = InvestigationFinding(
                case_id=case_id,
                fingerprint=fingerprint,
                finding_type=result.finding_type,
                title=result.title[:512],
                description=result.description,
                confidence=result.confidence,
                severity=result.severity,
                status=result.status,
                source_engine=result.source_engine,
                engine_version=result.engine_version,
                entity_refs=list(result.entity_refs),
                event_refs=list(result.event_refs),
                evidence_refs=list(result.evidence_refs),
                component_scores=dict(result.component_scores),
                reason_codes=list(result.reason_codes),
                reasoning=result.reasoning,
                citations=list(result.citations),
                supporting_refs=list(result.supporting_refs),
                contradicting_refs=list(result.contradicting_refs),
                missing_information=list(result.missing_information),
                suggested_actions=list(result.suggested_actions),
                generated_at_case_version=result.generated_at_case_version,
                freshness_status=result.freshness_status,
                observed_at=result.observed_at,
            )
            db.add(row)
            existing_map[fingerprint] = row
            created += 1
        else:
            prior_scores = dict(existing.component_scores or {})
            previous = _finding_snapshot(existing)
            materially_changed = _materially_changed(previous, result)
            prior_revision_count = int(prior_scores.get("revision_count") or 0)
            prior_history = list(prior_scores.get("revision_history") or [])

            existing.finding_type = result.finding_type
            existing.title = result.title[:512]
            existing.description = result.description
            existing.confidence = result.confidence
            existing.severity = result.severity
            existing.source_engine = result.source_engine
            existing.engine_version = result.engine_version
            existing.entity_refs = _merge_unique(existing.entity_refs, result.entity_refs)
            existing.event_refs = _merge_unique(existing.event_refs, result.event_refs)
            existing.evidence_refs = _merge_unique(existing.evidence_refs, result.evidence_refs)
            existing.supporting_refs = _merge_unique(existing.supporting_refs or [], result.supporting_refs)
            existing.contradicting_refs = _merge_unique(existing.contradicting_refs or [], result.contradicting_refs)
            existing.missing_information = _merge_unique(existing.missing_information or [], result.missing_information)
            existing.suggested_actions = _merge_unique(existing.suggested_actions or [], result.suggested_actions)
            existing.generated_at_case_version = result.generated_at_case_version
            existing.freshness_status = result.freshness_status

            new_scores = dict(result.component_scores)
            if materially_changed:
                new_scores["revision_count"] = prior_revision_count + 1
                new_scores["previous"] = previous
                new_scores["revision_history"] = (
                    copy.deepcopy(prior_history) + [copy.deepcopy(previous)]
                )[-REVISION_HISTORY_LIMIT:]
                existing.reason_codes = _merge_unique(existing.reason_codes, ["REVISED"])
            else:
                new_scores.update(_revision_metadata(prior_scores))
            existing.component_scores = new_scores
            existing.reason_codes = _merge_unique(existing.reason_codes, result.reason_codes)
            existing.reasoning = result.reasoning
            existing.citations = list(result.citations)
            existing.observed_at = result.observed_at or existing.observed_at
            if existing.status not in HUMAN_REVIEW_STATUSES and result.status == STATUS_OPEN:
                existing.status = STATUS_OPEN
            updated += 1

    await db.flush()
    return {"created": created, "updated": updated, "total": len(results)}


def confidence_status_for(finding_type: str, confidence: float | None) -> str:
    """Honest meaning of a finding's confidence value.

    A bare number must never be presented as a probability when it is actually a
    rule score, a similarity, or a hand-set heuristic. No calibrated model exists
    in this build, so CALIBRATED is never emitted.
    """
    if finding_type == "MO_MATCH":
        return "SCREENING"
    if finding_type in ("HIDDEN_LINK", "CROSS_CASE_SIGNAL"):
        return "INFERRED"
    if finding_type == "COUNTERFACTUAL":
        return "SIMULATION"
    if finding_type in ("HYPOTHESIS", "UNCERTAINTY", "NEXT_BEST_ACTION"):
        return "NOT_CALIBRATED"
    if finding_type in ("CONTRADICTION", "FINGERPRINT_VARIANT", "REPLAY_ANOMALY", "VERIFICATION"):
        return "RULE_BASED"
    return "NOT_CALIBRATED" if confidence is not None else "UNRESOLVED"


def serialize_finding(row: InvestigationFinding) -> dict[str, Any]:
    from cognitive.uncertainty import determine_epistemic_tier

    tier, score_type, tier_desc = determine_epistemic_tier(
        row.finding_type,
        row.source_engine or "",
        row.confidence,
    )

    return {
        "id":               str(row.id),
        "case_id":          str(row.case_id),
        "fingerprint":      row.fingerprint,
        "finding_type":     row.finding_type,
        "title":            row.title,
        "description":      row.description,
        "confidence":       row.confidence,
        "confidence_status": confidence_status_for(row.finding_type, row.confidence),
        "confidence_details": {
            "epistemic_tier": tier,
            "score_type": score_type,
            "tier_description": tier_desc,
            "raw_score": row.confidence,
            "evidence_count": len(row.evidence_refs or []),
        },
        "severity":         row.severity,
        "status":           row.status,
        "source_engine":    row.source_engine,
        "engine_version":   row.engine_version,
        "entity_refs":      row.entity_refs or [],
        "event_refs":       row.event_refs or [],
        "evidence_refs":    row.evidence_refs or [],
        "component_scores": row.component_scores or {},
        "reason_codes":     row.reason_codes or [],
        "reasoning":        row.reasoning,
        "citations":        row.citations or [],
        "supporting_refs":  row.supporting_refs or [],
        "contradicting_refs": row.contradicting_refs or [],
        "missing_information": row.missing_information or [],
        "suggested_actions": row.suggested_actions or [],
        "generated_at_case_version": row.generated_at_case_version or 1,
        "freshness_status": row.freshness_status or "CURRENT",
        "has_evidence":     bool(row.evidence_refs),
        "observed_at":      row.observed_at.isoformat() if row.observed_at else None,
        "created_at":       row.created_at.isoformat() if row.created_at else None,
        "updated_at":       row.updated_at.isoformat() if row.updated_at else None,
    }


async def list_findings(
    db: AsyncSession,
    case_id,
    *,
    finding_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    min_confidence: float | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[InvestigationFinding]:
    q = select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
    if finding_type:
        q = q.where(InvestigationFinding.finding_type == finding_type)
    if severity:
        q = q.where(InvestigationFinding.severity == severity)
    if status:
        q = q.where(InvestigationFinding.status == status)
    if min_confidence is not None:
        q = q.where(InvestigationFinding.confidence >= min_confidence)
    q = q.order_by(InvestigationFinding.confidence.desc(), InvestigationFinding.created_at.desc())
    q = q.limit(limit).offset(offset)
    return list((await db.execute(q)).scalars().all())


async def get_finding(db: AsyncSession, finding_id: str) -> InvestigationFinding | None:
    try:
        finding_uuid = uuid.UUID(str(finding_id))
    except (TypeError, ValueError):
        return None
    return await db.get(InvestigationFinding, finding_uuid)
