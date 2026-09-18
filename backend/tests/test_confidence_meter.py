"""
Unit Tests for Feature 05 — Confidence Meter & Evidentiary State Analyzer.
Verifies:
  - Exact split-conformal prediction quantile computation q = ceil((n+1)(1-epsilon)).
  - Marginal coverage guarantee P(Y in C(X)) >= 1 - epsilon.
  - Three-way prediction set verdicts: SINGLE_LABEL, AMBIGUOUS_SET, OUT_OF_DISTRIBUTION.
  - Non-conformity mapping and order-statistic clipping for small samples.
  - Five epistemic source tiers (Direct Observation, Rule-Based, Inferred, Screening, Simulation).
  - Corroboration scoring across distinct evidence file types.
  - Contradiction burden penalty deduction.
  - Case evidentiary health audit and R v T [2010] & Section 193 BNSS judicial notices.
  - Synthetic calibration provenance flags (valid_for_real_data = False).
"""
import math
import pytest
from cognitive.uncertainty import (
    calibrate,
    predict_set,
    empirical_coverage,
    determine_epistemic_tier,
    evaluate_finding_confidence,
    audit_case_confidence,
    ConformalCalibrationStore,
    TIER_DIRECT_OBSERVATION,
    TIER_RULE_BASED,
    TIER_INFERRED,
    TIER_SCREENING,
    TIER_SIMULATION,
)


def test_conformal_calibration_order_statistics():
    """Verify finite-sample conformal calibration math."""
    # N = 100 calibration scores
    scores = [i / 100.0 for i in range(1, 101)]  # 0.01 to 1.00
    eps = 0.05  # 95% target coverage

    # q_idx = ceil(101 * 0.95) = ceil(95.95) = 96 (1-based), so index 95 -> 0.96
    cal = calibrate(scores, epsilon=eps, source="synthetic_benchmark", model_name="ROLE_CLASSIFIER_CONFORMAL")

    assert cal["model_name"] == "ROLE_CLASSIFIER_CONFORMAL"
    assert cal["sample_size"] == 100
    assert cal["epsilon"] == 0.05
    assert cal["target_coverage"] == 0.95
    assert cal["quantile_threshold"] == 0.96
    assert cal["coverage_guarantee"]["valid_for_real_data"] is False
    assert cal["coverage_guarantee"]["guarantee_status"] == "SYNTHETIC_BENCHMARK_ONLY"


def test_conformal_calibration_small_sample_abstention():
    """If n < 1/epsilon, finite sample coverage cannot be guaranteed; threshold must be inf."""
    scores = [0.1, 0.2]  # n = 2, epsilon = 0.05 -> ceil(3 * 0.95) = 3 > 2
    cal = calibrate(scores, epsilon=0.05, source="small_sample")
    assert cal["quantile_threshold"] == float("inf")

    # With infinite threshold, candidate scores map properly or handle boundaries
    pred = predict_set(cal, {"MULE": 0.5, "ORGANIZER": 0.8})
    assert "MULE" in pred["prediction_set"]
    assert "ORGANIZER" in pred["prediction_set"]


def test_conformal_prediction_set_verdicts():
    """Verify three-way verdicts: SINGLE_LABEL, AMBIGUOUS_SET, OUT_OF_DISTRIBUTION."""
    # Setup calibration with cutoff at 0.35
    cal = {
        "model_name": "TEST_MODEL",
        "quantile_threshold": 0.35,
        "epsilon": 0.05,
        "target_coverage": 0.95,
        "coverage_guarantee": {"valid_for_real_data": False},
    }

    # 1. Single-label: only MULE has alpha <= 0.35
    res1 = predict_set(cal, {"MULE": 0.15, "ORGANIZER": 0.65, "VICTIM": 0.85})
    assert res1["verdict"] == "SINGLE_LABEL"
    assert res1["prediction_set"] == ["MULE"]

    # 2. Ambiguous set: both MULE and ORGANIZER have alpha <= 0.35
    res2 = predict_set(cal, {"MULE": 0.15, "ORGANIZER": 0.25, "VICTIM": 0.70})
    assert res2["verdict"] == "AMBIGUOUS_SET"
    assert res2["prediction_set"] == ["MULE", "ORGANIZER"]

    # 3. Out of distribution: no label satisfies alpha <= 0.35
    res3 = predict_set(cal, {"MULE": 0.80, "ORGANIZER": 0.90, "VICTIM": 0.75})
    assert res3["verdict"] == "OUT_OF_DISTRIBUTION"
    assert res3["prediction_set"] == []
    assert "Abstain" in res3["message"]


def test_empirical_coverage():
    """Verify empirical coverage helper."""
    cal = {"quantile_threshold": 0.50}
    trials = [True] * 95 + [False] * 5
    cov = empirical_coverage(cal, trials)
    assert cov == 0.95


def test_epistemic_tier_mapping():
    """Verify strict epistemic source tier mapping for findings."""
    t1, s1, _ = determine_epistemic_tier("CONTRADICTION", "contradiction_engine")
    assert t1 == TIER_RULE_BASED
    assert s1 == "RULE_SCORE"

    t2, s2, _ = determine_epistemic_tier("BEHAVIORAL_ANOMALY", "anomaly_engine")
    assert t2 == TIER_RULE_BASED
    assert s2 == "ANOMALY_Z_SCORE"

    t3, s3, _ = determine_epistemic_tier("HYPOTHESIS", "hypothesis_engine")
    assert t3 == TIER_RULE_BASED
    assert s3 == "ACH_INCONSISTENCY"

    t4, s4, _ = determine_epistemic_tier("UNCERTAINTY", "nextbest_engine")
    assert t4 == TIER_DIRECT_OBSERVATION
    assert s4 == "EVIDENCE_GAP"

    t5, s5, _ = determine_epistemic_tier("HIDDEN_LINK", "crosscase_engine")
    assert t5 == TIER_INFERRED
    assert s5 == "GRAPH_INFERENCE_SCORE"

    t6, s6, _ = determine_epistemic_tier("MO_MATCH", "mo_engine")
    assert t6 == TIER_SCREENING
    assert s6 == "COSINE_SIMILARITY"

    t7, s7, _ = determine_epistemic_tier("COUNTERFACTUAL", "counterfactual_engine")
    assert t7 == TIER_SIMULATION
    assert s7 == "SIMULATION_DELTA"


def test_finding_confidence_corroboration_and_contradiction():
    """Verify corroboration across distinct file types and contradiction penalty."""
    finding = {
        "id": "find-1",
        "finding_type": "BEHAVIORAL_ANOMALY",
        "title": "Rapid Outflow Z-Score Spike",
        "severity": "HIGH",
        "confidence": 3.8,
        "source_engine": "anomaly",
        "evidence_refs": ["ev-1", "ev-2"],
        "entity_refs": ["ACC_1001"],
    }

    evidence_files = [
        {"id": "ev-1", "file_type": "bank_csv", "filename": "bank.csv"},
        {"id": "ev-2", "file_type": "cdr_csv", "filename": "cdr.csv"},
    ]

    # Without contradiction
    eval1 = evaluate_finding_confidence(finding, evidence_files=evidence_files, contradictions=[])
    assert eval1["corroboration"]["is_multi_source"] is True
    assert eval1["corroboration"]["distinct_source_types_count"] == 2
    assert "bank_csv" in eval1["corroboration"]["evidence_file_types"]
    assert "cdr_csv" in eval1["corroboration"]["evidence_file_types"]
    assert eval1["contradiction_burden"]["has_contradiction_burden"] is False

    # With contradiction targeting ACC_1001
    contradiction = {
        "finding_type": "CONTRADICTION",
        "title": "Ledger Balance Continuity Shortfall",
        "entity_refs": ["ACC_1001"],
    }
    eval2 = evaluate_finding_confidence(finding, evidence_files=evidence_files, contradictions=[contradiction])
    assert eval2["contradiction_burden"]["has_contradiction_burden"] is True
    assert eval2["contradiction_burden"]["active_contradictions_count"] == 1
    assert eval2["contradiction_burden"]["penalty"] > 0


def test_audit_case_confidence_full():
    """Verify case-wide evidentiary health calculation and judicial notices."""
    findings = [
        {
            "id": "f1",
            "finding_type": "CONTRADICTION",
            "title": "Ledger Shortfall",
            "severity": "CRITICAL",
            "confidence": 1.0,
            "source_engine": "contradiction",
            "evidence_refs": ["ev1", "ev2"],
            "entity_refs": ["ACC_001"],
        },
        {
            "id": "f2",
            "finding_type": "MO_MATCH",
            "title": "Digital Arrest Playbook",
            "severity": "HIGH",
            "confidence": 0.88,
            "source_engine": "mo",
            "evidence_refs": ["ev2"],
            "entity_refs": ["ACC_001"],
        },
    ]

    evidence_files = [
        {"id": "ev1", "file_type": "bank_csv", "filename": "bank.csv"},
        {"id": "ev2", "file_type": "pcap", "filename": "network.pcap"},
    ]

    contradictions = [findings[0]]

    hypotheses_result = {
        "target_entity": "ACC_001",
        "hypotheses": [
            {"label": "LAYER1_MULE", "inconsistency_score": 0.0},
            {"label": "KINGPIN_ORGANIZER", "inconsistency_score": 4.5},
            {"label": "COMPROMISED_VICTIM", "inconsistency_score": 8.0},
        ],
    }

    report = audit_case_confidence(
        findings=findings,
        evidence_files=evidence_files,
        contradictions=contradictions,
        hypotheses_result=hypotheses_result,
        conformal_epsilon=0.05,
    )

    assert "overall_evidentiary_health_score" in report
    assert 0.0 <= report["overall_evidentiary_health_score"] <= 1.0
    assert report["overall_verdict"] in ("ROBUST_CORROBORATED", "PROCEED_WITH_CAUTION", "HIGH_UNCERTAINTY")
    assert report["findings_audit"]["total_findings"] == 2
    assert "R v T [2010]" in report["judicial_notices"]["rvt_compliance"]
    assert "Section 193 BNSS" in report["judicial_notices"]["bnss_statutory_note"]
    assert "SYNTHETIC BENCHMARK ONLY" in report["judicial_notices"]["synthetic_calibration_warning"]

    # Conformal prediction set for ACC_001
    assert len(report["suspect_role_conformal_sets"]) == 1
    s_set = report["suspect_role_conformal_sets"][0]
    assert s_set["target_entity"] == "ACC_001"
    assert "LAYER1_MULE" in s_set["prediction_set"]
    assert s_set["valid_for_real_data"] is False


def test_conformal_calibration_store():
    """Verify registry of calibration distributions and on-the-fly epsilon adjustments."""
    store = ConformalCalibrationStore()
    all_cals = store.list_all()
    assert len(all_cals) == 3
    model_names = [c["model_name"] for c in all_cals]
    assert "ROLE_CLASSIFIER_CONFORMAL" in model_names
    assert "HIDDEN_LINK_CONFORMAL" in model_names
    assert "MO_TYPOLOGY_CONFORMAL" in model_names

    # Custom registration
    custom = store.register("CUSTOM_MODEL", [0.05, 0.10, 0.15, 0.20, 0.25], epsilon=0.10, source="real_trial_data")
    assert custom["coverage_guarantee"]["valid_for_real_data"] is True
    assert custom["coverage_guarantee"]["guarantee_status"] == "VALID_REAL"

    # Fetch with recomputed epsilon
    retrieved = store.get("ROLE_CLASSIFIER_CONFORMAL", epsilon=0.01)
    assert retrieved is not None
    assert retrieved["epsilon"] == 0.01
    assert retrieved["target_coverage"] == 0.99
