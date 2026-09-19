from __future__ import annotations

"""
NETRA 5.0 — Forensic Graph Retriever

Connects the Copilot to NETRA's case graph architecture:
1. Strict Case Boundary Isolation:
   - All queries require case_id and filter strictly by case_id.
   - Cross-case identical canonical identifiers remain 100% isolated.
2. Epistemic Separation Contract:
   - OBSERVED (direct evidence support) vs INFERRED (cognitive / hidden link)
   - Preserves confidence, evidence_refs, event_refs, amount, timestamps, and reason_codes.
3. Query-Driven Adaptive Retrieval:
   - Direct entity resolution against canonical entities
   - 1-hop & multi-hop neighborhood traversal (bounded by max_graph_hops)
   - Shortest path extraction between entity pairs
   - Hidden link / inferred relationship discovery
4. Deterministic Deduplication:
   - Eliminates duplicate bidirectional edges
   - Returns structured GraphNodeSnippet and GraphEdgeSnippet lists
"""

import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Entity, Relationship
from graph import relationship_types as RT
from .config import CopilotConfig, get_copilot_config
from .schemas import GraphEdgeSnippet, GraphNodeSnippet, QueryPlan

logger = logging.getLogger(__name__)


class GraphRetriever:
    """Investigative graph retriever operating over NETRA case graphs."""

    def __init__(self, config: Optional[CopilotConfig] = None):
        self.config = config or get_copilot_config()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Canonical Entity Resolution
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def parse_entity_tag(tag: str) -> Tuple[Optional[str], str]:
        """Split 'TYPE:VALUE' tag into (type, value) or (None, raw)."""
        if ":" in tag:
            etype, val = tag.split(":", 1)
            return etype.strip().upper(), val.strip()
        return None, tag.strip()

    @staticmethod
    def _extract_risk_score(e: Any) -> float:
        """Safely extract risk_score from model or dict with fallback to degree_centrality."""
        if isinstance(e, dict):
            return float(e.get("risk_score", 0.0) or 0.0)
        if hasattr(e, "risk_score") and getattr(e, "risk_score") is not None:
            try:
                return float(getattr(e, "risk_score"))
            except (ValueError, TypeError):
                pass
        meta = getattr(e, "node_metadata", None) or {}
        if isinstance(meta, dict) and "risk_score" in meta and meta["risk_score"] is not None:
            try:
                return float(meta["risk_score"])
            except (ValueError, TypeError):
                pass
        deg = getattr(e, "degree_centrality", None)
        if deg is not None:
            try:
                return float(deg)
            except (ValueError, TypeError):
                pass
        return 0.0

    @staticmethod
    def _extract_bridge_score(e: Any) -> float:
        """Safely extract bridge_score from model or dict."""
        if isinstance(e, dict):
            return float(e.get("bridge_score", 0.0) or 0.0)
        b = getattr(e, "bridge_score", None)
        if b is not None:
            try:
                return float(b)
            except (ValueError, TypeError):
                pass
        return 0.0

    async def resolve_entities(
        self,
        db: AsyncSession,
        case_uuid: uuid.UUID,
        target_tags: Sequence[str],
    ) -> List[Entity]:
        """
        Resolve QueryPlan target_entities (e.g. 'ACCOUNT:4821', 'PHONE:+919876543210')
        against the case's actual canonical Entity records.
        """
        if not target_tags:
            return []

        resolved: List[Entity] = []
        seen_ids: Set[uuid.UUID] = set()

        for tag in target_tags:
            etype, val = self.parse_entity_tag(tag)
            val_clean = val.strip().lower()

            # Query within case boundary only
            stmt = select(Entity).where(Entity.case_id == case_uuid)
            if etype:
                stmt = stmt.where(Entity.entity_type.ilike(etype))

            rows = (await db.execute(stmt)).scalars().all()

            # Match exact canonical value or substring/digits match
            matched = False
            for ent in rows:
                c_val = (ent.canonical_value or "").strip().lower()
                if c_val == val_clean or val_clean in c_val or (len(val_clean) >= 4 and c_val in val_clean):
                    if ent.id not in seen_ids:
                        seen_ids.add(ent.id)
                        resolved.append(ent)
                        matched = True

            # If no typed match, try fallback match without entity_type restriction
            if not matched and etype:
                fallback_stmt = select(Entity).where(
                    Entity.case_id == case_uuid,
                    Entity.canonical_value.ilike(f"%{val}%"),
                )
                fallback_rows = (await db.execute(fallback_stmt)).scalars().all()
                for ent in fallback_rows:
                    if ent.id not in seen_ids:
                        seen_ids.add(ent.id)
                        resolved.append(ent)

        return resolved

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Case Graph Retrieval Core (Database Layer)
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_case_subgraph(
        self,
        db: AsyncSession,
        case_id: str,
        target_entity_tags: Sequence[str] = (),
        max_hops: Optional[int] = None,
        relationship_types: Optional[Sequence[str]] = None,
        include_inferred: Optional[bool] = None,
    ) -> Tuple[List[GraphNodeSnippet], List[GraphEdgeSnippet]]:
        """
        Retrieve a bounded, query-targeted investigative subgraph from PostgreSQL.
        Strictly enforces case_id boundary isolation.
        """
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            logger.warning("Malformed case_id '%s' passed to GraphRetriever", case_id)
            return [], []

        hops = min(max_hops or self.config.default_graph_hops, self.config.max_graph_hops)
        allow_inferred = include_inferred if include_inferred is not None else self.config.include_inferred_relationships

        # 1. Load all entities for this case to build fast in-memory map
        entity_stmt = select(Entity).where(Entity.case_id == case_uuid)
        all_entities = (await db.execute(entity_stmt)).scalars().all()
        if not all_entities:
            return [], []

        id_to_entity: Dict[uuid.UUID, Entity] = {e.id: e for e in all_entities}
        canon_to_id: Dict[str, uuid.UUID] = {e.canonical_value: e.id for e in all_entities}

        # 2. Resolve target seed entities
        seeds = await self.resolve_entities(db, case_uuid, target_entity_tags)
        seed_ids: Set[uuid.UUID] = {s.id for s in seeds}
        if target_entity_tags and not seed_ids:
            return [], []

        # 3. Query Relationships strictly within case_id
        rel_stmt = select(Relationship).where(Relationship.case_id == case_uuid)
        if relationship_types:
            rel_stmt = rel_stmt.where(Relationship.relationship_type.in_(relationship_types))
        if not allow_inferred:
            rel_stmt = rel_stmt.where(Relationship.epistemic_status == RT.OBSERVED)

        all_rels = (await db.execute(rel_stmt)).scalars().all()
        if not all_rels:
            # Return seed nodes if available, or top nodes by risk
            return self._build_node_snippets(seeds or all_entities[:10]), []

        # 4. Construct NetworkX graph for multi-hop neighborhood traversal
        G = nx.Graph()
        for ent in all_entities:
            G.add_node(ent.id, data=ent)

        for rel in all_rels:
            if rel.source_entity_id in id_to_entity and rel.target_entity_id in id_to_entity:
                G.add_edge(
                    rel.source_entity_id,
                    rel.target_entity_id,
                    data=rel,
                )

        # 5. Extract query-targeted nodes and edges
        selected_node_ids: Set[uuid.UUID] = set()
        selected_rels: List[Relationship] = []

        if seed_ids:
            # Neighborhood expansion from seed entities
            for s_id in seed_ids:
                if s_id in G:
                    selected_node_ids.add(s_id)
                    # Traverse up to hops
                    lengths = nx.single_source_shortest_path_length(G, s_id, cutoff=hops)
                    selected_node_ids.update(lengths.keys())

            # If two seeds are present, attempt shortest path between them
            if len(seed_ids) >= 2:
                seed_list = list(seed_ids)
                for i in range(len(seed_list)):
                    for j in range(i + 1, len(seed_list)):
                        if nx.has_path(G, seed_list[i], seed_list[j]):
                            try:
                                path = nx.shortest_path(G, seed_list[i], seed_list[j])
                                selected_node_ids.update(path)
                            except Exception:
                                pass

            # Collect edges among selected nodes
            for rel in all_rels:
                if rel.source_entity_id in selected_node_ids and rel.target_entity_id in selected_node_ids:
                    selected_rels.append(rel)
        else:
            # If no specific seed entities, select top entities by risk/bridge score
            sorted_ents = sorted(
                all_entities,
                key=lambda e: (self._extract_risk_score(e), self._extract_bridge_score(e)),
                reverse=True,
            )
            top_k_nodes = sorted_ents[: self.config.max_graph_nodes]
            selected_node_ids = {e.id for e in top_k_nodes}

            for rel in all_rels:
                if rel.source_entity_id in selected_node_ids or rel.target_entity_id in selected_node_ids:
                    selected_rels.append(rel)
                    selected_node_ids.add(rel.source_entity_id)
                    selected_node_ids.add(rel.target_entity_id)

        # 6. Build final snippets
        selected_entities = [id_to_entity[nid] for nid in selected_node_ids if nid in id_to_entity]
        node_snippets = self._build_node_snippets(selected_entities[: self.config.max_graph_nodes])
        edge_snippets = self._build_edge_snippets(selected_rels[: self.config.max_graph_edges], id_to_entity)

        return node_snippets, edge_snippets

    # ─────────────────────────────────────────────────────────────────────────
    # 3. QueryPlan Adapter
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_for_plan(
        self,
        db: AsyncSession,
        case_id: str,
        plan: QueryPlan,
    ) -> Tuple[List[GraphNodeSnippet], List[GraphEdgeSnippet]]:
        """High-level entrypoint: extracts graph context according to the QueryPlan."""
        include_inferred = True
        rel_types: Optional[List[str]] = None

        if plan.intent == RT.OBSERVED:
            include_inferred = False

        hops = 2 if plan.intent == "relational" else 1

        return await self.retrieve_case_subgraph(
            db=db,
            case_id=case_id,
            target_entity_tags=plan.target_entities,
            max_hops=hops,
            relationship_types=rel_types,
            include_inferred=include_inferred,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Pure In-Memory / Test Mode Methods (DB-free)
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve_from_memory(
        self,
        case_id: str,
        entities: Sequence[Dict[str, Any]],
        relationships: Sequence[Dict[str, Any]],
        target_tags: Sequence[str] = (),
        max_hops: int = 2,
    ) -> Tuple[List[GraphNodeSnippet], List[GraphEdgeSnippet]]:
        """
        Pure in-memory traversal for unit tests and local graph reasoning.
        Enforces case_id matching on every record.
        """
        # Filter strictly by case_id
        valid_entities = [e for e in entities if str(e.get("case_id")) == str(case_id)]
        valid_rels = [r for r in relationships if str(r.get("case_id")) == str(case_id)]

        if not valid_entities:
            return [], []

        id_to_ent = {e.get("id", e.get("canonical_value")): e for e in valid_entities}
        canon_to_ent = {e.get("canonical_value"): e for e in valid_entities}

        # Resolve seeds
        seed_keys: Set[str] = set()
        for tag in target_tags:
            etype, val = self.parse_entity_tag(tag)
            for c_val, ent in canon_to_ent.items():
                if val.lower() in c_val.lower():
                    seed_keys.add(c_val)

        # Build NetworkX graph
        G = nx.Graph()
        for e in valid_entities:
            G.add_node(e.get("canonical_value"))

        for r in valid_rels:
            src = r.get("source_canonical") or r.get("source_value")
            tgt = r.get("target_canonical") or r.get("target_value")
            if src and tgt:
                G.add_edge(src, tgt, data=r)

        selected_canons: Set[str] = set()
        if target_tags:
            if not seed_keys:
                # Target tags were specified but none resolved
                return [], []
            for s in seed_keys:
                if s in G:
                    selected_canons.add(s)
                    lengths = nx.single_source_shortest_path_length(G, s, cutoff=max_hops)
                    selected_canons.update(lengths.keys())
        else:
            selected_canons = set(G.nodes())

        # Build snippets
        node_snippets = []
        for c in selected_canons:
            ent = canon_to_ent.get(c, {})
            node_snippets.append(
                GraphNodeSnippet(
                    entity_id=str(ent.get("id", c)),
                    canonical_value=c,
                    entity_type=ent.get("entity_type", "UNKNOWN"),
                    risk_score=float(ent.get("risk_score", 0.0)),
                    bridge_score=float(ent.get("bridge_score", 0.0)),
                )
            )

        edge_snippets = []
        seen_edges = set()
        for r in valid_rels:
            src = r.get("source_canonical") or r.get("source_value")
            tgt = r.get("target_canonical") or r.get("target_value")
            if src in selected_canons and tgt in selected_canons:
                edge_key = tuple(sorted([src, tgt])) + (r.get("relationship_type"),)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    citations = list(r.get("citations", []))
                    if not citations and (r.get("evidence_refs") or r.get("event_refs") or r.get("id")):
                        cit_item: Dict[str, Any] = {
                            "relationship_id": str(r.get("id", "")),
                            "epistemic_status": r.get("epistemic_status", RT.OBSERVED),
                            "evidence_refs": r.get("evidence_refs") or [],
                            "event_refs": r.get("event_refs") or [],
                            "observation_count": r.get("observation_count") or 1,
                        }
                        if r.get("amount") is not None:
                            cit_item["amount"] = float(r["amount"])
                        if r.get("reason_codes"):
                            cit_item["reason_codes"] = list(r["reason_codes"])
                        if r.get("source_engine"):
                            cit_item["source_engine"] = r["source_engine"]
                        citations.append(cit_item)

                    edge_snippets.append(
                        GraphEdgeSnippet(
                            source_canonical=src,
                            target_canonical=tgt,
                            relationship_type=r.get("relationship_type", RT.CO_OCCURRENCE),
                            confidence=float(r.get("confidence", 1.0)),
                            epistemic_status=r.get("epistemic_status", RT.OBSERVED),
                            citations=citations,
                        )
                    )

        return node_snippets, edge_snippets

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Helper Snippet Builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_node_snippets(self, entities: Sequence[Entity]) -> List[GraphNodeSnippet]:
        snippets = []
        for e in entities:
            snippets.append(
                GraphNodeSnippet(
                    entity_id=str(e.id),
                    canonical_value=e.canonical_value,
                    entity_type=e.entity_type or "UNKNOWN",
                    risk_score=self._extract_risk_score(e),
                    bridge_score=self._extract_bridge_score(e),
                    community_id=getattr(e, "community_id", None),
                )
            )
        return snippets

    def _build_edge_snippets(
        self,
        relationships: Sequence[Relationship],
        id_to_entity: Dict[uuid.UUID, Entity],
    ) -> List[GraphEdgeSnippet]:
        snippets = []
        seen_edges = set()

        for r in relationships:
            src_ent = id_to_entity.get(r.source_entity_id)
            tgt_ent = id_to_entity.get(r.target_entity_id)
            if not src_ent or not tgt_ent:
                continue

            src_val = src_ent.canonical_value
            tgt_val = tgt_ent.canonical_value

            # Deduplicate bidirectional duplicates deterministically
            edge_key = (src_val, tgt_val, r.relationship_type, r.epistemic_status)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            # Build full provenance citations payload
            citation_item: Dict[str, Any] = {
                "relationship_id": str(r.id),
                "epistemic_status": r.epistemic_status,
                "evidence_refs": r.evidence_refs or [],
                "event_refs": r.event_refs or [],
                "observation_count": r.observation_count or 1,
            }
            if r.amount is not None:
                citation_item["amount"] = float(r.amount)
            if r.event_timestamp is not None:
                citation_item["timestamp"] = r.event_timestamp.isoformat()
            if r.reason_codes:
                citation_item["reason_codes"] = list(r.reason_codes)
            if r.source_engine:
                citation_item["source_engine"] = r.source_engine

            snippets.append(
                GraphEdgeSnippet(
                    source_canonical=src_val,
                    target_canonical=tgt_val,
                    relationship_type=r.relationship_type,
                    confidence=float(r.confidence if r.confidence is not None else 1.0),
                    epistemic_status=r.epistemic_status,
                    citations=[citation_item],
                )
            )

        return snippets
