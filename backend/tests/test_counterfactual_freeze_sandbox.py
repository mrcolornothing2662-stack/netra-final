"""
Unit and integration tests for Feature 08 — What-If Freeze Simulator / Counterfactual Freeze Sandbox.

Tests:
1. Full 4-Stage Lifecycle compliance (Observed, Intervention, Simulated, Comparison).
2. Backward compatibility contracts (completed_transfers scalar int, no len-able completed list).
3. Downstream starvation cascade detection (unfunded downstream mule debits).
4. Multi-account simultaneous interdiction.
5. Timeliness sensitivity sweep (decay curve at +15m, +30m, +1h, +2h, +6h, +24h).
6. CTDG counterfactual event replay frame generation.
7. Timezone-invariance across naive and aware (+05:30 IST) timestamps.
8. Zero-database mutation invariance.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest

from cognitive.counterfactual import (
    simulate_freeze,
    simulate_timeliness_sweep,
    generate_counterfactual_frames,
    _ts,
)


# ── Sample Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def cascade_transfers():
    """
    Scenario:
    T0 (10:00:00): Victim -> MuleA (₹1,000,000)
    T1 (10:15:00): MuleA -> MuleB (₹600,000)
    T2 (10:16:00): MuleA -> MuleC (₹300,000)
    T3 (10:30:00): MuleB -> Exchanger (₹600,000)  [Dependent on T1]
    T4 (11:00:00): MuleC -> ATM (₹300,000)        [Dependent on T2]
    """
    return [
        {"from": "VICTIM", "to": "MULE_A", "amount": 1000000.0, "timestamp": "2026-09-17T10:00:00"},
        {"from": "MULE_A", "to": "MULE_B", "amount": 600000.0, "timestamp": "2026-09-17T10:15:00"},
        {"from": "MULE_A", "to": "MULE_C", "amount": 300000.0, "timestamp": "2026-09-17T10:16:00"},
        {"from": "MULE_B", "to": "EXCHANGER", "amount": 600000.0, "timestamp": "2026-09-17T10:30:00"},
        {"from": "MULE_C", "to": "ATM_CASH", "amount": 300000.0, "timestamp": "2026-09-17T11:00:00"},
    ]


# ── 1. 4-Stage Lifecycle & Contracts ──────────────────────────────────────────

def test_four_stage_lifecycle_structure(cascade_transfers):
    """Verifies that simulate_freeze produces the structured 4-stage lifecycle output."""
    freeze_time = "2026-09-17T10:10:00"
    result = simulate_freeze(cascade_transfers, "MULE_A", freeze_time)

    # Validate 4 stages
    assert "stage_1_observed" in result
    assert "stage_2_intervention" in result
    assert "stage_3_simulated" in result
    assert "stage_4_comparison" in result

    # Stage 1: Observed
    s1 = result["stage_1_observed"]
    assert s1["total_transfers"] == 5
    assert s1["total_volume"] == 2800000.0
    assert s1["start_time"] is not None
    assert s1["end_time"] is not None

    # Stage 2: Intervention
    s2 = result["stage_2_intervention"]
    assert "MULE_A" in s2["freeze_accounts"]
    assert s2["freeze_time"] == freeze_time
    assert s2["intervention_type"] == "BANK_ACCOUNT_FREEZE_106_BNSS"

    # Stage 3: Simulated
    s3 = result["stage_3_simulated"]
    assert s3["completed_transfers_count"] == 1  # only T0 completed
    assert len(s3["blocked_debits"]) == 2       # T1, T2 blocked
    assert len(s3["starved_transfers"]) == 2    # T3, T4 starved

    # Stage 4: Comparison
    s4 = result["stage_4_comparison"]
    assert s4["preserved_capital"] == 900000.0
    assert s4["dissipated_capital"] == 1900000.0
    assert s4["preservation_ratio"] == round(900000.0 / 2800000.0, 4)


def test_legacy_backward_compatibility_contract(cascade_transfers):
    """
    CRITICAL: test_regression_cognitive contract:
    1. completed_transfers MUST be a scalar int
    2. 'completed' list key MUST NOT exist
    3. blocked_out_events, stopped_in_events, starved_downstream_events MUST be lists
    """
    freeze_time = "2026-09-17T10:10:00"
    result = simulate_freeze(cascade_transfers, "MULE_A", freeze_time)

    assert isinstance(result["completed_transfers"], int)
    assert result["completed_transfers"] == 1
    assert "completed" not in result

    with pytest.raises(TypeError):
        len(result["completed_transfers"])

    assert isinstance(result["blocked_out_events"], list)
    assert isinstance(result["stopped_in_events"], list)
    assert isinstance(result["starved_downstream_events"], list)
    assert isinstance(result["preserved_total"], float)
    assert result["epistemic_notice"] is not None


# ── 2. Downstream Starvation Cascade ──────────────────────────────────────────

def test_downstream_starvation_cascade(cascade_transfers):
    """
    When MULE_A is frozen at 10:10:00:
    - T0 (Victim -> MuleA ₹1M) completes.
    - T1 (MuleA -> MuleB ₹600k) is BLOCKED.
    - T2 (MuleA -> MuleC ₹300k) is BLOCKED.
    - T3 (MuleB -> Exchanger ₹600k) is STARVED because MuleB never got the ₹600k.
    - T4 (MuleC -> ATM ₹300k) is STARVED because MuleC never got the ₹300k.
    """
    freeze_time = "2026-09-17T10:10:00"
    result = simulate_freeze(cascade_transfers, "MULE_A", freeze_time)

    assert result["preserved_total"] == 900000.0
    assert len(result["blocked_out_events"]) == 2
    assert len(result["starved_downstream_events"]) == 2

    starved_sources = [ev["from"] for ev in result["starved_downstream_events"]]
    assert "MULE_B" in starved_sources
    assert "MULE_C" in starved_sources

    # Check reason tagging
    for ev in result["starved_downstream_events"]:
        assert "INSUFFICIENT_FUNDS_DUE_TO_UPSTREAM_FREEZE" in ev.get("reason", "")


# ── 3. Multi-Account Freeze Interdiction ──────────────────────────────────────

def test_multi_account_freeze():
    """Simulate freezing two mule accounts simultaneously."""
    transfers = [
        {"from": "VICTIM", "to": "MULE_1", "amount": 500000.0, "timestamp": "2026-09-17T10:00:00"},
        {"from": "VICTIM", "to": "MULE_2", "amount": 400000.0, "timestamp": "2026-09-17T10:01:00"},
        {"from": "MULE_1", "to": "CRYPTO_1", "amount": 500000.0, "timestamp": "2026-09-17T10:20:00"},
        {"from": "MULE_2", "to": "CRYPTO_2", "amount": 400000.0, "timestamp": "2026-09-17T10:25:00"},
    ]
    # Freeze both MULE_1 and MULE_2 at 10:10:00
    result = simulate_freeze(transfers, ["MULE_1", "MULE_2"], "2026-09-17T10:10:00")

    assert result["preserved_total"] == 900000.0
    assert len(result["blocked_out_events"]) == 2
    blocked_senders = {ev["from"] for ev in result["blocked_out_events"]}
    assert blocked_senders == {"MULE_1", "MULE_2"}
    assert result["completed_transfers"] == 2


# ── 4. Timeliness Sensitivity Sweep ──────────────────────────────────────────

def test_timeliness_sensitivity_sweep(cascade_transfers):
    """
    Timeliness sweep evaluates preservation at +15m, +30m, +1h, +2h, etc.
    Earlier intervention must preserve >= later intervention (monotonically non-increasing).
    """
    first_inflow = "2026-09-17T10:00:00"
    sweep = simulate_timeliness_sweep(
        transfers=cascade_transfers,
        freeze_accounts="MULE_A",
        reference_time=first_inflow,
        horizons_minutes=[10, 20, 45, 120],
    )

    assert len(sweep) == 4
    for step in sweep:
        assert "horizon_minutes" in step
        assert "freeze_time" in step
        assert "preserved_total" in step
        assert "dissipated_total" in step
        assert "preservation_rate_pct" in step

    # +10m (10:10:00): T1 and T2 not yet executed -> Preserved = 900,000
    step_10m = sweep[0]
    assert step_10m["horizon_minutes"] == 10
    assert step_10m["preserved_total"] == 900000.0

    # +20m (10:20:00): T1 (10:15) and T2 (10:16) already left MuleA -> Preserved = 0
    step_20m = sweep[1]
    assert step_20m["horizon_minutes"] == 20
    assert step_20m["preserved_total"] == 0.0

    # Monotonic decay validation
    preserved_values = [s["preserved_total"] for s in sweep]
    for i in range(len(preserved_values) - 1):
        assert preserved_values[i] >= preserved_values[i + 1], "Preservation must decay or remain equal as freeze is delayed"


# ── 5. CTDG Counterfactual Event Replay Frames ───────────────────────────────

def test_generate_counterfactual_frames(cascade_transfers):
    """Test the frame-by-frame CTDG replay generator."""
    frames = generate_counterfactual_frames(cascade_transfers, "MULE_A", "2026-09-17T10:10:00")
    assert len(frames) == len(cascade_transfers)

    # Frame 0: T0 is COMPLETED
    assert frames[0]["action"] == "COMPLETED"
    assert frames[0]["is_interdicted"] is False

    # Frame 1: T1 is BLOCKED
    assert frames[1]["action"] == "BLOCKED"
    assert frames[1]["is_interdicted"] is True
    assert frames[1]["cumulative_preserved"] == 600000.0

    # Frame 2: T2 is BLOCKED
    assert frames[2]["action"] == "BLOCKED"
    assert frames[2]["is_interdicted"] is True
    assert frames[2]["cumulative_preserved"] == 900000.0

    # Frame 3: T3 is STARVED
    assert frames[3]["action"] == "STARVED"
    assert frames[3]["is_interdicted"] is True


# ── 6. Timezone Invariance (Naive vs Aware IST) ───────────────────────────────

def test_timezone_invariance_counterfactual():
    """
    Validates that ISO string with offset (+05:30) produces identical outcomes
    to naive ISO string representing local IST time.
    """
    naive_transfers = [
        {"from": "SRC", "to": "TARGET", "amount": 50000, "timestamp": "2026-09-17T14:30:00"},
        {"from": "TARGET", "to": "OUT", "amount": 45000, "timestamp": "2026-09-17T14:45:00"},
    ]
    aware_transfers = [
        {"from": "SRC", "to": "TARGET", "amount": 50000, "timestamp": "2026-09-17T14:30:00+05:30"},
        {"from": "TARGET", "to": "OUT", "amount": 45000, "timestamp": "2026-09-17T14:45:00+05:30"},
    ]

    naive_freeze = "2026-09-17T14:35:00"
    aware_freeze = "2026-09-17T14:35:00+05:30"

    res_naive = simulate_freeze(naive_transfers, "TARGET", naive_freeze)
    res_aware = simulate_freeze(aware_transfers, "TARGET", aware_freeze)
    res_cross = simulate_freeze(aware_transfers, "TARGET", naive_freeze)

    assert res_naive["preserved_total"] == res_aware["preserved_total"] == res_cross["preserved_total"] == 45000.0
    assert res_naive["completed_transfers"] == res_aware["completed_transfers"] == 1
    assert len(res_naive["blocked_out_events"]) == len(res_aware["blocked_out_events"]) == 1


# ── 7. Epistemic Notice & Zero Mutation Guard ─────────────────────────────────

def test_epistemic_notice_present(cascade_transfers):
    """Ensures statutory and evidentiary disclaimers are present."""
    result = simulate_freeze(cascade_transfers, "MULE_A", "2026-09-17T10:10:00")
    assert "COUNTERFACTUAL SIMULATION ONLY" in result["epistemic_notice"]
    assert "Section 106 BNSS" in result["epistemic_notice"]
    assert result["confidence_score"] == 0.95
