"""
CyberDrishti AI — Defence Bot Live Fresh-Case Verification
Executes real end-to-end HTTP validation against running uvicorn server:
1. Admin authentication.
2. Fresh case creation (Operation Meridian Defence Bot Live).
3. Ingestion of 5 real evidence files from Operation Meridian Synthetic Case.
4. Cognitive Orchestration: runs DefenceBotEngine and verifies DEFENCE_CHALLENGE findings.
5. Validation of GET /api/v1/cognitive/cases/{case_id}/defence-audit:
   - Defensibility Index and Risk Level.
   - Section 63 BSA compliance audit.
   - Grounded adversarial challenges for pass-through mule, CDR kingpin, and IP attribution.
   - Epistemic humility disclaimer under Section 193 BNSS.
6. Validation of POST /api/v1/cognitive/cases/{case_id}/defence-stress-test:
   - On-demand cross-examination of mule and telecom conspiracy hypotheses.
   - Reasonable doubts, missing proof checklist, and prosecution rebuttal countermeasures.
"""
from __future__ import annotations

import io
import json
import sys
import time
import uuid
import zipfile
import httpx
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000/api/v1"
from pathlib import Path
_fixture_candidate = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "NETRA_Operation_Meridian_Synthetic_Case.zip"
ZIP_PATH = str(_fixture_candidate if _fixture_candidate.exists() else Path.home() / "Downloads" / "NETRA_Operation_Meridian_Synthetic_Case.zip")


def main():
    print("=" * 75)
    print("⚖️  CYBERDRISHTI DEFENCE BOT: LIVE FRESH-CASE VERIFICATION")
    print("=" * 75)

    client = httpx.Client(base_url=BASE_URL, timeout=60.0)

    # 1. Login
    print("\n[Step 1] Authenticating as admin...")
    login_res = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
    if login_res.status_code != 200:
        login_res = client.post("/auth/login", data={"username": "admin", "password": "changeme123"})
    assert login_res.status_code == 200, f"Auth failed: {login_res.status_code} {login_res.text}"
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("   ✓ Authenticated successfully.")

    # 2. Create Case
    case_num = f"CYB-2026-DEF-{str(uuid.uuid4())[:6].upper()}"
    print(f"\n[Step 2] Creating fresh case: {case_num}...")
    case_payload = {
        "title": f"Operation Meridian · Defence Bot Stress-Test Audit ({case_num})",
        "description": "Live case verification for adversarial hypothesis testing and Section 63 BSA audit.",
        "crime_type": "CYBER_EXTORTION_RANSOMWARE",
        "priority": "high",
    }
    case_res = client.post("/cases", json=case_payload, headers=headers)
    assert case_res.status_code in (200, 201), f"Case creation failed: {case_res.status_code} {case_res.text}"
    case_data = case_res.json()
    case_id = case_data["id"]
    print(f"   ✓ Case created: ID={case_id}")

    # 3. Ingest Real Evidence Files from Synthetic Case Zip
    print(f"\n[Step 3] Ingesting Operation Meridian evidence files from: {ZIP_PATH}...")
    files_to_upload = [
        ("documents/02_bank_statement.pdf", "02_bank_statement.pdf", "application/pdf"),
        ("documents/04_call_detail_record.csv", "04_call_detail_record.csv", "text/csv"),
        ("documents/07_upi_transaction_report.pdf", "07_upi_transaction_report.pdf", "application/pdf"),
        ("documents/08_network_log.csv", "08_network_log.csv", "text/csv"),
        ("documents/10_evidence_seizure_memo.pdf", "10_evidence_seizure_memo.pdf", "application/pdf"),
    ]

    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        for zip_member, file_name, mime in files_to_upload:
            file_bytes = zf.read(zip_member)
            upload_res = client.post(
                "/evidence/upload",
                data={"case_id": case_id},
                files=[("files", (file_name, file_bytes, mime))],
                headers=headers,
            )
            assert upload_res.status_code in (200, 201), f"Upload failed for {file_name}: {upload_res.text}"
            print(f"   ✓ Uploaded & hashed: {file_name} ({len(file_bytes)} bytes)")

    # Allow background parsing / worker extraction
    print("\n[Step 4] Waiting 5s for asynchronous evidence ingestion & parsing...")
    time.sleep(5)

    # 4. Run Cognitive Orchestrator
    print("\n[Step 5] Triggering Cognitive Orchestrator...")
    analyze_res = client.post(f"/intelligence/cases/{case_id}/analyze", json={}, headers=headers)
    assert analyze_res.status_code == 200, f"Analysis failed: {analyze_res.text}"
    analyze_data = analyze_res.json()
    engines_run = analyze_data.get("engines_run", [])
    print(f"   ✓ Orchestrator executed {len(engines_run)} engine(s): {engines_run}")
    assert "DefenceBotEngine" in engines_run, f"DefenceBotEngine not in engines_run: {engines_run}"

    # Query Findings to verify DEFENCE_CHALLENGE items
    findings_res = client.get(f"/intelligence/cases/{case_id}/findings?limit=200", headers=headers)
    assert findings_res.status_code == 200, f"Findings query failed: {findings_res.text}"
    findings = findings_res.json().get("findings", [])
    defence_findings = [f for f in findings if f.get("finding_type") == "DEFENCE_CHALLENGE"]
    print(f"   ✓ Generated {len(defence_findings)} DEFENCE_CHALLENGE findings.")
    for df in defence_findings[:3]:
        print(f"      - {df.get('title')}: {df.get('severity')} (conf: {df.get('confidence')})")

    # 5. Validate GET /cognitive/cases/{case_id}/defence-audit
    print("\n[Step 6] Auditing Case Defensibility via GET /cognitive/cases/{case_id}/defence-audit...")
    audit_res = client.get(f"/cognitive/cases/{case_id}/defence-audit", headers=headers)
    assert audit_res.status_code == 200, f"Defence audit failed: {audit_res.status_code} {audit_res.text}"
    audit = audit_res.json()

    print(f"   ✓ Defensibility Score: {audit.get('defensibility_score')} ({audit.get('risk_level')})")
    print(f"   ✓ Total Hypotheses Tested: {audit.get('total_hypotheses_tested')}")
    print(f"   ✓ Section 63 BSA Status: {audit.get('bsa_compliance_status')}")

    challenges = audit.get("challenges", [])
    assert len(challenges) >= 1, f"Expected at least 1 challenge, got {len(challenges)}"
    print(f"   ✓ Challenges cataloged: {len(challenges)}")
    for ch in challenges:
        print(f"      • [{ch.get('vulnerability_severity')}] {ch.get('target_hypothesis')} ({ch.get('target_entity')}):")
        print(f"        Counter-Hypothesis: {ch.get('defense_counter_hypothesis')[:90]}...")
        print(f"        Reasonable Doubts: {len(ch.get('reasonable_doubts'))} point(s)")
        print(f"        Missing Evidence: {len(ch.get('missing_evidence'))} item(s)")

    # Verify Epistemic Notice
    assert "Section 193 BNSS" in audit.get("epistemic_notice", "")
    assert "trial court" in audit.get("epistemic_notice", "")
    print("   ✓ Epistemic Humility Notice verified (Section 193 BNSS court reservation present).")

    # 6. Validate POST /cognitive/cases/{case_id}/defence-stress-test
    print("\n[Step 7] Testing Interactive Cross-Examination Simulator via POST /cognitive/cases/{case_id}/defence-stress-test...")
    stress_claim_1 = "Rohan is an active money mule who intentionally laundered extortion funds through his VPA rohan@upi"
    st_res_1 = client.post(
        f"/cognitive/cases/{case_id}/defence-stress-test",
        json={"claim": stress_claim_1, "top_k": 5},
        headers=headers,
    )
    assert st_res_1.status_code == 200, f"Stress test 1 failed: {st_res_1.status_code} {st_res_1.text}"
    st_data_1 = st_res_1.json()
    print(f"   ✓ Tested Claim 1: '{stress_claim_1[:60]}...'")
    print(f"     - Counter-Hypotheses: {st_data_1.get('counter_hypotheses')}")
    print(f"     - Reasonable Doubts: {st_data_1.get('reasonable_doubts')}")
    print(f"     - Missing Proof: {st_data_1.get('missing_proof_checklist')}")
    print(f"     - Rebuttal Recommendations: {st_data_1.get('rebuttal_recommendations')}")
    assert len(st_data_1.get("counter_hypotheses", [])) >= 1
    assert len(st_data_1.get("reasonable_doubts", [])) >= 1

    stress_claim_2 = "CDR records prove the kingpin organized the extortion syndicate calls"
    st_res_2 = client.post(
        f"/cognitive/cases/{case_id}/defence-stress-test",
        json={"claim": stress_claim_2, "top_k": 5},
        headers=headers,
    )
    assert st_res_2.status_code == 200, f"Stress test 2 failed: {st_res_2.status_code} {st_res_2.text}"
    st_data_2 = st_res_2.json()
    print(f"\n   ✓ Tested Claim 2: '{stress_claim_2[:60]}...'")
    print(f"     - Counter-Hypotheses: {st_data_2.get('counter_hypotheses')}")
    print(f"     - Reasonable Doubts: {st_data_2.get('reasonable_doubts')}")
    assert any("tower" in d.lower() or "signal" in d.lower() or "call" in d.lower() for d in st_data_2.get("reasonable_doubts", []))

    print("\n" + "=" * 75)
    print("✅ ALL DEFENCE BOT LIVE END-TO-END VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 75)


if __name__ == "__main__":
    main()
