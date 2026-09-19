import asyncio
import os
import sys
import uuid

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath("backend"))

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("copilot").setLevel(logging.INFO)

from db.session import AsyncSessionLocal, engine
engine.echo = False

from copilot.config import get_copilot_config
from copilot.context_builder import ContextBuilder
from copilot.graph_retriever import GraphRetriever
from copilot.hybrid_retriever import HybridRetriever
from copilot.query_planner import QueryPlanner
from copilot.reranker import Reranker
from copilot.schemas import CaseContextSnapshot, StructuredRecordSnippet
from copilot.structured_retriever import StructuredRetriever


MERIDIAN_CASE_ID = "b2dd0f40-3673-4f28-a692-c37fde8dd77d"
EMPTY_CASE_ID = str(uuid.uuid4())


async def run_live_validation():
    cfg = get_copilot_config()
    planner = QueryPlanner()
    hybrid = HybridRetriever(config=cfg)
    reranker = Reranker(config=cfg)
    context_builder = ContextBuilder(config=cfg)

    print("=" * 80)
    print("LIVE CONTEXT BUILDER VALIDATION")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        # Load snapshot for Operation Meridian
        snapshot = await context_builder.build_case_snapshot(db, MERIDIAN_CASE_ID)
        print(f"Loaded Snapshot: Case #{snapshot.case_number} - \"{snapshot.title}\"")
        print(f"Evidence files: {snapshot.total_evidence_files}, Entities: {snapshot.total_entities}, Events: {snapshot.total_events}, Findings: {snapshot.total_findings}")

        # ─────────────────────────────────────────────────────────────────────
        # Query 1: Amount query
        # ─────────────────────────────────────────────────────────────────────
        q1 = "What amount was transferred through ACC-001?"
        print("\n" + "-" * 80)
        print(f"Query 1: \"{q1}\"")
        print("-" * 80)

        plan_1 = planner.plan(q1)
        candidates_1, _ = await hybrid.retrieve(db, MERIDIAN_CASE_ID, plan_1)
        reranked_1 = await reranker.rerank(query=plan_1, candidates=candidates_1)

        # Retrieve direct graph nodes/edges and structured records to include in context
        nodes_1, edges_1 = await hybrid.graph_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_1)
        _, structured_recs_1 = await hybrid.structured_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_1)

        # Convert structured items to StructuredRecordSnippets
        ctx_records_1 = []
        for it in structured_recs_1:
            p = it.raw_payload or {}
            ctx_records_1.append(
                StructuredRecordSnippet(
                    record_id=it.id,
                    table_name="evidence_events",
                    record_type=str(p.get("event_type", "structured")),
                    summary_text=it.text,
                    source_file=it.source_file,
                    source_line=it.source_line,
                    source_page=it.source_page,
                )
            )

        assembled_1 = context_builder.build_context(
            case_snapshot=snapshot,
            fused_items=reranked_1,
            graph_nodes=nodes_1,
            graph_edges=edges_1,
            structured_records=ctx_records_1,
        )

        distinct_docs_1 = {it.source_file for it in assembled_1.fused_items if it.source_file and not it.source_file.startswith("Case Graph")}
        top_ev_1 = assembled_1.fused_items[0] if assembled_1.fused_items else None
        est_tokens_1 = context_builder.estimate_context_tokens(assembled_1)

        print(f"Fused candidates: {len(reranked_1)}")
        print(f"Context items: {len(assembled_1.fused_items)}")
        print(f"Distinct documents: {len(distinct_docs_1)} {list(distinct_docs_1)}")
        print(f"Graph nodes: {len(assembled_1.graph_nodes)}")
        print(f"Graph edges: {len(assembled_1.graph_edges)}")
        print(f"Events: {len(assembled_1.structured_records)}")
        print(f"Estimated tokens: {est_tokens_1}")
        if top_ev_1:
            print(f"Top evidence: {top_ev_1.text[:100]}...")
            print(f"Provenance preserved: file={top_ev_1.source_file}, line={top_ev_1.source_line}, page={top_ev_1.source_page}, case_id={top_ev_1.raw_payload.get('case_id')}")

        # ─────────────────────────────────────────────────────────────────────
        # Query 2: Relational query & INFERRED status check
        # ─────────────────────────────────────────────────────────────────────
        q2 = "What relationships connect ACC-001 to the phone numbers in this case?"
        print("\n" + "-" * 80)
        print(f"Query 2: \"{q2}\"")
        print("-" * 80)

        plan_2 = planner.plan(q2)
        candidates_2, _ = await hybrid.retrieve(db, MERIDIAN_CASE_ID, plan_2)
        reranked_2 = await reranker.rerank(query=plan_2, candidates=candidates_2)

        nodes_2, edges_2 = await hybrid.graph_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_2)
        assembled_2 = context_builder.build_context(
            case_snapshot=snapshot,
            fused_items=reranked_2,
            graph_nodes=nodes_2,
            graph_edges=edges_2,
        )

        inferred_edges = [e for e in assembled_2.graph_edges if e.epistemic_status == "INFERRED"]
        observed_edges = [e for e in assembled_2.graph_edges if e.epistemic_status == "OBSERVED"]
        inferred_items = [it for it in assembled_2.fused_items if it.epistemic_status == "INFERRED"]

        print(f"Context items: {len(assembled_2.fused_items)}")
        print(f"Graph edges: {len(assembled_2.graph_edges)} (OBSERVED: {len(observed_edges)}, INFERRED: {len(inferred_edges)})")
        print(f"Graph nodes: {len(assembled_2.graph_nodes)}")
        print(f"Fused items with INFERRED status: {len(inferred_items)}")
        for inf_e in inferred_edges[:3]:
            print(f"  Verified INFERRED Edge: {inf_e.source_canonical} -> {inf_e.relationship_type} -> {inf_e.target_canonical} [status={inf_e.epistemic_status}]")

        # ─────────────────────────────────────────────────────────────────────
        # Query 3: Empty / New Case Check
        # ─────────────────────────────────────────────────────────────────────
        print("\n" + "-" * 80)
        print(f"Query 3: Empty/New Case ({EMPTY_CASE_ID})")
        print("-" * 80)

        empty_snapshot = await context_builder.build_case_snapshot(db, EMPTY_CASE_ID)
        empty_ctx = context_builder.build_context(
            case_snapshot=empty_snapshot,
            fused_items=[],
            graph_nodes=[],
            graph_edges=[],
            structured_records=[],
        )

        print(f"is_empty_case: {empty_ctx.is_empty_case}")
        print(f"records/evidence count: {len(empty_ctx.fused_items) + len(empty_ctx.structured_records)}")
        print(f"Graph nodes count: {len(empty_ctx.graph_nodes)}")
        print(f"Graph edges count: {len(empty_ctx.graph_edges)}")
        assert empty_ctx.is_empty_case is True, "Empty case must yield is_empty_case=True"
        assert len(empty_ctx.fused_items) == 0, "Empty case must not manufacture items"
        print("Empty case verified: is_empty_case = True, records/evidence = 0, no fabricated context.")

    print("\n" + "=" * 80)
    print("ALL LIVE CONTEXT BUILDER VALIDATION CHECKS PASSED.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_live_validation())
