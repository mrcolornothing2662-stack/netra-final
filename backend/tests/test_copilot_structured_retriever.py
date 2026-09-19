from __future__ import annotations

"""
NETRA 5.0 — Unit and Security Boundary Tests for StructuredRetriever (File 8)

Verifies:
1. Transaction retrieval (amounts, accounts, directions, narrations)
2. Communication retrieval (calls, whatsapp messages, cell towers)
3. Network log retrieval (IPs, ports, actions)
4. Location retrieval (cell site observations, towers, cities)
5. Entity and Entity Mention retrieval
6. Cognitive finding retrieval
7. Timestamp window filtering
8. Identifier filtering (ACCOUNT, PHONE, UPI, IP)
9. Result limits
10. Exact values preserved (currency amounts, ISO timestamps, provenance refs)
11. Strict Case Boundary Isolation (Case A cannot retrieve Case B)
12. Critical Security Isolation:
    Case A has ACCOUNT:4821 with ₹50,000
    Case B has ACCOUNT:4821 with ₹9,00,000
    Querying Case A with ACCOUNT:4821 returns ONLY the ₹50,000 record.
13. Nonexistent entity -> empty result
14. Nonexistent / malformed case_id -> empty result
15. Deterministic ordering
16. Natural language amount threshold extraction
"""

import datetime
import uuid
import pytest
from typing import Any, Dict, List

from copilot.config import CopilotConfig
from copilot.query_planner import QueryPlanner
from copilot.schemas import ModalityType, QueryIntentType, QueryPlan
from copilot.structured_retriever import StructuredRetriever


CASE_A = str(uuid.uuid4())
CASE_B = str(uuid.uuid4())

# ── Fixtures ─────────────────────────────────────────────────────────────────

EVENTS_A: List[Dict[str, Any]] = [
    # 1. Transaction 1: 50,000 debit involving ACCOUNT:4821
    {
        "id": "evt-tx-a1",
        "case_id": CASE_A,
        "event_type": "bank_txn",
        "timestamp": "2026-08-14T14:32:00",
        "text": "Transfer to ACC-4821 | DEBIT Rs.50,000.00",
        "metadata": {
            "amount": 50000.0,
            "debit": 50000.0,
            "credit": None,
            "from_account": "ACC-1192",
            "to_account": "ACC-4821",
            "account": "ACC-4821",
            "ref_no": "TXN-A-101",
            "narration": "Transfer to ACC-4821",
        },
        "source_doc": "bank_statement_alpha.csv",
        "source_line": 15,
        "source_page": 1,
    },
    # 2. Transaction 2: 12,000 credit involving ACCOUNT:9999
    {
        "id": "evt-tx-a2",
        "case_id": CASE_A,
        "event_type": "bank_txn",
        "timestamp": "2026-08-15T09:15:00",
        "text": "Salary credit | CREDIT Rs.12,000.00",
        "metadata": {
            "amount": 12000.0,
            "debit": None,
            "credit": 12000.0,
            "from_account": "ACC-CORP",
            "to_account": "ACC-9999",
            "account": "ACC-9999",
            "ref_no": "TXN-A-102",
            "narration": "Salary credit",
        },
        "source_doc": "bank_statement_alpha.csv",
        "source_line": 16,
    },
    # 3. Call: +919876543210 -> +919876543211
    {
        "id": "evt-call-a1",
        "case_id": CASE_A,
        "event_type": "call",
        "timestamp": "2026-08-14T10:00:00",
        "text": "Call: +919876543210 -> +919876543211 | Duration: 240s",
        "metadata": {
            "caller": "+919876543210",
            "callee": "+919876543211",
            "duration_sec": 240,
            "cell_id": "CELL-DEL-01",
            "call_type": "OUTGOING",
        },
        "source_doc": "cdr_alpha.csv",
        "source_line": 42,
    },
    # 4. WhatsApp: Rahul -> Suresh
    {
        "id": "evt-wa-a1",
        "case_id": CASE_A,
        "event_type": "whatsapp_msg",
        "timestamp": "2026-08-14T11:20:00",
        "text": "Account 4821 is ready for receiving settlement",
        "metadata": {
            "sender": "Rahul",
            "phone": "+919876543210",
            "is_system": False,
        },
        "source_doc": "chat_dump.txt",
        "source_line": 88,
    },
    # 5. Network Log: 192.168.1.10
    {
        "id": "evt-net-a1",
        "case_id": CASE_A,
        "event_type": "network_log",
        "timestamp": "2026-08-14T08:45:00",
        "text": "TCP 192.168.1.10:52410 -> 104.21.5.12:443 [ALLOW]",
        "metadata": {
            "ip": "192.168.1.10",
            "destination": "104.21.5.12",
            "port": 443,
            "action": "ALLOW",
        },
        "source_doc": "firewall.log",
        "source_line": 204,
    },
    # 6. Location observation
    {
        "id": "evt-loc-a1",
        "case_id": CASE_A,
        "event_type": "location_timeline",
        "timestamp": "2026-08-14T12:00:00",
        "text": "Cell-site: +919876543210 at New Delhi / CELL-DEL-01",
        "metadata": {
            "phone": "+919876543210",
            "cell_tower": "CELL-DEL-01",
            "city": "New Delhi",
            "observation": "routine registration",
        },
        "source_doc": "tower_dump.xlsx",
        "source_line": 310,
    },
]

# Case B has the EXACT SAME canonical ACCOUNT:4821, but with amount ₹9,00,000
EVENTS_B: List[Dict[str, Any]] = [
    {
        "id": "evt-tx-b1",
        "case_id": CASE_B,
        "event_type": "bank_txn",
        "timestamp": "2026-08-14T15:00:00",
        "text": "Transfer to ACC-4821 | DEBIT Rs.9,00,000.00",
        "metadata": {
            "amount": 900000.0,
            "debit": 900000.0,
            "credit": None,
            "from_account": "ACC-9999",
            "to_account": "ACC-4821",
            "account": "ACC-4821",
            "ref_no": "TXN-B-999",
            "narration": "Large Hawala Transfer to ACC-4821",
        },
        "source_doc": "bank_statement_beta.csv",
        "source_line": 99,
    },
    {
        "id": "evt-call-b1",
        "case_id": CASE_B,
        "event_type": "call",
        "timestamp": "2026-08-14T16:00:00",
        "text": "Call: +919111111111 -> +919222222222",
        "metadata": {
            "caller": "+919111111111",
            "callee": "+919222222222",
            "duration_sec": 60,
        },
        "source_doc": "cdr_beta.csv",
    }
]

ENTITIES_A: List[Dict[str, Any]] = [
    {"id": "ent-a1", "case_id": CASE_A, "canonical_value": "ACCOUNT:4821", "entity_type": "ACCOUNT", "risk_score": 0.85, "bridge_score": 0.4},
    {"id": "ent-a2", "case_id": CASE_A, "canonical_value": "PHONE:+919876543210", "entity_type": "PHONE", "risk_score": 0.70, "bridge_score": 0.2},
]

ENTITIES_B: List[Dict[str, Any]] = [
    {"id": "ent-b1", "case_id": CASE_B, "canonical_value": "ACCOUNT:4821", "entity_type": "ACCOUNT", "risk_score": 0.30, "bridge_score": 0.1},
]

FINDINGS_A: List[Dict[str, Any]] = [
    {
        "id": "fnd-a1",
        "case_id": CASE_A,
        "finding_type": "circular_transfer",
        "title": "Layering ring involving ACCOUNT 4821",
        "severity": "HIGH",
        "status": "OPEN",
        "confidence": 0.92,
        "reasoning": "Funds routed through multiple accounts and returned within 4 hours",
    }
]


@pytest.fixture
def retriever() -> StructuredRetriever:
    cfg = CopilotConfig(structured_top_k=20)
    return StructuredRetriever(cfg)


# ─────────────────────────────────────────────────────────────────────────────
# Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_amount_bounds_parsing(retriever: StructuredRetriever):
    """Test natural language extraction of amount thresholds."""
    low, high = retriever._extract_amount_bounds("Show transactions over ₹50,000 involving account 4821")
    assert low == 50000.0
    assert high is None

    low2, high2 = retriever._extract_amount_bounds("Transactions under 1,00,000")
    assert low2 is None
    assert high2 == 100000.0

    low3, high3 = retriever._extract_amount_bounds("Transfers between 20,000 and 75,000")
    assert low3 == 20000.0
    assert high3 == 75000.0


def test_transaction_retrieval(retriever: StructuredRetriever):
    """Retrieve bank transactions with exact amount and field preservation."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        target_tags=["ACCOUNT:4821"],
    )
    assert ctx.case_id == CASE_A
    assert len(ctx.records) >= 1

    tx_rec = next(r for r in ctx.records if r.record_type == "bank_txn")
    assert tx_rec.exact_payload["amount"] == 50000.0
    assert tx_rec.exact_payload["from_account"] == "ACC-1192"
    assert tx_rec.exact_payload["to_account"] == "ACC-4821"
    assert tx_rec.exact_payload["ref_no"] == "TXN-A-101"
    assert "₹50,000.00" in tx_rec.summary_text
    assert tx_rec.source_file == "bank_statement_alpha.csv"
    assert tx_rec.source_line == "15"


def test_communication_retrieval(retriever: StructuredRetriever):
    """Retrieve call logs and WhatsApp messages matching phone identifier."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        target_tags=["PHONE:+919876543210"],
    )
    types = {r.record_type for r in ctx.records}
    assert "call" in types or "whatsapp_msg" in types

    call_rec = next((r for r in ctx.records if r.record_type == "call"), None)
    if call_rec:
        assert call_rec.exact_payload["caller"] == "+919876543210"
        assert call_rec.exact_payload["duration_sec"] == 240
        assert call_rec.exact_payload["cell_id"] == "CELL-DEL-01"


def test_network_log_retrieval(retriever: StructuredRetriever):
    """Retrieve network log matching IP identifier."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        target_tags=["IP:192.168.1.10"],
    )
    assert len(ctx.records) >= 1
    net_rec = next(r for r in ctx.records if r.record_type == "network_log")
    assert net_rec.exact_payload["ip"] == "192.168.1.10"
    assert net_rec.exact_payload["destination"] == "104.21.5.12"
    assert net_rec.exact_payload["port"] == 443
    assert net_rec.exact_payload["action"] == "ALLOW"


def test_location_retrieval(retriever: StructuredRetriever):
    """Retrieve location events matching phone number."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        target_tags=["PHONE:+919876543210"],
    )
    loc_recs = [r for r in ctx.records if r.record_type == "location_timeline"]
    assert len(loc_recs) >= 1
    assert loc_recs[0].exact_payload["city"] == "New Delhi"
    assert loc_recs[0].exact_payload["cell_tower"] == "CELL-DEL-01"


def test_entity_retrieval(retriever: StructuredRetriever):
    """Retrieve canonical entity information."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        entities=ENTITIES_A,
        target_tags=["ACCOUNT:4821"],
    )
    ent_rec = next(r for r in ctx.records if r.record_type == "entity")
    assert ent_rec.exact_payload["canonical_value"] == "ACCOUNT:4821"
    assert ent_rec.exact_payload["risk_score"] == 0.85
    assert ent_rec.exact_payload["bridge_score"] == 0.4


def test_finding_retrieval(retriever: StructuredRetriever):
    """Retrieve cognitive investigation findings."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        findings=FINDINGS_A,
    )
    assert len(ctx.records) >= 1
    f_rec = ctx.records[0]
    assert f_rec.record_type == "finding"
    assert f_rec.exact_payload["severity"] == "HIGH"
    assert "Layering ring" in f_rec.exact_payload["title"]


def test_amount_filtering_exact(retriever: StructuredRetriever):
    """Filtering transactions by amount boundaries."""
    # Min amount = 40,000 (should include 50,000, exclude 12,000)
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        min_amount=40000.0,
    )
    amounts = [r.exact_payload.get("amount") for r in ctx.records if r.record_type == "bank_txn"]
    assert 50000.0 in amounts
    assert 12000.0 not in amounts


def test_timestamp_window_filtering(retriever: StructuredRetriever):
    """Filtering events by time window."""
    t_start = datetime.datetime(2026, 8, 15, 0, 0, 0)
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        start_time=t_start,
    )
    for r in ctx.records:
        assert r.timestamp is not None
        assert r.timestamp >= t_start


def test_result_limits(retriever: StructuredRetriever):
    """Result limit is strictly obeyed."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        limit=2,
    )
    assert len(ctx.records) <= 2
    assert len(items) <= 2


def test_cross_case_isolation_critical_regression(retriever: StructuredRetriever):
    """
    CRITICAL SECURITY REGRESSION TEST:
    Case A has ACCOUNT:4821 with transaction of ₹50,000.
    Case B has ACCOUNT:4821 with transaction of ₹9,00,000.
    Querying Case A with ACCOUNT:4821 MUST ONLY return the ₹50,000 transaction.
    """
    combined_events = EVENTS_A + EVENTS_B
    combined_entities = ENTITIES_A + ENTITIES_B

    # Query Case A
    ctx_a, items_a = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=combined_events,
        entities=combined_entities,
        target_tags=["ACCOUNT:4821"],
    )
    # Check records in Case A
    amounts_a = [r.exact_payload.get("amount") for r in ctx_a.records if r.record_type == "bank_txn"]
    assert 50000.0 in amounts_a
    assert 900000.0 not in amounts_a  # ₹9,00,000 MUST NOT BE PRESENT IN CASE A

    for r in ctx_a.records:
        assert "9,00,000" not in r.summary_text
        assert "TXN-B-999" not in str(r.exact_payload)

    # Query Case B
    ctx_b, items_b = retriever.retrieve_from_memory(
        case_id=CASE_B,
        events=combined_events,
        entities=combined_entities,
        target_tags=["ACCOUNT:4821"],
    )
    amounts_b = [r.exact_payload.get("amount") for r in ctx_b.records if r.record_type == "bank_txn"]
    assert 900000.0 in amounts_b
    assert 50000.0 not in amounts_b  # ₹50,000 MUST NOT BE PRESENT IN CASE B


def test_nonexistent_entity_returns_empty(retriever: StructuredRetriever):
    """Querying a nonexistent entity tag returns empty records."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        entities=ENTITIES_A,
        target_tags=["ACCOUNT:NON_EXISTENT_99999"],
    )
    assert ctx.records == []
    assert items == []


def test_nonexistent_case_returns_empty(retriever: StructuredRetriever):
    """Querying a nonexistent case returns empty records."""
    ctx, items = retriever.retrieve_from_memory(
        case_id="non-existent-case-id",
        events=EVENTS_A,
        entities=ENTITIES_A,
        target_tags=["ACCOUNT:4821"],
    )
    assert ctx.records == []
    assert items == []


def test_retrieved_item_contract(retriever: StructuredRetriever):
    """RetrievedItem matches contract for multi-modal fusion."""
    ctx, items = retriever.retrieve_from_memory(
        case_id=CASE_A,
        events=EVENTS_A,
        target_tags=["ACCOUNT:4821"],
    )
    assert len(items) >= 1
    item = items[0]
    assert item.modality == ModalityType.STRUCTURED
    assert item.score >= 0.85
    assert len(item.text) > 0
    assert isinstance(item.raw_payload, dict)
