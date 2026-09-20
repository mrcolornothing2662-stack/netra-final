"""
Test the existing backend/copilot pipeline on Operation Meridian case
"""
import sys
import os
from pathlib import Path
sys.path.insert(0, "/Users/shubhamrana/netra5.0/backend")
import asyncio
import logging
logging.basicConfig(level=logging.INFO)

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

CASE_ID = "d456ad33-6411-4ece-baa8-397d9f422fe3"

async def test_question(question: str):
    print(f"\n==================================================")
    print(f"QUERY: {question}")
    print(f"==================================================")
    
    cfg = get_copilot_config()
    planner = QueryPlanner()
    plan = planner.plan(question)
    print(f"1. Query Plan Intent: {plan.intent.value}")
    print(f"   Target Entities: {plan.target_entities}")
    print(f"   Target Modalities: {plan.target_modalities}")
    print(f"   Time window: {plan.time_window_start} -> {plan.time_window_end}")

    async with AsyncSessionLocal() as db:
        v_store = VectorStore(config=cfg)
        g_retriever = GraphRetriever(config=cfg)
        s_retriever = StructuredRetriever(config=cfg)
        hybrid = HybridRetriever(
            config=cfg,
            vector_store=v_store,
            graph_retriever=g_retriever,
            structured_retriever=s_retriever,
        )

        fused_items, diag = await hybrid.retrieve(db=db, case_id=CASE_ID, plan=plan, limit=15)
        print(f"2. Hybrid Retrieval: {diag}")

        reranker = Reranker(config=cfg)
        reranked_items = await reranker.rerank(query=question, candidates=fused_items, plan=plan)
        print(f"3. Reranked Items Count: {len(reranked_items)}")

        c_builder = ContextBuilder(config=cfg)
        case_snapshot = await c_builder.build_case_snapshot(db=db, case_id=CASE_ID)
        assembled_context = c_builder.build_context(case_snapshot=case_snapshot, fused_items=reranked_items)
        print(f"4. Assembled Context:")
        print(f"   Empty case? {assembled_context.is_empty_case}")
        print(f"   Fused items: {len(assembled_context.fused_items)}")
        print(f"   Structured records: {len(assembled_context.structured_records)}")
        print(f"   Graph edges: {len(assembled_context.graph_edges)}")

        p_builder = PromptBuilder(config=cfg)
        generation_prompt = p_builder.build_prompt(query=plan, context=assembled_context)
        print(f"5. Prompt Generated: System prompt ({len(generation_prompt.system_prompt)} chars), User prompt ({len(generation_prompt.user_prompt)} chars)")

        generator = Generator(config=cfg)
        generated_resp = await generator.generate(prompt=generation_prompt)
        print(f"6. Generated Response ({generated_resp.model}):")
        print(f"   Raw Text:\n{generated_resp.text}")

        verifier = ClaimVerifier(config=cfg)
        verified = verifier.verify(response=generated_resp, context=assembled_context)
        print(f"7. Claim Verification:")
        print(f"   Passed: {verified.passed}")
        print(f"   Abstained: {verified.abstained}")
        print(f"   Grounded ratio: {verified.grounded_claim_ratio}")
        print(f"   Total claims: {verified.report.total_claims}")
        print(f"   Valid citations: {verified.report.valid_citation_count}")
        print(f"   Final Text:\n{verified.text}")

async def main():
    await test_question("What amount was transferred through ACC-001?")
    await test_question("What relationships connect ACC-001 to the available phone numbers?")
    await test_question("What happened between August 20 and August 25?")
    await test_question("What is the suspect's passport number?")

if __name__ == "__main__":
    asyncio.run(main())
