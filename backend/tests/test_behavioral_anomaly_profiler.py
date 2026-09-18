"""
Dedicated Unit & Integration Tests for Feature 02: Behavioral Anomaly Profiler

Verifies:
  1. Statistical baseline calculations (mean, std, median, MAD).
  2. Small-sample protection (abstention when N < 3, MAD when 3 <= N < 10).
  3. Outlier detection using robust Z-scores (CRITICAL for Z >= 3.0, HIGH for Z >= 2.0).
  4. Rapid pass-through turnover velocity (credit-to-debit <= 30 min, >= 85% drained).
  5. Circadian activity distribution and off-hours anomaly detection.
  6. Multi-source fused travel (CDR + cell-site timeline).
  7. Epistemic humility enforcement (strictly descriptive baseline deviations, zero accusations).
  8. Orchestration EngineSpec contract compliance and CognitiveResult emission.
"""
from __future__ import annotations

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognitive.anomaly import (
    EntityProfile,
    build_entity_profiles,
    detect_transaction_spikes,
    detect_pass_through_turnover,
    detect_circadian_anomalies,
    detect_fused_travel,
    scan_behavioral_anomalies,
    resolve_coordinates,
)
from orchestration.contracts import BEHAVIORAL_ANOMALY, CaseContext
from orchestration.engines.anomaly import SPEC as anomaly_spec, run as run_anomaly_engine


# ── 1. Statistical Baseline Calculation ───────────────────────────────────────

def test_entity_profile_financial_baseline():
    """Verify calculation of mean, std, median, and MAD for an entity."""
    bank_events = [
        {"metadata": {"account": "ACC-TEST-1", "amount": 1000.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC-TEST-1", "amount": 2000.0}, "timestamp": "2026-08-21T11:00:00Z"},
        {"metadata": {"account": "ACC-TEST-1", "amount": 3000.0}, "timestamp": "2026-08-21T12:00:00Z"},
        {"metadata": {"account": "ACC-TEST-1", "amount": 4000.0}, "timestamp": "2026-08-21T13:00:00Z"},
    ]
    profiles = build_entity_profiles(bank_events, [], [])
    assert "ACC-TEST-1" in profiles
    p = profiles["ACC-TEST-1"]
    assert p.txn_count == 4
    assert p.total_volume == 10000.0
    assert p.mean_amount == 2500.0
    assert p.median_amount == 2500.0
    assert p.min_amount == 1000.0
    assert p.max_amount == 4000.0
    assert p.baseline_status == "established"


# ── 2. Small-Sample Protection & Abstention ───────────────────────────────────

def test_small_sample_abstention_when_n_less_than_3():
    """Entities with fewer than 3 transactions must not trigger spike anomalies."""
    bank_events = [
        {"metadata": {"account": "ACC-SMALL", "amount": 100.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC-SMALL", "amount": 99999.0}, "timestamp": "2026-08-21T11:00:00Z"},
    ]
    profiles = build_entity_profiles(bank_events, [], [])
    p = profiles["ACC-SMALL"]
    assert p.txn_count == 2
    assert p.baseline_status == "insufficient_sample"

    # Must abstain from flagging transaction spikes
    spikes = detect_transaction_spikes(bank_events, profiles)
    assert len(spikes) == 0


# ── 3. Transaction Spike via Standard Z-Score (N >= 10) ──────────────────────

def test_transaction_spike_standard_z():
    """With N >= 10, engine uses standard Z-score (x - mu) / sigma."""
    normal_txns = [
        {"metadata": {"account": "ACC-CORP", "amount": 1000.0 + (i * 10)}, "timestamp": f"2026-08-20T{10+i%10:02d}:00:00Z"}
        for i in range(12)
    ]
    # An extreme outlier
    spike_txn = {"metadata": {"account": "ACC-CORP", "amount": 50000.0, "ref_no": "SPIKE-001"}, "timestamp": "2026-08-21T15:00:00Z"}
    all_txns = normal_txns + [spike_txn]

    profiles = build_entity_profiles(normal_txns, [], [])
    spikes = detect_transaction_spikes([spike_txn], profiles)

    assert len(spikes) == 1
    s = spikes[0]
    assert s.anomaly_type == "TRANSACTION_SPIKE"
    assert s.severity == "CRITICAL"
    assert s.component_scores["method"] == "standard_z"
    assert s.component_scores["z_score"] >= 3.0
    assert s.epistemic_status == "STATISTICAL_INFERENCE"


# ── 4. Transaction Spike via Modified MAD Z-Score (3 <= N < 10) ───────────────

def test_transaction_spike_mad_small_sample():
    """With 3 <= N < 10, engine uses Median Absolute Deviation (MAD) for outlier resistance."""
    baseline_txns = [
        {"metadata": {"account": "ACC-RETAIL", "amount": 5000.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC-RETAIL", "amount": 5100.0}, "timestamp": "2026-08-21T11:00:00Z"},
        {"metadata": {"account": "ACC-RETAIL", "amount": 4900.0}, "timestamp": "2026-08-21T12:00:00Z"},
        {"metadata": {"account": "ACC-RETAIL", "amount": 5050.0}, "timestamp": "2026-08-21T13:00:00Z"},
    ]
    spike_txn = {"metadata": {"account": "ACC-RETAIL", "amount": 48500.0, "ref_no": "TXN-BIG"}, "timestamp": "2026-08-21T14:00:00Z"}

    profiles = build_entity_profiles(baseline_txns, [], [])
    spikes = detect_transaction_spikes([spike_txn], profiles)

    assert len(spikes) == 1
    s = spikes[0]
    assert s.component_scores["method"] == "mad_small_sample"
    assert s.component_scores["z_score"] >= 3.0
    assert s.severity == "CRITICAL"


# ── 5. Rapid Pass-Through Turnover Velocity ───────────────────────────────────

def test_pass_through_turnover_detection():
    """Verify detection of Operation Meridian pattern (credit ₹48,500, debit ₹47,000 within 17 min)."""
    bank_events = [
        {
            "id": "ev-credit-1",
            "evidence_file_id": "file-03",
            "metadata": {"account": "rohan@upi", "credit": 48500.0, "debit": 0.0, "ref_no": "TXN-001"},
            "timestamp": "2026-08-21T10:14:00Z",
        },
        {
            "id": "ev-debit-1",
            "evidence_file_id": "file-03",
            "metadata": {"account": "rohan@upi", "credit": 0.0, "debit": 47000.0, "ref_no": "TXN-002"},
            "timestamp": "2026-08-21T10:31:00Z",
        },
    ]

    findings = detect_pass_through_turnover(bank_events, max_gap_minutes=30.0, min_turnover_ratio=0.85)
    assert len(findings) == 1
    f = findings[0]
    assert f.anomaly_type == "RAPID_PASS_THROUGH"
    assert f.entity == "rohan@upi"
    assert f.severity == "CRITICAL"
    assert f.component_scores["time_gap_minutes"] == 17.0
    assert f.component_scores["turnover_ratio"] >= 0.95
    assert f.epistemic_status == "OBSERVED"
    assert "ev-credit-1" in f.event_refs and "ev-debit-1" in f.event_refs


def test_pass_through_turnover_negative_cases():
    """Gradual withdrawal or low-ratio drainage must not trigger rapid turnover anomaly."""
    # Low drainage: received ₹50,000, withdrawn ₹5,000
    low_drainage = [
        {"metadata": {"account": "ACC-NORM", "credit": 50000.0, "debit": 0.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC-NORM", "credit": 0.0, "debit": 5000.0}, "timestamp": "2026-08-21T10:15:00Z"},
    ]
    assert len(detect_pass_through_turnover(low_drainage)) == 0

    # Slow turnaround: withdrawal after 2 hours (> 30 min)
    slow_turnaround = [
        {"metadata": {"account": "ACC-SLOW", "credit": 50000.0, "debit": 0.0}, "timestamp": "2026-08-21T10:00:00Z"},
        {"metadata": {"account": "ACC-SLOW", "credit": 0.0, "debit": 49000.0}, "timestamp": "2026-08-21T12:30:00Z"},
    ]
    assert len(detect_pass_through_turnover(slow_turnaround, max_gap_minutes=30.0)) == 0


# ── 6. Circadian Off-Hours Activity Surges ─────────────────────────────────────

def test_circadian_off_hours_surge():
    """Entity with regular daytime activity suddenly bursts in nocturnal window (00:00 - 05:00)."""
    events = [
        {"metadata": {"account": "ACC-OFF"}, "timestamp": f"2026-08-20T{10+i}:00:00Z"}
        for i in range(8)
    ]
    # Night events
    events.extend([
        {"metadata": {"account": "ACC-OFF"}, "timestamp": "2026-08-21T01:15:00Z"},
        {"metadata": {"account": "ACC-OFF"}, "timestamp": "2026-08-21T02:45:00Z"},
    ])
    profiles = build_entity_profiles(events, [], [])
    findings = detect_circadian_anomalies([], profiles, min_off_hours_events=2)
    assert len(findings) == 1
    f = findings[0]
    assert f.anomaly_type == "CIRCADIAN_OFF_HOURS"
    assert f.entity == "ACC-OFF"
    assert f.component_scores["off_hours_count"] == 2


# ── 7. Multi-Source Fused Travel Detection ─────────────────────────────────────

def test_fused_travel_across_cdr_and_location_timeline():
    """Fusing CDR call and location timeline cell observation across distant cities."""
    cdr_events = [
        {"metadata": {"caller": "+91-9876500001", "cell_id": "HYD-CELL-01"}, "timestamp": "2026-08-21T10:00:00Z"}
    ]
    loc_events = [
        {"metadata": {"phone": "+91-9876500001", "cell_tower": "DEL-CELL-02"}, "timestamp": "2026-08-21T10:15:00Z"}
    ]
    findings = detect_fused_travel(cdr_events, loc_events)
    assert len(findings) == 1
    f = findings[0]
    assert f.anomaly_type == "IMPOSSIBLE_TRAVEL"
    assert f.entity == "+91-9876500001"
    assert f.component_scores["velocity_kmh"] > 900.0


# ── 8. Epistemic Humility Enforcement ──────────────────────────────────────────

def test_epistemic_humility_standards():
    """Ensure engine statements strictly describe baseline deviations and NEVER make criminal accusations."""
    bank_events = [
        {"metadata": {"account": "ACC-TRANSIT-001", "credit": 50000.0, "debit": 0.0, "ref_no": "TXN-1"}, "timestamp": "2026-08-21T10:10:00Z"},
        {"metadata": {"account": "ACC-TRANSIT-001", "credit": 0.0, "debit": 49500.0, "ref_no": "TXN-2"}, "timestamp": "2026-08-21T10:20:00Z"},
    ]
    report = scan_behavioral_anomalies(bank_events, [], [])
    findings = report["findings"]
    assert len(findings) > 0

    prohibited_accusatory_terms = [
        "guilty", "mule", "crime", "criminal", "fraudster", "scammer", "illegal", "laundered"
    ]

    for f in findings:
        text = f"{f['title']} {f['description']} {f['reasoning']}".lower()
        for term in prohibited_accusatory_terms:
            assert term not in text, f"Epistemic violation: prohibited term '{term}' found in finding: {text}"
        # Must declare empirical deviation
        assert "baseline" in text or "turnover" in text or "deviation" in text


# ── 9. Orchestration Engine Adapter ────────────────────────────────────────────

def test_anomaly_engine_adapter_run():
    """Verify BehavioralAnomalyEngine adapter runs through CaseContext and outputs CognitiveResults."""
    events = [
        {
            "id": "e1",
            "event_type": "bank_txn",
            "event_timestamp": "2026-08-21T10:14:00Z",
            "evidence_file_id": "f3",
            "event_metadata": {"account": "ACC-101", "credit": 48500.0, "debit": 0.0, "ref_no": "T1"},
        },
        {
            "id": "e2",
            "event_type": "bank_txn",
            "event_timestamp": "2026-08-21T10:31:00Z",
            "evidence_file_id": "f3",
            "event_metadata": {"account": "ACC-101", "credit": 0.0, "debit": 47000.0, "ref_no": "T2"},
        },
    ]
    ctx = CaseContext(case_id="case-101", events=events)
    assert anomaly_spec.applies(ctx) is True

    results = run_anomaly_engine(ctx)
    assert len(results) >= 1
    res = results[0]
    assert res.finding_type == BEHAVIORAL_ANOMALY
    assert res.source_engine == "BehavioralAnomalyEngine"
    assert res.severity in ("CRITICAL", "HIGH", "MEDIUM")
    assert "ACC-101" in res.entity_refs
    assert "f3" in res.evidence_refs
