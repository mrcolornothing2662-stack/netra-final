from __future__ import annotations

"""
Cross-Case Intelligence Adapter (Syndicate Radar / Blind Index)

Authorised cross-case analysis only. The orchestrator loads collisions when
`settings.enable_cross_case_analysis` is on; this adapter turns collisions that
involve the current case into CROSS_CASE_SIGNAL findings. Alerts carry only the
HMAC blind token and case ids — never raw identifiers or foreign case content.
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cognitive.crosscase import BlindIndex, build_index, find_collisions, cluster_syndicates
from orchestration.contracts import (
    CROSS_CASE_SIGNAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "CrossCaseEngine"
ENGINE_VERSION = "2.0"

HARD_ID_TYPES = ("PHONE", "UPI", "ACCOUNT", "IFSC", "IMEI", "MAC", "EMAIL", "IP")


async def load_cross_case_collisions(db: AsyncSession, case_id) -> list[dict]:
    """Build the blind index across cases and return alerts touching this case."""
    from db.models import Entity, Case

    # Load entities across all cases
    entities = (await db.execute(
        select(Entity).where(Entity.entity_type.in_(HARD_ID_TYPES))
    )).scalars().all()

    # Load case metadata for rich context
    cases = (await db.execute(select(Case))).scalars().all()
    case_meta = {
        str(c.id): {
            "case_number": c.case_number,
            "case_title": c.title,
            "crime_type": c.crime_type,
            "police_station": c.police_station,
        }
        for c in cases
    }

    key = os.environ.get("CD_INDEX_KEY", "cyberdrishti-local-dev-key")
    index = BlindIndex(key)
    entries = [{
        "case_id": str(e.case_id),
        "case_number": case_meta.get(str(e.case_id), {}).get("case_number", ""),
        "case_title": case_meta.get(str(e.case_id), {}).get("case_title", ""),
        "crime_type": case_meta.get(str(e.case_id), {}).get("crime_type", ""),
        "police_station": case_meta.get(str(e.case_id), {}).get("police_station", ""),
        "entity_type": e.entity_type,
        "value": e.canonical_value,
        "degree": int(e.degree_centrality or 1) or 1,
        "severity": 1.0,
    } for e in entities]

    store = build_index(entries, index)
    target = str(case_id)
    all_collisions = find_collisions(store)
    syndicates = cluster_syndicates(store, case_meta)

    # Attach syndicate cluster info to collisions touching this case
    case_collisions = [c for c in all_collisions if target in c.get("case_ids", [])]
    for col in case_collisions:
        tok = col.get("blind_token")
        for syn in syndicates:
            if any(t.get("blind_token") == tok for t in syn.get("shared_tokens", [])):
                col["syndicate_id"] = syn["cluster_id"]
                col["syndicate_name"] = syn["name"]
                col["syndicate_risk"] = syn["risk_level"]
                col["threat_indicators"] = syn["threat_indicators"]
                break

    return case_collisions


def applies(context: CaseContext) -> bool:
    return bool(context.cross_case_collisions)


def run(context: CaseContext) -> list[CognitiveResult]:
    results: list[CognitiveResult] = []
    for collision in context.cross_case_collisions:
        case_count = int(collision.get("case_count") or 0)
        score = float(collision.get("syndicate_score") or 0.0)
        other_cases = [c for c in collision.get("case_ids", []) if c != context.case_id]
        syn_id = collision.get("syndicate_id")
        syn_risk = collision.get("syndicate_risk", "MONITORED")

        title_suffix = f" (Syndicate {syn_id})" if syn_id else ""
        results.append(CognitiveResult(
            finding_type=CROSS_CASE_SIGNAL,
            title=f"Cross-case signal — {collision.get('entity_type', 'IDENTIFIER')} in {case_count} cases{title_suffix}",
            description=(
                f"A hard identifier recurs across {case_count} authorised cases "
                f"({len(other_cases)} other). Raw value withheld (zero-knowledge blind index)."
            ),
            confidence=None,
            severity=SEVERITY_HIGH if (case_count >= 3 or syn_risk == "CRITICAL") else SEVERITY_MEDIUM,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            component_scores={
                "syndicate_score": score,
                "case_count": case_count,
                "other_case_count": len(other_cases),
                "syndicate_id": syn_id or "",
            },
            reason_codes=[
                "BLIND_INDEX_COLLISION",
                collision.get("entity_type", ""),
                "SYNDICATE_RADAR",
            ],
            reasoning=(
                "Zero-knowledge collision on a hard identifier; coordinate inter-station "
                "evidence requisition via Section 94 BNSS rather than exposing case content."
            ),
            citations=[{"blind_token": collision.get("blind_token")}],
            dedup_key=f"crosscase:{collision.get('blind_token')}",
        ))
    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Cross-case blind-index collision signals (permission-gated).",
    applicability=applies,
    skip_reason="cross_case_analysis_disabled",
)
