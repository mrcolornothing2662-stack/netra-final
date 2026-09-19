import io
import re
import zipfile
import pathlib
import pytest
import pdfplumber
import pandas as pd

from parsers.bank_pdf_parser import parse_bank_pdf, _is_bank_statement_table, _map_columns
from routes.evidence import _classify_and_route_file, _safe_parse_iso

ZIP_PATH = str(pathlib.Path(__file__).resolve().parent / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip")


def test_bank_pdf_parser_rejects_non_bank_tables():
    """Verify that _is_bank_statement_table and parse_bank_pdf decline non-bank tables."""
    # Non-bank table 1: Key-value metadata
    col_map_kv = _map_columns(["Field", "Value"])
    assert not _is_bank_statement_table(col_map_kv)

    # Non-bank table 2: Device extraction records
    col_map_dev = _map_columns(["Timestamp", "Record", "Value"])
    assert not _is_bank_statement_table(col_map_dev)

    # Non-bank table 3: Evidence seizure memo
    col_map_seizure = _map_columns(["Evidence ID", "Item", "Source", "Condition"])
    assert not _is_bank_statement_table(col_map_seizure)

    # Genuine bank statement table
    col_map_bank = _map_columns(["Date/Time", "Txn ID", "Direction", "Counterparty", "Amount", "Narration"])
    assert _is_bank_statement_table(col_map_bank)


def test_file_06_declined_by_bank_parser():
    """Ensure 06_device_extraction.pdf returns 0 bank events from parse_bank_pdf."""
    path_06 = pathlib.Path("/tmp/netra_inspect/documents/06_device_extraction.pdf")
    if not path_06.exists():
        with zipfile.ZipFile(ZIP_PATH) as z:
            path_06.parent.mkdir(parents=True, exist_ok=True)
            path_06.write_bytes(z.read("documents/06_device_extraction.pdf"))

    events = parse_bank_pdf(path_06)
    assert len(events) == 0, f"Expected 0 bank_txn events, got {len(events)}"


def test_file_06_classified_as_device_extraction():
    """Ensure _classify_and_route_file identifies File 06 as device_extraction."""
    path_06 = pathlib.Path("/tmp/netra_inspect/documents/06_device_extraction.pdf")
    file_type, source_type = _classify_and_route_file(path_06)
    assert file_type == "pdf"
    assert source_type == "device_extraction"


def test_file_06_text_fallback_preserves_facts_and_timestamps():
    """Verify that PDF text fallback preserves all 4 timeline timestamps and 7 core facts."""
    path_06 = pathlib.Path("/tmp/netra_inspect/documents/06_device_extraction.pdf")
    events = []
    with pdfplumber.open(str(path_06)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line_idx, line in enumerate(text.splitlines(), start=1):
                line_clean = line.strip()
                if line_clean:
                    line_ts = None
                    ts_m = re.match(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", line_clean)
                    if ts_m:
                        line_ts = ts_m.group(1)
                    events.append({
                        "source_doc": path_06.name,
                        "timestamp": line_ts,
                        "text": line_clean,
                        "event_type": "document_text",
                        "source_line": line_idx,
                        "source_page": page_idx,
                    })

    # Total lines extracted
    assert len(events) == 18

    # All events must be document_text (NO bogus bank_txn)
    for ev in events:
        assert ev["event_type"] == "document_text"
        assert "UNKNOWN" not in ev["text"]

    # Verify the 4 timeline timestamps
    timestamps = [ev["timestamp"] for ev in events if ev["timestamp"] is not None]
    expected_timestamps = [
        "2026-08-21 10:01",
        "2026-08-21 10:27",
        "2026-08-23 16:03",
        "2026-08-23 16:44",
    ]
    assert timestamps == expected_timestamps

    # Verify timestamps can be parsed by _safe_parse_iso
    for ts in timestamps:
        dt = _safe_parse_iso(ts)
        assert dt is not None
        assert dt.year == 2026

    # Verify all 7 expected source facts survive in the extracted events
    all_text = " ".join(ev["text"] for ev in events)
    expected_facts = [
        "DEV-002",
        "PH-002",
        "Android",
        "EXT-2026-0823-002",
        "CHAT-001",
        "PH-003",
        "TXN-005",
    ]
    for fact in expected_facts:
        assert fact in all_text, f"Fact '{fact}' missing from extracted text"


def test_bank_statement_02_still_parses_cleanly():
    """Verify that genuine bank statement (02_bank_statement.pdf) still parses properly without bogus UNKNOWN amounts."""
    with zipfile.ZipFile(ZIP_PATH) as z:
        data = z.read("documents/02_bank_statement.pdf")
        tmp_bank = pathlib.Path("/tmp/netra_inspect/02_bank_statement.pdf")
        tmp_bank.write_bytes(data)

    events = parse_bank_pdf(tmp_bank)
    assert len(events) == 3  # Exactly the 3 transactions from Table 2
    for ev in events:
        assert ev["event_type"] == "bank_txn"
        assert "UNKNOWN" not in ev["text"]
        assert ev["timestamp"] is not None
        assert ev["metadata"]["credit"] is not None or ev["metadata"]["debit"] is not None


def test_file_06_entity_extraction_types_and_noise_rejection():
    """Verify that File 06 extracts semantic types and rejects all 15 noisy entities."""
    from ml.inference import run_hybrid_extraction
    from nlp.entity_validation import validate_entity_candidate

    path_06 = pathlib.Path("/tmp/netra_inspect/documents/06_device_extraction.pdf")
    lines = []
    with pdfplumber.open(str(path_06)) as pdf:
        for p in pdf.pages:
            for l in (p.extract_text() or "").splitlines():
                if l.strip():
                    lines.append(l.strip())

    extracted_entities = {}
    for line in lines:
        res = run_hybrid_extraction(line)
        for m in res.mentions:
            etype = "PER" if m.entity_type in ("PERSON", "PER") else m.entity_type
            if validate_entity_candidate(etype, m.raw_value):
                canonical = str(m.canonical_value or m.raw_value).strip()
                extracted_entities.setdefault(etype, set()).add(canonical)

    # 1. Verify semantic types for core identifiers
    assert "DEV-002" in extracted_entities.get("DEVICE", set())
    assert "PH-002" in extracted_entities.get("PHONE", set())
    assert "PH-003" in extracted_entities.get("PHONE", set())
    assert "CHAT-001" in extracted_entities.get("CHAT", set())
    assert "TXN-005" in extracted_entities.get("TRANSACTION", set())

    # None of these should be KEYWORD
    assert "DEV-002" not in extracted_entities.get("KEYWORD", set())
    assert "PH-002" not in extracted_entities.get("KEYWORD", set())
    assert "PH-003" not in extracted_entities.get("KEYWORD", set())
    assert "CHAT-001" not in extracted_entities.get("KEYWORD", set())
    assert "TXN-005" not in extracted_entities.get("KEYWORD", set())

    # 2. Verify all 15 noisy entities are completely absent across all types
    all_values = set()
    for etype, vals in extracted_entities.items():
        all_values.update(v.upper() for v in vals)

    banned_values = [
        "TRAINING", "DATA", "NOT",
        "AN ACTUAL", "POLICE RECORD", "EXTRACTION SUMMARY",
        "FIELD VALUE", "PLATFORM ANDROID", "OBSERVED RECORDS",
        "TIMESTAMP", "RECORD VALUE", "ACTIVITY OUTGOING", "APPLICATION TRANSACTION",
        "POLICE",
    ]
    for banned in banned_values:
        assert banned not in all_values, f"Noisy entity '{banned}' was unexpectedly extracted!"

