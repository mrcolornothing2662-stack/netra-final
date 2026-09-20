import sys
sys.path.insert(0, "/Users/shubhamrana/netra5.0/backend")
import asyncio
import re
import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)

from db.session import AsyncSessionLocal
from copilot.config import get_copilot_config
from copilot.query_planner import QueryPlanner
from copilot.hybrid_retriever import HybridRetriever
from copilot.vector_store import VectorStore
from copilot.graph_retriever import GraphRetriever
from copilot.structured_retriever import StructuredRetriever
from copilot.reranker import Reranker
from copilot.context_builder import ContextBuilder
from copilot.prompt_builder import PromptBuilder
from copilot.generator import Generator
from copilot.claim_verifier import ClaimVerifier
from copilot.schemas import GraphEdgeSnippet, StructuredRecordSnippet, GraphNodeSnippet

CASE_ID = "d456ad33-6411-4ece-baa8-397d9f422fe3"

async def test_q(q: str):
    print("="*60)
    print("QUERY:", q)
    print("="*60)
    cfg = get_copilot_config()
    planner = QueryPlanner()
    plan = planner.plan(q)

    async with AsyncSessionLocal() as db:
        v_store = VectorStore(config=cfg)
        g_retriever = GraphRetriever(config=cfg)
        s_retriever = StructuredRetriever(config=cfg)
        hybrid = HybridRetriever(cfg, v_store, g_retriever, s_retriever)

        fused_items, diag = await hybrid.retrieve(db=db, case_id=CASE_ID, plan=plan, limit=20)
        reranker = Reranker(config=cfg)
        reranked_items = await reranker.rerank(query=q, candidates=fused_items, plan=plan)

        # Extract edges, records, and nodes
        edges = []
        records = []
        nodes = []
        for it in reranked_items:
            p = it.raw_payload or {}
            if "source" in p and "target" in p:
                edges.append(GraphEdgeSnippet(
                    source_canonical=str(p["source"]),
                    target_canonical=str(p["target"]),
                    relationship_type=str(p.get("type") or p.get("relationship_type")),
                    confidence=float(p.get("confidence", 1.0)),
                    epistemic_status=str(p.get("epistemic_status") or it.epistemic_status or "OBSERVED"),
                    citations=p.get("citations", []),
                ))
            elif it.text.startswith("[GRAPH "):
                m = re.search(r"\[GRAPH\s+([A-Z_]+)\]\s+(.*?)\s+->\s+(.*?)\s+->\s+(.*?)(?:\s+\(confidence=([0-9.]+)\))?$", it.text.strip())
                if m:
                    edges.append(GraphEdgeSnippet(
                        source_canonical=m.group(2).strip(),
                        target_canonical=m.group(4).strip(),
                        relationship_type=m.group(3).strip(),
                        confidence=float(m.group(5)) if m.group(5) else 1.0,
                        epistemic_status=m.group(1).strip(),
                        citations=it.citations or [],
                    ))
            if "event_id" in p or "finding_id" in p or any(it.text.startswith(f"[{tag}]") for tag in ("TRANSACTION", "WHATSAPP", "CALL", "LOCATION", "TIMELINE", "FINDING", "DEVICE", "NETWORK")):
                records.append(StructuredRecordSnippet(
                    record_id=str(p.get("event_id") or p.get("finding_id") or it.id),
                    table_name="findings" if "finding_id" in p or "[FINDING]" in it.text else "evidence_events",
                    record_type=str(p.get("event_type") or p.get("finding_type") or "record"),
                    timestamp=None,
                    summary_text=it.text,
                    source_file=it.source_file,
                    source_line=it.source_line,
                    source_page=it.source_page,
                    exact_payload=p,
                ))
            if "canonical_value" in p and "entity_type" in p:
                nodes.append(GraphNodeSnippet(
                    entity_id=str(p.get("entity_id") or it.id),
                    canonical_value=str(p["canonical_value"]),
                    entity_type=str(p["entity_type"]),
                    risk_score=float(p.get("risk_score") or 0.0),
                    bridge_score=float(p.get("bridge_score") or 0.0),
                ))

        c_builder = ContextBuilder(config=cfg)
        case_snapshot = await c_builder.build_case_snapshot(db=db, case_id=CASE_ID)
        assembled_context = c_builder.build_context(
            case_snapshot=case_snapshot,
            fused_items=reranked_items,
            graph_nodes=nodes,
            graph_edges=edges,
            structured_records=records,
        )

        print(f"Context: fused_items={len(assembled_context.fused_items)}, edges={len(assembled_context.graph_edges)}, records={len(assembled_context.structured_records)}")

        p_builder = PromptBuilder(config=cfg)
        gen_prompt = p_builder.build_prompt(query=plan, context=assembled_context)

        generator = Generator(config=cfg)
        gen_resp = await generator.generate(prompt=gen_prompt)
        print("\n--- GENERATOR OUTPUT ---")
        print(gen_resp.text)

        verifier = ClaimVerifier(config=cfg)
        verified = verifier.verify(response=gen_resp, context=assembled_context)
        print("\n--- VERIFICATION ---")
        print(f"Passed: {verified.passed}, Abstained: {verified.abstained}, Grounded Ratio: {verified.grounded_claim_ratio}")
        print("\n--- FINAL VERIFIED TEXT ---")
        print(verified.text)

async def main():
    await test_q("What amount was transferred through ACC-001?")
    await test_q("What relationships connect ACC-001 to the available phone numbers?")
    await test_q("What happened between August 20 and August 25?")
    await test_q("What is the suspect's passport number?")

if __name__ == "__main__":
    asyncio.run(main())
