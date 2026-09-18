from __future__ import annotations

"""
Case Correlation Runner

The single, reusable implementation of the rule-based hidden-link scan for one
case. It is invoked both by the manual endpoint (routes/correlations.py) and by
the cognitive orchestrator, so inferred relationships are materialised on every
analysis run rather than only when an investigator remembers to press a button.

It writes to the session but never commits — the caller owns the transaction.
"""
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, Correlation, Entity, EntityMention, EvidenceEvent, Relationship

logger = logging.getLogger(__name__)

WEIGHTS = {
    "jaccard":     0.20,
    "adamic_adar": 0.15,
    "temporal":    0.25,
    "financial":   0.20,
    "bridge":      0.10,
    "common_nbrs": 0.10,
}

DEFAULT_THRESHOLD = 0.30  # Conservative — investigator reviews flagged pairs


async def run_case_correlations(db: AsyncSession, case: Case) -> dict[str, Any]:
    """Scan one case for inferred (hidden) links and persist them.

    Returns a summary dict. Writes Correlation rows and mirrors each flagged
    link into the unified case graph as an INFERRED Relationship with the same
    provenance contract. Observed relationships are never touched.
    """
    from graph.graph_builder import build_case_graph
    from graph.hidden_link_engine import HiddenLinkEngine, compute_pair_features
    from graph.relationships import upsert_relationship
    from graph import relationship_types as RT

    c_id = case.id

    entities_db = (await db.execute(
        select(Entity).where(Entity.case_id == c_id)
    )).scalars().all()

    if not entities_db:
        return {
            "case_id": str(c_id),
            "entity_count": 0,
            "flagged": 0,
            "inferred_relationships": 0,
            "message": "No entities found. Upload and process evidence first.",
        }

    events_db = (await db.execute(
        select(EvidenceEvent).where(EvidenceEvent.case_id == c_id)
    )).scalars().all()

    mention_rows = (await db.execute(
        select(EntityMention).where(
            EntityMention.entity_id.in_([e.id for e in entities_db])
        )
    )).scalars().all()

    event_to_entities: dict[str, list[str]] = {}
    entity_id_to_canonical: dict[str, str] = {str(e.id): e.canonical_value for e in entities_db}
    event_to_evidence: dict[str, str] = {
        str(ev.id): str(ev.evidence_file_id)
        for ev in events_db if ev.evidence_file_id
    }

    for m in mention_rows:
        eid = str(m.evidence_event_id)
        canon = entity_id_to_canonical.get(str(m.entity_id))
        if canon:
            event_to_entities.setdefault(eid, []).append(canon)

    event_dicts = []
    for ev in events_db:
        event_dicts.append({
            "id": str(ev.id),
            "event_type": ev.event_type,
            "event_timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
            "event_metadata": ev.event_metadata or {},
            "entity_mentions": [
                {"canonical_value": cv}
                for cv in event_to_entities.get(str(ev.id), [])
            ],
        })

    entity_dicts = [
        {
            "id": str(e.id),
            "canonical_value": e.canonical_value,
            "entity_type": e.entity_type,
        }
        for e in entities_db
    ]

    G = build_case_graph(entity_dicts, event_dicts)

    nodes = list(G.nodes())
    engine = HiddenLinkEngine()  # No model loaded — rule-based path
    flagged_count = 0
    inferred_count = 0

    canonical_to_entity: dict[str, Entity] = {e.canonical_value: e for e in entities_db}

    amount_signals: dict[str, float] = {}
    ts_signals: dict[str, float] = {}
    for ev in events_db:
        if ev.event_type == "bank_txn" and ev.event_metadata:
            meta = ev.event_metadata
            amount = meta.get("amount") or meta.get("debit") or meta.get("credit")
            if amount:
                try:
                    amount_f = float(str(amount).replace(",", "").replace("₹", "").strip())
                    for cv in event_to_entities.get(str(ev.id), []):
                        amount_signals[cv] = amount_f
                        if ev.event_timestamp:
                            ts_signals[cv] = ev.event_timestamp.timestamp()
                except (ValueError, TypeError):
                    pass

    high_confidence: list[tuple[Any, float, dict[str, Any], list[str]]] = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            u, v = nodes[i], nodes[j]

            if G.has_edge(u, v):
                continue

            entity_u = canonical_to_entity.get(u)
            entity_v = canonical_to_entity.get(v)
            if not entity_u or not entity_v:
                continue

            if entity_u.entity_type in {"AMOUNT", "KEYWORD"} or entity_v.entity_type in {"AMOUNT", "KEYWORD"}:
                continue

            if entity_u.entity_type == entity_v.entity_type:
                comm_u = G.nodes[u].get("community_id")
                comm_v = G.nodes[v].get("community_id")
                if comm_u is None or comm_v is None or comm_u == comm_v:
                    continue

            feats = compute_pair_features(
                G, u, v,
                amount_u=amount_signals.get(u),
                amount_v=amount_signals.get(v),
                ts_u=ts_signals.get(u),
                ts_v=ts_signals.get(v),
            )

            cn_norm = min(feats["cn"] / 5.0, 1.0)
            aa_norm = min(feats["aa"] / 3.0, 1.0)
            tmp_norm = min(feats["temporal"] / 5.0, 1.0)

            score = (
                WEIGHTS["jaccard"]     * feats["jaccard"] +
                WEIGHTS["adamic_adar"] * aa_norm +
                WEIGHTS["temporal"]    * tmp_norm +
                WEIGHTS["financial"]   * feats["fin"] +
                WEIGHTS["bridge"]      * feats["bridge"] +
                WEIGHTS["common_nbrs"] * cn_norm
            )

            if score < DEFAULT_THRESHOLD:
                continue

            reasons = []
            if feats["cn"] >= 1:
                reasons.append(f"{int(feats['cn'])} common co-occurrence(s)")
            if feats["jaccard"] >= 0.2:
                reasons.append("shared entity neighborhood")
            if tmp_norm >= 0.3:
                reasons.append("temporal proximity")
            if feats["fin"] >= 0.3:
                reasons.append("financial correlation")
            if feats["bridge"] >= 0.4:
                reasons.append("bridge entity signal")

            component_scores = {
                "jaccard": round(feats["jaccard"], 4),
                "adamic_adar_norm": round(aa_norm, 4),
                "temporal_norm": round(tmp_norm, 4),
                "fin_score": round(feats["fin"], 4),
                "bridge_score": round(feats["bridge"], 4),
                "common_neighbors": int(feats["cn"]),
            }

            high_confidence.append(((u, v), score, component_scores, reasons))

    existing_corrs = (await db.execute(
        select(Correlation).where(Correlation.case_id == c_id)
    )).scalars().all()
    corr_map = {(c.entity_a_id, c.entity_b_id): c for c in existing_corrs}

    existing_rels = (await db.execute(
        select(Relationship).where(
            Relationship.case_id == c_id,
            Relationship.relationship_type == RT.ASSOCIATED_WITH,
            Relationship.epistemic_status == RT.INFERRED,
        )
    )).scalars().all()
    rel_map = {(r.source_entity_id, r.target_entity_id): r for r in existing_rels}

    for pair, score, component_scores, reasons in high_confidence:
        u, v = pair
        entity_u = id_to_entity.get(u)
        entity_v = id_to_entity.get(v)
        if not entity_u or not entity_v:
            continue

        # Gather citations: events mentioning both entities, or shared neighbors
        citations: list[dict] = []
        evidence_ids: list[str] = []
        common = set(G.neighbors(u)) & set(G.neighbors(v))
        for nbr in list(common)[:5]:
            nbr_ent = id_to_entity.get(nbr)
            if not nbr_ent:
                continue
            events_nbr = (await db.execute(
                select(EvidenceEvent)
                .join(EntityMention, EntityMention.evidence_event_id == EvidenceEvent.id)
                .where(
                    EntityMention.entity_id == nbr_ent.id,
                    EvidenceEvent.case_id == c_id,
                )
                .limit(2)
            )).scalars().all()
            for ev in events_nbr:
                meta = ev.event_metadata or {}
                citations.append({
                    "event_id": str(ev.id),
                    "file": meta.get("source_doc", ""),
                    "line": ev.source_line,
                    "page": ev.source_page,
                    "event_type": ev.event_type,
                    "timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                })
                evidence_id = event_to_evidence.get(str(ev.id))
                if evidence_id:
                    evidence_ids.append(evidence_id)

        pair_key = (entity_u.id, entity_v.id)
        existing_corr = corr_map.get(pair_key)
        if existing_corr:
            existing_corr.final_score = score
            existing_corr.threshold = DEFAULT_THRESHOLD
            existing_corr.decision = "flagged"
            existing_corr.component_scores = component_scores
            existing_corr.model_weights = WEIGHTS
            existing_corr.source_citations = citations
        else:
            new_corr = Correlation(
                case_id=c_id,
                entity_a_id=entity_u.id,
                entity_b_id=entity_v.id,
                link_type="hidden_link",
                final_score=score,
                threshold=DEFAULT_THRESHOLD,
                decision="flagged",
                component_scores=component_scores,
                model_weights=WEIGHTS,
                source_citations=citations,
            )
            db.add(new_corr)
            corr_map[pair_key] = new_corr
            flagged_count += 1

        ev_refs = list(dict.fromkeys(evidence_ids))
        evt_refs = [c["event_id"] for c in citations]
        existing_rel = rel_map.get(pair_key)
        if existing_rel is None:
            new_rel = Relationship(
                case_id=c_id,
                source_entity_id=entity_u.id,
                target_entity_id=entity_v.id,
                relationship_type=RT.ASSOCIATED_WITH,
                epistemic_status=RT.INFERRED,
                direction=RT.BIDIRECTIONAL,
                confidence=score,
                evidence_refs=ev_refs,
                event_refs=evt_refs,
                attributes={"link_type": "hidden_link", "threshold": DEFAULT_THRESHOLD},
                component_scores=component_scores,
                reason_codes=reasons,
                source_engine="HiddenLinkEngine",
                engine_version="2.0",
            )
            db.add(new_rel)
            rel_map[pair_key] = new_rel
        else:
            existing_rel.confidence = score
            existing_rel.evidence_refs = ev_refs
            existing_rel.event_refs = evt_refs
            existing_rel.component_scores = component_scores
            existing_rel.reason_codes = reasons
            existing_rel.source_engine = "HiddenLinkEngine"
            existing_rel.engine_version = "2.0"
        inferred_count += 1

    await db.flush()

    return {
        "case_id": str(c_id),
        "case_number": case.case_number,
        "entity_count": len(entities_db),
        "flagged": flagged_count,
        "inferred_relationships": inferred_count,
        "threshold": DEFAULT_THRESHOLD,
        "message": f"Analysis complete. {flagged_count} potential hidden links detected.",
    }
