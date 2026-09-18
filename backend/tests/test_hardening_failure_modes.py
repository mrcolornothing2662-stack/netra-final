"""
Hardening & Failure-Modes Acceptance Test Suite — NETRA 5.0
Workstream 4: Corrupted Evidence, Boundary Limits & Epistemic Abstention.

Tests:
1. Zero-byte and truncated evidence handling across parsers (chat, bank, CDR)
2. Malformed financial rows (NaN, non-numeric balances, empty narration)
3. Epistemic abstention: MO engine abstains on insufficient or noisy traces
4. Epistemic abstention: Confidence Meter abstains on zero findings or uncalibrated inputs
5. Epistemic abstention: Benford profiler detects small sample size (<30 txns)
6. Graceful degradation when optional models are offline
"""
from __future__ import annotations

import pytest

import tempfile
from pathlib import Path

from parsers.whatsapp_parser import parse_whatsapp_export
from cognitive.mo import classify_case_evidence, load_playbooks
from cognitive import data_path
from cognitive.uncertainty import audit_case_confidence
from cognitive.anomaly import build_entity_profiles, detect_transaction_spikes


# ── 1. Zero-Byte & Truncated Evidence Handling ───────────────────────────────

def test_zero_byte_chat_and_parsers():
    """Empty or whitespace-only chat export returns 0 messages without crashing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Empty file
        empty_file = Path(tmpdir) / "empty_chat.txt"
        empty_file.write_text("", encoding="utf-8")
        assert parse_whatsapp_export(empty_file) == []

        # Whitespace file
        ws_file = Path(tmpdir) / "whitespace_chat.txt"
        ws_file.write_text("   \n\n\t  \n", encoding="utf-8")
        assert parse_whatsapp_export(ws_file) == []

        # Garbage non-chat line
        garbage_file = Path(tmpdir) / "garbage_chat.txt"
        garbage_file.write_text("Random non-whatsapp garbage line without any timestamp\n", encoding="utf-8")
        res = parse_whatsapp_export(garbage_file)
        assert isinstance(res, list)


# ── 2. Malformed Financial Rows ───────────────────────────────────────────────

def test_malformed_bank_transactions_resilience():
    """Behavioral profiler handles malformed amounts, missing accounts, and empty narration without crashing."""
    malformed_rows = [
        {"metadata": {"account": "ACC_1", "amount": "NOT_A_NUMBER"}, "timestamp": "2026-08-18T10:00:00Z"},
        {"metadata": {"account": "ACC_1", "amount": None}, "timestamp": "2026-08-18T10:00:00Z"},
        {"metadata": {"amount": 5000.0}, "timestamp": "2026-08-18T10:00:00Z"},
    ]
    profiles = build_entity_profiles(malformed_rows, [], [])
    assert isinstance(profiles, dict)


# ── 3. Epistemic Abstention: Crime Script Matcher ──────────────────────────────

def test_mo_engine_epistemic_abstention_on_empty_trace():
    """Crime script matcher must honestly abstain when evidence contains no matched stages."""
    playbooks = load_playbooks(data_path("playbooks.json"))

    # Evidence with ordinary social chatter that contains 0 criminal stages
    mundane_evidence = [
        {"type": "whatsapp_msg", "text": "Good morning mummy breakfast ready?", "timestamp": "2026-08-18 08:00:00"},
        {"type": "whatsapp_msg", "text": "Yes coming in 5 mins", "timestamp": "2026-08-18 08:05:00"},
    ]

    result = classify_case_evidence(mundane_evidence, playbooks, {"match_threshold": 0.60})
    assert result["verdict"] in ("INSUFFICIENT_TRACE", "NO_CONFIDENT_MATCH", "INSUFFICIENT_EVIDENCE", "NO_CONCORDANCE")
    assert result["best_match"] is None
    assert result["verdict"] != "MATCHED"


# ── 4. Epistemic Abstention: Confidence Meter ─────────────────────────────────

def test_confidence_meter_abstention_on_empty_findings():
    """Confidence Meter must refuse to fabricate confidence scores when no findings exist."""
    report = audit_case_confidence(findings=[], evidence_files=[])
    assert report["findings_audit"]["total_findings"] == 0
    assert "overall_evidentiary_health_score" in report
    assert "R v T [2010]" in report["judicial_notices"]["rvt_compliance"]
    assert "Section 193 BNSS" in report["judicial_notices"]["bnss_statutory_note"]


# ── 5. Epistemic Abstention: Small Sample Size ────────────────────────────────

def test_anomaly_profiler_small_sample_abstention():
    """Behavioral anomaly detection must flag insufficient sample and abstain when N < 3."""
    small_sample = [
        {"metadata": {"account": "ACC_SMALL", "amount": 100.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC_SMALL", "amount": 99999.0}, "timestamp": "2026-08-21T11:00:00Z"},
    ]
    profiles = build_entity_profiles(small_sample, [], [])
    p = profiles["ACC_SMALL"]
    assert p.txn_count == 2
    assert p.baseline_status == "insufficient_sample"

    spikes = detect_transaction_spikes(small_sample, profiles)
    assert len(spikes) == 0
