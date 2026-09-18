#!/usr/bin/env python3
"""
Live E2E Verification for Feature 11 — Training Simulator & Synthetic Benchmark.

Verification Gates:
  1. Authentication (JWT token via /auth/login)
  2. Mission catalog discovery (GET /cognitive/training/drills)
  3. Training session initialization & DPDP demarcation (POST /cognitive/training/start)
  4. Investigator blind & redaction boundary (GET /cognitive/training/{session_id})
  5. NETRA AI Co-Pilot hints execution (POST /cognitive/training/{session_id}/engine-hints)
  6. Perfect submission grading & Master Investigator tier (POST /cognitive/training/{session_id}/submit)
  7. Multi-tier evaluation calibration (Proficient Officer & Novice in Training)
  8. Solution & ground truth pedagogical reveal (GET /cognitive/training/{session_id}/solution)
  9. Sandbox case export to DB with [TRAINING SIMULATION] tag (POST /cognitive/training/{session_id}/export-case)
 10. Post-submission session persistence and idempotency
"""
from __future__ import annotations

import json
import sys
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0


def ok(msg: str):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str, detail: str = ""):
    global failed
    failed += 1
    print(f"  {RED}✗ FAIL:{RESET} {msg}")
    if detail:
        print(f"    {RED}→ {detail}{RESET}")


def section(title: str):
    print(f"\n{CYAN}{BOLD}▶ {title}{RESET}")


def assert_eq(label: str, got, expected):
    if got == expected:
        ok(f"{label}: {got!r}")
    else:
        fail(f"{label}: expected {expected!r}, got {got!r}")


def assert_ge(label: str, got, threshold):
    if got >= threshold:
        ok(f"{label}: {got!r} >= {threshold!r}")
    else:
        fail(f"{label}: expected >= {threshold!r}, got {got!r}")


def assert_in(label: str, item, container):
    if item in container:
        ok(f"{label}: '{item}' present")
    else:
        fail(f"{label}: '{item}' NOT found in container")


client = httpx.Client(base_url=BASE_URL, timeout=45)

# ---------------------------------------------------------------------------
# Gate 1: Authentication
# ---------------------------------------------------------------------------
section("Gate 1 / 10 — Authentication")
r = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
if r.status_code != 200:
    r = client.post("/auth/login", data={"username": "admin", "password": "admin"})
if r.status_code != 200:
    r = client.post("/auth/login", data={"username": "admin", "password": "changeme123"})
if r.status_code != 200:
    print(f"  {RED}✗ Login failed: {r.status_code} {r.text}{RESET}")
    sys.exit(1)
token = r.json().get("access_token") or r.json().get("token")
headers = {"Authorization": f"Bearer {token}"}
ok("Login → JWT bearer token acquired")

# ---------------------------------------------------------------------------
# Gate 2: Mission Catalog Discovery
# ---------------------------------------------------------------------------
section("Gate 2 / 10 — Mission catalog discovery (/cognitive/training/drills)")
r = client.get("/cognitive/training/drills", headers=headers)
assert_eq("Status code", r.status_code, 200)
drills_data = r.json()
drills = drills_data.get("drills", [])
assert_ge("Drill count", len(drills), 4)

drill_ids = {d["id"] for d in drills}
assert_in("Catalog contains DRILL-01", "DRILL-01-DIGITAL-ARREST", drill_ids)
assert_in("Catalog contains DRILL-02", "DRILL-02-INVESTMENT-TASK", drill_ids)
assert_in("Catalog contains DRILL-03", "DRILL-03-SHADOW-MULE-DEFENCE", drill_ids)
assert_in("Catalog contains DRILL-04", "DRILL-04-PREDATORY-LOAN-BSA", drill_ids)

drill1 = next(d for d in drills if d["id"] == "DRILL-01-DIGITAL-ARREST")
assert_eq("Drill 1 typology", drill1["typology"], "DIGITAL_ARREST")
assert_eq("Drill 1 tasks count", drill1["tasks_count"], 4)
assert_ge("Drill 1 planted defects", len(drill1.get("planted_defects", [])), 1)

# ---------------------------------------------------------------------------
# Gate 3: Training Session Initialization
# ---------------------------------------------------------------------------
section("Gate 3 / 10 — Session initialization (/cognitive/training/start)")
start_payload = {
    "drill_id": "DRILL-01-DIGITAL-ARREST",
    "seed": 101,
}
r = client.post("/cognitive/training/start", json=start_payload, headers=headers)
assert_eq("Status code", r.status_code, 200)
s_data = r.json()

session_id = s_data.get("session_id")
assert_eq("Session drill_id", s_data.get("drill_id"), "DRILL-01-DIGITAL-ARREST")
assert_eq("Session seed", s_data.get("seed"), 101)
assert_in("DPDP statutory notice", "Digital Personal Data Protection (DPDP) Act, 2023", s_data.get("statutory_notice", ""))

# Verify synthetic evidence artifacts
artifacts = s_data.get("artifacts", {})
assert_in("Artifact whatsapp_export.txt", "whatsapp_export.txt", artifacts)
assert_in("Artifact evidence_seizure_memo.txt", "evidence_seizure_memo.txt", artifacts)
assert_eq("whatsapp artifact type", artifacts["whatsapp_export.txt"]["type"], "text")
ok(f"Session started: ID={session_id}")

# ---------------------------------------------------------------------------
# Gate 4: Investigator Blind & Redaction Boundary
# ---------------------------------------------------------------------------
section("Gate 4 / 10 — Redaction boundary check (/cognitive/training/{session_id})")
r = client.get(f"/cognitive/training/{session_id}", headers=headers)
assert_eq("Status code", r.status_code, 200)
active_s = r.json()

assert_eq("has_hints initial", active_s.get("has_hints"), False)
assert_eq("is_evaluated initial", active_s.get("is_evaluated"), False)
tasks = active_s.get("tasks", [])
assert_eq("Student tasks count", len(tasks), 4)

for t in tasks:
    if "correct_option" in t:
        fail("Ground truth leaked: 'correct_option' found in student view")
    else:
        ok(f"Task '{t['task_id']}' redacted cleanly: options count={len(t['options'])}")

# ---------------------------------------------------------------------------
# Gate 5: NETRA AI Co-Pilot Hints Execution
# ---------------------------------------------------------------------------
section("Gate 5 / 10 — Co-Pilot hints execution (/cognitive/training/{session_id}/engine-hints)")
r = client.post(f"/cognitive/training/{session_id}/engine-hints", headers=headers)
assert_eq("Status code", r.status_code, 200)
hints = r.json().get("hints") or r.json().get("engine_hints", {})

assert_in("MO engine in hints", "mo_engine", hints)
assert_in("Defence Bot in hints", "defence_bot_engine", hints)
assert_in("NextBest in hints", "nextbest_engine", hints)

mo_hint = hints.get("mo_engine", {})
assert_eq("MO best playbook", mo_hint.get("best_playbook"), "DIGITAL_ARREST_EXTORTION")
assert_ge("MO similarity", mo_hint.get("similarity", 0), 0.70)

def_hint = hints.get("defence_bot_engine", {})
assert_ge("Defensibility score", def_hint.get("defensibility_score", 0), 0)
assert_in("BSA compliance status", "COMPLIANT", def_hint.get("bsa_status", ""))

nb_hint = hints.get("nextbest_engine", {})
assert_ge("Next-best statutory basis length", len(nb_hint.get("statutory_basis", "") or ""), 3)
sim_val = mo_hint.get("similarity") or 0.0
ok(f"Cognitive engines evaluated synthetic case: MO={mo_hint.get('best_playbook')} ({sim_val*100:.1f}%)")

# ---------------------------------------------------------------------------
# Gate 6: Perfect Submission Grading & Master Investigator Tier
# ---------------------------------------------------------------------------
section("Gate 6 / 10 — Perfect submission grading (/cognitive/training/{session_id}/submit)")

# Retrieve solution tasks to form perfect answer sheet
r_sol = client.get(f"/cognitive/training/{session_id}/solution", headers=headers)
assert_eq("Solution status code", r_sol.status_code, 200)
sol_tasks = r_sol.json().get("solution_tasks", [])

perfect_answers = {
    t["task_id"]: t["correct_option"]
    for t in sol_tasks
}
ok(f"Assembled perfect answer sheet: {perfect_answers}")

submit_payload = {"answers": perfect_answers}
r = client.post(f"/cognitive/training/{session_id}/submit", json=submit_payload, headers=headers)
assert_eq("Submit status code", r.status_code, 200)
eval_data = r.json().get("evaluation", {})

assert_eq("Score percentage", eval_data.get("score_pct"), 100)
assert_eq("Total points earned", eval_data.get("total_points_earned"), 100)
assert_eq("Readiness tier", eval_data.get("readiness_tier"), "MASTER_INVESTIGATOR")
assert_eq("Tier badge", eval_data.get("tier_badge"), "🎖️ MASTER INVESTIGATOR")

# 4-Pillar verification
pb = eval_data.get("pillar_breakdown", {})
assert_eq("Typology pillar", pb.get("typology", {}).get("earned"), 25)
assert_eq("Hidden links pillar", pb.get("hidden_links", {}).get("earned"), 25)
assert_eq("Legal rigor pillar", pb.get("legal_rigor", {}).get("earned"), 25)
assert_eq("Action priority pillar", pb.get("action_priority", {}).get("earned"), 25)

# Task evaluation debriefs
te_list = eval_data.get("task_evaluations", [])
assert_eq("Task evaluations count", len(te_list), 4)
for te in te_list:
    assert_eq(f"Task {te['task_id']} is_correct", te.get("is_correct"), True)
    assert_ge(f"Task {te['task_id']} lesson text", len(te.get("pedagogical_lesson", "")), 10)

# Statutory recap citations
recap = eval_data.get("statutory_recap", [])
assert_ge("Statutory recap entries", len(recap), 4)
recap_str = " ".join(recap)
assert_in("Section 193 BNSS in recap", "Section 193 BNSS", recap_str)
assert_in("Section 63 BSA in recap", "Section 63 BSA", recap_str)
assert_in("Section 105 BNSS in recap", "Section 105 BNSS", recap_str)

# ---------------------------------------------------------------------------
# Gate 7: Multi-Tier Evaluation Calibration
# ---------------------------------------------------------------------------
section("Gate 7 / 10 — Multi-tier evaluation calibration (Proficient & Novice)")

# Session B: DRILL-02-INVESTMENT-TASK
r_b = client.post("/cognitive/training/start", json={"drill_id": "DRILL-02-INVESTMENT-TASK", "seed": 202}, headers=headers)
s_b_id = r_b.json().get("session_id")
r_b_sol = client.get(f"/cognitive/training/{s_b_id}/solution", headers=headers)
sol_b_tasks = r_b_sol.json().get("solution_tasks", [])

# 2 out of 4 correct -> 50% PROFICIENT_OFFICER
partial_answers = {
    sol_b_tasks[0]["task_id"]: sol_b_tasks[0]["correct_option"],
    sol_b_tasks[1]["task_id"]: sol_b_tasks[1]["correct_option"],
    sol_b_tasks[2]["task_id"]: "WRONG_CHOICE_A",
    sol_b_tasks[3]["task_id"]: "WRONG_CHOICE_B",
}
r_part = client.post(f"/cognitive/training/{s_b_id}/submit", json={"answers": partial_answers}, headers=headers)
eval_part = r_part.json().get("evaluation", {})
assert_eq("Partial score pct", eval_part.get("score_pct"), 50)
assert_eq("Partial tier", eval_part.get("readiness_tier"), "PROFICIENT_OFFICER")
assert_eq("Partial badge", eval_part.get("tier_badge"), "🔷 PROFICIENT OFFICER")

# Session C: 0 out of 4 correct -> 0% NOVICE_IN_TRAINING
r_c = client.post("/cognitive/training/start", json={"drill_id": "DRILL-03-SHADOW-MULE-DEFENCE", "seed": 303}, headers=headers)
s_c_id = r_c.json().get("session_id")
all_wrong = {t["task_id"]: "WRONG" for t in sol_b_tasks}
r_nov = client.post(f"/cognitive/training/{s_c_id}/submit", json={"answers": all_wrong}, headers=headers)
eval_nov = r_nov.json().get("evaluation", {})
assert_eq("Zero score pct", eval_nov.get("score_pct"), 0)
assert_eq("Novice tier", eval_nov.get("readiness_tier"), "NOVICE_IN_TRAINING")
assert_eq("Novice badge", eval_nov.get("tier_badge"), "🔰 IN TRAINING")

# ---------------------------------------------------------------------------
# Gate 8: Solution & Ground Truth Pedagogical Reveal
# ---------------------------------------------------------------------------
section("Gate 8 / 10 — Solution & Ground Truth reveal (/cognitive/training/{session_id}/solution)")
r = client.get(f"/cognitive/training/{session_id}/solution", headers=headers)
assert_eq("Status code", r.status_code, 200)
sol_data = r.json()

assert_in("ground_truth block present", "ground_truth", sol_data)
assert_in("solution_tasks block present", "solution_tasks", sol_data)

gt = sol_data.get("ground_truth", {})
assert_in("typology in GT", "typology", gt)
assert_in("planted_hidden_links in GT", "planted_hidden_links", gt)
assert_ge("ground_truth entities count", len(gt.get("entities", {})), 2)
ok("Full pedagogical ground truth verified accessible after submission")

# ---------------------------------------------------------------------------
# Gate 9: Sandbox Case Export to Production Investigation Table
# ---------------------------------------------------------------------------
section("Gate 9 / 10 — Sandbox case export to DB (/cognitive/training/{session_id}/export-case)")
r = client.post(f"/cognitive/training/{session_id}/export-case", headers=headers)
assert_eq("Status code", r.status_code, 200)
export_data = r.json()

exported_case_id = export_data.get("exported_case_id")
case_number = export_data.get("case_number")
assert_in("Export title has [TRAINING SIMULATION]", "[TRAINING SIMULATION]", export_data.get("title", ""))
assert_in("Case number prefix", "TRN-", case_number)
assert_ge("Evidence files created count", export_data.get("evidence_files_created", 0), 2)
assert_ge("Evidence events created count", export_data.get("evidence_events_created", 0), 5)
ok(f"Training session successfully exported to case: {case_number} (ID={exported_case_id})")

# Verify case queryable in core /cases endpoint
r_case = client.get(f"/cases/{exported_case_id}", headers=headers)
assert_eq("Exported case retrieval status", r_case.status_code, 200)
c_obj = r_case.json()
assert_in("TRAINING_SIMULATOR in tags", "TRAINING_SIMULATOR", c_obj.get("tags", []))
assert_in("SYNTHETIC in tags", "SYNTHETIC", c_obj.get("tags", []))
ok("Exported case verified in production investigations registry")

# ---------------------------------------------------------------------------
# Gate 10: Post-Submission Persistence & Idempotency
# ---------------------------------------------------------------------------
section("Gate 10 / 10 — Post-submission persistence & idempotency")
r = client.get(f"/cognitive/training/{session_id}", headers=headers)
assert_eq("Status code", r.status_code, 200)
recheck = r.json()

assert_eq("is_evaluated is True", recheck.get("is_evaluated"), True)
assert_eq("has_hints is True", recheck.get("has_hints"), True)
assert_eq("evaluation score is 100", recheck.get("evaluation", {}).get("score_pct"), 100)
ok("Session state faithfully persisted in simulator memory")

# ---------------------------------------------------------------------------
# Final Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print(f"{BOLD}FEATURE 11 LIVE E2E VERIFICATION RESULTS:{RESET}")
print(f"  Passed Checks: {GREEN}{passed}{RESET}")
print(f"  Failed Checks: {RED}{failed}{RESET}")
print("=" * 70)

if failed > 0:
    print(f"\n{RED}{BOLD}❌ Feature 11 Live Verification FAILED with {failed} failures.{RESET}\n")
    sys.exit(1)
else:
    print(f"\n{GREEN}{BOLD}✅ Feature 11 Training Simulator Live Verification PASSED completely!{RESET}\n")
    sys.exit(0)
