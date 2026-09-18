"""
Unit & Integration Tests for Feature 04: Hypothesis Investigation Board
Validates Richards Heuer's ACH framework, 5 suspect roles, R v T [2010] EWCA Crim 2439
admissibility safeguards, diagnosticity spreads, refuting evidence, and Section 193 BNSS reports.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognitive.hypothesis import load_model, evaluate, extract_entity_observations
from cognitive import data_path


@pytest.fixture
def hypothesis_model():
    path = data_path("hypotheses.json")
    return load_model(path)


def test_ach_model_structure(hypothesis_model):
    """Verifies all 5 hypotheses, equal priors (0.20), and 6 diagnostic indicators."""
    assert len(hypothesis_model["hypotheses"]) == 5
    expected_labels = {
        "KINGPIN_ORGANIZER",
        "LAYER1_MULE",
        "COMPROMISED_VICTIM",
        "TECHNICAL_OPERATOR",
        "BENEFICIARY_CASHOUT",
    }
    actual_labels = {h["label"] for h in hypothesis_model["hypotheses"]}
    assert actual_labels == expected_labels

    for h in hypothesis_model["hypotheses"]:
        assert abs(h["prior"] - 0.20) < 1e-6

    indicator_names = {ind["name"] for ind in hypothesis_model["indicators"]}
    expected_indicators = {
        "pass_through_speed",
        "account_age",
        "victim_contact",
        "dormancy",
        "device_dispersion",
        "turnover_scale",
    }
    assert indicator_names == expected_indicators

    # Every bucket across all indicators must sum to exactly 1.000 across all 5 hypotheses
    for ind in hypothesis_model["indicators"]:
        for bucket_name, dist in ind["evidence"].items():
            total = sum(dist.values())
            assert abs(total - 1.0) < 1e-6, f"Bucket {bucket_name} in {ind['name']} sums to {total}"


def test_mule_signature_evaluation(hypothesis_model):
    """A rapid turnover (<15m) fresh account (<30d) with no victim calls ranks LAYER1_MULE #1."""
    observations = {
        "velocity_minutes": 8.5,
        "account_age_days": 12,
        "inbound_victim_calls": 0,
        "dormancy_before_crime_days": 60,
        "turnover_volume_inr": 350000,
    }
    res = evaluate(observations, hypothesis_model)

    assert res["ranked_labels"][0] == "LAYER1_MULE"
    assert "R v T [2010]" in res["display_label"]
    assert res["assessment_type"] == "RULE_BASED_ASSESSMENT"
    assert "Richards Heuer" in res["epistemic_notice"]

    # Epistemic safeguard: posteriors must be None (no fake % numbers)
    for h in res["hypotheses"]:
        assert h["posterior"] is None

    # Refuting evidence on COMPROMISED_VICTIM
    by_label = {h["label"]: h for h in res["hypotheses"]}
    victim_refute = by_label["COMPROMISED_VICTIM"]["refuting_evidence"]
    assert victim_refute is not None
    assert victim_refute["likelihood_under_this_hypothesis"] <= 0.10
    assert victim_refute["indicator"] in ("turnover_scale", "pass_through_speed")

    # Supporting evidence on LAYER1_MULE
    mule_support = by_label["LAYER1_MULE"]["supporting_evidence"]
    assert mule_support is not None
    assert mule_support["likelihood_under_this_hypothesis"] >= 0.50


def test_kingpin_signature_evaluation(hypothesis_model):
    """High victim calls, seasoned account, and large turnover ranks KINGPIN_ORGANIZER #1."""
    observations = {
        "velocity_minutes": 720,
        "account_age_days": 1200,
        "inbound_victim_calls": 18,
        "dormancy_before_crime_days": 5,
        "turnover_volume_inr": 8500000,
        "device_sharing_count": 1,
    }
    res = evaluate(observations, hypothesis_model)
    assert res["ranked_labels"][0] == "KINGPIN_ORGANIZER"
    assert "R v T [2010]" in res["display_label"]


def test_technical_operator_signature(hypothesis_model):
    """Multiple devices shared, high turnover, seasoned account elevates TECHNICAL_OPERATOR."""
    observations = {
        "velocity_minutes": 45,
        "account_age_days": 400,
        "inbound_victim_calls": 0,
        "dormancy_before_crime_days": 10,
        "device_sharing_count": 5,
        "turnover_volume_inr": 1500000,
    }
    res = evaluate(observations, hypothesis_model)
    by_label = {h["label"]: h for h in res["hypotheses"]}
    # Technical operator should have low inconsistency
    assert by_label["TECHNICAL_OPERATOR"]["inconsistency_score"] < by_label["COMPROMISED_VICTIM"]["inconsistency_score"]


def test_evidence_matrix_and_diagnosticity(hypothesis_model):
    """Verifies Heuer ACH evidence matrix rows, likelihood distributions, and diagnosticity spread."""
    observations = {
        "velocity_minutes": 10,
        "account_age_days": 20,
    }
    res = evaluate(observations, hypothesis_model)
    matrix = res["evidence_matrix"]
    assert len(matrix) == 2

    for row in matrix:
        assert "indicator" in row
        assert "observed_value" in row
        assert "bucket" in row
        assert "diagnosticity" in row
        assert row["diagnosticity"] >= 0.0
        assert len(row["likelihoods"]) == 5
        assert abs(sum(row["likelihoods"].values()) - 1.0) < 1e-6

    # Unobserved indicators reported with Section 193 BNSS details
    assert "victim_contact" in res["unobserved_indicators"]
    assert "device_dispersion" in res["unobserved_indicators"]
    assert len(res["unobserved_details"]) >= 4
    for gap in res["unobserved_details"]:
        assert "required_evidence" in gap
        assert "potential_impact" in gap


def test_entity_observation_extraction():
    """Extracts empirical observations and provenance citations from multi-modal events."""
    bank_events = [
        {
            "from_account": "ACC_VICTIM",
            "to_account": "ACC_SUSPECT",
            "amount": 250000.0,
            "timestamp": "2026-09-17T10:00:00Z",
            "source_file": "axis_bank.csv",
            "source_line": 15,
        },
        {
            "from_account": "ACC_SUSPECT",
            "to_account": "ACC_CASH_OUT",
            "amount": 248000.0,
            "timestamp": "2026-09-17T10:12:00Z",  # 12 minutes delta!
            "source_file": "axis_bank.csv",
            "source_line": 16,
        },
    ]

    call_events = [
        {
            "calling_number": "VICTIM_PHONE",
            "called_number": "ACC_SUSPECT",
            "call_type": "INCOMING",
            "source_file": "cdr.csv",
            "source_line": 42,
        },
    ]

    net_events = [
        {
            "metadata": {
                "ip": "ACC_SUSPECT",
                "device_id": "DEV_001",
                "mac": "00:1A:2B:3C:4D:5E",
            },
            "source_file": "firewall.log",
        },
        {
            "metadata": {
                "ip": "ACC_SUSPECT",
                "device_id": "DEV_002",
                "mac": "00:1A:2B:3C:4D:5F",
            },
            "source_file": "firewall.log",
        },
    ]

    obs, prov = extract_entity_observations(
        target_entity="ACC_SUSPECT",
        bank_events=bank_events,
        call_events=call_events,
        network_events=net_events,
    )

    assert "velocity_minutes" in obs
    assert obs["velocity_minutes"] == 12.0
    assert "turnover_volume_inr" in obs
    assert obs["turnover_volume_inr"] == 498000.0
    assert "inbound_victim_calls" in obs
    assert obs["inbound_victim_calls"] == 1
    assert "device_sharing_count" in obs
    assert obs["device_sharing_count"] == 3.0

    assert "pass_through_speed" in prov
    assert prov["pass_through_speed"]["source_file"] == "axis_bank.csv"
    assert prov["pass_through_speed"]["source_line"] in (15, 16)
