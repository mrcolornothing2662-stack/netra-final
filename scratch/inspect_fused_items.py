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

CASE_ID = "d456ad33-6411-4ece-baa8-397d9f422fe3"

async def check_items(question: str):
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
        for i, it in enumerate(fused_items):
            print(f"[{i+1}] ID: {it.id} | Modalities: {it.modalities} | Source: {it.source_file} (line={it.source_line}, page={it.source_page})")
            print(f"    Text: {it.text[:120]}")
            print(f"    Raw payload keys: {list(it.raw_payload.keys()) if it.raw_payload else None}")

async def main():
    await check_items("What amount was transferred through ACC-001?")
    await check_items("What relationships connect ACC-001 to the available phone numbers?")
    await check_items("What happened between August 20 and August 25?")

if __name__ == "__main__":
    asyncio.run(main())
