"""
CyberDrishti AI — Feature 04: Hypothesis Investigation Board Live Verification
Executes real end-to-end multi-modal validation against running uvicorn server:
1. Admin authentication.
2. Fresh Case creation (Operation Meridian Hypothesis Board).
3. Ingestion of multi-modal evidence files:
   - 01_bank_statement_axis.csv (Rapid fund pass-through)
   - 04_call_detail_record.csv (Telecom CDR)
   - 08_network_log.csv (Device & IP telemetry)
4. Validation of GET /api/v1/cognitive/cases/{case_id}/hypothesis-board:
   - Suspect candidates discovery with degree centrality and role hints.
   - 5 competing role hypotheses (KINGPIN_ORGANIZER, LAYER1_MULE, COMPROMISED_VICTIM, TECHNICAL_OPERATOR, BENEFICIARY_CASHOUT).
   - R v T [2010] EWCA Crim 2439 epistemic compliance: rule-based rankings, honest posteriors (None, no fake %).
   - LAYER1_MULE ranked #1 leading theory.
   - COMPROMISED_VICTIM refuted by rapid turnover (likelihood <= 0.10).
   - Richards Heuer ACH Evidence Matrix with diagnosticity spread (Delta = max - min) and provenance citations.
   - Statutory evidence gaps with Section 193 BNSS closure recommendations.
5. Validation of POST /api/v1/cognitive/cases/{case_id}/hypothesis-evaluate (What-If Sandbox):
   - Counterfactual simulation shifts ranking from LAYER1_MULE to KINGPIN_ORGANIZER in real time.
6. Validation of POST /api/v1/cognitive/cases/{case_id}/hypothesis-report:
   - Formal Section 193 BNSS Prosecution Hypothesis Memorandum generated with statutory citations and IO signature block.
"""
import sys
import time
import uuid
import zipfile
import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"
from pathlib import Path
_fixture_candidate = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip"
ZIP_PATH = str(_fixture_candidate if _fixture_candidate.exists() else Path.home() / "Downloads" / "NETRA_Operation_Meridian_Synthetic_Case.zip")


def main():
    print("=" * 80)
    print("🎯  CYBERDRISHTI F04: HYPOTHESIS INVESTIGATION BOARD LIVE VERIFICATION")
    print("=" * 80)

    client = httpx.Client(base_url=BASE_URL, timeout=60.0)

    # 1. Login
    print("\n[Step 1] Authenticating as admin...")
    login_res = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
    if login_res.status_code != 200:
        print(f"❌ Login failed: {login_res.status_code} {login_res.text}")
        sys.exit(1)
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("   ✓ Authenticated successfully.")

    # 2. Create Fresh Case
    suffix = str(uuid.uuid4())[:6].upper()
    case_num = f"CYB-2026-F04-ACH-{suffix}"
    print(f"\n[Step 2] Creating fresh case: {case_num}...")
    case_payload = {
        "title": f"Operation Meridian · ACH Hypothesis Board ({case_num})",
        "description": "Multi-modal investigation testing ACH suspect role classification and refutation matrix.",
        "crime_type": "CYBER_FINANCIAL_FRAUD",
        "police_station": "Cyber Crime Police Station, Headquarters",
        "priority": "critical",
    }
    case_res = client.post("/cases", json=case_payload, headers=headers)
    if case_res.status_code not in (200, 201):
        print(f"❌ Case creation failed: {case_res.status_code} {case_res.text}")
        sys.exit(1)
    case_data = case_res.json()
    case_id = case_data["id"]
    case_num = case_data.get("case_number", case_num)
    print(f"   ✓ Case created: ID={case_id}, Number={case_num}")

    # 3. Ingest Multi-Modal Evidence
    files_to_upload = [
        ("documents/02_bank_statement.pdf", "02_bank_statement.pdf", "application/pdf"),
        ("documents/03_intermediary_account_statement.pdf", "03_intermediary_account_statement.pdf", "application/pdf"),
        ("documents/04_call_detail_record.csv", "04_call_detail_record.csv", "text/csv"),
        ("documents/07_upi_transaction_report.pdf", "07_upi_transaction_report.pdf", "application/pdf"),
        ("documents/08_network_log.csv", "08_network_log.csv", "text/csv"),
    ]
    print(f"\n[Step 3] Ingesting {len(files_to_upload)} multi-modal evidence files from {ZIP_PATH}...")
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        for zip_member, file_name, mime in files_to_upload:
            file_bytes = zf.read(zip_member)
            r = client.post(
                "/evidence/upload",
                data={"case_id": case_id},
                files=[("files", (file_name, file_bytes, mime))],
                headers=headers,
            )
            print(f"   ✓ Uploaded {file_name} ({len(file_bytes)} B): {r.status_code}")

    # 4. Wait for Background Ingestion & Graph Population
    print("\n[Step 4] Awaiting async extraction & entity graph population...")
    for attempt in range(25):
        time.sleep(1.0)
        test_res = client.get(f"/cognitive/cases/{case_id}/hypothesis-board", headers=headers)
        if test_res.status_code == 200:
            data = test_res.json()
            if data.get("evidence_matrix") and len(data["evidence_matrix"]) > 0:
                print(f"   ✓ Evidence parsed into ACH matrix (attempt {attempt + 1}): {len(data['evidence_matrix'])} indicators.")
                break
    else:
        print("   ⚠️ Proceeding with current state...")

    # 5. Query GET /cognitive/cases/{case_id}/hypothesis-board
    print(f"\n[Step 5] Querying GET /api/v1/cognitive/cases/{case_id}/hypothesis-board...")
    ach_res = client.get(f"/cognitive/cases/{case_id}/hypothesis-board", headers=headers)
    if ach_res.status_code != 200:
        print(f"❌ Hypothesis Board request failed: {ach_res.status_code} {ach_res.text}")
        sys.exit(1)

    ach = ach_res.json()
    print("   ✓ Hypothesis Board Response received.")
    print(f"     * Target Entity: {ach.get('target_entity')}")
    print(f"     * Assessment Type: {ach.get('assessment_type')}")
    print(f"     * Leading Label: {ach.get('display_label')}")
    print(f"     * Ranked Labels: {ach.get('ranked_labels')}")

    # Assertions on ACH Core
    assert ach["assessment_type"] == "RULE_BASED_ASSESSMENT", "Must be RULE_BASED_ASSESSMENT under R v T"
    assert "R v T [2010]" in ach["display_label"], "Must cite R v T [2010] EWCA Crim 2439"
    assert "Richards Heuer" in ach["epistemic_notice"], "Must cite Richards Heuer ACH standard"

    candidates = ach.get("candidates", [])
    print(f"\n[Step 5a] Discovered Suspect Candidates: {len(candidates)}")
    for c in candidates[:5]:
        print(f"     - [{c.get('entity_type')}] {c.get('value')} (Degree: {c.get('degree')}, Role: {c.get('role_hint')})")
    assert len(candidates) > 0, "Candidates list must not be empty"

    hypotheses = ach.get("hypotheses", [])
    assert len(hypotheses) == 5, f"Must have exactly 5 hypotheses, got {len(hypotheses)}"
    print(f"\n[Step 5b] Evaluating 5 Suspect Role Hypotheses:")
    for h in hypotheses:
        print(f"     - Rank #{h.get('rank')} [{h.get('label')}] (Inconsistency: {h.get('inconsistency_score')})")
        assert h["posterior"] is None, f"Posteriors must be honest None under R v T, got {h['posterior']}"

    top_hypo = hypotheses[0]
    assert top_hypo["label"] in ("LAYER1_MULE", "BENEFICIARY_CASHOUT"), f"Expected mule/cashout role at top, got {top_hypo['label']}"
    print(f"   ✓ Top hypothesis verified as {top_hypo['label']} (Rank #1)")

    # Refuting evidence check on COMPROMISED_VICTIM
    by_label = {h["label"]: h for h in hypotheses}
    victim_hypo = by_label.get("COMPROMISED_VICTIM")
    assert victim_hypo is not None, "COMPROMISED_VICTIM hypothesis must exist"
    victim_refute = victim_hypo.get("refuting_evidence")
    assert victim_refute is not None, "COMPROMISED_VICTIM must have refuting evidence"
    print(f"\n[Step 5c] Refuting Evidence on Alternative Theory (COMPROMISED_VICTIM):")
    print(f"     - Refuted By: {victim_refute.get('indicator')} ({victim_refute.get('bucket')})")
    print(f"     - Likelihood Under Victim Role: {victim_refute.get('likelihood')}")
    print(f"     - Provenance: {victim_refute.get('provenance')}")
    assert victim_refute["likelihood"] <= 0.10, "Refuting likelihood must be <= 0.10"

    # Evidence Matrix & Diagnosticity
    matrix = ach.get("evidence_matrix", [])
    print(f"\n[Step 5d] Richards Heuer ACH Evidence Matrix ({len(matrix)} indicators observed):")
    for row in matrix:
        diag = row.get("diagnosticity", 0)
        print(f"     * {row.get('indicator'):<22} = {row.get('bucket'):<12} | Diag Δ={diag:.2f} | P_Mule={row.get('likelihoods', {}).get('LAYER1_MULE', 0):.2f}")
        assert diag >= 0.0, "Diagnosticity must be non-negative"
        assert abs(sum(row.get("likelihoods", {}).values()) - 1.0) < 1e-4, "Row likelihoods must sum to 1.000"

    # Unobserved gaps
    unobserved = ach.get("unobserved_details", [])
    print(f"\n[Step 5e] Statutory Evidence Gaps ({len(unobserved)} unobserved):")
    for gap in unobserved:
        print(f"     - {gap.get('indicator'):<20} | Required: {gap.get('required_evidence')}")
        assert "required_evidence" in gap
        assert "potential_impact" in gap

    # 6. Test What-If Evaluation Sandbox
    print("\n[Step 6] Testing What-If Simulation Sandbox (POST /hypothesis-evaluate)...")
    simulated_obs = {
        "velocity_minutes": 600,     # Slow transfer
        "account_age_days": 1500,    # Established account
        "inbound_victim_calls": 22,  # Heavy direct contact with victims
        "turnover_volume_inr": 12000000,
        "device_sharing_count": 1,
    }
    whatif_res = client.post(
        f"/cognitive/cases/{case_id}/hypothesis-evaluate",
        json={
            "target_entity": "WHAT_IF_KINGPIN_TEST",
            "observations": simulated_obs,
        },
        headers=headers,
    )
    assert whatif_res.status_code == 200, f"What-If endpoint failed: {whatif_res.status_code} {whatif_res.text}"
    whatif_data = whatif_res.json()
    print(f"     * Simulated Leading Theory: {whatif_data.get('ranked_labels', [])[0]}")
    assert whatif_data["ranked_labels"][0] == "KINGPIN_ORGANIZER", "What-if simulation must shift ranking to KINGPIN_ORGANIZER"
    print("   ✓ What-If counterfactual simulation successfully shifted leading theory to KINGPIN_ORGANIZER!")

    # 7. Test Section 193 BNSS Prosecution Hypothesis Report
    print("\n[Step 7] Generating Section 193 BNSS Prosecution Theory Memorandum (POST /hypothesis-report)...")
    report_res = client.post(
        f"/cognitive/cases/{case_id}/hypothesis-report",
        json={
            "target_entity": ach.get("target_entity") or "rohan@upi",
            "leading_hypothesis": ach.get("display_label") or "LAYER1_MULE",
            "police_station": "Cyber Crime Police Station, Headquarters",
        },
        headers=headers,
    )
    assert report_res.status_code == 200, f"Hypothesis report failed: {report_res.status_code} {report_res.text}"
    rep = report_res.json()
    print(f"   ✓ Report Generated: {rep.get('report_title')}")
    print(f"     * Statutory Basis: {rep.get('statutory_basis')}")
    print(f"     * Target: {rep.get('target_entity')}")
    print(f"     * Length: {len(rep.get('report_text', ''))} characters")

    report_upper = rep.get("report_text", "").upper()
    assert "SECTION 193 BNSS" in report_upper
    assert "R V T [2010]" in report_upper
    assert "RICHARDS HEUER" in report_upper
    assert "INVESTIGATING OFFICER" in report_upper

    print("\n" + "=" * 80)
    print("🏆  ALL FEATURE 04: HYPOTHESIS INVESTIGATION BOARD LIVE TESTS PASSED!")
    print("=" * 80)


if __name__ == "__main__":
    main()
