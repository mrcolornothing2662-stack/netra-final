from __future__ import annotations

"""
NETRA 5.0 — Forensic Multi-Modal Hybrid Retriever
Fusion layer executing Reciprocal Rank Fusion (RRF) across:
1. Dense Vector Embeddings (VectorStore / ChromaDB)
2. Case Graph Subgraph (GraphRetriever / PostgreSQL relationships & entities)
3. Structured Records (StructuredRetriever / exact database events, transactions, findings)
4. Chronological Timeline (temporal EvidenceEvent sequence)

Core Guarantees:
- Strict Case Boundary Isolation (`case_id` on every candidate and query)
- Weighted Reciprocal Rank Fusion: RRF(d) = Σ weight / (k + rank)
- Cross-modality deterministic deduplication by provenance identity
- Preservation of Modalities (`modalities: List[ModalityType]`)
- Epistemic Status preservation (`OBSERVED` vs `INFERRED` graph truth)
- Exact values and provenance preserved (source_file, line, page, citations, payload)
- 100% deterministic ordering and tie-breaking
- Zero LLM calls (deterministic fusion infrastructure only)
"""

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EvidenceEvent, EvidenceFile
from .config import CopilotConfig, get_copilot_config
from .graph_retriever import GraphRetriever
from .schemas import (
    FusedItem,
    GraphEdgeSnippet,
    GraphNodeSnippet,
    ModalityType,
    QueryIntentType,
    QueryPlan,
    RetrievedItem,
)
from .structured_retriever import StructuredRetriever
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


def _normalize_dt(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


class HybridRetriever:
    """
    Forensic Multi-Modal Hybrid Retriever.
    Executes and fuses candidate retrieval across all modalities using weighted RRF.
    """

    def __init__(
        self,
        config: Optional[CopilotConfig] = None,
        vector_store: Optional[VectorStore] = None,
        graph_retriever: Optional[GraphRetriever] = None,
        structured_retriever: Optional[StructuredRetriever] = None,
    ):
        self.config = config or get_copilot_config()
        self.vector_store = vector_store
        self.graph_retriever = graph_retriever or GraphRetriever(config=self.config)
        self.structured_retriever = structured_retriever or StructuredRetriever(config=self.config)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. RRF Scoring & Deduplication
    # ─────────────────────────────────────────────────────────────────────────

    def get_modality_weight(self, modality: ModalityType, plan: Optional[QueryPlan] = None) -> float:
        """Fetch configured RRF weight for the given retrieval modality, adaptive to plan intent."""
        if plan:
            if plan.intent == QueryIntentType.TEMPORAL:
                if modality == ModalityType.TIMELINE:
                    return 3.0
                elif modality == ModalityType.STRUCTURED:
                    return 1.2
            elif plan.intent == QueryIntentType.RELATIONAL:
                if modality == ModalityType.GRAPH:
                    return 2.5
        if modality == ModalityType.VECTOR:
            return float(self.config.vector_rrf_weight)
        elif modality == ModalityType.GRAPH:
            return float(self.config.graph_rrf_weight)
        elif modality == ModalityType.STRUCTURED:
            return float(self.config.structured_rrf_weight)
        elif modality == ModalityType.TIMELINE:
            return float(self.config.timeline_rrf_weight)
        return 1.0

    def compute_rrf_score(self, rank: int, modality: ModalityType, plan: Optional[QueryPlan] = None) -> float:
        """
        Weighted Reciprocal Rank Fusion contribution:
        score = weight / (k + rank)
        """
        k = self.config.rrf_k
        w = self.get_modality_weight(modality, plan=plan)
        return w / (k + rank)

    @staticmethod
    def get_dedup_key(item: RetrievedItem, case_id: str) -> str:
        """
        Generate deterministic provenance-aware deduplication identity.
        Prevents duplicate representations of the same underlying event or entity.
        """
        clean_case = str(case_id).strip()
        payload = item.raw_payload or {}

        # 1. Underlying database EvidenceEvent identity
        ev_id = payload.get("event_id") or payload.get("evidence_event_id")
        if ev_id:
            return f"{clean_case}:event:{str(ev_id).strip()}"

        if item.id.startswith("evidence_events:"):
            return f"{clean_case}:event:{item.id.split(':', 1)[1].strip()}"
        if item.id.startswith("timeline:"):
            return f"{clean_case}:event:{item.id.split(':', 1)[1].strip()}"

        # 2. Canonical entity identity
        if item.id.startswith("entities:") or item.id.startswith("graph_node:") or "canonical_value" in payload:
            c_val = payload.get("canonical_value") or item.id.split(":", 1)[1]
            return f"{clean_case}:entity:{str(c_val).strip().lower()}"

        # 3. Graph edge identity (preserves epistemic status)
        if item.id.startswith("graph_edge:") or ("source" in payload and "target" in payload):
            src = payload.get("source") or ""
            tgt = payload.get("target") or ""
            rtype = payload.get("type") or payload.get("relationship_type") or ""
            ep = payload.get("epistemic_status") or "OBSERVED"
            # Normalize undirected edge identity alphabetically
            norm_endpoints = ":".join(sorted([str(src).strip().lower(), str(tgt).strip().lower()]))
            return f"{clean_case}:edge:{norm_endpoints}:{str(rtype).strip().upper()}:{str(ep).strip().upper()}"

        # 4. Cognitive finding identity
        if item.id.startswith("findings:") or payload.get("finding_id"):
            fid = payload.get("finding_id") or item.id.split(":", 1)[1]
            return f"{clean_case}:finding:{str(fid).strip()}"

        # 5. Vector document chunk identity
        if item.modality == ModalityType.VECTOR:
            chunk_id = payload.get("chunk_id") or payload.get("id") or item.id
            s_file = item.source_file or payload.get("filename") or ""
            s_line = item.source_line or payload.get("source_line") or ""
            return f"{clean_case}:chunk:{s_file}:{s_line}:{chunk_id}"

        # 6. Fallback identity
        return f"{clean_case}:{item.modality.value}:{item.id}"

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Pure Fusion Engine (DB-Free & Test Compatible)
    # ─────────────────────────────────────────────────────────────────────────

    def fuse_candidates(
        self,
        case_id: str,
        candidate_lists: Dict[ModalityType, Sequence[RetrievedItem]],
        limit: Optional[int] = None,
        plan: Optional[QueryPlan] = None,
    ) -> List[FusedItem]:
        """
        Merge candidate lists from all modalities into a deduplicated, RRF-ranked list.
        Enforces strict case isolation, epistemic preservation, and deterministic ordering.
        """
        clean_case = str(case_id).strip()
        max_candidates = limit or self.config.max_retrieval_candidates

        rrf_scores: Dict[str, float] = {}
        modalities_seen: Dict[str, Set[ModalityType]] = {}
        min_ranks: Dict[str, int] = {}
        canonical_items: Dict[str, RetrievedItem] = {}

        # Modality richness priority for selecting best display text/payload
        richness_priority = {
            ModalityType.STRUCTURED: 4,
            ModalityType.GRAPH: 3,
            ModalityType.TIMELINE: 2,
            ModalityType.VECTOR: 1,
        }

        for modality, items in candidate_lists.items():
            if not items:
                continue

            for rank_idx, item in enumerate(items, start=1):
                # Enforce case isolation: reject item if payload explicitly states a different case
                item_payload = item.raw_payload or {}
                item_case = item_payload.get("case_id")
                if item_case is not None and str(item_case).strip() != clean_case:
                    logger.warning(
                        "Security violation prevented: Item %s with case_id %s rejected for query case %s",
                        item.id,
                        item_case,
                        clean_case,
                    )
                    continue

                dedup_key = self.get_dedup_key(item, clean_case)
                score_contrib = self.compute_rrf_score(rank_idx, modality, plan=plan)

                # 1. Accumulate RRF score
                rrf_scores[dedup_key] = rrf_scores.get(dedup_key, 0.0) + score_contrib

                # 2. Track modalities
                if dedup_key not in modalities_seen:
                    modalities_seen[dedup_key] = set()
                    min_ranks[dedup_key] = rank_idx
                else:
                    min_ranks[dedup_key] = min(min_ranks[dedup_key], rank_idx)

                modalities_seen[dedup_key].add(modality)

                # 3. Preserve richest representation for the deduplicated candidate
                if dedup_key not in canonical_items:
                    canonical_items[dedup_key] = item
                else:
                    existing = canonical_items[dedup_key]
                    curr_prio = richness_priority.get(modality, 0)
                    exist_prio = richness_priority.get(existing.modality, 0)

                    # Update if current modality has richer structured information
                    if curr_prio > exist_prio:
                        # Retain any citations or epistemic status from previous representation
                        merged_payload = {**(existing.raw_payload or {}), **(item.raw_payload or {})}
                        if "citations" in (existing.raw_payload or {}) and "citations" not in (item.raw_payload or {}):
                            merged_payload["citations"] = existing.raw_payload["citations"]
                        if "epistemic_status" in (existing.raw_payload or {}) and "epistemic_status" not in (item.raw_payload or {}):
                            merged_payload["epistemic_status"] = existing.raw_payload["epistemic_status"]

                        canonical_items[dedup_key] = RetrievedItem(
                            id=item.id,
                            modality=item.modality,
                            score=item.score,
                            text=item.text,
                            source_file=item.source_file or existing.source_file,
                            source_line=item.source_line or existing.source_line,
                            source_page=item.source_page or existing.source_page,
                            raw_payload=merged_payload,
                        )
                    else:
                        # Merge citations/status into existing if present in current item
                        if "citations" in item_payload and "citations" not in (existing.raw_payload or {}):
                            existing.raw_payload["citations"] = item_payload["citations"]
                        if "epistemic_status" in item_payload and "epistemic_status" not in (existing.raw_payload or {}):
                            existing.raw_payload["epistemic_status"] = item_payload["epistemic_status"]

        if not rrf_scores:
            return []

        # Deterministic sorting:
        # 1. fused_score descending (-score)
        # 2. min_original_rank ascending (min_rank)
        # 3. item id ascending for absolute tie breaking
        def sort_key(k: str) -> Tuple[float, int, str]:
            score = rrf_scores[k]
            m_rank = min_ranks[k]
            it_id = canonical_items[k].id
            return (-score, m_rank, it_id)

        sorted_keys = sorted(rrf_scores.keys(), key=sort_key)
        fused_results: List[FusedItem] = []

        for final_rank, k in enumerate(sorted_keys[:max_candidates], start=1):
            item = canonical_items[k]
            score = rrf_scores[k]
            mods = sorted(list(modalities_seen[k]), key=lambda m: richness_priority.get(m, 0), reverse=True)

            payload = item.raw_payload or {}
            ep_status = payload.get("epistemic_status")
            citations = payload.get("citations", [])
            if isinstance(citations, dict):
                citations = [citations]

            fused_results.append(
                FusedItem(
                    id=item.id,
                    rank=final_rank,
                    fused_score=round(score, 6),
                    text=item.text,
                    source_file=item.source_file,
                    source_line=item.source_line,
                    source_page=item.source_page,
                    modalities=mods,
                    raw_payload=payload,
                    epistemic_status=ep_status,
                    citations=citations,
                )
            )

        return fused_results

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Timeline Retrieval Adapter
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve_timeline(
        self,
        db: AsyncSession,
        case_id: str,
        plan: QueryPlan,
        limit: Optional[int] = None,
    ) -> List[RetrievedItem]:
        """
        Query chronological EvidenceEvents from PostgreSQL for timeline context.
        Strictly enforces case_id boundary.
        """
        try:
            case_uuid = uuid.UUID(str(case_id).strip())
        except (ValueError, TypeError):
            return []

        max_limit = max(limit or 0, self.config.timeline_top_k, 25)
        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case_uuid,
            EvidenceEvent.event_timestamp.is_not(None),
        )

        if plan.time_window_start:
            q = q.where(EvidenceEvent.event_timestamp >= _normalize_dt(plan.time_window_start))
        if plan.time_window_end:
            q = q.where(EvidenceEvent.event_timestamp <= _normalize_dt(plan.time_window_end))

        from sqlalchemy import case as sql_case
        priority_order = sql_case(
            (EvidenceEvent.event_type.in_(["bank_txn", "call", "location_timeline", "network_log", "seizure_memo", "document_text"]), 1),
            else_=2
        )
        q = q.order_by(priority_order.asc(), EvidenceEvent.event_timestamp.asc()).limit(max(max_limit * 4, 100))
        raw_events = (await db.execute(q)).scalars().all()

        if not raw_events:
            return []

        priority_types = {"bank_txn", "call", "location_timeline", "network_log", "seizure_memo", "document_text"}
        milestones = [e for e in raw_events if e.event_type in priority_types][:max_limit]
        chats = [e for e in raw_events if e.event_type not in priority_types][:3]
        events = sorted(milestones + chats, key=lambda e: e.event_timestamp or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))

        # Load file map for source doc provenance
        ev_files = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case_uuid))).scalars().all()
        file_map = {f.id: f.original_name or f.filename for f in ev_files}

        timeline_items: List[RetrievedItem] = []
        for ev in events:
            source_doc = file_map.get(ev.evidence_file_id, "Case Timeline")
            ts_str = ev.event_timestamp.isoformat() if ev.event_timestamp else "N/A"
            text = f"[TIMELINE] {ts_str} | {ev.event_type} | {ev.text_content or ''}"

            timeline_items.append(
                RetrievedItem(
                    id=f"timeline:{ev.id}",
                    modality=ModalityType.TIMELINE,
                    score=1.0,
                    text=text,
                    source_file=source_doc,
                    source_line=str(ev.source_line) if ev.source_line is not None else None,
                    source_page=str(ev.source_page) if ev.source_page is not None else None,
                    raw_payload={
                        "event_id": str(ev.id),
                        "event_type": ev.event_type,
                        "timestamp": ts_str,
                        "metadata": ev.event_metadata or {},
                        "text": ev.text_content,
                        "case_id": str(case_uuid),
                    },
                )
            )

        return timeline_items

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Graph Conversion Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _convert_graph_snippets_to_items(
        self,
        nodes: Sequence[GraphNodeSnippet],
        edges: Sequence[GraphEdgeSnippet],
        case_id: str,
    ) -> List[RetrievedItem]:
        """Convert GraphNodeSnippet and GraphEdgeSnippet lists into RetrievedItems."""
        items: List[RetrievedItem] = []

        # Edges (highest relational value)
        for r_idx, edge in enumerate(edges, start=1):
            edge_id = f"graph_edge:{edge.source_canonical}:{edge.relationship_type}:{edge.target_canonical}:{edge.epistemic_status}"
            summary = (
                f"[GRAPH {edge.epistemic_status}] {edge.source_canonical} -> "
                f"{edge.relationship_type} -> {edge.target_canonical} "
                f"(confidence={edge.confidence:.2f})"
            )
            items.append(
                RetrievedItem(
                    id=edge_id,
                    modality=ModalityType.GRAPH,
                    score=float(edge.confidence),
                    text=summary,
                    source_file="Case Graph (Relationships)",
                    raw_payload={
                        "source": edge.source_canonical,
                        "target": edge.target_canonical,
                        "type": edge.relationship_type,
                        "confidence": edge.confidence,
                        "epistemic_status": edge.epistemic_status,
                        "citations": edge.citations,
                        "case_id": str(case_id),
                    },
                )
            )

        # Nodes
        for n_idx, node in enumerate(nodes, start=1):
            node_id = f"graph_node:{node.canonical_value}"
            summary = (
                f"[GRAPH NODE] {node.canonical_value} (type={node.entity_type}, "
                f"risk={node.risk_score:.2f}, bridge={node.bridge_score:.2f})"
            )
            items.append(
                RetrievedItem(
                    id=node_id,
                    modality=ModalityType.GRAPH,
                    score=float(node.risk_score),
                    text=summary,
                    source_file="Case Graph (Entities)",
                    raw_payload={
                        "canonical_value": node.canonical_value,
                        "entity_type": node.entity_type,
                        "risk_score": node.risk_score,
                        "bridge_score": node.bridge_score,
                        "case_id": str(case_id),
                    },
                )
            )

        return items

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Full End-to-End Orchestrator
    # ─────────────────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        db: AsyncSession,
        case_id: str,
        plan: QueryPlan,
        limit: Optional[int] = None,
    ) -> Tuple[List[FusedItem], Dict[str, Any]]:
        """
        Orchestrate multi-modal retrieval across Vector, Graph, Structured, and Timeline,
        then fuse via weighted RRF.
        Returns (fused_items, retrieval_diagnostics).
        """
        clean_case = str(case_id).strip()
        candidate_lists: Dict[ModalityType, List[RetrievedItem]] = {
            ModalityType.VECTOR: [],
            ModalityType.GRAPH: [],
            ModalityType.STRUCTURED: [],
            ModalityType.TIMELINE: [],
        }

        # 1. Vector Retrieval
        if "vector" in plan.target_modalities and self.vector_store:
            try:
                v_candidates = self.vector_store.search_text(
                    case_id=clean_case,
                    query_text=plan.original_query,
                    top_k=self.config.vector_top_k,
                )
                candidate_lists[ModalityType.VECTOR] = v_candidates
            except Exception as e:
                logger.warning("Vector retrieval encountered error in HybridRetriever: %s", e)

        # 2. Graph Retrieval
        if "graph" in plan.target_modalities and self.graph_retriever:
            try:
                nodes, edges = await self.graph_retriever.retrieve_for_plan(
                    db=db,
                    case_id=clean_case,
                    plan=plan,
                )
                g_candidates = self._convert_graph_snippets_to_items(nodes, edges, clean_case)
                candidate_lists[ModalityType.GRAPH] = g_candidates
            except Exception as e:
                logger.warning("Graph retrieval encountered error in HybridRetriever: %s", e)

        # 3. Structured Retrieval
        if "structured" in plan.target_modalities and self.structured_retriever:
            try:
                _, s_candidates = await self.structured_retriever.retrieve_for_plan(
                    db=db,
                    case_id=clean_case,
                    plan=plan,
                    limit=self.config.structured_top_k,
                )
                candidate_lists[ModalityType.STRUCTURED] = s_candidates
            except Exception as e:
                logger.warning("Structured retrieval encountered error in HybridRetriever: %s", e)

        # 4. Timeline Retrieval
        timeline_needed = (
            "timeline" in plan.target_modalities
            or plan.intent in (QueryIntentType.TEMPORAL, "temporal")
            or plan.time_window_start is not None
            or any(kw in plan.original_query.lower() for kw in ("timeline", "sequence", "chronology", "when", "after", "before", "happened"))
        )
        if timeline_needed:
            try:
                t_candidates = await self.retrieve_timeline(
                    db=db,
                    case_id=clean_case,
                    plan=plan,
                    limit=self.config.timeline_top_k,
                )
                candidate_lists[ModalityType.TIMELINE] = t_candidates
            except Exception as e:
                logger.warning("Timeline retrieval encountered error in HybridRetriever: %s", e)

        # 5. Weighted RRF Fusion
        retrieval_limit = limit
        if plan.intent in (QueryIntentType.TEMPORAL, "temporal") or plan.time_window_start is not None:
            retrieval_limit = max(limit or 0, 35)

        fused_items = self.fuse_candidates(
            case_id=clean_case,
            candidate_lists=candidate_lists,
            limit=retrieval_limit,
            plan=plan,
        )

        diagnostics = {
            "case_id": clean_case,
            "vector_candidates": len(candidate_lists[ModalityType.VECTOR]),
            "graph_candidates": len(candidate_lists[ModalityType.GRAPH]),
            "structured_candidates": len(candidate_lists[ModalityType.STRUCTURED]),
            "timeline_candidates": len(candidate_lists[ModalityType.TIMELINE]),
            "unique_fused_items": len(fused_items),
        }

        return fused_items, diagnostics
