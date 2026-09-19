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

from copilot.claim_verifier import ClaimVerifier
from copilot.config import get_copilot_config
from copilot.context_builder import ContextBuilder
from copilot.generator import Generator
from copilot.hybrid_retriever import HybridRetriever
from copilot.prompt_builder import PromptBuilder
from copilot.query_planner import QueryPlanner
from copilot.reranker import Reranker
from copilot.schemas import GeneratedResponse, StructuredRecordSnippet

MERIDIAN_CASE_ID = "b2dd0f40-3673-4f28-a692-c37fde8dd77d"


async def run_live_claim_verifier_validation():
    cfg = get_copilot_config()
    planner = QueryPlanner()
    hybrid = HybridRetriever(config=cfg)
    reranker = Reranker(config=cfg)
    context_builder = ContextBuilder(config=cfg)
    prompt_builder = PromptBuilder(config=cfg)
    generator = Generator(config=cfg)
    verifier = ClaimVerifier(config=cfg)

    print("=" * 80)
    print("NETRA 5.0 — FILE 14 LIVE CLAIM VERIFIER VALIDATION (EVIDENCE GATE)")
    print("=" * 80)

    async with AsyncSessionLocal() as db:
        snapshot = await context_builder.build_case_snapshot(db, MERIDIAN_CASE_ID)

        # ─────────────────────────────────────────────────────────────────────
        # Scenario 1: Amount Query Grounding ("What amount was transferred through ACC-001?")
        # ─────────────────────────────────────────────────────────────────────
        q1 = "What amount was transferred through ACC-001?"
        print("\n" + "=" * 80)
        print(f"SCENARIO 1: \"{q1}\"")
        print("=" * 80)

        plan_1 = planner.plan(q1)
        candidates_1, _ = await hybrid.retrieve(db, MERIDIAN_CASE_ID, plan_1)
        reranked_1 = await reranker.rerank(query=plan_1, candidates=candidates_1)
        nodes_1, edges_1 = await hybrid.graph_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_1)
        _, structured_recs_1 = await hybrid.structured_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_1)

        ctx_records_1 = [
            StructuredRecordSnippet(
                record_id=it.id,
                table_name="evidence_events",
                record_type=str((it.raw_payload or {}).get("event_type", "structured")),
                summary_text=it.text,
                source_file=it.source_file,
                source_line=it.source_line,
                source_page=it.source_page,
            )
            for it in structured_recs_1
        ]

        assembled_1 = context_builder.build_context(
            case_snapshot=snapshot,
            fused_items=reranked_1,
            graph_nodes=nodes_1,
            graph_edges=edges_1,
            structured_records=ctx_records_1,
        )

        prompt_1 = prompt_builder.build_prompt(query=q1, context=assembled_1, plan=plan_1)
        gen_1 = await generator.generate(prompt_1)
        ver_1 = verifier.verify(gen_1, assembled_1)

        print(f"Total claims: {ver_1.report.total_claims}")
        print(f"Verifiable claims: {ver_1.report.verifiable_claims}")
        print(f"Grounded claims: {ver_1.report.grounded_claims}")
        print(f"Unsupported claims: {ver_1.report.unsupported_claims}")
        print(f"Grounded ratio: {ver_1.report.grounded_claim_ratio:.4f}")
        print(f"Valid citations: {ver_1.report.valid_citation_count}")
        print(f"Invalid citations: {ver_1.report.invalid_citations}")
        print(f"Epistemic violations: {ver_1.report.epistemic_violations}")
        print(f"Passed: {ver_1.passed}")
        print(f"Abstained/repaired: {ver_1.abstained}")
        print("-" * 80)
        print(f"Verified text:\n{ver_1.text}")
        print("-" * 80)

        assert ver_1.passed is True
        assert ver_1.report.grounded_claim_ratio >= 0.90
        assert ver_1.report.valid_citation_count >= 1
        grounded_claims = [c for c in ver_1.report.claims if c.grounded]
        assert any("07_upi_transaction_report.pdf" in c.get("file", "") for gc in grounded_claims for c in gc.supporting_citations)
        print("[PASSED] Scenario 1 grounded to 07_upi_transaction_report.pdf, page 1.")

        # ─────────────────────────────────────────────────────────────────────
        # Scenario 2: Relational Query Epistemic Preservation
        # ─────────────────────────────────────────────────────────────────────
        q2 = "What relationships connect ACC-001 to the phone numbers in this case?"
        print("\n" + "=" * 80)
        print(f"SCENARIO 2: \"{q2}\"")
        print("=" * 80)

        plan_2 = planner.plan(q2)
        candidates_2, _ = await hybrid.retrieve(db, MERIDIAN_CASE_ID, plan_2)
        reranked_2 = await reranker.rerank(query=plan_2, candidates=candidates_2)
        nodes_2, edges_2 = await hybrid.graph_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_2)
        _, structured_recs_2 = await hybrid.structured_retriever.retrieve_for_plan(db, MERIDIAN_CASE_ID, plan_2)

        ctx_records_2 = [
            StructuredRecordSnippet(
                record_id=it.id,
                table_name="evidence_events",
                record_type=str((it.raw_payload or {}).get("event_type", "structured")),
                summary_text=it.text,
                source_file=it.source_file,
                source_line=it.source_line,
                source_page=it.source_page,
            )
            for it in structured_recs_2
        ]

        assembled_2 = context_builder.build_context(
            case_snapshot=snapshot,
            fused_items=reranked_2,
            graph_nodes=nodes_2,
            graph_edges=edges_2,
            structured_records=ctx_records_2,
        )

        prompt_2 = prompt_builder.build_prompt(query=q2, context=assembled_2, plan=plan_2)
        gen_2 = await generator.generate(prompt_2)
        ver_2 = verifier.verify(gen_2, assembled_2)

        print(f"Total claims: {ver_2.report.total_claims}")
        print(f"Verifiable claims: {ver_2.report.verifiable_claims}")
        print(f"Grounded claims: {ver_2.report.grounded_claims}")
        print(f"Unsupported claims: {ver_2.report.unsupported_claims}")
        print(f"Grounded ratio: {ver_2.report.grounded_claim_ratio:.4f}")
        print(f"Valid citations: {ver_2.report.valid_citation_count}")
        print(f"Invalid citations: {ver_2.report.invalid_citations}")
        print(f"Epistemic violations: {ver_2.report.epistemic_violations}")
        print(f"Passed: {ver_2.passed}")
        print(f"Abstained/repaired: {ver_2.abstained}")
        for c in ver_2.report.claims:
            print(f"  CLAIM: {c.text}")
            print(f"    entities: {c.entities}, grounded: {c.grounded}, reason: {c.reason}")

        assert ver_2.passed is True
        assert ver_2.report.epistemic_violations == 0
        print("[PASSED] Scenario 2 graph relationships verified with epistemic status preserved.")

        # ─────────────────────────────────────────────────────────────────────
        # Scenario 3: Adversarial Unsupported Injection ("ACC-001 transferred ₹9,00,000 to PERSON-X")
        # ─────────────────────────────────────────────────────────────────────
        print("\n" + "=" * 80)
        print("SCENARIO 3: ADVERSARIAL UNSUPPORTED CLAIM INJECTION")
        print("=" * 80)

        unsupported_gen = GeneratedResponse(
            text=(
                "- Based on the case evidence, the transaction shows an amount of ₹18,750.00.\n"
                "- ACC-001 transferred ₹9,00,000 to PERSON-X.\n\n"
                "[Evidence: 07_upi_transaction_report.pdf, page 1]"
            ),
            provider="offline",
            model="netra-grounded-fallback",
            used_fallback=False,
        )
        ver_3 = verifier.verify(unsupported_gen, assembled_1)

        print(f"Total claims: {ver_3.report.total_claims}")
        print(f"Verifiable claims: {ver_3.report.verifiable_claims}")
        print(f"Grounded claims: {ver_3.report.grounded_claims}")
        print(f"Unsupported claims: {ver_3.report.unsupported_claims}")
        print(f"Grounded ratio: {ver_3.report.grounded_claim_ratio:.4f}")
        print(f"Valid citations: {ver_3.report.valid_citation_count}")
        print(f"Invalid citations: {ver_3.report.invalid_citations}")
        print(f"Epistemic violations: {ver_3.report.epistemic_violations}")
        print(f"Passed: {ver_3.passed}")
        print(f"Abstained/repaired: {ver_3.abstained}")
        print("-" * 80)
        print(f"Repaired / Abstained Response:\n{ver_3.text}")
        print("-" * 80)

        assert ver_3.passed is False, "Unsupported statement must fail verification"
        assert ver_3.abstained is True, "Must trigger abstention / repair"
        assert ver_3.report.unsupported_claims >= 1
        assert "9,00,000" in ver_3.text and "does not establish" in ver_3.text
        print("[PASSED] Scenario 3 correctly failed grounding and produced safe repaired response.")

        print("\n" + "=" * 80)
        print("ALL LIVE CLAIM VERIFIER VALIDATIONS COMPLETED SUCCESSFULLY")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_live_claim_verifier_validation())
