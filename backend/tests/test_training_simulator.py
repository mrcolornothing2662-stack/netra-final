"""
Unit test suite for Feature 11: Training Simulator & Synthetic Benchmark
Pedagogical Validation Layer over Cognitive Engines (F01–F10 + Defence Bot)

Tests:
1. Drill catalog listing and schema integrity (drills, typologies, statutory citations)
2. Deterministic seeded session initialization (evidence generation, memo generation)
3. Student redaction boundary (answers & lessons hidden before submission)
4. Multi-engine execution over synthetic evidence (MO, Contradiction, Defence, Next-Best)
5. Multi-dimensional 4-pillar grading (Typology, Hidden Links, Legal Rigor, Golden Hours)
6. Dynamic readiness tier classification (Master, Lead, Proficient, Novice)
7. Statutory debrief & cognitive insight correlation (BNSS 193, BSA 63)
8. Ground truth revelation control (hidden until explicitly requested / post-submission)
9. Session storage isolation and bounding
"""
from __future__ import annotations

import pytest
from cognitive.training import (
    READINESS_TIERS,
    STATUTORY_TRAINING_NOTICE,
    TrainingSession,
    TrainingSimulator,
    get_training_simulator,
)


@pytest.fixture
def simulator():
    return TrainingSimulator()


# ── 1. Drill Catalog & Typology Loading ───────────────────────────────────────

def test_drill_catalog_loading(simulator: TrainingSimulator):
    drills = simulator.list_drills()
    assert len(drills) >= 4

    drill_ids = {d["id"] for d in drills}
    assert "DRILL-01-DIGITAL-ARREST" in drill_ids
    assert "DRILL-02-INVESTMENT-TASK" in drill_ids
    assert "DRILL-03-SHADOW-MULE-DEFENCE" in drill_ids
    assert "DRILL-04-PREDATORY-LOAN-BSA" in drill_ids

    for d in drills:
        assert d["title"]
        assert d["typology"]
        assert d["incident_brief"]
        assert d["tasks_count"] == 4
        assert isinstance(d["planted_defects"], list)


def test_get_drill_by_id(simulator: TrainingSimulator):
    drill = simulator.get_drill("DRILL-01-DIGITAL-ARREST")
    assert drill is not None
    assert drill["typology"] == "DIGITAL_ARREST"
    assert len(drill["tasks"]) == 4

    # Non-existent drill returns None
    assert simulator.get_drill("NON-EXISTENT-DRILL") is None


# ── 2. Session Initialization & Determinism ───────────────────────────────────

def test_session_creation_determinism(simulator: TrainingSimulator):
    # Running with identical seeds must yield identical synthetic evidence
    s1 = simulator.start_session(drill_id="DRILL-01-DIGITAL-ARREST", seed=101)
    s2 = simulator.start_session(drill_id="DRILL-01-DIGITAL-ARREST", seed=101)

    assert s1.session_id != s2.session_id
    assert s1.seed == s2.seed == 101

    # Verify identical evidence artifacts
    art1 = s1.case_data.get("artifacts", {})
    art2 = s2.case_data.get("artifacts", {})
    assert "whatsapp_export.txt" in art1
    assert "bank_statement_noisy.csv" in art1 or "bank_statement.csv" in art1
    assert "evidence_seizure_memo.txt" in art1
    assert art1["whatsapp_export.txt"] == art2["whatsapp_export.txt"]
    assert art1["evidence_seizure_memo.txt"] == art2["evidence_seizure_memo.txt"]


def test_student_task_redaction(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-02-INVESTMENT-TASK", seed=202)

    # Redacted student tasks must NOT leak the answers or pedagogical lessons
    for task in session.tasks:
        assert "task_id" in task
        assert "pillar" in task
        assert "prompt" in task
        assert "options" in task
        assert "correct_option" not in task
        assert "pedagogical_lesson" not in task

    # Full tasks internal to session must preserve ground truth
    for ft in session._full_tasks:
        assert "correct_option" in ft
        assert "pedagogical_lesson" in ft


def test_session_dict_ground_truth_isolation(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-03-SHADOW-MULE-DEFENCE", seed=303)

    student_view = session.to_dict(include_ground_truth=False)
    assert "ground_truth" not in student_view
    assert "solution_tasks" not in student_view
    assert student_view["statutory_notice"] == STATUTORY_TRAINING_NOTICE
    assert "artifacts" in student_view

    solution_view = session.to_dict(include_ground_truth=True)
    assert "ground_truth" in solution_view
    assert "solution_tasks" in solution_view
    assert len(solution_view["solution_tasks"]) == 4


# ── 3. Multi-Engine Execution Over Synthetic Case ─────────────────────────────

def test_cognitive_engines_run_on_case(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-01-DIGITAL-ARREST", seed=101)
    analysis = simulator.run_netra_engines_on_case(session)

    assert "mo_engine" in analysis
    assert "contradiction_engine" in analysis
    assert "defence_bot_engine" in analysis
    assert "nextbest_engine" in analysis

    # MO engine should recognize digital arrest patterns
    mo = analysis["mo_engine"]
    assert mo["best_playbook"] is not None
    assert mo["similarity"] > 0.50

    # Defence bot should produce defensibility audit
    defence = analysis["defence_bot_engine"]
    assert 0 <= defence["defensibility_score"] <= 100
    assert defence["risk_level"] in {"LOW_RISK", "MODERATE_RISK", "HIGH_RISK", "CRITICAL_RISK"}
    assert defence["bsa_status"]

    # Next-best should provide prioritized action
    nb = analysis["nextbest_engine"]
    assert nb["top_action"] is not None
    assert nb["statutory_basis"] is not None

    # Cached evaluation check
    cached = simulator.run_netra_engines_on_case(session)
    assert cached is analysis


# ── 4. Multi-Dimensional 4-Pillar Scoring & Readiness Tiers ───────────────────

def test_perfect_submission_grading(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-01-DIGITAL-ARREST", seed=101)

    # Assemble perfect answer sheet from ground truth
    perfect_answers = {
        t["task_id"]: t["correct_option"]
        for t in session._full_tasks
    }

    eval_result = simulator.evaluate_submission(session.session_id, perfect_answers)

    assert eval_result["score_pct"] == 100
    assert eval_result["total_points_earned"] == 100
    assert eval_result["readiness_tier"] == "MASTER_INVESTIGATOR"
    assert eval_result["tier_title"] == READINESS_TIERS["MASTER_INVESTIGATOR"]["title"]

    # Check 4 pillars
    pb = eval_result["pillar_breakdown"]
    assert pb["typology"]["earned"] == 25
    assert pb["hidden_links"]["earned"] == 25
    assert pb["legal_rigor"]["earned"] == 25
    assert pb["action_priority"]["earned"] == 25

    # Check task evaluations
    for te in eval_result["task_evaluations"]:
        assert te["is_correct"] is True
        assert te["points_earned"] == 25
        assert te["netra_engine_finding"] != ""
        assert te["pedagogical_lesson"] != ""


def test_flawed_submission_readiness_tiers(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-02-INVESTMENT-TASK", seed=202)

    full_tasks = session._full_tasks

    # 1. 3 out of 4 correct (75%) -> LEAD_CYBER_INVESTIGATOR
    lead_answers = {
        full_tasks[0]["task_id"]: full_tasks[0]["correct_option"],
        full_tasks[1]["task_id"]: full_tasks[1]["correct_option"],
        full_tasks[2]["task_id"]: full_tasks[2]["correct_option"],
        full_tasks[3]["task_id"]: "WRONG_OPTION",
    }
    eval_lead = simulator.evaluate_submission(session.session_id, lead_answers)
    assert eval_lead["score_pct"] == 75
    assert eval_lead["readiness_tier"] == "LEAD_CYBER_INVESTIGATOR"

    # 2. 2 out of 4 correct (50%) -> PROFICIENT_OFFICER
    proficient_answers = {
        full_tasks[0]["task_id"]: full_tasks[0]["correct_option"],
        full_tasks[1]["task_id"]: full_tasks[1]["correct_option"],
        full_tasks[2]["task_id"]: "WRONG_OPTION",
        full_tasks[3]["task_id"]: "WRONG_OPTION",
    }
    eval_prof = simulator.evaluate_submission(session.session_id, proficient_answers)
    assert eval_prof["score_pct"] == 50
    assert eval_prof["readiness_tier"] == "PROFICIENT_OFFICER"

    # 3. 0 out of 4 correct (0%) -> NOVICE_IN_TRAINING
    novice_answers = {
        full_tasks[0]["task_id"]: "WRONG_OPTION",
        full_tasks[1]["task_id"]: "WRONG_OPTION",
        full_tasks[2]["task_id"]: "WRONG_OPTION",
        full_tasks[3]["task_id"]: "WRONG_OPTION",
    }
    eval_novice = simulator.evaluate_submission(session.session_id, novice_answers)
    assert eval_novice["score_pct"] == 0
    assert eval_novice["readiness_tier"] == "NOVICE_IN_TRAINING"


def test_statutory_debrief_recap(simulator: TrainingSimulator):
    session = simulator.start_session(drill_id="DRILL-04-PREDATORY-LOAN-BSA", seed=404)
    eval_result = simulator.evaluate_submission(session.session_id, {})

    recap = eval_result["statutory_recap"]
    assert len(recap) >= 4
    recap_text = " ".join(recap)
    assert "Section 193 BNSS" in recap_text
    assert "Section 63 BSA" in recap_text
    assert "Section 105 BNSS" in recap_text


# ── 5. Session Isolation and Global Singleton ─────────────────────────────────

def test_session_isolation(simulator: TrainingSimulator):
    s1 = simulator.start_session(drill_id="DRILL-01-DIGITAL-ARREST", seed=10)
    s2 = simulator.start_session(drill_id="DRILL-02-INVESTMENT-TASK", seed=20)

    assert simulator.get_session(s1.session_id) == s1
    assert simulator.get_session(s2.session_id) == s2

    # Grading s1 does not alter s2
    simulator.evaluate_submission(s1.session_id, {})
    assert s1.evaluation is not None
    assert s2.evaluation is None


def test_get_training_simulator_singleton():
    sim1 = get_training_simulator()
    sim2 = get_training_simulator()
    assert sim1 is sim2
