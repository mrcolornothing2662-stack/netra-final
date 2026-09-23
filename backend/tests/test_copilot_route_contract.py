"""
Copilot route contract regression test.

Why this exists:
  * The V5 Copilot edits removed the `total_ms` stage-latency assignment while the
    response payload still referenced it, producing a latent NameError -> HTTP 500.
    No test executed `routes.copilot.copilot_endpoint`, so the regression was silent.
  * Audit test 5 ("no silent mutation") reconstructs a proposal dict by hand instead
    of exercising the real route. This test drives the real endpoint so the emitted
    `mutation_proposals` payload is locked against the actual capability policy.

The RAG pipeline is stubbed (no DB, no Ollama/Gemini calls). Only the route's own
response assembly, latency accounting, and command-gateway proposal emission are
under test.
"""
import types
import uuid
from unittest.mock import patch

import pytest

from copilot.schemas import (
    AssembledContext,
    CaseContextSnapshot,
    Claim,
    FusedItem,
    GeneratedResponse,
    GenerationPrompt,
    ModalityType,
    QueryIntentType,
    QueryPlan,
    VerificationReport,
    VerifiedResponse,
)
from investigation import policies
from routes import copilot as copilot_routes
from routes.copilot import CopilotQuery, copilot_endpoint


# ── Stubbed pipeline collaborators ───────────────────────────────────────────

class _StubPlanner:
    def plan(self, question: str) -> QueryPlan:
        return QueryPlan(
            original_query=question,
            intent=QueryIntentType.RELATIONAL,
            target_modalities=["graph", "vector"],
        )


class _StubHybridRetriever:
    def __init__(self, items):
        self._items = items

    async def retrieve(self, db, case_id, plan, limit):
        return list(self._items), {"vector_hits": 0, "graph_hits": len(self._items)}


class _StubReranker:
    def __init__(self, items):
        self._items = items

    async def rerank(self, query, candidates, plan):
        return list(self._items)


class _StubContextBuilder:
    async def build_case_snapshot(self, db, case_id):
        return CaseContextSnapshot(case_id=str(case_id), case_number="CR-001", title="Stub Case")

    def build_context(self, case_snapshot, fused_items, graph_nodes, graph_edges, structured_records):
        return AssembledContext(
            case_snapshot=case_snapshot,
            fused_items=list(fused_items),
            graph_nodes=list(graph_nodes),
            graph_edges=list(graph_edges),
            structured_records=list(structured_records),
        )


class _StubPromptBuilder:
    def build_prompt(self, query, context) -> GenerationPrompt:
        # Mirrors copilot.prompt_builder.PromptBuilder.build_prompt, which accepts
        # Union[str, CopilotQuery, QueryPlan]; routes/copilot.py passes the QueryPlan.
        query_text = query.original_query if isinstance(query, QueryPlan) else str(query)
        return GenerationPrompt(
            system_prompt="system",
            user_prompt="user",
            query=query_text,
            case_id="case",
            estimated_tokens=42,
        )


class _StubGenerator:
    async def generate(self, prompt) -> GeneratedResponse:
        return GeneratedResponse(
            text="Rohit Sharma appears linked to ACC-777 by an inferred ownership edge.",
            provider="stub",
            model="stub-model",
            used_fallback=True,
            latency_ms=12.5,
        )


class _StubClaimVerifier:
    def verify(self, response, context) -> VerifiedResponse:
        return VerifiedResponse(
            text=response.text,
            original_text=response.text,
            passed=True,
            abstained=False,
            grounded_claim_ratio=0.5,
            report=VerificationReport(
                passed=True,
                total_claims=2,
                verifiable_claims=2,
                grounded_claims=1,
                unsupported_claims=1,
                grounded_claim_ratio=0.5,
                claims=[
                    Claim(
                        claim_id="c1",
                        text="Rohit Sharma owns ACC-777",
                        grounded=False,
                        reason="Inferred edge is not an observed fact",
                    ),
                    Claim(claim_id="c2", text="Account ACC-777 received funds", grounded=True),
                ],
            ),
            case_id=str(uuid.uuid4()),
        )


def _inferred_edge_item() -> FusedItem:
    """A single reranked item describing one INFERRED graph edge."""
    return FusedItem(
        id="edge-1",
        rank=1,
        fused_score=0.91,
        # Deliberately avoids the "[GRAPH ...]" prefix so the edge is produced by the
        # raw_payload path only, keeping the assertion target unambiguous.
        text="Analytical overlay: Rohit Sharma -> OWNS -> ACC-777",
        source_file="bank_statement.pdf",
        source_line="L42",
        source_page="P3",
        modalities=[ModalityType.GRAPH],
        raw_payload={
            "source": "Rohit Sharma",
            "target": "ACC-777",
            "relationship_type": "OWNS",
            "type": "OWNS",
            "confidence": 0.72,
            "epistemic_status": "INFERRED",
            "citations": [],
        },
        epistemic_status="INFERRED",
    )


# ── Test ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_copilot_endpoint_response_contract_and_readonly_proposals():
    case_id = str(uuid.uuid4())
    item = _inferred_edge_item()
    fake_case = types.SimpleNamespace(id=uuid.UUID(case_id))
    fake_operator = types.SimpleNamespace(id=uuid.uuid4(), role="io")

    async def _fake_require_case_access(db, current, requested_case_id, **kwargs):
        return fake_case

    with patch.object(copilot_routes, "require_case_access", _fake_require_case_access), \
            patch("copilot.config.get_copilot_config", return_value=types.SimpleNamespace()), \
            patch("copilot.query_planner.QueryPlanner", return_value=_StubPlanner()), \
            patch("copilot.vector_store.VectorStore"), \
            patch("copilot.graph_retriever.GraphRetriever"), \
            patch("copilot.structured_retriever.StructuredRetriever"), \
            patch("copilot.hybrid_retriever.HybridRetriever",
                  return_value=_StubHybridRetriever([item])), \
            patch("copilot.reranker.Reranker", return_value=_StubReranker([item])), \
            patch("copilot.context_builder.ContextBuilder",
                  return_value=_StubContextBuilder()), \
            patch("copilot.prompt_builder.PromptBuilder",
                  return_value=_StubPromptBuilder()), \
            patch("copilot.generator.Generator", return_value=_StubGenerator()), \
            patch("copilot.claim_verifier.ClaimVerifier",
                  return_value=_StubClaimVerifier()), \
            patch("investigation.commands.dispatch_command") as dispatch_mock:

        # 1. The real endpoint must execute without raising (regression guard: `total_ms`).
        out = await copilot_endpoint(
            case_id=case_id,
            body=CopilotQuery(question="Show me the hypothesis on the mule account", top_k=5),
            db=None,
            current=fake_operator,
        )

        # 2. Copilot must never invoke the mutation gateway itself.
        assert dispatch_mock.called is False, "Copilot route must not dispatch commands directly"
        assert dispatch_mock.await_count == 0

    # 3. Stage-latency contract (this is what the deleted `total_ms` assignment broke).
    stage = out["stage_latencies"]
    assert set(stage) == {
        "retrieval_ms", "context_ms", "generation_ms", "verification_ms", "total_ms",
    }
    for key, value in stage.items():
        assert isinstance(value, (int, float)), f"{key} must be numeric, got {type(value)}"
        assert value >= 0
    assert stage["total_ms"] >= stage["verification_ms"]

    assert out["status"] == "ready"
    assert out["latency_ms"] == 12.5
    assert out["grounded_claim_ratio"] == 0.5

    # 4. Ungrounded claims surface as verification warnings, not silent drops.
    flags = out["verification"]["flags"]
    assert len(flags) == 1
    assert flags[0]["check"] == "UNGROUNDED_CLAIM"
    assert "Rohit Sharma owns ACC-777" in flags[0]["message"]

    # 5. Observed vs inferred facts stay separated.
    assert out["inferred_facts"] == ["Rohit Sharma -> OWNS -> ACC-777"]
    assert out["observed_facts"] == []

    # 6. Proposals are inert, read-only payloads targeting the Command Gateway.
    proposals = out["mutation_proposals"]
    assert proposals, "an INFERRED edge must yield a confirmation proposal"
    confirm = [p for p in proposals if p["command"] == "CONFIRM_RELATIONSHIP"]
    assert len(confirm) == 1
    proposal = confirm[0]
    assert proposal["endpoint"] == f"/cases/{case_id}/commands"
    assert proposal["payload"]["source"] == "Rohit Sharma"
    assert proposal["payload"]["target"] == "ACC-777"
    assert proposal["payload"]["relationship_type"] == "OWNS"

    # 7. Drift guard: every advertised capability must exist in the policy module
    #    and be granted to the acting role (io / INVESTIGATOR).
    for prop in proposals:
        capability_name = prop["capability_required"]
        assert hasattr(policies, capability_name), (
            f"Copilot advertised unknown capability '{capability_name}'"
        )
        assert getattr(policies, capability_name) in policies.ROLE_CAPABILITIES["io"], (
            f"Capability '{capability_name}' is not grantable to the io role"
        )
