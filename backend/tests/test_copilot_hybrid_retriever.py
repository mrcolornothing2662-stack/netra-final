from __future__ import annotations

"""
NETRA 5.0 — Unit and Security Boundary Tests for HybridRetriever (File 9)

Verifies:
1. RRF mathematical correctness: score = Σ weight / (k + rank)
2. Modality weights (Vector 1.0, Graph 1.2, Structured 1.2, Timeline 1.0)
3. Multi-modality fusion across all 4 modalities
4. Cross-modality deterministic deduplication by provenance identity
5. Provenance preservation (source_file, source_line, source_page, raw_payload, citations)
6. Graph OBSERVED status preservation
7. Graph INFERRED status preservation (confidence, reason codes, citations)
8. Empty modality handling (gracefully handles 0 results in any modality)
9. Candidate limit enforcement
10. Deterministic tie ordering (score descending, original rank ascending, item ID)
11. Case isolation (Case A never accepts Case B items)
12. Identical evidence appearing through multiple modalities fuses to single FusedItem with all modalities
13. Structured exact facts remain intact without score fabrication
"""

import uuid
import pytest
from typing import Dict, List, Sequence

from copilot.config import CopilotConfig
from copilot.hybrid_retriever import HybridRetriever
from copilot.schemas import FusedItem, ModalityType, RetrievedItem

CASE_A = str(uuid.uuid4())
CASE_B = str(uuid.uuid4())


@pytest.fixture
def retriever() -> HybridRetriever:
    cfg = CopilotConfig(
        rrf_k=60,
        vector_rrf_weight=1.0,
        graph_rrf_weight=1.2,
        structured_rrf_weight=1.2,
        timeline_rrf_weight=1.0,
        max_retrieval_candidates=50,
    )
    return HybridRetriever(config=cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_rrf_mathematical_correctness(retriever: HybridRetriever):
    """
    Verify exact RRF formula:
    With k=60, Structured weight=1.2 at rank 1, Graph weight=1.2 at rank 3:
    Expected score = (1.2 / 61) + (1.2 / 63) = 0.01967213 + 0.01904762 = 0.03871975
    """
    # Item 1 present in Structured (#1) and Graph (#3)
    structured_item = RetrievedItem(
        id="evidence_events:evt-001",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Transfer ₹50,000 to ACC-4821",
        source_file="bank_statement.csv",
        source_line="10",
        raw_payload={"event_id": "evt-001", "amount": 50000.0, "case_id": CASE_A},
    )

    graph_item = RetrievedItem(
        id="graph_edge:PERSON:Rahul:TRANSFERRED_TO:ACCOUNT:4821:OBSERVED",
        modality=ModalityType.GRAPH,
        score=0.95,
        text="Rahul transferred to 4821",
        source_file="Case Graph (Relationships)",
        raw_payload={"event_id": "evt-001", "source": "Rahul", "target": "4821", "case_id": CASE_A},
    )

    candidate_lists: Dict[ModalityType, Sequence[RetrievedItem]] = {
        ModalityType.STRUCTURED: [structured_item],
        # Graph has dummy items at #1 and #2, our target item is at rank #3
        ModalityType.GRAPH: [
            RetrievedItem(id="dummy-1", modality=ModalityType.GRAPH, score=1.0, text="d1", source_file="g", raw_payload={"case_id": CASE_A}),
            RetrievedItem(id="dummy-2", modality=ModalityType.GRAPH, score=1.0, text="d2", source_file="g", raw_payload={"case_id": CASE_A}),
            graph_item,
        ],
    }

    fused = retriever.fuse_candidates(case_id=CASE_A, candidate_lists=candidate_lists)
    target_fused = next(f for f in fused if f.raw_payload.get("event_id") == "evt-001")

    expected_score = round((1.2 / 61) + (1.2 / 63), 6)
    assert target_fused.fused_score == expected_score


def test_modality_weights_respected(retriever: HybridRetriever):
    """Items ranked #1 in Structured (weight 1.2) rank higher than items ranked #1 in Vector (weight 1.0)."""
    item_struct = RetrievedItem(
        id="struct-item-1",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Structured record",
        source_file="file1.csv",
        raw_payload={"case_id": CASE_A},
    )
    item_vector = RetrievedItem(
        id="vector-item-1",
        modality=ModalityType.VECTOR,
        score=1.0,
        text="Vector chunk",
        source_file="file2.pdf",
        raw_payload={"case_id": CASE_A},
    )

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={
            ModalityType.STRUCTURED: [item_struct],
            ModalityType.VECTOR: [item_vector],
        },
    )
    assert len(fused) == 2
    assert fused[0].id == "struct-item-1"
    assert fused[0].rank == 1
    assert fused[0].fused_score > fused[1].fused_score


def test_cross_modality_deduplication_and_modalities_tracking(retriever: HybridRetriever):
    """
    An event retrieved by Structured, Timeline, and Vector must deduplicate
    into a single FusedItem containing all 3 modalities in its modalities list.
    """
    ev_id = "ev-shared-12345"

    struct_item = RetrievedItem(
        id=f"evidence_events:{ev_id}",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Invoice payment ₹75,000",
        source_file="bank_statement.csv",
        source_line="45",
        raw_payload={"event_id": ev_id, "amount": 75000.0, "case_id": CASE_A},
    )

    timeline_item = RetrievedItem(
        id=f"timeline:{ev_id}",
        modality=ModalityType.TIMELINE,
        score=1.0,
        text="Timeline entry: Invoice payment ₹75,000",
        source_file="bank_statement.csv",
        source_line="45",
        raw_payload={"event_id": ev_id, "case_id": CASE_A},
    )

    vector_item = RetrievedItem(
        id="chunk-vec-99",
        modality=ModalityType.VECTOR,
        score=0.88,
        text="Invoice payment ₹75,000",
        source_file="bank_statement.csv",
        raw_payload={"event_id": ev_id, "case_id": CASE_A},
    )

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={
            ModalityType.STRUCTURED: [struct_item],
            ModalityType.TIMELINE: [timeline_item],
            ModalityType.VECTOR: [vector_item],
        },
    )

    # Must be deduplicated to exactly 1 fused item
    assert len(fused) == 1
    item = fused[0]
    assert item.rank == 1
    # Modalities must list all contributing sources
    assert ModalityType.STRUCTURED in item.modalities
    assert ModalityType.TIMELINE in item.modalities
    assert ModalityType.VECTOR in item.modalities
    # Provenance fields preserved
    assert item.source_file == "bank_statement.csv"
    assert item.source_line == "45"
    assert item.raw_payload.get("amount") == 75000.0


def test_provenance_and_citations_preservation(retriever: HybridRetriever):
    """Citations and exact payloads from graph/structured candidates are preserved in FusedItem."""
    graph_item = RetrievedItem(
        id="graph_edge:PERSON:Rahul:OWNS:PHONE:+919876543210:OBSERVED",
        modality=ModalityType.GRAPH,
        score=1.0,
        text="Rahul owns Phone",
        source_file="Case Graph (Relationships)",
        raw_payload={
            "source": "PERSON:Rahul",
            "target": "PHONE:+919876543210",
            "type": "OWNS",
            "epistemic_status": "OBSERVED",
            "confidence": 1.0,
            "citations": [{"evidence_id": "EV-CDR-01", "event_id": "EVT-01"}],
            "case_id": CASE_A,
        },
    )

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={ModalityType.GRAPH: [graph_item]},
    )
    assert len(fused) == 1
    res = fused[0]
    assert res.epistemic_status == "OBSERVED"
    assert len(res.citations) == 1
    assert res.citations[0]["evidence_id"] == "EV-CDR-01"


def test_graph_inferred_preservation(retriever: HybridRetriever):
    """
    CRITICAL REQUIREMENT:
    Inferred relationships must retain epistemic_status='INFERRED' and must never
    be converted or flattened into observed facts during fusion.
    """
    inferred_edge = RetrievedItem(
        id="graph_edge:PERSON:Rahul:BENEFICIAL_OWNER:ACCOUNT:4821:INFERRED",
        modality=ModalityType.GRAPH,
        score=0.82,
        text="Inferred beneficial owner link between Rahul and Account 4821",
        source_file="Case Graph (Relationships)",
        raw_payload={
            "source": "PERSON:Rahul",
            "target": "ACCOUNT:4821",
            "type": "BENEFICIAL_OWNER",
            "epistemic_status": "INFERRED",
            "confidence": 0.82,
            "citations": [{"engine": "hidden_link_engine", "reason_codes": ["COMMON_DEVICE"]}],
            "case_id": CASE_A,
        },
    )

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={ModalityType.GRAPH: [inferred_edge]},
    )
    assert len(fused) == 1
    res = fused[0]
    assert res.epistemic_status == "INFERRED"
    assert res.raw_payload["confidence"] == 0.82
    assert "hidden_link_engine" in str(res.citations)


def test_empty_modality_handling(retriever: HybridRetriever):
    """If one or more modalities return zero items, fusion continues without error."""
    struct_item = RetrievedItem(
        id="struct-1",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Lone structured record",
        source_file="file.csv",
        raw_payload={"case_id": CASE_A},
    )

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={
            ModalityType.VECTOR: [],  # Empty
            ModalityType.GRAPH: [],   # Empty
            ModalityType.STRUCTURED: [struct_item],
            ModalityType.TIMELINE: [], # Empty
        },
    )
    assert len(fused) == 1
    assert fused[0].id == "struct-1"

    # All empty returns empty list
    fused_empty = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={
            ModalityType.VECTOR: [],
            ModalityType.GRAPH: [],
            ModalityType.STRUCTURED: [],
            ModalityType.TIMELINE: [],
        },
    )
    assert fused_empty == []


def test_candidate_limit_enforcement(retriever: HybridRetriever):
    """Candidate limit is strictly enforced."""
    items = [
        RetrievedItem(
            id=f"item-{i}",
            modality=ModalityType.VECTOR,
            score=1.0 / (i + 1),
            text=f"Text {i}",
            source_file="f.txt",
            raw_payload={"case_id": CASE_A},
        )
        for i in range(20)
    ]

    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={ModalityType.VECTOR: items},
        limit=5,
    )
    assert len(fused) == 5
    assert [f.rank for f in fused] == [1, 2, 3, 4, 5]


def test_deterministic_tie_ordering(retriever: HybridRetriever):
    """When fused scores are identical, ordering is broken deterministically by min original rank and item id."""
    # Two items with identical score contributions
    item1 = RetrievedItem(id="item-alpha", modality=ModalityType.VECTOR, score=0.9, text="Alpha", source_file="a.txt", raw_payload={"case_id": CASE_A})
    item2 = RetrievedItem(id="item-beta", modality=ModalityType.VECTOR, score=0.9, text="Beta", source_file="b.txt", raw_payload={"case_id": CASE_A})

    # In single modality, rank 1 and rank 2 have different scores, so let's cross modalities:
    # Item 1 is #1 in Vector (1.0 / 61)
    # Item 2 is #1 in Timeline (1.0 / 61)
    fused = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={
            ModalityType.VECTOR: [item1],
            ModalityType.TIMELINE: [item2],
        },
    )
    assert len(fused) == 2
    assert fused[0].fused_score == fused[1].fused_score
    # Tie broken by item ID alphabetically: "item-alpha" comes before "item-beta"
    assert fused[0].id == "item-alpha"
    assert fused[1].id == "item-beta"


def test_case_isolation_critical_regression(retriever: HybridRetriever):
    """
    CRITICAL SECURITY REGRESSION:
    If a candidate carries a case_id from Case B when querying Case A,
    it must be rejected and must NEVER leak into Case A's fused results.
    """
    item_case_a = RetrievedItem(
        id="item-case-a",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Case A Transaction ₹50,000",
        source_file="case_a.csv",
        raw_payload={"case_id": CASE_A, "amount": 50000.0},
    )

    item_case_b = RetrievedItem(
        id="item-case-b",
        modality=ModalityType.STRUCTURED,
        score=1.0,
        text="Case B Transaction ₹9,00,000",
        source_file="case_b.csv",
        raw_payload={"case_id": CASE_B, "amount": 900000.0},
    )

    # Query Case A with a list containing both
    fused_a = retriever.fuse_candidates(
        case_id=CASE_A,
        candidate_lists={ModalityType.STRUCTURED: [item_case_a, item_case_b]},
    )
    # Only Case A item must exist in results
    assert len(fused_a) == 1
    assert fused_a[0].id == "item-case-a"
    assert fused_a[0].raw_payload.get("amount") == 50000.0

    # Query Case B with a list containing both
    fused_b = retriever.fuse_candidates(
        case_id=CASE_B,
        candidate_lists={ModalityType.STRUCTURED: [item_case_a, item_case_b]},
    )
    assert len(fused_b) == 1
    assert fused_b[0].id == "item-case-b"
    assert fused_b[0].raw_payload.get("amount") == 900000.0
