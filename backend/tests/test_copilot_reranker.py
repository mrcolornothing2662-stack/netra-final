import pytest
import pytest_asyncio
from typing import List

from copilot.config import CopilotConfig
from copilot.query_planner import QueryPlanner
from copilot.reranker import (
    DeterministicFallbackRerankerProvider,
    LocalCrossEncoderProvider,
    Reranker,
    RerankerProvider,
)
from copilot.schemas import FusedItem, ModalityType, QueryPlan


def _create_sample_fused_item(
    id: str,
    rank: int,
    fused_score: float,
    text: str,
    source_file: str = "doc_evidence.pdf",
    source_line: str = "10",
    source_page: str = "1",
    modalities: List[ModalityType] = None,
    epistemic_status: str = "OBSERVED",
    raw_payload: dict = None,
    citations: list = None,
) -> FusedItem:
    return FusedItem(
        id=id,
        rank=rank,
        fused_score=fused_score,
        text=text,
        source_file=source_file,
        source_line=source_line,
        source_page=source_page,
        modalities=modalities or [ModalityType.STRUCTURED],
        raw_payload=raw_payload or {"case_id": "test-case-alpha", "event_type": "GENERIC"},
        epistemic_status=epistemic_status,
        citations=citations or [{"source_file": source_file, "page": source_page}],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Deterministic Fallback Scoring
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deterministic_fallback_scoring():
    provider = DeterministicFallbackRerankerProvider()
    query = "wire transfer INR 50,000 to offshore bank"
    docs = [
        "Customer executed wire transfer of INR 50,000 to offshore bank account.",
        "The weather today is warm and sunny with gentle breezes.",
        "",
    ]

    scores_1 = await provider.score(query, docs)
    scores_2 = await provider.score(query, docs)

    assert len(scores_1) == 3
    assert scores_1 == scores_2, "Fallback scoring must be 100% deterministic"
    assert scores_1[0] > scores_1[1], "Matching document should score higher than unrelated document"
    assert scores_1[2] == 0.0, "Empty document should score 0.0"
    for s in scores_1:
        assert 0.0 <= s <= 1.0, "Scores must be bounded in [0.0, 1.0]"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Exact Amount Query Prioritization
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exact_amount_query_prioritization():
    reranker = Reranker()
    query = "What amount was transferred through ACC-001?"

    candidates = [
        _create_sample_fused_item(
            id="item_entity",
            rank=1,
            fused_score=0.035,
            text="[GRAPH NODE] ACC-001 (type=ACCOUNT, risk=0.40, bridge=0.10)",
            modalities=[ModalityType.GRAPH],
            raw_payload={"canonical_value": "ACC-001", "entity_type": "ACCOUNT"},
        ),
        _create_sample_fused_item(
            id="item_transaction",
            rank=2,
            fused_score=0.030,
            text="[STRUCTURED TRANSACTION] ACC-001 transferred INR 1,500,000 to ACC-002",
            modalities=[ModalityType.STRUCTURED],
            raw_payload={
                "event_type": "TRANSACTION",
                "amount": 1500000.0,
                "source": "ACC-001",
                "target": "ACC-002",
            },
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert len(reranked) == 2
    # The transaction record should be promoted to #1 because of exact amount/transaction intent match
    assert reranked[0].id == "item_transaction"
    assert reranked[0].rank == 1
    assert reranked[0].final_score > reranked[1].final_score


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Account/Phone Identifier Relevance
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_phone_identifier_relevance():
    reranker = Reranker()
    query = "Find evidence relating to account ACC-9821 and phone +919876543210"

    candidates = [
        _create_sample_fused_item(
            id="item_other",
            rank=1,
            fused_score=0.035,
            text="Communication between ACC-1111 and +911111111111",
            raw_payload={"source": "ACC-1111", "target": "+911111111111"},
        ),
        _create_sample_fused_item(
            id="item_matching",
            rank=2,
            fused_score=0.025,
            text="Transaction from ACC-9821 verified via SMS alert to +919876543210",
            raw_payload={"source": "ACC-9821", "phone": "+919876543210"},
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert reranked[0].id == "item_matching"
    assert reranked[0].rank == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Semantic Relevance
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_relevance():
    reranker = Reranker()
    query = "shell corporation laundering hawala syndicate"

    candidates = [
        _create_sample_fused_item(
            id="generic_doc",
            rank=1,
            fused_score=0.030,
            text="General guidelines on corporate administrative filing procedures.",
        ),
        _create_sample_fused_item(
            id="highly_relevant_doc",
            rank=2,
            fused_score=0.025,
            text="Investigation uncovered shell corporation funneling illicit laundering funds through hawala syndicate networks.",
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert reranked[0].id == "highly_relevant_doc"


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: RRF Preservation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rrf_preservation():
    reranker = Reranker()
    query = "any investigative query"

    candidates = [
        _create_sample_fused_item(id="cand_1", rank=1, fused_score=0.041234, text="Candidate one text"),
        _create_sample_fused_item(id="cand_2", rank=2, fused_score=0.028765, text="Candidate two text"),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    item_map = {item.id: item for item in reranked}
    assert item_map["cand_1"].fused_score == 0.041234
    assert item_map["cand_2"].fused_score == 0.028765
    assert item_map["cand_1"].fused_score != item_map["cand_1"].final_score


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: Final-Score Calculation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_final_score_calculation():
    reranker = Reranker()
    query = "wire transfer"

    candidates = [
        _create_sample_fused_item(
            id="cand_1",
            rank=1,
            fused_score=0.030000,
            text="Wire transfer execution confirmation.",
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert len(reranked) == 1
    item = reranked[0]
    assert item.rerank_score is not None
    assert item.final_score is not None
    assert item.final_score >= item.fused_score
    assert item.final_score >= item.rerank_score


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Observed Relationship Preservation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observed_relationship_preservation():
    reranker = Reranker()
    query = "What relationships connect ACC-001 to ACC-002?"

    candidates = [
        _create_sample_fused_item(
            id="graph_observed",
            rank=1,
            fused_score=0.035,
            text="[GRAPH OBSERVED] ACC-001 -> TRANSFERRED_TO -> ACC-002 (confidence=1.00)",
            modalities=[ModalityType.GRAPH],
            epistemic_status="OBSERVED",
            raw_payload={"source": "ACC-001", "target": "ACC-002", "epistemic_status": "OBSERVED"},
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert reranked[0].epistemic_status == "OBSERVED"
    assert reranked[0].raw_payload["epistemic_status"] == "OBSERVED"


# ─────────────────────────────────────────────────────────────────────────────
# Test 8: Inferred Relationship Preservation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_inferred_relationship_preservation():
    reranker = Reranker()
    query = "What relationships connect ACC-001 to ACC-002?"

    candidates = [
        _create_sample_fused_item(
            id="graph_inferred",
            rank=1,
            fused_score=0.035,
            text="[GRAPH INFERRED] ACC-001 -> CO_LOCATED -> ACC-002 (confidence=0.75)",
            modalities=[ModalityType.GRAPH],
            epistemic_status="INFERRED",
            raw_payload={"source": "ACC-001", "target": "ACC-002", "epistemic_status": "INFERRED"},
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    # Must remain explicitly INFERRED; reranker must never convert INFERRED to OBSERVED
    assert reranked[0].epistemic_status == "INFERRED"
    assert reranked[0].raw_payload["epistemic_status"] == "INFERRED"


# ─────────────────────────────────────────────────────────────────────────────
# Test 9: Provenance Preservation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provenance_preservation():
    reranker = Reranker()
    query = "transaction records"

    raw_payload = {
        "event_id": "EV-9999",
        "case_id": "case-provenance-test",
        "transaction_hash": "0xabc123",
        "amount": 25000.0,
    }
    citations = [{"file": "forensic_report.pdf", "page": "12", "line": "45"}]

    candidates = [
        _create_sample_fused_item(
            id="prov_item",
            rank=1,
            fused_score=0.033,
            text="Forensic finding for transaction 0xabc123",
            source_file="forensic_report.pdf",
            source_line="45",
            source_page="12",
            modalities=[ModalityType.STRUCTURED, ModalityType.VECTOR],
            epistemic_status="OBSERVED",
            raw_payload=raw_payload,
            citations=citations,
        )
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    res = reranked[0]
    assert res.source_file == "forensic_report.pdf"
    assert res.source_line == "45"
    assert res.source_page == "12"
    assert res.citations == citations
    assert res.raw_payload == raw_payload
    assert set(res.modalities) == {ModalityType.STRUCTURED, ModalityType.VECTOR}


# ─────────────────────────────────────────────────────────────────────────────
# Test 10: Empty Candidate List
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_candidate_list():
    reranker = Reranker()
    res = await reranker.rerank(query="What is the account status?", candidates=[])
    assert res == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 11: Candidate Limit = 30
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_candidate_limit_30():
    config = CopilotConfig(reranker_candidate_k=30, reranker_final_k=12)
    reranker = Reranker(config=config)
    query = "critical target match"

    # Create 40 candidates
    # Items 1-30 are normal; items 31-40 have the exact keyword but are outside budget
    candidates = []
    for i in range(1, 41):
        if i > 30:
            text = f"critical target match in document {i}"
        else:
            text = f"document content {i}"
        candidates.append(
            _create_sample_fused_item(
                id=f"cand_{i}",
                rank=i,
                fused_score=round(1.0 / (60 + i), 6),
                text=text,
            )
        )

    reranked = await reranker.rerank(query=query, candidates=candidates)

    reranked_ids = {item.id for item in reranked}
    # Candidates 31-40 must not be included because they were excluded by the 30-candidate budget limit
    for i in range(31, 41):
        assert f"cand_{i}" not in reranked_ids


# ─────────────────────────────────────────────────────────────────────────────
# Test 12: Final Limit = 12
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_final_limit_12():
    config = CopilotConfig(reranker_candidate_k=30, reranker_final_k=12)
    reranker = Reranker(config=config)
    query = "investigation documents"

    candidates = [
        _create_sample_fused_item(
            id=f"cand_{i}",
            rank=i,
            fused_score=round(1.0 / (60 + i), 6),
            text=f"investigation evidence file number {i}",
        )
        for i in range(1, 25)
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert len(reranked) == 12
    for idx, item in enumerate(reranked, start=1):
        assert item.rank == idx


# ─────────────────────────────────────────────────────────────────────────────
# Test 13: Deterministic Tie Ordering
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deterministic_tie_ordering():
    reranker = Reranker()
    query = "arbitrary query"

    # Create 3 candidates with identical text and identical fused_score
    candidates = [
        _create_sample_fused_item(id="item_b", rank=1, fused_score=0.03, text="same content"),
        _create_sample_fused_item(id="item_a", rank=2, fused_score=0.03, text="same content"),
        _create_sample_fused_item(id="item_c", rank=3, fused_score=0.03, text="same content"),
    ]

    reranked_1 = await reranker.rerank(query=query, candidates=candidates)
    reranked_2 = await reranker.rerank(query=query, candidates=candidates)

    order_1 = [item.id for item in reranked_1]
    order_2 = [item.id for item in reranked_2]

    assert order_1 == order_2, "Tie-breaking must produce identical order across repeated runs"
    # Tied by final_score, tied by fused_score -> broken by original_rank (item_b, item_a, item_c)
    assert order_1 == ["item_b", "item_a", "item_c"]


# ─────────────────────────────────────────────────────────────────────────────
# Test 14: Disabled Cross-Encoder Does Not Attempt Model Download
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disabled_cross_encoder_does_not_attempt_model_download():
    config = CopilotConfig(reranker_enabled=False)
    reranker = Reranker(config=config)

    assert isinstance(reranker.provider, DeterministicFallbackRerankerProvider)

    # Ensure running rerank succeeds without touching any remote models
    candidates = [
        _create_sample_fused_item(id="c1", rank=1, fused_score=0.02, text="offline safe text")
    ]
    res = await reranker.rerank(query="offline query", candidates=candidates)
    assert len(res) == 1
    assert res[0].id == "c1"


# ─────────────────────────────────────────────────────────────────────────────
# Test 15: Provider Failure Falls Back Safely
# ─────────────────────────────────────────────────────────────────────────────

class FailingProvider:
    """Mock provider simulating an unexpected error (e.g. CUDA OOM or network error)."""
    async def score(self, query: str, documents: list[str]) -> list[float]:
        raise RuntimeError("Simulated provider failure / GPU OOM")


@pytest.mark.asyncio
async def test_provider_failure_falls_back_safely():
    failing_provider = FailingProvider()
    reranker = Reranker(provider=failing_provider)

    candidates = [
        _create_sample_fused_item(id="c1", rank=1, fused_score=0.02, text="resilient forensic evidence")
    ]

    # Must NOT raise exception; must log warning and fall back to DeterministicFallbackRerankerProvider
    res = await reranker.rerank(query="forensic evidence", candidates=candidates)
    assert len(res) == 1
    assert res[0].id == "c1"
    assert res[0].rerank_score is not None
    assert res[0].final_score is not None


# ─────────────────────────────────────────────────────────────────────────────
# Test 16: No Risk/Confidence -> Guilt Transformation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_risk_confidence_to_guilt_transformation():
    reranker = Reranker()
    query = "Evaluate network connections"

    # Candidate with high risk_score, high bridge_score, and finding confidence
    candidates = [
        _create_sample_fused_item(
            id="suspect_entity",
            rank=1,
            fused_score=0.035,
            text="[GRAPH NODE] John Doe (risk=0.98, bridge=0.95)",
            epistemic_status="INFERRED",
            raw_payload={
                "canonical_value": "John Doe",
                "risk_score": 0.98,
                "bridge_score": 0.95,
                "confidence": 0.99,
            },
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)
    item = reranked[0]

    # 1. Epistemic status remains purely evidential / INFERRED
    assert item.epistemic_status == "INFERRED"
    # 2. No guilt transformation: check item dict has no guilt probability field
    item_dict = item.model_dump()
    for key in item_dict:
        assert "guilt" not in key.lower()
    for key in item.raw_payload:
        assert "guilt" not in key.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Test 17: Case Isolation and Provenance Case ID Preservation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_case_isolation_and_provenance_case_id():
    reranker = Reranker()
    query = "account transfer details"

    case_a_id = "case-uuid-aaaa"
    candidates = [
        _create_sample_fused_item(
            id="item_case_a",
            rank=1,
            fused_score=0.03,
            text="Transfer from account in case A",
            raw_payload={"case_id": case_a_id, "amount": 10000.0},
        ),
    ]

    reranked = await reranker.rerank(query=query, candidates=candidates)

    assert len(reranked) == 1
    assert reranked[0].raw_payload["case_id"] == case_a_id
