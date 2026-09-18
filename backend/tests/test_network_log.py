from __future__ import annotations
"""
File 08 — 08_network_log.csv — Dedicated Parser, Extraction, and Relationship Tests

Verifies:
  1. Classification: 08_network_log.csv -> ("csv", "network_log")
  2. Dedicated network_log parser:
     - Exactly 3 events
     - No header event
     - event_type == "network_log"
     - All 3 timestamps preserved
     - device, ip, destination, port (443), action (TLS_SESSION) preserved
  3. IP Validation:
     - validate_entity_candidate("IP", "198.51.100.24") == True
     - validate_entity_candidate("PHONE", "198.51.100.24") == False
  4. Entity Extraction:
     - DEV-002 is DEVICE
     - 198.51.100.24 is IP
     - No false PHONE classification for the IP
  5. Relationship Derivation:
     - DEV-002 -> [CONNECTED_TO] -> 198.51.100.24
     - epistemic_status == OBSERVED
     - confidence == 1.0
     - attributes contain port=443, action="TLS_SESSION"
     - Provenance (evidence_refs, event_refs, timestamp) preserved
  6. Negative Semantic Checks:
     - Does NOT produce LOGGED_IN_FROM from TLS_SESSION
     - Does NOT produce USES from network_log record
"""
from pathlib import Path
import tempfile
import zipfile
import pytest

from graph import relationship_types as RT
from graph.relationships import derive_observed_relationships
from nlp.entity_validation import validate_entity_candidate
from parsers.network_log_parser import parse_network_log_csv, is_network_log_header
from routes.evidence import _classify_and_route_file


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def file_08_csv_path(tmp_path):
    """Extract File 08 from the synthetic case zip to a temp file."""
    zip_path = Path("/Users/shubhamrana/Downloads/NETRA_Operation_Meridian_Synthetic_Case.zip")
    if not zip_path.exists():
        pytest.skip("Synthetic case zip not found")
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_bytes = z.read("documents/08_network_log.csv")
    out = tmp_path / "08_network_log.csv"
    out.write_bytes(csv_bytes)
    return out


# ── 1. Classification Tests ───────────────────────────────────────────────────

class TestNetworkLogClassification:

    def test_classify_file_08(self, file_08_csv_path):
        file_type, source_type = _classify_and_route_file(file_08_csv_path)
        assert file_type == "csv"
        assert source_type == "network_log"

    def test_not_classified_as_bank_despite_bank_hostname(self, file_08_csv_path):
        """Verify that bank.example.invalid in payload does NOT trigger bank_statement."""
        _, source_type = _classify_and_route_file(file_08_csv_path)
        assert source_type != "bank_statement"

    def test_is_network_log_header_helper(self):
        valid = ["timestamp", "device", "ip", "destination", "port", "action"]
        assert is_network_log_header(valid) is True
        # Missing IP
        invalid = ["timestamp", "device", "destination", "port", "action"]
        assert is_network_log_header(invalid) is False
        # Bank ledger
        bank = ["date", "narration", "credit", "debit", "balance"]
        assert is_network_log_header(bank) is False


# ── 2. Dedicated Parser Tests ─────────────────────────────────────────────────

class TestNetworkLogParser:

    def test_parser_emits_exactly_3_events(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        assert len(events) == 3

    def test_no_header_event(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert "timestamp,device" not in ev["text"]
            assert ev["metadata"]["device"] != "device"

    def test_event_type_is_network_log(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert ev["event_type"] == "network_log"

    def test_all_3_timestamps_preserved(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        timestamps = [ev["timestamp"] for ev in events]
        assert timestamps == [
            "2026-08-21T09:58:00",
            "2026-08-21T10:29:00",
            "2026-08-23T16:42:00",
        ]

    def test_device_preserved(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert ev["metadata"]["device"] == "DEV-002"

    def test_ip_preserved(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert ev["metadata"]["ip"] == "198.51.100.24"

    def test_destination_preserved(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        destinations = [ev["metadata"]["destination"] for ev in events]
        assert destinations == [
            "bank.example.invalid",
            "messaging.example.invalid",
            "bank.example.invalid",
        ]

    def test_port_is_443(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert ev["metadata"]["port"] == 443

    def test_action_is_tls_session(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            assert ev["metadata"]["action"] == "TLS_SESSION"

    def test_provenance_lines(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        lines = [ev["source_line"] for ev in events]
        assert lines == [2, 3, 4]


# ── 3. IP Validation Tests ────────────────────────────────────────────────────

class TestIPValidation:

    def test_ip_198_51_100_24_passes(self):
        assert validate_entity_candidate("IP", "198.51.100.24") is True

    def test_ip_not_misclassified_as_phone(self):
        assert validate_entity_candidate("PHONE", "198.51.100.24") is False

    def test_ip_not_keyword(self):
        assert validate_entity_candidate("KEYWORD", "198.51.100.24") is False

    def test_real_phone_still_passes_as_phone(self):
        assert validate_entity_candidate("PHONE", "+91 98765 43210") is True
        assert validate_entity_candidate("PHONE", "9876543210") is True

    def test_phone_protection_against_person_still_active(self):
        assert validate_entity_candidate("PER", "+91 98765 43210") is False


# ── 4. Entity Extraction Tests ────────────────────────────────────────────────

class TestEntityExtraction:

    def test_dev_002_and_ip_extracted_from_event_text(self, file_08_csv_path):
        from ml.inference import run_hybrid_extraction
        events = parse_network_log_csv(file_08_csv_path)
        ev1 = events[0]
        res = run_hybrid_extraction(ev1["text"])

        types = {m.entity_type: m.canonical_value for m in res.mentions}
        assert "DEVICE" in types
        assert types["DEVICE"] == "DEV-002"
        assert "IP" in types
        assert types["IP"] == "198.51.100.24"

    def test_no_false_phone_for_ip(self, file_08_csv_path):
        from ml.inference import run_hybrid_extraction
        events = parse_network_log_csv(file_08_csv_path)
        for ev in events:
            res = run_hybrid_extraction(ev["text"])
            for m in res.mentions:
                if "198.51.100.24" in str(m.canonical_value):
                    assert m.entity_type == "IP"
                    assert m.entity_type != "PHONE"


# ── 5. Relationship Derivation Tests ──────────────────────────────────────────

class TestRelationshipDerivation:

    def test_network_log_produces_connected_to(self, file_08_csv_path):
        events = parse_network_log_csv(file_08_csv_path)
        for idx, ev in enumerate(events):
            ev["id"] = f"ev-{idx+1}"
            ev["evidence_file_id"] = "f-08"
            ev["entity_mentions"] = [
                {"canonical_value": ev["metadata"]["device"], "entity_type": "DEVICE", "raw_value": ev["metadata"]["device"]},
                {"canonical_value": ev["metadata"]["ip"], "entity_type": "IP", "raw_value": ev["metadata"]["ip"]},
            ]

        drafts = derive_observed_relationships(events)
        connected = [d for d in drafts if d.relationship_type == RT.CONNECTED_TO]
        assert len(connected) == 1

        edge = connected[0]
        assert edge.source_value == "DEV-002"
        assert edge.target_value == "198.51.100.24"
        assert edge.epistemic_status == RT.OBSERVED
        assert edge.confidence == 1.0
        assert edge.attributes["port"] == 443
        assert edge.attributes["action"] == "TLS_SESSION"
        assert edge.attributes["destination"] in ("bank.example.invalid", "messaging.example.invalid")
        assert edge.evidence_refs == ["f-08"]
        assert len(edge.event_refs) == 3
        assert edge.observation_count == 3
        assert edge.timestamp is not None

    def test_negative_semantics_no_logged_in_from(self, file_08_csv_path):
        """TLS_SESSION must NOT produce LOGGED_IN_FROM."""
        events = parse_network_log_csv(file_08_csv_path)
        for idx, ev in enumerate(events):
            ev["id"] = f"ev-{idx+1}"
            ev["entity_mentions"] = [
                {"canonical_value": ev["metadata"]["device"], "entity_type": "DEVICE", "raw_value": ev["metadata"]["device"]},
                {"canonical_value": ev["metadata"]["ip"], "entity_type": "IP", "raw_value": ev["metadata"]["ip"]},
            ]
        drafts = derive_observed_relationships(events)
        assert all(d.relationship_type != RT.LOGGED_IN_FROM for d in drafts)

    def test_negative_semantics_no_uses(self, file_08_csv_path):
        """Network log must NOT produce USES."""
        events = parse_network_log_csv(file_08_csv_path)
        for idx, ev in enumerate(events):
            ev["id"] = f"ev-{idx+1}"
            ev["entity_mentions"] = [
                {"canonical_value": ev["metadata"]["device"], "entity_type": "DEVICE", "raw_value": ev["metadata"]["device"]},
                {"canonical_value": ev["metadata"]["ip"], "entity_type": "IP", "raw_value": ev["metadata"]["ip"]},
            ]
        drafts = derive_observed_relationships(events)
        assert all(d.relationship_type != RT.USES for d in drafts)

    def test_suppresses_redundant_cooccurrence(self, file_08_csv_path):
        """The typed pair DEV-002 -> 198.51.100.24 must NOT also emit CO_OCCURRENCE."""
        events = parse_network_log_csv(file_08_csv_path)
        for idx, ev in enumerate(events):
            ev["id"] = f"ev-{idx+1}"
            ev["entity_mentions"] = [
                {"canonical_value": ev["metadata"]["device"], "entity_type": "DEVICE", "raw_value": ev["metadata"]["device"]},
                {"canonical_value": ev["metadata"]["ip"], "entity_type": "IP", "raw_value": ev["metadata"]["ip"]},
            ]
        drafts = derive_observed_relationships(events)
        cooc = [d for d in drafts if d.relationship_type == RT.CO_OCCURRENCE]
        assert len(cooc) == 0
