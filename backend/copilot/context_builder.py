from __future__ import annotations

"""
NETRA 5.0 — Forensic Context Builder
Assembles, constrains, and boundaries multi-modal evidence for the Copilot Generator.

Guarantees:
1. Strict Context Budgets:
   - max_context_items: <= 24 evidence items
   - max_context_documents: <= 12 distinct evidence documents
   - max_graph_nodes: <= 30 nodes
   - max_graph_edges: <= 50 edges
   - max_timeline_events: <= 50 events
   - max_context_tokens: <= 12,000 estimated tokens (approx chars / 4)
2. Provenance Preservation:
   - Preserves source_file, line, page, citations, raw_payload, and case_id.
3. Epistemic Separation:
   - Strictly preserves OBSERVED vs INFERRED; never converts an inferred relationship to observed.
4. Defensive Deduplication:
   - Deduplicates by event_id -> relationship identity -> entity identity -> docloc -> item ID.
5. Diversity Preservation:
   - Relevance order remains primary, but prevents a single document from crowding out all other evidence.
6. Empty Case Abstention:
   - Emits valid AssembledContext with is_empty_case=True and zero fabricated evidence.
7. Prompt-Injection Boundary:
   - Treats evidence as untrusted data safely bounded inside structured envelopes.
"""

import logging
import math
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, Entity, EvidenceEvent, EvidenceFile, InvestigationFinding
from .config import CopilotConfig, get_copilot_config
from .schemas import (
    AssembledContext,
    CaseContextSnapshot,
    FusedItem,
    GraphEdgeSnippet,
    GraphNodeSnippet,
    ModalityType,
    StructuredRecordSnippet,
)

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Forensic Context Builder.
    Assembles and bounds multi-modal evidence into an AssembledContext.
    Does NOT perform new retrieval or reasoning.
    """

    def __init__(self, config: Optional[CopilotConfig] = None):
        self.config = config or get_copilot_config()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Token Estimation
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Deterministic budget approximation:
        estimated_tokens ≈ max(1, math.ceil(len(text) / 4))
        Documented as a budget estimate, not an exact BPE/wordpiece count.
        """
        if not text:
            return 0
        return max(1, math.ceil(len(text) / 4))

    def estimate_item_tokens(self, item: FusedItem) -> int:
        """Estimate tokens for a FusedItem including header metadata."""
        meta_chars = len(f"{item.id} {item.source_file} {item.source_line or ''} {item.source_page or ''} {item.epistemic_status or ''}")
        content_chars = len(item.text)
        return self.estimate_tokens(f"{meta_chars}_{content_chars}") + self.estimate_tokens(item.text)

    def estimate_context_tokens(self, context: AssembledContext) -> int:
        """Compute total estimated tokens across all parts of an AssembledContext."""
        total = 0

        # Snapshot
        snap = context.case_snapshot
        snap_text = f"{snap.case_number} {snap.title} {snap.status} {snap.priority} {snap.crime_type or ''}"
        total += self.estimate_tokens(snap_text)

        # Fused items
        for it in context.fused_items:
            total += self.estimate_item_tokens(it)

        # Graph nodes
        for node in context.graph_nodes:
            total += self.estimate_tokens(f"{node.canonical_value} {node.entity_type} {node.risk_score} {node.bridge_score}")

        # Graph edges
        for edge in context.graph_edges:
            total += self.estimate_tokens(
                f"{edge.source_canonical} {edge.relationship_type} {edge.target_canonical} {edge.epistemic_status} {edge.confidence}"
            )

        # Structured records
        for rec in context.structured_records:
            total += self.estimate_tokens(f"{rec.record_id} {rec.record_type} {rec.summary_text} {rec.source_file or ''}")

        # Statutory context
        if context.statutory_context:
            total += self.estimate_tokens(str(context.statutory_context))

        return total

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Defensive Deduplication Key Extraction
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_dedup_key(item: FusedItem) -> str:
        """
        Hierarchical deduplication key extraction:
        1. event_id
        2. relationship identity (min:max:rel:status)
        3. entity identity (type:canonical_value)
        4. evidence_file_id + source location (file:line:page)
        5. stable item ID
        """
        payload = item.raw_payload or {}

        # 1. Event ID
        event_id = payload.get("event_id") or payload.get("finding_id")
        if event_id:
            return f"event:{str(event_id).strip().lower()}"

        # 2. Relationship Identity
        if (
            payload.get("relationship_type")
            and payload.get("source")
            and payload.get("target")
        ):
            src = str(payload["source"]).strip().lower()
            tgt = str(payload["target"]).strip().lower()
            rel = str(payload["relationship_type"]).strip().lower()
            status = str(payload.get("epistemic_status", "")).strip().lower()
            # Order endpoints symmetrically
            p1, p2 = min(src, tgt), max(src, tgt)
            return f"rel:{p1}:{p2}:{rel}:{status}"

        # 3. Entity Identity
        if payload.get("canonical_value"):
            etype = str(payload.get("entity_type", "")).strip().lower()
            cval = str(payload["canonical_value"]).strip().lower()
            return f"entity:{etype}:{cval}"

        # 4. Evidence File ID + Source Location
        ev_file_id = payload.get("evidence_file_id")
        if ev_file_id and (item.source_line is not None or item.source_page is not None):
            loc = f"{item.source_line or ''}:{item.source_page or ''}"
            chunk_idx = payload.get("chunk_index")
            if chunk_idx is not None:
                loc = f"{loc}:{chunk_idx}"
            return f"fileloc:{str(ev_file_id).strip().lower()}:{loc}"

        # 5. Stable Item ID
        return f"item:{item.id.strip().lower()}"

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Case Snapshot Builder (Optional DB Helper)
    # ─────────────────────────────────────────────────────────────────────────

    async def build_case_snapshot(
        self,
        db: AsyncSession,
        case_id: str,
    ) -> CaseContextSnapshot:
        """
        Build database ground-truth snapshot strictly bound to case_id.
        Counts files, entities, events, and findings without fetching large payloads.
        """
        clean_id = str(case_id).strip()
        try:
            case_uuid = uuid.UUID(clean_id)
        except (ValueError, TypeError):
            return CaseContextSnapshot(
                case_id=clean_id,
                case_number="UNKNOWN",
                title="Invalid Case ID",
                status="closed",
                priority="low",
                total_evidence_files=0,
                total_entities=0,
                total_events=0,
                total_findings=0,
            )

        c_res = await db.execute(select(Case).where(Case.id == case_uuid))
        case_rec = c_res.scalars().first()
        if not case_rec:
            return CaseContextSnapshot(
                case_id=clean_id,
                case_number="UNKNOWN",
                title="Non-Existent Case",
                status="closed",
                priority="low",
                total_evidence_files=0,
                total_entities=0,
                total_events=0,
                total_findings=0,
            )

        ev_rows = (
            await db.execute(
                select(EvidenceFile.original_name, EvidenceFile.filename).where(EvidenceFile.case_id == case_uuid)
            )
        ).all()
        files_cnt = len(ev_rows)
        ev_file_names = [r[0] or r[1] for r in ev_rows if (r[0] or r[1])]

        entities_cnt = (
            await db.execute(
                select(func.count(Entity.id)).where(Entity.case_id == case_uuid)
            )
        ).scalar() or 0

        events_cnt = (
            await db.execute(
                select(func.count(EvidenceEvent.id)).where(EvidenceEvent.case_id == case_uuid)
            )
        ).scalar() or 0

        findings_cnt = (
            await db.execute(
                select(func.count(InvestigationFinding.id)).where(InvestigationFinding.case_id == case_uuid)
            )
        ).scalar() or 0

        return CaseContextSnapshot(
            case_id=clean_id,
            case_number=case_rec.case_number or "N/A",
            title=case_rec.title or "Untitled Case",
            crime_type=case_rec.crime_type,
            status=case_rec.status or "open",
            priority=case_rec.priority or "medium",
            total_evidence_files=int(files_cnt),
            total_entities=int(entities_cnt),
            total_events=int(events_cnt),
            total_findings=int(findings_cnt),
            evidence_files=ev_file_names,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Context Assembly & Budget Enforcement
    # ─────────────────────────────────────────────────────────────────────────

    def build_context(
        self,
        case_snapshot: CaseContextSnapshot,
        fused_items: List[FusedItem],
        graph_nodes: Optional[List[GraphNodeSnippet]] = None,
        graph_edges: Optional[List[GraphEdgeSnippet]] = None,
        structured_records: Optional[List[StructuredRecordSnippet]] = None,
        statutory_context: Optional[Dict[str, Any]] = None,
        is_empty_case: Optional[bool] = None,
    ) -> AssembledContext:
        """
        Assemble and strictly constrain context within forensic budgets.
        - max_context_items <= 24
        - max_context_documents <= 12
        - max_graph_nodes <= 30
        - max_graph_edges <= 50
        - max_timeline_events <= 50
        - max_context_tokens <= 12,000
        - Preserves OBSERVED vs INFERRED epistemic status
        - Preserves complete provenance
        - Defensive second-layer deduplication
        """
        max_items = self.config.max_context_items
        max_docs = self.config.max_context_documents
        max_nodes = self.config.max_graph_nodes
        max_edges = self.config.max_graph_edges
        max_events = self.config.max_timeline_events
        max_tokens = self.config.max_context_tokens

        # Per-document chunk ceiling to prevent a single file from crowding out all other evidence
        max_chunks_per_doc = 4

        # Track allocated tokens
        allocated_tokens = 0

        # Snapshot base tokens
        snap_text = f"{case_snapshot.case_number} {case_snapshot.title} {case_snapshot.status} {case_snapshot.priority} {case_snapshot.crime_type or ''}"
        allocated_tokens += self.estimate_tokens(snap_text)

        # Statutory context
        statutory = statutory_context or {}
        if statutory:
            allocated_tokens += self.estimate_tokens(str(statutory))

        # ─────────────────────────────────────────────────────────────────────
        # A. Fused Items Selection (Relevance Primary, Diversity Preserved)
        # ─────────────────────────────────────────────────────────────────────
        selected_items: List[FusedItem] = []
        seen_dedup_keys: Dict[str, int] = {}
        seen_documents: Set[str] = set()
        doc_chunk_counts: Dict[str, int] = {}
        deferred_items: List[FusedItem] = []

        # Pass 1: Select top items adhering to per-document chunk diversity cap
        for item in fused_items:
            if len(selected_items) >= max_items:
                break

            dedup_key = self._extract_dedup_key(item)

            # Defensive Deduplication
            if dedup_key in seen_dedup_keys:
                # Merge citations and modalities into existing selected item
                existing_idx = seen_dedup_keys[dedup_key]
                existing_item = selected_items[existing_idx]
                merged_citations = list(existing_item.citations)
                for cit in (item.citations or []):
                    if cit not in merged_citations:
                        merged_citations.append(cit)
                merged_modalities = list(set(existing_item.modalities + item.modalities))
                selected_items[existing_idx] = FusedItem(
                    id=existing_item.id,
                    rank=existing_item.rank,
                    fused_score=existing_item.fused_score,
                    text=existing_item.text,
                    source_file=existing_item.source_file,
                    source_line=existing_item.source_line,
                    source_page=existing_item.source_page,
                    modalities=merged_modalities,
                    raw_payload=existing_item.raw_payload,
                    epistemic_status=existing_item.epistemic_status,
                    citations=merged_citations,
                    rerank_score=existing_item.rerank_score,
                    final_score=existing_item.final_score,
                )
                continue

            # Document Budget Check
            s_file = (item.source_file or "").strip()
            is_doc_file = bool(s_file and not s_file.startswith("Case Graph"))

            if is_doc_file:
                if s_file not in seen_documents and len(seen_documents) >= max_docs:
                    # Exceeds distinct document budget (12)
                    continue

                curr_doc_chunks = doc_chunk_counts.get(s_file, 0)
                if curr_doc_chunks >= max_chunks_per_doc:
                    # Defer chunk to preserve diversity across other documents
                    deferred_items.append(item)
                    continue

            # Token Budget Check & Oversized Item Handling
            item_tokens = self.estimate_item_tokens(item)
            remaining_tokens = max_tokens - allocated_tokens

            if remaining_tokens <= 20:
                # Token budget exhausted
                break

            accepted_item = item
            if item_tokens > remaining_tokens:
                # Single oversized item: truncate safely to fit remaining budget
                allowed_chars = max(40, (remaining_tokens - 15) * 4)
                truncated_text = item.text[:allowed_chars] + " ... [TRUNCATED TO FIT TOKEN BUDGET]"
                accepted_item = FusedItem(
                    id=item.id,
                    rank=len(selected_items) + 1,
                    fused_score=item.fused_score,
                    text=truncated_text,
                    source_file=item.source_file,
                    source_line=item.source_line,
                    source_page=item.source_page,
                    modalities=list(item.modalities),
                    raw_payload=dict(item.raw_payload),
                    epistemic_status=item.epistemic_status,
                    citations=list(item.citations),
                    rerank_score=item.rerank_score,
                    final_score=item.final_score,
                )
                item_tokens = self.estimate_item_tokens(accepted_item)

            seen_dedup_keys[dedup_key] = len(selected_items)
            selected_items.append(accepted_item)
            allocated_tokens += item_tokens

            if is_doc_file:
                seen_documents.add(s_file)
                doc_chunk_counts[s_file] = doc_chunk_counts.get(s_file, 0) + 1

        # Pass 2: If item slots and token budget remain, admit deferred items
        if len(selected_items) < max_items and (max_tokens - allocated_tokens) > 50:
            for item in deferred_items:
                if len(selected_items) >= max_items:
                    break

                dedup_key = self._extract_dedup_key(item)
                if dedup_key in seen_dedup_keys:
                    continue

                item_tokens = self.estimate_item_tokens(item)
                remaining_tokens = max_tokens - allocated_tokens
                if item_tokens > remaining_tokens:
                    if remaining_tokens <= 40:
                        break
                    allowed_chars = max(40, (remaining_tokens - 15) * 4)
                    truncated_text = item.text[:allowed_chars] + " ... [TRUNCATED TO FIT TOKEN BUDGET]"
                    item = FusedItem(
                        id=item.id,
                        rank=len(selected_items) + 1,
                        fused_score=item.fused_score,
                        text=truncated_text,
                        source_file=item.source_file,
                        source_line=item.source_line,
                        source_page=item.source_page,
                        modalities=list(item.modalities),
                        raw_payload=dict(item.raw_payload),
                        epistemic_status=item.epistemic_status,
                        citations=list(item.citations),
                        rerank_score=item.rerank_score,
                        final_score=item.final_score,
                    )
                    item_tokens = self.estimate_item_tokens(item)

                seen_dedup_keys[dedup_key] = len(selected_items)
                selected_items.append(item)
                allocated_tokens += item_tokens

        # Re-index ranks deterministically
        final_fused_items: List[FusedItem] = []
        for r_idx, it in enumerate(selected_items, start=1):
            final_fused_items.append(
                FusedItem(
                    id=it.id,
                    rank=r_idx,
                    fused_score=it.fused_score,
                    text=it.text,
                    source_file=it.source_file,
                    source_line=it.source_line,
                    source_page=it.source_page,
                    modalities=list(it.modalities),
                    raw_payload=dict(it.raw_payload),
                    epistemic_status=it.epistemic_status,
                    citations=list(it.citations),
                    rerank_score=it.rerank_score,
                    final_score=it.final_score,
                )
            )

        # ─────────────────────────────────────────────────────────────────────
        # B. Graph Nodes Selection (Budget: <= 30)
        # ─────────────────────────────────────────────────────────────────────
        selected_nodes: List[GraphNodeSnippet] = []
        seen_nodes: Set[str] = set()

        for node in (graph_nodes or []):
            if len(selected_nodes) >= max_nodes:
                break
            n_key = node.canonical_value.strip().lower()
            if n_key in seen_nodes:
                continue

            node_text = f"{node.canonical_value} {node.entity_type} {node.risk_score} {node.bridge_score}"
            n_tokens = self.estimate_tokens(node_text)
            if allocated_tokens + n_tokens > max_tokens:
                break

            seen_nodes.add(n_key)
            selected_nodes.append(node)
            allocated_tokens += n_tokens

        # ─────────────────────────────────────────────────────────────────────
        # C. Graph Edges Selection (Budget: <= 50)
        # Strictly preserves OBSERVED vs INFERRED
        # ─────────────────────────────────────────────────────────────────────
        selected_edges: List[GraphEdgeSnippet] = []
        seen_edges: Set[Tuple[str, str, str, str]] = set()

        for edge in (graph_edges or []):
            if len(selected_edges) >= max_edges:
                break
            src = edge.source_canonical.strip().lower()
            tgt = edge.target_canonical.strip().lower()
            rel = edge.relationship_type.strip().lower()
            status = edge.epistemic_status.strip().upper()

            e_key = (min(src, tgt), max(src, tgt), rel, status)
            if e_key in seen_edges:
                continue

            edge_text = f"{edge.source_canonical} {edge.relationship_type} {edge.target_canonical} {status} {edge.confidence}"
            e_tokens = self.estimate_tokens(edge_text)
            if allocated_tokens + e_tokens > max_tokens:
                break

            seen_edges.add(e_key)
            selected_edges.append(
                GraphEdgeSnippet(
                    source_canonical=edge.source_canonical,
                    target_canonical=edge.target_canonical,
                    relationship_type=edge.relationship_type,
                    confidence=float(edge.confidence),
                    epistemic_status=status,  # STRICTLY PRESERVED
                    citations=list(edge.citations),
                )
            )
            allocated_tokens += e_tokens

        # ─────────────────────────────────────────────────────────────────────
        # D. Structured Records Selection (Budget: <= 50)
        # ─────────────────────────────────────────────────────────────────────
        selected_records: List[StructuredRecordSnippet] = []
        seen_records: Set[str] = set()

        for rec in (structured_records or []):
            if len(selected_records) >= max_events:
                break
            r_key = rec.record_id.strip().lower()
            if r_key in seen_records:
                continue

            rec_text = f"{rec.record_id} {rec.record_type} {rec.summary_text} {rec.source_file or ''}"
            r_tokens = self.estimate_tokens(rec_text)
            if allocated_tokens + r_tokens > max_tokens:
                break

            seen_records.add(r_key)
            selected_records.append(rec)
            allocated_tokens += r_tokens

        # ─────────────────────────────────────────────────────────────────────
        # E. Empty Case Evaluation
        # ─────────────────────────────────────────────────────────────────────
        empty_case_flag = (
            is_empty_case
            if is_empty_case is not None
            else (
                case_snapshot.total_evidence_files == 0
                and len(final_fused_items) == 0
                and len(selected_nodes) == 0
                and len(selected_edges) == 0
                and len(selected_records) == 0
            )
        )

        return AssembledContext(
            case_snapshot=case_snapshot,
            fused_items=final_fused_items,
            graph_nodes=selected_nodes,
            graph_edges=selected_edges,
            structured_records=selected_records,
            statutory_context=statutory,
            is_empty_case=empty_case_flag,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Prompt Formatting & Prompt-Injection Boundary
    # ─────────────────────────────────────────────────────────────────────────

    def format_for_prompt(self, context: AssembledContext) -> str:
        """
        Formats AssembledContext into bounded, provenance-preserving evidence sections.
        Ensures evidence text is clearly demarcated as untrusted case data.
        """
        lines: List[str] = []

        # 1. Case Snapshot
        snap = context.case_snapshot
        lines.append("=== CASE METADATA ===")
        lines.append(f"Case ID: {snap.case_id}")
        lines.append(f"Case Number: {snap.case_number}")
        lines.append(f"Title: {snap.title}")
        lines.append(f"Status: {snap.status} | Priority: {snap.priority}")
        lines.append(f"Crime Type: {snap.crime_type or 'Unspecified'}")
        lines.append(
            f"Ground Truth Statistics: {snap.total_evidence_files} files, "
            f"{snap.total_entities} entities, {snap.total_events} events, {snap.total_findings} findings"
        )
        lines.append("")

        # 2. Empty Case Flag
        if context.is_empty_case:
            lines.append("[CASE STATE]")
            lines.append("Status: EMPTY_CASE")
            lines.append("Notice: This case contains no uploaded evidence files or corroborating records.")
            lines.append("[/CASE STATE]")
            lines.append("")
            return "\n".join(lines)

        # 3. Statutory Audit Framework
        if context.statutory_context:
            lines.append("=== STATUTORY AUDIT FRAMEWORK ===")
            for k, v in context.statutory_context.items():
                lines.append(f"{k}: {v}")
            lines.append("")

        # 4. Structured Records
        if context.structured_records:
            lines.append(f"=== STRUCTURED EVIDENCE RECORDS ({len(context.structured_records)}) ===")
            for rec in context.structured_records:
                ts_str = rec.timestamp.isoformat() if rec.timestamp else "N/A"
                loc = f" (line={rec.source_line}, page={rec.source_page})" if (rec.source_line or rec.source_page) else ""
                lines.append("[STRUCTURED_RECORD]")
                lines.append(f"id: {rec.record_id}")
                lines.append(f"type: {rec.record_type}")
                lines.append(f"timestamp: {ts_str}")
                lines.append(f"source: {rec.source_file or 'Database'}{loc}")
                lines.append(f"summary: {rec.summary_text}")
                lines.append("[/STRUCTURED_RECORD]")
            lines.append("")

        # 5. Graph Relationships
        if context.graph_edges:
            lines.append(f"=== GRAPH RELATIONSHIPS ({len(context.graph_edges)}) ===")
            for edge in context.graph_edges:
                lines.append("[GRAPH_RELATIONSHIP]")
                lines.append(f"source: {edge.source_canonical}")
                lines.append(f"target: {edge.target_canonical}")
                lines.append(f"relationship: {edge.relationship_type}")
                lines.append(f"epistemic_status: {edge.epistemic_status}")
                lines.append(f"confidence: {edge.confidence:.2f}")
                if edge.citations:
                    lines.append(f"citations: {edge.citations}")
                lines.append("[/GRAPH_RELATIONSHIP]")
            lines.append("")

        # 6. Graph Entity Nodes
        if context.graph_nodes:
            lines.append(f"=== GRAPH ENTITIES ({len(context.graph_nodes)}) ===")
            for node in context.graph_nodes:
                lines.append(
                    f"[GRAPH_ENTITY] {node.canonical_value} (type={node.entity_type}, "
                    f"risk={node.risk_score:.2f}, bridge={node.bridge_score:.2f})"
                )
            lines.append("")

        # 7. Reranked Evidence Items (Untrusted Case Data Encapsulated)
        if context.fused_items:
            lines.append(f"=== EVIDENCE ITEMS ({len(context.fused_items)}) ===")
            for it in context.fused_items:
                mods = [m.value for m in it.modalities]
                loc = f"line={it.source_line or 'N/A'}, page={it.source_page or 'N/A'}"
                lines.append("[EVIDENCE]")
                lines.append(f"id: {it.id}")
                lines.append(f"rank: {it.rank}")
                lines.append(f"source: {it.source_file} ({loc})")
                lines.append(f"modalities: {mods}")
                lines.append(f"epistemic_status: {it.epistemic_status or 'OBSERVED'}")
                if it.final_score is not None:
                    lines.append(f"relevance_score: {it.final_score:.4f}")
                lines.append("content:")
                lines.append(it.text)
                lines.append("[/EVIDENCE]")
            lines.append("")

        return "\n".join(lines)
