"""
File 07 — 07_upi_transaction_report.pdf — Dedicated Parser & Extraction Tests

Verifies:
  1. bank_pdf_parser detects transfer tables and identifier/alias tables
  2. Alias resolution: UPI-001 → arjun@upi, UPI-002 → rohan@upi
  3. ZapfDingbats glyph: n48,500 → 48500.0
  4. Events are bank_txn with correct transfer metadata shape
  5. TXN_RE matches UPI-TXN-001 in full (not truncated to TXN-001)
  6. Entity validation rejects table header noise (PER, KEYWORD)
  7. Existing bank statement PDFs are not broken
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def file_07_pdf_path(tmp_path):
    """Extract File 07 from the synthetic case zip to a temp file."""
    import zipfile
    zip_path = Path(__file__).resolve().parent / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip"
    if not zip_path.exists():
        zip_path = Path.home() / "Downloads" / "NETRA_Operation_Meridian_Synthetic_Case.zip"
    if not zip_path.exists():
        pytest.skip("Synthetic case zip not found")
    with zipfile.ZipFile(zip_path, "r") as z:
        pdf_bytes = z.read("documents/07_upi_transaction_report.pdf")
    out = tmp_path / "07_upi_transaction_report.pdf"
    out.write_bytes(pdf_bytes)
    return out


# ── Layer 1: bank_pdf_parser transfer schema ──────────────────────────────────

class TestBankPdfParserTransfer:

    def test_parse_bank_pdf_returns_3_transfer_events(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        assert len(events) == 3, f"Expected 3 events, got {len(events)}"
        for ev in events:
            assert ev["event_type"] == "bank_txn"
            assert ev["metadata"]["model"] == "transfer"

    def test_alias_resolution_upi_001_to_arjun(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        ev1 = events[0]
        assert ev1["metadata"]["from_account"] == "arjun@upi"
        assert ev1["metadata"]["to_account"] == "rohan@upi"
        assert ev1["metadata"]["from_alias"] == "UPI-001"
        assert ev1["metadata"]["to_alias"] == "UPI-002"

    def test_alias_resolution_mixed_with_acc(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        ev2 = events[1]
        assert ev2["metadata"]["from_account"] == "rohan@upi"
        assert ev2["metadata"]["to_account"] == "ACC-003"
        assert ev2["metadata"]["from_alias"] == "UPI-002"
        assert ev2["metadata"]["to_alias"] is None

    def test_glyph_amount_n48500_parsed(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        amounts = [ev["metadata"]["amount"] for ev in events]
        assert amounts == [48500.0, 47000.0, 18750.0]

    def test_timestamps_preserved(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        timestamps = [ev["timestamp"] for ev in events]
        assert timestamps[0] == "2026-08-21T10:14:00"
        assert timestamps[1] == "2026-08-21T10:31:00"
        assert timestamps[2] == "2026-08-23T16:20:00"

    def test_ref_no_preserved(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        refs = [ev["metadata"]["ref_no"] for ev in events]
        assert refs == ["UPI-TXN-001", "UPI-TXN-002", "UPI-TXN-004"]

    def test_status_preserved(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        for ev in events:
            assert ev["metadata"]["status"] == "SUCCESS"

    def test_metadata_has_transfer_keys_for_relationship_engine(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        events = parse_bank_pdf(file_07_pdf_path)
        required_keys = {"from_account", "to_account", "amount", "ref_no", "status"}
        for ev in events:
            meta_keys = set(ev["metadata"].keys())
            assert required_keys.issubset(meta_keys), f"Missing keys: {required_keys - meta_keys}"


class TestBankPdfParserHelpers:

    def test_is_identifier_table(self):
        from parsers.bank_pdf_parser import _is_identifier_table
        assert _is_identifier_table(["Field", "Value"]) is True
        assert _is_identifier_table(["field", "value"]) is True
        assert _is_identifier_table(["Date", "Amount"]) is False
        assert _is_identifier_table(["A", "B", "C"]) is False

    def test_build_alias_map(self):
        from parsers.bank_pdf_parser import _build_alias_map
        table = [
            ["Field", "Value"],
            ["UPI-001", "arjun@upi"],
            ["UPI-002", "rohan@upi"],
        ]
        aliases = _build_alias_map(table)
        assert aliases == {"UPI-001": "arjun@upi", "UPI-002": "rohan@upi"}

    def test_parse_transfer_amount_glyph(self):
        from parsers.bank_pdf_parser import _parse_transfer_amount
        assert _parse_transfer_amount("n48,500") == 48500.0
        assert _parse_transfer_amount("n47,000") == 47000.0
        assert _parse_transfer_amount("n18,750") == 18750.0
        assert _parse_transfer_amount("") is None
        assert _parse_transfer_amount("-") is None

    def test_is_transfer_table_with_payer_payee(self):
        from parsers.bank_pdf_parser import _map_transfer_columns, _is_transfer_table
        col_map = _map_transfer_columns(["Time", "Reference", "Payer", "Payee", "Amount", "Status"])
        assert _is_transfer_table(col_map) is True
        assert col_map["from_account"] == "Payer"
        assert col_map["to_account"] == "Payee"
        assert col_map["amount"] == "Amount"
        assert col_map["date"] == "Time"

    def test_is_transfer_table_rejects_field_value(self):
        from parsers.bank_pdf_parser import _map_transfer_columns, _is_transfer_table
        col_map = _map_transfer_columns(["Field", "Value"])
        assert _is_transfer_table(col_map) is False

    def test_ledger_table_still_detected(self):
        from parsers.bank_pdf_parser import _map_columns, _is_bank_statement_table
        col_map = _map_columns(["Date", "Narration", "Debit", "Credit", "Balance"])
        assert _is_bank_statement_table(col_map) is True


# ── Layer 2: TXN_RE ──────────────────────────────────────────────────────────

class TestTxnRegex:

    def test_upi_txn_001_full_match(self):
        from correlation.regex_extractors import TXN_RE
        m = TXN_RE.search("UPI-TXN-001")
        assert m is not None
        assert m.group() == "UPI-TXN-001"

    def test_upi_txn_in_context(self):
        from correlation.regex_extractors import TXN_RE
        line = "2026-08-21 10:14 UPI-TXN-001 UPI-001 UPI-002 n48,500 SUCCESS"
        m = TXN_RE.search(line)
        assert m is not None
        assert m.group() == "UPI-TXN-001"

    def test_plain_txn_still_works(self):
        from correlation.regex_extractors import TXN_RE
        assert TXN_RE.search("TXN-005").group() == "TXN-005"
        assert TXN_RE.search("TX-01").group() == "TX-01"


# ── Layer 3: Entity validation ────────────────────────────────────────────────

class TestEntityValidationFile07:

    def test_table_header_rejected_as_person(self):
        from nlp.entity_validation import validate_entity_candidate
        bad_persons = ["Time Reference", "Payer Payee", "Amount Status"]
        for val in bad_persons:
            assert validate_entity_candidate("PERSON", val) is False, f"PERSON:{val} should be rejected"
            assert validate_entity_candidate("PER", val) is False, f"PER:{val} should be rejected"

    def test_status_values_rejected_as_keyword(self):
        from nlp.entity_validation import validate_entity_candidate
        for val in ["SUCCESS", "FAILED", "PENDING", "COMPLETED"]:
            assert validate_entity_candidate("KEYWORD", val) is False, f"KEYWORD:{val} should be rejected"

    def test_valid_upi_entities_pass(self):
        from nlp.entity_validation import validate_entity_candidate
        assert validate_entity_candidate("UPI", "arjun@upi") is True
        assert validate_entity_candidate("UPI", "rohan@upi") is True

    def test_valid_account_entities_pass(self):
        from nlp.entity_validation import validate_entity_candidate
        assert validate_entity_candidate("ACCOUNT", "ACC-003") is True
        assert validate_entity_candidate("ACCOUNT", "ACC-001") is True

    def test_valid_transaction_entities_pass(self):
        from nlp.entity_validation import validate_entity_candidate
        assert validate_entity_candidate("TRANSACTION", "UPI-TXN-001") is True
        assert validate_entity_candidate("TRANSACTION", "UPI-TXN-002") is True


# ── Layer 4: Classification and routing ───────────────────────────────────────

class TestClassificationFile07:

    def test_classify_and_route_file_07(self, file_07_pdf_path):
        from routes.evidence import _classify_and_route_file
        file_type, source_type = _classify_and_route_file(file_07_pdf_path)
        assert file_type == "pdf"
        assert source_type == "bank_statement"


# ── Full Pipeline: Relationships derived from File 07 ─────────────────────────

class TestRelationshipsFile07:

    def test_transferred_to_relationships_derived(self, file_07_pdf_path):
        from parsers.bank_pdf_parser import parse_bank_pdf
        from ml.inference import run_hybrid_extraction
        from nlp.entity_validation import validate_entity_candidate
        from graph.relationships import derive_observed_relationships
        from graph import relationship_types as RT

        events = parse_bank_pdf(file_07_pdf_path)
        assert len(events) == 3

        for idx, ev in enumerate(events):
            ev["id"] = f"ev-{idx+1}"
            res = run_hybrid_extraction(ev["text"])
            mentions = []
            for m in res.mentions:
                if validate_entity_candidate(m.entity_type, m.raw_value):
                    mentions.append({
                        "canonical_value": m.canonical_value,
                        "entity_type": m.entity_type,
                        "raw_value": m.raw_value,
                    })
            ev["entity_mentions"] = mentions

        drafts = derive_observed_relationships(events)
        transfers = [d for d in drafts if d.relationship_type == RT.TRANSFERRED_TO]
        assert len(transfers) == 3

        # Transfer 1: arjun@upi -> rohan@upi (48,500)
        t1 = next(t for t in transfers if t.source_value == "arjun@upi")
        assert t1.target_value == "rohan@upi"
        assert t1.amount == 48500.0
        assert t1.attributes["ref_no"] == "UPI-TXN-001"
        assert t1.attributes["status"] == "SUCCESS"
        assert t1.timestamp is not None
        assert t1.timestamp.year == 2026

        # Transfer 2: rohan@upi -> ACC-003 (47,000)
        t2 = next(t for t in transfers if t.source_value == "rohan@upi")
        assert t2.target_value == "ACC-003"
        assert t2.amount == 47000.0
        assert t2.attributes["ref_no"] == "UPI-TXN-002"
        assert t2.attributes["status"] == "SUCCESS"

        # Transfer 3: ACC-001 -> rohan@upi (18,750)
        t3 = next(t for t in transfers if t.source_value == "ACC-001")
        assert t3.target_value == "rohan@upi"
        assert t3.amount == 18750.0
        assert t3.attributes["ref_no"] == "UPI-TXN-004"
        assert t3.attributes["status"] == "SUCCESS"

