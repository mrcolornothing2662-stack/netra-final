from __future__ import annotations
"""
Unit and integration tests for File 09: 09_location_timeline.pdf.

Verifies:
  A. PDF Classification as ("pdf", "location_timeline")
  B. Dedicated parser extraction (3 events, non-GPS disclaimer, no preamble/footer noise)
  C. Masked phone extraction (+91-98XXXX1201, +91-97XXXX4418)
  D. Cell tower extraction without generic KEYWORD degradation
  E. Validation firewall (Phone Location, GPS rejected; Mohali accepted)
  F. Semantic relationship derivation (LOCATED_AT, OBSERVED, conf 1.0, no redundant CO_OCCURRENCE)
  G. Non-precise GPS limitation preservation
"""
import io
import pathlib
import tempfile
import zipfile

import pytest

from correlation.regex_extractors import extract, PHONE_RE, CELL_TOWER_RE
from graph import relationship_types as RT
from graph.relationships import derive_observed_relationships
from nlp.entity_validation import validate_entity_candidate
from nlp.ner import extract_entities
from parsers.location_timeline_parser import (
    parse_location_timeline,
    is_location_timeline_header,
    LOCATION_DISCLAIMER,
)
from routes.evidence import _classify_and_route_file

from pathlib import Path
ZIP_PATH = str(Path(__file__).resolve().parent / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip")


@pytest.fixture(scope="module")
def file09_pdf_path() -> str:
    """Extract File 09 from synthetic case zip to a temporary file for testing."""
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        content = zf.read("documents/09_location_timeline.pdf")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp.flush()
        return tmp.name


# ── A. Classification ─────────────────────────────────────────────────────────

def test_file09_classification(file09_pdf_path: str):
    """File 09 must be classified as ('pdf', 'location_timeline'), never bank_statement."""
    ftype, stype = _classify_and_route_file(pathlib.Path(file09_pdf_path))
    assert ftype == "pdf"
    assert stype == "location_timeline"


def test_is_location_timeline_header():
    """Header matcher identifies the location timeline table schema."""
    valid_header = ["Time", "Phone", "Location reference", "Observation"]
    assert is_location_timeline_header(valid_header) is True

    bank_header = ["Date", "Narration", "Withdrawal", "Deposit", "Balance"]
    assert is_location_timeline_header(bank_header) is False

    short_header = ["Time", "Phone"]
    assert is_location_timeline_header(short_header) is False


# ── B. Dedicated Parser ───────────────────────────────────────────────────────

def test_file09_parser_events(file09_pdf_path: str):
    """Parser must produce exactly 3 observation events with full metadata."""
    events = parse_location_timeline(file09_pdf_path, "09_location_timeline.pdf")
    assert len(events) == 3

    # All events must be location_timeline type
    for ev in events:
        assert ev["event_type"] == "location_timeline"
        assert ev["source_doc"] == "09_location_timeline.pdf"
        assert ev["source_page"] == 1
        assert ev["timestamp"] is not None
        assert "Cell-site association" in ev["text"]

    # Verify Row 1: 2026-08-21 10:02 | +91-98XXXX1201 | Chandigarh / CHD-CELL-17 | Cell-site association
    ev1 = events[0]
    assert ev1["timestamp"] == "2026-08-21T10:02:00"
    assert ev1["source_line"] == 2
    assert ev1["metadata"]["phone"] == "+91-98XXXX1201"
    assert ev1["metadata"]["city"] == "Chandigarh"
    assert ev1["metadata"]["cell_tower"] == "CHD-CELL-17"
    assert ev1["metadata"]["observation"] == "Cell-site association"
    assert ev1["metadata"]["limitation"] == LOCATION_DISCLAIMER

    # Verify Row 2: 2026-08-21 10:27 | +91-97XXXX4418 | Mohali / MOH-CELL-04 | Cell-site association
    ev2 = events[1]
    assert ev2["timestamp"] == "2026-08-21T10:27:00"
    assert ev2["source_line"] == 3
    assert ev2["metadata"]["phone"] == "+91-97XXXX4418"
    assert ev2["metadata"]["city"] == "Mohali"
    assert ev2["metadata"]["cell_tower"] == "MOH-CELL-04"
    assert ev2["metadata"]["observation"] == "Cell-site association"

    # Verify Row 3: 2026-08-23 16:05 | +91-97XXXX4418 | Chandigarh / CHD-CELL-22 | Cell-site association
    ev3 = events[2]
    assert ev3["timestamp"] == "2026-08-23T16:05:00"
    assert ev3["source_line"] == 4
    assert ev3["metadata"]["phone"] == "+91-97XXXX4418"
    assert ev3["metadata"]["city"] == "Chandigarh"
    assert ev3["metadata"]["cell_tower"] == "CHD-CELL-22"
    assert ev3["metadata"]["observation"] == "Cell-site association"


def test_no_preamble_or_footer_events(file09_pdf_path: str):
    """Preamble and disclaimer rows must NOT become events."""
    events = parse_location_timeline(file09_pdf_path)
    raw_texts = [e["text"] for e in events]
    assert not any("SYNTHETIC" in t for t in raw_texts)
    assert not any("Interpretation" in t for t in raw_texts)
    assert not any("Observations" in t for t in raw_texts)


# ── C. Phone Extraction ───────────────────────────────────────────────────────

def test_masked_phone_regex():
    """PHONE_RE must match masked synthetic phone numbers without altering X masking."""
    p1 = "+91-98XXXX1201"
    p2 = "+91-97XXXX4418"
    assert PHONE_RE.search(p1) is not None
    assert PHONE_RE.search(p2) is not None
    assert PHONE_RE.search(p1).group() == p1
    assert PHONE_RE.search(p2).group() == p2


def test_masked_phone_extraction():
    """Deterministic extractor extracts masked phones as canonical PHONE entities."""
    res1 = extract("+91-98XXXX1201")
    assert len(res1) == 1
    assert res1[0].entity_type == "PHONE"
    assert res1[0].raw_value == "+91-98XXXX1201"
    assert res1[0].norm_value == "+91-98XXXX1201"
    assert "XXXX" in res1[0].raw_value

    res2 = extract("+91-97XXXX4418")
    assert len(res2) == 1
    assert res2[0].entity_type == "PHONE"
    assert res2[0].raw_value == "+91-97XXXX4418"
    assert res2[0].norm_value == "+91-97XXXX4418"
    assert "XXXX" in res2[0].raw_value


def test_standard_phone_regression():
    """Existing phone extraction continues to work unchanged."""
    res = extract("Call me at +91 98765 43210 or 98765-12345")
    types = [r.entity_type for r in res]
    assert all(t == "PHONE" for t in types)
    assert len(res) == 2


# ── D. Cell Tower Extraction ──────────────────────────────────────────────────

def test_cell_tower_regex_extraction():
    """Cell towers must be extracted as CELL_TOWER, never generic KEYWORD."""
    for tower in ["CHD-CELL-17", "MOH-CELL-04", "CHD-CELL-22"]:
        res = extract(tower)
        assert len(res) == 1
        assert res[0].entity_type == "CELL_TOWER"
        assert res[0].raw_value == tower
        assert res[0].norm_value == tower


def test_cell_tower_not_keyword():
    """Cell tower identifiers must be rejected if categorized as KEYWORD."""
    assert validate_entity_candidate("KEYWORD", "CHD-CELL-17") is False
    assert validate_entity_candidate("KEYWORD", "MOH-CELL-04") is False
    assert validate_entity_candidate("KEYWORD", "CHD-CELL-22") is False
    assert validate_entity_candidate("CELL_TOWER", "CHD-CELL-17") is True
    assert validate_entity_candidate("CELL_TOWER", "MOH-CELL-04") is True
    assert validate_entity_candidate("CELL_TOWER", "CHD-CELL-22") is True


# ── E. Validation Firewall ────────────────────────────────────────────────────

def test_phone_location_per_rejected():
    """'Phone Location' from table header must NEVER pass as PER/PERSON."""
    assert validate_entity_candidate("PER", "Phone Location") is False
    assert validate_entity_candidate("PERSON", "Phone Location") is False


def test_gps_disclaimer_keyword_rejected():
    """'GPS' from the technical disclaimer must NEVER pass as KEYWORD."""
    assert validate_entity_candidate("KEYWORD", "GPS") is False


def test_mohali_accepted_as_location():
    """Mohali must be recognized and validated as LOCATION in parity with Chandigarh."""
    assert validate_entity_candidate("LOCATION", "Mohali") is True
    assert validate_entity_candidate("LOCATION", "Chandigarh") is True

    ents = extract_entities("Observations recorded in Mohali and Chandigarh.")
    locs = [e.canonical_value for e in ents if e.entity_type == "LOCATION"]
    assert "Mohali" in locs
    assert "Chandigarh" in locs


# ── F. Semantic Relationships ─────────────────────────────────────────────────

def test_location_timeline_relationships():
    """Location timeline events derive strictly typed LOCATED_AT edges without redundant co-occurrences."""
    events = [
        {
            "id": "ev-1",
            "event_type": "location_timeline",
            "timestamp": "2026-08-21T10:02:00",
            "metadata": {
                "phone": "+91-98XXXX1201",
                "city": "Chandigarh",
                "cell_tower": "CHD-CELL-17",
                "observation": "Cell-site association",
                "limitation": LOCATION_DISCLAIMER,
                "source_doc": "09_location_timeline.pdf",
            },
            "evidence_file_id": "file-09",
            "entity_mentions": [
                {"canonical_value": "+91-98XXXX1201", "entity_type": "PHONE"},
                {"canonical_value": "CHD-CELL-17", "entity_type": "CELL_TOWER"},
                {"canonical_value": "Chandigarh", "entity_type": "LOCATION"},
            ],
        },
        {
            "id": "ev-2",
            "event_type": "location_timeline",
            "timestamp": "2026-08-21T10:27:00",
            "metadata": {
                "phone": "+91-97XXXX4418",
                "city": "Mohali",
                "cell_tower": "MOH-CELL-04",
                "observation": "Cell-site association",
                "limitation": LOCATION_DISCLAIMER,
                "source_doc": "09_location_timeline.pdf",
            },
            "evidence_file_id": "file-09",
            "entity_mentions": [
                {"canonical_value": "+91-97XXXX4418", "entity_type": "PHONE"},
                {"canonical_value": "MOH-CELL-04", "entity_type": "CELL_TOWER"},
                {"canonical_value": "Mohali", "entity_type": "LOCATION"},
            ],
        },
        {
            "id": "ev-3",
            "event_type": "location_timeline",
            "timestamp": "2026-08-23T16:05:00",
            "metadata": {
                "phone": "+91-97XXXX4418",
                "city": "Chandigarh",
                "cell_tower": "CHD-CELL-22",
                "observation": "Cell-site association",
                "limitation": LOCATION_DISCLAIMER,
                "source_doc": "09_location_timeline.pdf",
            },
            "evidence_file_id": "file-09",
            "entity_mentions": [
                {"canonical_value": "+91-97XXXX4418", "entity_type": "PHONE"},
                {"canonical_value": "CHD-CELL-22", "entity_type": "CELL_TOWER"},
                {"canonical_value": "Chandigarh", "entity_type": "LOCATION"},
            ],
        },
    ]

    drafts = derive_observed_relationships(events)
    # Exactly 3 relationships — one per observation
    assert len(drafts) == 3

    # All must be LOCATED_AT, OBSERVED, confidence 1.0
    for d in drafts:
        assert d.relationship_type == RT.LOCATED_AT
        assert d.epistemic_status == RT.OBSERVED
        assert d.confidence == 1.0
        assert d.timestamp is not None
        assert "file-09" in d.evidence_refs
        assert len(d.event_refs) == 1
        assert "city" in d.attributes
        assert "observation" in d.attributes
        assert d.attributes["limitation"] == LOCATION_DISCLAIMER

    # No forbidden relationship types
    types = {d.relationship_type for d in drafts}
    assert RT.LOGGED_IN_FROM not in types
    assert RT.USES not in types
    assert RT.CONNECTED_TO not in types
    assert RT.CO_OCCURRENCE not in types

    # Verify exact edge pairs
    pairs = {(d.source_value, d.target_value) for d in drafts}
    expected_pairs = {
        ("+91-98XXXX1201", "CHD-CELL-17"),
        ("+91-97XXXX4418", "MOH-CELL-04"),
        ("+91-97XXXX4418", "CHD-CELL-22"),
    }
    assert pairs == expected_pairs
