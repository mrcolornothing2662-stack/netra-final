import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath("backend"))

import logging
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("copilot").setLevel(logging.INFO)

from db.session import AsyncSessionLocal, engine
engine.echo = False
from copilot.config import get_copilot_config
from copilot.hybrid_retriever import HybridRetriever
from copilot.query_planner import QueryPlanner
from copilot.reranker import Reranker


CASE_ID = "b2dd0f40-3673-4f28-a692-c37fde8dd77d"

QUERIES = [
    "What amount was transferred through ACC-001?",
    "What relationships connect ACC-001 to the phone numbers in this case?",
    "What happened between August 20 and August 25?",
]


async def run_validation():
    cfg = get_copilot_config()
    planner = QueryPlanner()
    hybrid = HybridRetriever(config=cfg)
    reranker = Reranker(config=cfg)

    print("=" * 80)
    print(f"LIVE VALIDATION: Operation Meridian ({CASE_ID})")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        for idx, q_text in enumerate(QUERIES, start=1):
            print(f"\n[{idx}] Query: \"{q_text}\"")
            print("-" * 80)

            plan = planner.plan(q_text)
            fused_candidates, diagnostics = await hybrid.retrieve(db=db, case_id=CASE_ID, plan=plan)

            received_count = len(fused_candidates)
            eval_count = min(received_count, cfg.reranker_candidate_k)

            # Check if any candidate has INFERRED status
            has_inferred_before = any(
                c.epistemic_status == "INFERRED" for c in fused_candidates
            )

            reranked_items = await reranker.rerank(query=plan, candidates=fused_candidates)
            final_count = len(reranked_items)

            # Check if any reranked item was INFERRED and check status preservation
            for item in reranked_items:
                orig = next((c for c in fused_candidates if c.id == item.id), None)
                if orig and orig.epistemic_status == "INFERRED":
                    assert item.epistemic_status == "INFERRED", (
                        f"CRITICAL ERROR: Item {item.id} was INFERRED before reranking but became {item.epistemic_status}"
                    )

            top_item = reranked_items[0] if reranked_items else None

            print(f"Candidates received: {received_count}")
            print(f"Candidates reranked: {eval_count}")
            print(f"Final items: {final_count}")

            if top_item:
                print(f"Top item: {top_item.text}")
                print(f"Top modality/modalities: {[m.value for m in top_item.modalities]}")
                print(f"RRF score: {top_item.fused_score:.6f}")
                print(f"Rerank score: {top_item.rerank_score:.6f}" if top_item.rerank_score is not None else "Rerank score: N/A")
                print(f"Final score: {top_item.final_score:.6f}" if top_item.final_score is not None else "Final score: N/A")
                print(f"Epistemic status: {top_item.epistemic_status}")
                print(f"Provenance: file={top_item.source_file}, line={top_item.source_line}, page={top_item.source_page}, citations={len(top_item.citations)}")
            else:
                print("No items retrieved.")

            # Print top 3 items for deep inspection
            print("\nTop Items Detail:")
            for rank_idx, it in enumerate(reranked_items[:3], start=1):
                print(f"  #{rank_idx} [Final: {it.final_score:.4f} | RRF: {it.fused_score:.4f} | Epistemic: {it.epistemic_status} | Mods: {[m.value for m in it.modalities]}]")
                print(f"      Text: {it.text[:120]}...")
                print(f"      Source: {it.source_file} (line={it.source_line}, page={it.source_page})")

    print("\n" + "=" * 80)
    print("ALL 3 LIVE QUERIES EXECUTED AND VERIFIED SUCCESSFULLY.")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_validation())
