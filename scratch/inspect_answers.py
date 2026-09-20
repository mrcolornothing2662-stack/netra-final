import sys
sys.path.insert(0, "/Users/shubhamrana/netra5.0/backend")
import asyncio
import logging
logging.disable(logging.CRITICAL)

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

async def test_q(question: str):
    print(f"\n==================================================")
    print(f"QUESTION: {question}")
    print(f"==================================================")
    cfg = get_copilot_config()
    planner = QueryPlanner()
    plan = planner.plan(question)

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
        print("DIAGNOSTICS:", diag)

        reranker = Reranker(config=cfg)
        reranked_items = await reranker.rerank(query=question, candidates=fused_items, plan=plan)

        c_builder = ContextBuilder(config=cfg)
        case_snapshot = await c_builder.build_case_snapshot(db=db, case_id=CASE_ID)
        assembled_context = c_builder.build_context(case_snapshot=case_snapshot, fused_items=reranked_items)

        p_builder = PromptBuilder(config=cfg)
        generation_prompt = p_builder.build_prompt(query=plan, context=assembled_context)

        generator = Generator(config=cfg)
        generated_resp = await generator.generate(prompt=generation_prompt)

        verifier = ClaimVerifier(config=cfg)
        verified = verifier.verify(response=generated_resp, context=assembled_context)

        print("\n--- GENERATED RAW ---")
        print(generated_resp.text)
        print("\n--- VERIFICATION REPORT ---")
        print("Passed:", verified.passed)
        print("Abstained:", verified.abstained)
        print("Claims:", len(verified.report.claims))
        for c in verified.report.claims:
            print(f"  Claim [{c.claim_type}]: {c.text} -> Grounded: {c.grounded} (Reason: {c.reason})")
        print("\n--- FINAL VERIFIED TEXT ---")
        print(verified.text)

async def main():
    await test_q("What amount was transferred through ACC-001?")
    await test_q("What relationships connect ACC-001 to the available phone numbers?")
    await test_q("What happened between August 20 and August 25?")
    await test_q("What is the suspect's passport number?")

if __name__ == "__main__":
    asyncio.run(main())
