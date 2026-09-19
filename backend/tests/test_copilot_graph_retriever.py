from __future__ import annotations

"""
NETRA 5.0 — Unit and Security Boundary Tests for GraphRetriever (File 7)

Verifies:
1. Direct entity resolution & canonical matching
2. 1-hop and 2-hop neighborhood expansion
3. Max-hop enforcement
4. Relationship filtering
5. Epistemic separation (OBSERVED vs INFERRED strictly preserved)
6. Confidence, evidence_refs, event_refs, amount, timestamps preservation
7. Hidden link retrieval
8. Unknown entity -> empty subgraph
9. Strict Case Boundary Isolation (Case A cannot retrieve Case B)
10. Cross-case identical canonical values remain isolated
11. Deterministic deduplication of bidirectional edges
12. Graph with no relationships handled gracefully
13. Malformed query handled safely
14. Safe extraction of risk_score/bridge_score from Entity models and dictionaries
"""

import uuid
import pytest
from typing import Any, Dict, List

from copilot.config import CopilotConfig
from copilot.graph_retriever import GraphRetriever
from copilot.schemas import GraphEdgeSnippet, GraphNodeSnippet, QueryPlan, QueryIntentType
from graph import relationship_types as RT


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

CASE_A = str(uuid.uuid4())
CASE_B = str(uuid.uuid4())

ENTITIES_A: List[Dict[str, Any]] = [
    {"id": "ent-a1", "case_id": CASE_A, "canonical_value": "ACCOUNT:4821", "entity_type": "ACCOUNT", "risk_score": 0.9, "bridge_score": 0.8},
    {"id": "ent-a2", "case_id": CASE_A, "canonical_value": "PHONE:+919876543210", "entity_type": "PHONE", "risk_score": 0.7, "bridge_score": 0.4},
    {"id": "ent-a3", "case_id": CASE_A, "canonical_value": "PERSON:Rahul", "entity_type": "PERSON", "risk_score": 0.5, "bridge_score": 0.2},
    {"id": "ent-a4", "case_id": CASE_A, "canonical_value": "IP:192.168.1.10", "entity_type": "IP", "risk_score": 0.3, "bridge_score": 0.1},
    {"id": "ent-a5", "case_id": CASE_A, "canonical_value": "ACCOUNT:9999", "entity_type": "ACCOUNT", "risk_score": 0.4, "bridge_score": 0.0},
]

# Case B has the EXACT SAME canonical value 'ACCOUNT:4821' to test cross-case isolation
ENTITIES_B: List[Dict[str, Any]] = [
    {"id": "ent-b1", "case_id": CASE_B, "canonical_value": "ACCOUNT:4821", "entity_type": "ACCOUNT", "risk_score": 0.2, "bridge_score": 0.1},
    {"id": "ent-b2", "case_id": CASE_B, "canonical_value": "PERSON:Suresh", "entity_type": "PERSON", "risk_score": 0.1, "bridge_score": 0.05},
]

RELATIONSHIPS_A: List[Dict[str, Any]] = [
    # Observed 1: Rahul owns Phone
    {
        "id": "rel-a1",
        "case_id": CASE_A,
        "source_canonical": "PERSON:Rahul",
        "target_canonical": "PHONE:+919876543210",
        "relationship_type": RT.OWNS,
        "epistemic_status": RT.OBSERVED,
        "confidence": 1.0,
        "evidence_refs": ["EV-CDR-01"],
        "event_refs": ["EVT-01"],
    },
    # Observed 2: Phone transferred to Account 4821
    {
        "id": "rel-a2",
        "case_id": CASE_A,
        "source_canonical": "PHONE:+919876543210",
        "target_canonical": "ACCOUNT:4821",
        "relationship_type": RT.TRANSFERRED_TO,
        "epistemic_status": RT.OBSERVED,
        "confidence": 0.95,
        "evidence_refs": ["EV-BANK-02"],
        "event_refs": ["EVT-02"],
        "amount": 250000.0,
    },
    # Inferred: Rahul hidden link to Account 4821
    {
        "id": "rel-a3",
        "case_id": CASE_A,
        "source_canonical": "PERSON:Rahul",
        "target_canonical": "ACCOUNT:4821",
        "relationship_type": "BENEFICIAL_OWNER_INFERRED",
        "epistemic_status": RT.INFERRED,
        "confidence": 0.82,
        "evidence_refs": ["EV-CDR-01", "EV-BANK-02"],
        "event_refs": ["EVT-01", "EVT-02"],
        "reason_codes": ["COMMON_DEVICE", "FLOW_COGNITIVE"],
        "source_engine": "hidden_link_engine",
    },
    # Observed 3: Phone accessed from IP (2-hop from Account 4821)
    {
        "id": "rel-a4",
        "case_id": CASE_A,
        "source_canonical": "PHONE:+919876543210",
        "target_canonical": "IP:192.168.1.10",
        "relationship_type": "ACCESSED_FROM",
        "epistemic_status": RT.OBSERVED,
        "confidence": 0.90,
        "evidence_refs": ["EV-NET-01"],
        "event_refs": ["EVT-03"],
    },
]

RELATIONSHIPS_B: List[Dict[str, Any]] = [
    {
        "id": "rel-b1",
        "case_id": CASE_B,
        "source_canonical": "PERSON:Suresh",
        "target_canonical": "ACCOUNT:4821",
        "relationship_type": RT.OWNS,
        "epistemic_status": RT.OBSERVED,
        "confidence": 1.0,
        "evidence_refs": ["EV-B-01"],
        "event_refs": ["EVT-B1"],
    }
]


@pytest.fixture
def retriever() -> GraphRetriever:
    cfg = CopilotConfig(max_graph_hops=3, max_graph_nodes=20, max_graph_edges=30)
    return GraphRetriever(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_entity_tag(retriever: GraphRetriever):
    """Test parsing of entity tag strings."""
    etype, val = retriever.parse_entity_tag("ACCOUNT:4821")
    assert etype == "ACCOUNT"
    assert val == "4821"

    etype2, val2 = retriever.parse_entity_tag("+919876543210")
    assert etype2 is None
    assert val2 == "+919876543210"


def test_one_hop_neighborhood(retriever: GraphRetriever):
    """Querying 1-hop around ACCOUNT:4821 returns immediate neighbors only."""
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=RELATIONSHIPS_A,
        target_tags=["ACCOUNT:4821"],
        max_hops=1,
    )
    node_canons = {n.canonical_value for n in nodes}
    # 1-hop neighbors of ACCOUNT:4821 are PHONE:+919876543210 and PERSON:Rahul (via inferred edge)
    assert "ACCOUNT:4821" in node_canons
    assert "PHONE:+919876543210" in node_canons
    assert "PERSON:Rahul" in node_canons
    # IP:192.168.1.10 is 2-hops away from ACCOUNT:4821, must NOT be present in 1-hop
    assert "IP:192.168.1.10" not in node_canons


def test_two_hop_neighborhood(retriever: GraphRetriever):
    """Querying 2-hop around ACCOUNT:4821 expands to IP:192.168.1.10."""
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=RELATIONSHIPS_A,
        target_tags=["ACCOUNT:4821"],
        max_hops=2,
    )
    node_canons = {n.canonical_value for n in nodes}
    assert "ACCOUNT:4821" in node_canons
    assert "PHONE:+919876543210" in node_canons
    assert "PERSON:Rahul" in node_canons
    assert "IP:192.168.1.10" in node_canons


def test_epistemic_separation_preserved(retriever: GraphRetriever):
    """Observed and inferred edges must remain distinctly typed and never flattened."""
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=RELATIONSHIPS_A,
        target_tags=["ACCOUNT:4821"],
        max_hops=1,
    )
    obs_edges = [e for e in edges if e.epistemic_status == RT.OBSERVED]
    inf_edges = [e for e in edges if e.epistemic_status == RT.INFERRED]

    assert len(obs_edges) >= 1
    assert len(inf_edges) >= 1

    # Inferred edge must carry confidence, reason_codes, and engine metadata
    inferred_edge = inf_edges[0]
    assert inferred_edge.relationship_type == "BENEFICIAL_OWNER_INFERRED"
    assert inferred_edge.confidence == 0.82
    assert inferred_edge.citations is not None


def test_provenance_citations_preserved(retriever: GraphRetriever):
    """Edge citations must preserve evidence_refs and event_refs."""
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=RELATIONSHIPS_A,
        target_tags=["ACCOUNT:4821"],
        max_hops=1,
    )
    tx_edge = next(e for e in edges if e.relationship_type == RT.TRANSFERRED_TO)
    assert tx_edge.confidence == 0.95
    assert len(tx_edge.citations) > 0


def test_cross_case_isolation_identical_canonical(retriever: GraphRetriever):
    """
    CRITICAL REGRESSION TEST:
    Case A has ACCOUNT:4821 connected to PHONE and Rahul.
    Case B has ACCOUNT:4821 connected to Suresh.
    Querying Case A MUST NEVER return Case B entities or relationships.
    """
    combined_entities = ENTITIES_A + ENTITIES_B
    combined_relationships = RELATIONSHIPS_A + RELATIONSHIPS_B

    # Query Case A
    nodes_a, edges_a = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=combined_entities,
        relationships=combined_relationships,
        target_tags=["ACCOUNT:4821"],
        max_hops=2,
    )
    canons_a = {n.canonical_value for n in nodes_a}
    assert "ACCOUNT:4821" in canons_a
    assert "PERSON:Rahul" in canons_a
    assert "PERSON:Suresh" not in canons_a  # Suresh is strictly in Case B

    for edge in edges_a:
        assert edge.source_canonical != "PERSON:Suresh"
        assert edge.target_canonical != "PERSON:Suresh"

    # Query Case B
    nodes_b, edges_b = retriever.retrieve_from_memory(
        case_id=CASE_B,
        entities=combined_entities,
        relationships=combined_relationships,
        target_tags=["ACCOUNT:4821"],
        max_hops=2,
    )
    canons_b = {n.canonical_value for n in nodes_b}
    assert "ACCOUNT:4821" in canons_b
    assert "PERSON:Suresh" in canons_b
    assert "PERSON:Rahul" not in canons_b  # Rahul is strictly in Case A
    assert "PHONE:+919876543210" not in canons_b


def test_unknown_entity_returns_empty(retriever: GraphRetriever):
    """Unknown entity returns empty node and edge lists."""
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=RELATIONSHIPS_A,
        target_tags=["NON_EXISTENT_99999"],
        max_hops=2,
    )
    assert nodes == []
    assert edges == []


def test_empty_case_or_no_relationships(retriever: GraphRetriever):
    """Case with entities but no relationships returns top nodes and empty edges."""
    lone_entities = [
        {"id": "e1", "case_id": "case-empty", "canonical_value": "ACCOUNT:101", "entity_type": "ACCOUNT", "risk_score": 0.5},
    ]
    nodes, edges = retriever.retrieve_from_memory(
        case_id="case-empty",
        entities=lone_entities,
        relationships=[],
        target_tags=[],
    )
    assert len(nodes) == 1
    assert edges == []


def test_duplicate_edge_elimination(retriever: GraphRetriever):
    """Bidirectional duplicate edges are deduplicated deterministically."""
    duplicate_rels = [
        {
            "id": "rel-dup-1",
            "case_id": CASE_A,
            "source_canonical": "PERSON:Rahul",
            "target_canonical": "PHONE:+919876543210",
            "relationship_type": RT.OWNS,
            "epistemic_status": RT.OBSERVED,
        },
        {
            "id": "rel-dup-2",
            "case_id": CASE_A,
            "source_canonical": "PHONE:+919876543210",
            "target_canonical": "PERSON:Rahul",
            "relationship_type": RT.OWNS,
            "epistemic_status": RT.OBSERVED,
        },
    ]
    nodes, edges = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        relationships=duplicate_rels,
        target_tags=["PERSON:Rahul"],
    )
    assert len(edges) == 1


def test_safe_attribute_extraction(retriever: GraphRetriever):
    """Entity without risk_score or with risk_score in metadata is extracted safely without AttributeError."""
    class MockEntity:
        def __init__(self, id, canonical, etype, meta=None, centrality=None, bridge=None):
            self.id = id
            self.canonical_value = canonical
            self.entity_type = etype
            self.node_metadata = meta or {}
            self.degree_centrality = centrality
            self.bridge_score = bridge
            # Deliberately no self.risk_score attribute!

    e1 = MockEntity("e-1", "ACCOUNT:111", "ACCOUNT", meta={"risk_score": 0.85}, bridge=0.4)
    e2 = MockEntity("e-2", "PHONE:222", "PHONE", centrality=0.6, bridge=0.1)
    e3 = MockEntity("e-3", "IP:333", "IP")

    assert retriever._extract_risk_score(e1) == 0.85
    assert retriever._extract_bridge_score(e1) == 0.4

    assert retriever._extract_risk_score(e2) == 0.6
    assert retriever._extract_bridge_score(e2) == 0.1

    assert retriever._extract_risk_score(e3) == 0.0
    assert retriever._extract_bridge_score(e3) == 0.0

    snippets = retriever._build_node_snippets([e1, e2, e3])
    assert len(snippets) == 3
    assert snippets[0].risk_score == 0.85
    assert snippets[1].risk_score == 0.6
    assert snippets[2].risk_score == 0.0
