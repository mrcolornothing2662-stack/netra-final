from __future__ import annotations
"""
Unit and integration tests for File 10: 10_evidence_seizure_memo.pdf.

Verifies:
  1. File 10 classification: ("pdf", "seizure_memo")
  2. File 10 is NOT classified as device_extraction.
  3. Dedicated parser returns exactly 5 inventory records.
  4. All five EVD IDs are preserved exactly.
  5. Item/source/condition fields are preserved exactly.
  6. Collector is preserved.
  7. Collection date 2026-08-23 is preserved.
  8. Integrity hash is preserved as synthetic source metadata and not emitted as a normal KEYWORD entity.
  9. Purpose is preserved.
  10. No preamble/footer becomes an event.
  11. No DEVICE-001 from EVD-DEVICE-001.
  12. No CHAT-001 from EVD-CHAT-001.
  13. EVD-BANK-001 does not become BANK.
  14. Table header combinations do not become PERSON.
  15. CSV/TXT do not become KEYWORD noise.
  16. No bogus CO_OCCURRENCE relationships are generated.
  17. Provenance is preserved for each inventory row.
  18. Regression: File 06 is still device_extraction, File 09 is location_timeline.
  19. Standalone DEVICE-001 and CHAT-001 match cleanly.
"""
import pathlib
import tempfile
import zipfile

import pytest

from correlation.regex_extractors import extract, DEVICE_RE, CHAT_RE
from graph.relationships import derive_observed_relationships
from nlp.entity_validation import validate_entity_candidate
from parsers.seizure_memo_parser import parse_seizure_memo, is_seizure_memo_header
from routes.evidence import _classify_and_route_file

from pathlib import Path
ZIP_PATH = str(Path(__file__).resolve().parent / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip")


@pytest.fixture(scope="module")
def file10_pdf_path() -> str:
    """Extract File 10 from synthetic case zip to a temporary file for testing."""
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        content = zf.read("documents/10_evidence_seizure_memo.pdf")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        return tmp.name


@pytest.fixture(scope="module")
def file06_pdf_path() -> str:
    """Extract File 06 from synthetic case zip for regression testing."""
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        content = zf.read("documents/06_device_extraction.pdf")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        return tmp.name


# ── 1 & 2. Classification ─────────────────────────────────────────────────────

def test_file10_classification(file10_pdf_path: str):
    """File 10 must classify as ('pdf', 'seizure_memo')."""
    ftype, stype = _classify_and_route_file(pathlib.Path(file10_pdf_path))
    assert ftype == "pdf"
    assert stype == "seizure_memo"


def test_file10_not_device_extraction(file10_pdf_path: str):
    """File 10 must NOT be classified as device_extraction despite having 'Device extraction' in table."""
    _, stype = _classify_and_route_file(pathlib.Path(file10_pdf_path))
    assert stype != "device_extraction"


def test_is_seizure_memo_header():
    """Header matcher identifies the seizure memo table schema."""
    header = ["Evidence ID", "Item", "Source", "Condition"]
    assert is_seizure_memo_header(header) is True
    assert is_seizure_memo_header(["Col1", "Col2"]) is False


# ── 3, 4, 5. Dedicated Parser & Inventory Records ─────────────────────────────

def test_parser_returns_exactly_five_records(file10_pdf_path: str):
    """Dedicated parser returns exactly 5 inventory records."""
    events = parse_seizure_memo(file10_pdf_path)
    assert len(events) == 5
    for evt in events:
        assert evt["event_type"] == "seizure_memo"


def test_all_five_evd_ids_preserved(file10_pdf_path: str):
    """All five EVD-* IDs are preserved exactly in order."""
    events = parse_seizure_memo(file10_pdf_path)
    evd_ids = [e["metadata"]["evidence_id"] for e in events]
    assert evd_ids == [
        "EVD-BANK-001",
        "EVD-CALL-001",
        "EVD-DEVICE-001",
        "EVD-CHAT-001",
        "EVD-NET-001",
    ]


def test_item_source_condition_preserved(file10_pdf_path: str):
    """Item, source, and condition fields are extracted with exact values."""
    events = parse_seizure_memo(file10_pdf_path)
    expected = [
        ("EVD-BANK-001", "Bank statement", "Financial records repository", "Digital copy"),
        ("EVD-CALL-001", "Call detail record", "Telecom records repository", "CSV export"),
        ("EVD-DEVICE-001", "Device extraction", "Forensic workstation", "Digital extraction"),
        ("EVD-CHAT-001", "Chat export", "Device extraction", "TXT export"),
        ("EVD-NET-001", "Network log", "Network monitoring export", "CSV export"),
    ]
    for evt, (exp_id, exp_item, exp_source, exp_cond) in zip(events, expected):
        meta = evt["metadata"]
        assert meta["evidence_id"] == exp_id
        assert meta["item"] == exp_item
        assert meta["source"] == exp_source
        assert meta["condition"] == exp_cond


# ── 6, 7, 8, 9, 10. Custody Metadata & No Preamble/Footer Events ──────────────

def test_collector_preserved(file10_pdf_path: str):
    """Collector 'Synthetic Test Operator' is preserved on every record."""
    events = parse_seizure_memo(file10_pdf_path)
    for evt in events:
        assert evt["metadata"]["collector"] == "Synthetic Test Operator"


def test_collection_date_preserved(file10_pdf_path: str):
    """Collection date 2026-08-23 is preserved without inventing a clock time."""
    events = parse_seizure_memo(file10_pdf_path)
    for evt in events:
        assert evt["timestamp"] == "2026-08-23"
        assert evt["metadata"]["collection_date"] == "2026-08-23"


def test_integrity_hash_preserved_and_not_keyword(file10_pdf_path: str):
    """Integrity hash is preserved as source metadata and blocked as a KEYWORD entity."""
    events = parse_seizure_memo(file10_pdf_path)
    for evt in events:
        assert evt["metadata"]["integrity_hash"] == "TEST-HASH-DO-NOT-TREAT-AS-REAL"

    assert validate_entity_candidate("KEYWORD", "TEST-HASH-DO-NOT-TREAT-AS-REAL") is False
    assert validate_entity_candidate("PER", "TEST-HASH-DO-NOT-TREAT-AS-REAL") is False


def test_purpose_preserved(file10_pdf_path: str):
    """Purpose 'NETRA parser and provenance testing.' is preserved in metadata."""
    events = parse_seizure_memo(file10_pdf_path)
    for evt in events:
        assert evt["metadata"]["purpose"] == "NETRA parser and provenance testing."


def test_no_preamble_or_footer_events(file10_pdf_path: str):
    """Only tabular rows produce events; titles, headers, and footer blocks do not."""
    events = parse_seizure_memo(file10_pdf_path)
    assert len(events) == 5
    for evt in events:
        assert "EVIDENCE SEIZURE" not in evt["text"]
        assert "Collector:" not in evt["text"]


# ── 11, 12, 13. Substring Bleed & Evidence ID Isolation ───────────────────────

def test_no_device_from_evd_device():
    """DEVICE regex and extract() must NOT emit DEVICE-001 from EVD-DEVICE-001."""
    extractions = list(extract("EVD-DEVICE-001"))
    assert not any(e.norm_value == "DEVICE-001" for e in extractions)
    assert not any(e.entity_type == "DEVICE" for e in extractions)
    assert DEVICE_RE.search("EVD-DEVICE-001") is None


def test_no_chat_from_evd_chat():
    """CHAT regex and extract() must NOT emit CHAT-001 from EVD-CHAT-001."""
    extractions = list(extract("EVD-CHAT-001"))
    assert not any(e.norm_value == "CHAT-001" for e in extractions)
    assert not any(e.entity_type == "CHAT" for e in extractions)
    assert CHAT_RE.search("EVD-CHAT-001") is None


def test_standalone_device_and_chat_still_match():
    """Legitimate standalone DEVICE-001 and CHAT-001 still match cleanly."""
    dev_ext = list(extract("DEVICE-001"))
    assert any(e.entity_type == "DEVICE" and e.norm_value == "DEVICE-001" for e in dev_ext)

    chat_ext = list(extract("CHAT-001"))
    assert any(e.entity_type == "CHAT" and e.norm_value == "CHAT-001" for e in chat_ext)


def test_evd_bank_does_not_become_bank():
    """EVD-BANK-001 and Bank statement are rejected by BANK validation."""
    assert validate_entity_candidate("BANK", "EVD-BANK-001") is False
    assert validate_entity_candidate("BANK", "Bank statement") is False
    assert validate_entity_candidate("BANK", "EVD-BANK-001 Bank") is False


def test_all_evd_ids_rejected_as_entities():
    """All EVD-* inventory IDs are rejected as entities across all entity types."""
    for eid in ["EVD-BANK-001", "EVD-CALL-001", "EVD-DEVICE-001", "EVD-CHAT-001", "EVD-NET-001"]:
        for etype in ["BANK", "PER", "DEVICE", "PHONE", "CHAT", "KEYWORD", "ACCOUNT"]:
            assert validate_entity_candidate(etype, eid) is False


# ── 14, 15. Validation Hardening ──────────────────────────────────────────────

def test_table_headers_do_not_become_person():
    """Combinations of table headers and field terms must NOT become PERSON entities."""
    header_phrases = [
        "ID Item",
        "Source Condition",
        "statement Financial",
        "workstation Digital",
        "log Network",
    ]
    for phrase in header_phrases:
        assert validate_entity_candidate("PER", phrase) is False
        assert validate_entity_candidate("PERSON", phrase) is False


def test_collector_valid_person():
    """Synthetic Test Operator is a valid PERSON entity."""
    assert validate_entity_candidate("PER", "Synthetic Test Operator") is True


def test_csv_txt_do_not_become_keyword():
    """File format / condition terms CSV and TXT are rejected as KEYWORD entities."""
    assert validate_entity_candidate("KEYWORD", "CSV") is False
    assert validate_entity_candidate("KEYWORD", "TXT") is False
    assert validate_entity_candidate("KEYWORD", "PDF") is False
    assert validate_entity_candidate("KEYWORD", "Digital copy") is False


# ── 16. Relationships ─────────────────────────────────────────────────────────

def test_no_bogus_cooccurrence_relationships():
    """Seizure memo events must produce ZERO CO_OCCURRENCE relationships from table columns."""
    events = [
        {
            "id": "test-event-1",
            "event_type": "seizure_memo",
            "event_timestamp": "2026-08-23",
            "entity_mentions": [
                {"canonical_value": "Synthetic Test Operator", "entity_type": "PER"},
                {"canonical_value": "Digital copy", "entity_type": "KEYWORD"},
            ],
            "event_metadata": {
                "evidence_id": "EVD-BANK-001",
                "item": "Bank statement",
            },
        },
        {
            "id": "test-event-2",
            "event_type": "seizure_memo",
            "event_timestamp": "2026-08-23",
            "entity_mentions": [
                {"canonical_value": "Synthetic Test Operator", "entity_type": "PER"},
            ],
            "event_metadata": {
                "evidence_id": "EVD-DEVICE-001",
                "item": "Device extraction",
            },
        },
    ]
    drafts = derive_observed_relationships(events)
    assert len(drafts) == 0


# ── 17. Provenance ────────────────────────────────────────────────────────────

def test_provenance_preserved_for_each_row(file10_pdf_path: str):
    """Source doc, page, and row index provenance are preserved for each record."""
    events = parse_seizure_memo(file10_pdf_path)
    for idx, evt in enumerate(events, start=2):
        assert evt["source_page"] == 1
        assert evt["source_line"] == idx
        assert evt["metadata"]["source_page"] == 1
        assert evt["metadata"]["source_row"] == idx
        assert evt["metadata"]["source_doc"] is not None


# ── 18. Regression ────────────────────────────────────────────────────────────

def test_file06_regression(file06_pdf_path: str):
    """Existing File 06 must retain ('pdf', 'device_extraction') classification."""
    ftype, stype = _classify_and_route_file(pathlib.Path(file06_pdf_path))
    assert ftype == "pdf"
    assert stype == "device_extraction"
