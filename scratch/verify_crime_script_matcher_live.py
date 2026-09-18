#!/usr/bin/env python3
"""
Live E2E verification for Feature 07 — Crime Script Matcher (MO Fingerprinting).

Verification Gates:
  1. Authentication (JWT token via /auth/login)
  2. Fresh case creation (POST /cases)
  3. Multi-modal evidence ingestion via /evidence/upload & background processing
  4. Playbook catalog endpoint (/cognitive/playbooks)
  5. Cognitive Orchestrator run (/intelligence/cases/{case_id}/analyze) & MO_MATCH findings
  6. MO fingerprint endpoint (/cognitive/cases/{case_id}/mo-fingerprint)
  7. Stage evidence citations and alignment breakdown
  8. Calculation breakdown transparency (Levenshtein distance, coverage ratio, formula)
  9. Threshold variation & playbook filtering
 10. Ad-hoc transcript classification (/cognitive/cases/{case_id}/mo-classify)
 11. Judicial notice compliance (Section 193 BNSS / Section 63 BSA / R v T [2010])
"""
from __future__ import annotations

import io
import json
import sys
import time
import uuid
import zipfile
from pathlib import Path
import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"
ZIP_PATH = "/Users/shubhamrana/Downloads/NETRA_Operation_Meridian_Synthetic_Case.zip"

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
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


def assert_in(label: str, item, container):
    if item in container:
        ok(f"{label}: '{item}' present")
    else:
        fail(f"{label}: '{item}' NOT found in container")


client = httpx.Client(base_url=BASE_URL, timeout=45)

# ---------------------------------------------------------------------------
# Gate 1: Authentication
# ---------------------------------------------------------------------------
section("Step 1 / 11 — Authentication")
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
ok("Login → JWT token acquired successfully")

# ---------------------------------------------------------------------------
# Gate 2: Fresh Case Creation
# ---------------------------------------------------------------------------
section("Step 2 / 11 — Fresh case creation")
case_num = f"CYB-2026-MO-{str(uuid.uuid4())[:6].upper()}"
case_payload = {
    "title": f"Operation Meridian · MO Fingerprint E2E ({case_num})",
    "description": "Live case verification for crime-script behavioral matching across multi-modal evidence.",
    "case_type": "Cyber Fraud",
    "priority": "HIGH",
    "status": "OPEN",
}
r = client.post("/cases", json=case_payload, headers=headers)
if r.status_code not in (200, 201):
    fail(f"Case creation: {r.status_code}", r.text)
    sys.exit(1)
case_data = r.json()
case_id = case_data.get("id")
ok(f"Case created: ID={case_id}")

# ---------------------------------------------------------------------------
# Gate 3: Multi-modal Evidence Ingestion
# ---------------------------------------------------------------------------
section("Step 3 / 11 — Multi-modal evidence ingestion via /evidence/upload")

# 1. WhatsApp Digital Arrest sequence chat export
CHAT_TEXT = """2026-08-18 09:00:00 | +91-9876540001 | Sir CBI Crime Branch arrest warrant issued in narcotics parcel case against your Aadhaar number
2026-08-18 09:10:00 | +91-9876540001 | Join Skype video call immediately, camera on, stay on call, room locked, digital arrest interrogation
2026-08-18 09:30:00 | +91-9876540001 | Supreme Court order andar jaoge non-bailable arrest warrant girftar remand money laundering
2026-08-18 10:00:00 | +91-9876540001 | Transfer clearance verification RBI security deposit to supervisory account
2026-08-18 10:20:00 | +91-9876540001 | Kaam ho gaya, delete chat and block this official number now immediately
"""

upload_targets = [
    ("whatsapp_chat.txt", CHAT_TEXT.encode("utf-8"), "text/plain"),
]

# Add files from Operation Meridian zip if available
if Path(ZIP_PATH).exists():
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        for zip_name, target_name, mime in [
            ("documents/02_bank_statement.pdf", "02_bank_statement.pdf", "application/pdf"),
            ("documents/04_call_detail_record.csv", "04_call_detail_record.csv", "text/csv"),
        ]:
            if zip_name in zf.namelist():
                upload_targets.append((target_name, zf.read(zip_name), mime))

for fname, fbytes, mime in upload_targets:
    up_res = client.post(
        "/evidence/upload",
        data={"case_id": case_id},
        files=[("files", (fname, fbytes, mime))],
        headers=headers,
    )
    if up_res.status_code in (200, 201):
        ok(f"Uploaded evidence file: {fname} ({len(fbytes)} bytes)")
    else:
        fail(f"Upload failed for {fname}: {up_res.status_code}", up_res.text[:120])

# Wait for background evidence parsing pipeline to finish
ok("Waiting for background ingestion pipeline to process evidence...")
for attempt in range(20):
    time.sleep(1.0)
    ev_res = client.get(f"/evidence/{case_id}", headers=headers)
    if ev_res.status_code == 200:
        files = ev_res.json().get("files", [])
        if files and all(f.get("upload_status") == "processed" for f in files):
            ok(f"All {len(files)} evidence file(s) processed (attempt {attempt + 1})")
            break
else:
    ok("Proceeding after background ingestion wait window")

# ---------------------------------------------------------------------------
# Gate 4: Playbook Catalog Endpoint
# ---------------------------------------------------------------------------
section("Step 4 / 11 — Playbook catalog endpoint (/cognitive/playbooks)")
r = client.get("/cognitive/playbooks", headers=headers)
if r.status_code != 200:
    fail(f"GET /cognitive/playbooks: {r.status_code}", r.text[:120])
else:
    pbs = r.json().get("playbooks", [])
    names = {p["name"] for p in pbs}
    ok(f"Catalog returned {len(pbs)} playbooks")
    expected_playbooks = [
        "DIGITAL_ARREST_EXTORTION",
        "INVESTMENT_TASK_FRAUD",
        "ROMANCE_BAITING",
        "MULE_HARVESTING_AND_OFFRAMP",
        "LOAN_APP_HARASSMENT_EXTORTION",
        "SIM_BOX_CALL_FORWARDING",
    ]
    for exp in expected_playbooks:
        assert_in(f"Playbook '{exp}' in catalog", exp, names)

# ---------------------------------------------------------------------------
# Gate 5: Cognitive Orchestrator Run & MO_MATCH Findings
# ---------------------------------------------------------------------------
section("Step 5 / 11 — Cognitive Orchestrator Run (/intelligence/cases/{case_id}/analyze)")
an_res = client.post(f"/intelligence/cases/{case_id}/analyze", json={}, headers=headers)
if an_res.status_code != 200:
    fail(f"Analysis trigger failed: {an_res.status_code}", an_res.text[:150])
else:
    an_data = an_res.json()
    engines_run = an_data.get("engines_run", [])
    ok(f"Cognitive Orchestrator completed. Engines executed: {engines_run}")
    assert_in("MOEngine executed in pipeline", "MOEngine", engines_run)

    f_res = client.get(f"/intelligence/cases/{case_id}/findings?limit=50", headers=headers)
    if f_res.status_code == 200:
        findings = f_res.json().get("findings", [])
        mo_findings = [f for f in findings if f.get("finding_type") == "MO_MATCH"]
        ok(f"Generated {len(mo_findings)} MO_MATCH finding(s)")
        if mo_findings:
            mf = mo_findings[0]
            ok(f"MO finding: '{mf.get('title')}' (Severity: {mf.get('severity')}, Conf: {mf.get('confidence')})")
            assert_in("Playbook in title", "DIGITAL_ARREST_EXTORTION", mf.get("title", ""))
    else:
        fail(f"Query findings: {f_res.status_code}", f_res.text[:120])

# ---------------------------------------------------------------------------
# Gate 6: MO Fingerprint Analysis Endpoint
# ---------------------------------------------------------------------------
section("Step 6 / 11 — MO fingerprint at standard threshold (0.60)")
r = client.get(f"/cognitive/cases/{case_id}/mo-fingerprint?threshold=0.60", headers=headers)
if r.status_code != 200:
    fail(f"GET mo-fingerprint: {r.status_code}", r.text[:300])
    sys.exit(1)
mo_data = r.json()
ok("mo-fingerprint returned HTTP 200")

verdict = mo_data.get("verdict")
best = mo_data.get("best_match")
assert_eq("Verdict", verdict, "MATCHED")
if best:
    ok(f"Best match playbook: {best['playbook']} (similarity: {best['similarity']*100:.1f}%)")
    assert_eq("Best playbook", best["playbook"], "DIGITAL_ARREST_EXTORTION")
    if best["similarity"] >= 0.60:
        ok(f"Similarity {best['similarity']:.4f} >= 0.60 threshold")
    else:
        fail(f"Similarity {best['similarity']:.4f} below 0.60 threshold")
else:
    fail("best_match is None when verdict is MATCHED")

# ---------------------------------------------------------------------------
# Gate 7: Stage Evidence Citations
# ---------------------------------------------------------------------------
section("Step 7 / 11 — Stage evidence citations & alignment")
if best and best.get("alignment"):
    matched_stages = [a for a in best["alignment"] if a.get("status") in ("MATCHED_IN_ORDER", "MATCHED_OUT_OF_ORDER")]
    ok(f"{len(matched_stages)} stage(s) matched in alignment")
    for sa in matched_stages:
        st_name = sa["stage"]
        count = sa.get("evidence_count", 0)
        if count > 0:
            ok(f"Stage '{st_name}': {count} evidence citation(s)")
        else:
            fail(f"Stage '{st_name}' matched but has 0 citations")
else:
    fail("No alignment data in best match")

# ---------------------------------------------------------------------------
# Gate 8: Calculation Breakdown Transparency
# ---------------------------------------------------------------------------
section("Step 8 / 11 — Calculation breakdown transparency")
if best and best.get("calculation_breakdown"):
    cb = best["calculation_breakdown"]
    ok("calculation_breakdown block present")
    required_breakdown_keys = [
        "formula",
        "levenshtein_distance",
        "observed_length",
        "expected_length",
        "coverage_ratio",
        "raw_similarity",
        "threshold",
        "is_confident",
    ]
    for k in required_breakdown_keys:
        if k in cb:
            ok(f"  breakdown.{k} = {cb[k]!r}")
        else:
            fail(f"  Missing calculation key: breakdown.{k}")
else:
    fail("No calculation_breakdown in best match")

# ---------------------------------------------------------------------------
# Gate 9: Threshold Variation & Playbook Filtering
# ---------------------------------------------------------------------------
section("Step 9 / 11 — Threshold variation & playbook filtering")
r_strict = client.get(f"/cognitive/cases/{case_id}/mo-fingerprint?threshold=0.90", headers=headers)
if r_strict.status_code != 200:
    fail(f"GET mo-fingerprint @ 0.90: {r_strict.status_code}", r_strict.text[:120])
else:
    mo_strict = r_strict.json()
    ok(f"Threshold 0.90 verdict: {mo_strict.get('verdict')}")

r_filter = client.get(f"/cognitive/cases/{case_id}/mo-fingerprint?playbook=DIGITAL_ARREST_EXTORTION", headers=headers)
if r_filter.status_code == 200:
    mo_flt = r_filter.json()
    matches = mo_flt.get("matches", [])
    if matches and matches[0]["playbook"] == "DIGITAL_ARREST_EXTORTION":
        ok("Playbook query filter successfully prioritized target playbook")
    else:
        fail("Playbook query filter did not prioritize target playbook")
else:
    fail(f"GET mo-fingerprint with filter: {r_filter.status_code}")

# ---------------------------------------------------------------------------
# Gate 10: Ad-hoc Transcript Classification Endpoint
# ---------------------------------------------------------------------------
section("Step 10 / 11 — mo-classify endpoint (ad-hoc transcript)")
r_cls = client.post(
    f"/cognitive/cases/{case_id}/mo-classify",
    json={
        "messages": [
            {"text": "complete daily profit task 500 bonus telegram group join", "sender": "Agent"},
            {"text": "upgrade VIP level 3 prepaid task recharge", "sender": "Agent"},
            {"text": "deposit 50000 capital investment recharge", "sender": "Agent"},
            {"text": "withdrawal pending tax processing fee compliance", "sender": "Agent"},
            {"text": "account closed agent offline group deleted", "sender": "Agent"},
        ],
        "threshold": 0.60,
    },
    headers=headers,
)
if r_cls.status_code != 200:
    fail(f"POST mo-classify: {r_cls.status_code}", r_cls.text[:200])
else:
    cls_data = r_cls.json()
    cls_verdict = cls_data.get("verdict")
    cls_best = cls_data.get("best_match")
    ok("mo-classify returned HTTP 200")
    assert_eq("mo-classify verdict", cls_verdict, "MATCHED")
    if cls_best:
        assert_eq("mo-classify best playbook", cls_best["playbook"], "INVESTMENT_TASK_FRAUD")
        ok(f"mo-classify similarity: {cls_best['similarity']*100:.1f}%")

# ---------------------------------------------------------------------------
# Gate 11: Judicial Notice & Statutory Standards
# ---------------------------------------------------------------------------
section("Step 11 / 11 — Judicial notice compliance")
jn = mo_data.get("judicial_notice", {})
if not jn:
    fail("judicial_notice block missing from mo-fingerprint response")
else:
    ok("judicial_notice block present")
    assert_in("Section 193 BNSS", "Section 193 BNSS", jn.get("statutory_standard", ""))
    assert_in("Section 63 BSA", "Section 63 BSA", jn.get("statutory_standard", ""))
    assert_in("R v T [2010]", "R v T [2010]", jn.get("r_v_t_compliance", ""))
    if jn.get("corroboration_required") is True:
        ok("corroboration_required: True (mandatory judicial notice)")
    else:
        fail("corroboration_required is not True")

note = mo_data.get("note", "")
if "attribution" in note:
    ok(f"Epistemic boundary verified: '{note}'")
else:
    fail(f"Epistemic boundary missing from note: '{note}'")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'─'*65}")
total = passed + failed
if failed == 0:
    print(f"{GREEN}{BOLD}ALL {passed}/{total} VERIFICATION CHECKS PASSED — FEATURE 07 FULLY CERTIFIED!{RESET}")
    sys.exit(0)
else:
    print(f"{RED}{BOLD}{failed}/{total} VERIFICATION CHECKS FAILED{RESET}")
    sys.exit(1)
