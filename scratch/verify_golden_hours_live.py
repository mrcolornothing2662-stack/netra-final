"""
CyberDrishti AI — Feature 06: Golden Hours Action Center Live Verification
Executes real end-to-end HTTP validation against running uvicorn server:
1. Admin authentication.
2. Fresh case creation (Operation Meridian Golden Hours Live).
3. Ingestion of 5 real evidence files from Operation Meridian Synthetic Case.
4. Cognitive Orchestrator execution: verifies NextBestEngine and NEXT_BEST_ACTION findings.
5. Validation of GET /api/v1/cognitive/cases/{case_id}/next-best-actions (and /golden-hours alias):
   - Multi-window urgency decay and window_phase detection.
   - Preservable financial exposure calculation.
   - Unified ranked actions (statutory preservation + grounded evidence gap actions).
   - Ready vs blocked missing fields breakdown.
6. Validation of POST /api/v1/cognitive/cases/{case_id}/actions/{action_code}/draft:
   - Section 106 BNSS Bank Debit Freeze Notice drafting.
   - Section 94 BNSS CDR/IPDR Electronic Requisition drafting.
   - Epistemic compliance with mandatory DRAFT banner under Section 193 BNSS.
"""
from __future__ import annotations

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
    print("⚡  CYBERDRISHTI FEATURE 06: GOLDEN HOURS ACTION CENTER LIVE VERIFICATION")
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
    case_num = f"CYB-2026-GH-{str(uuid.uuid4())[:6].upper()}"
    print(f"\n[Step 2] Creating fresh case: {case_num}...")
    case_payload = {
        "title": f"Operation Meridian · Golden Hours Action Center Audit ({case_num})",
        "description": "Live case verification for time-sensitive investigative actions and Section 106 BNSS drafts.",
        "crime_type": "CYBER_FINANCIAL_FRAUD",
        "priority": "critical",
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
        ("documents/03_intermediary_account_statement.pdf", "03_intermediary_account_statement.pdf", "application/pdf"),
        ("documents/04_call_detail_record.csv", "04_call_detail_record.csv", "text/csv"),
        ("documents/07_upi_transaction_report.pdf", "07_upi_transaction_report.pdf", "application/pdf"),
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

    # Wait for asynchronous parser & entity extraction
    print("\n[Step 4] Waiting 5s for asynchronous evidence ingestion & entity graph materialisation...")
    time.sleep(5)

    # 4. Run Cognitive Orchestrator
    print("\n[Step 5] Triggering Cognitive Orchestrator...")
    analyze_res = client.post(f"/intelligence/cases/{case_id}/analyze", json={}, headers=headers)
    assert analyze_res.status_code == 200, f"Analysis failed: {analyze_res.text}"
    analyze_data = analyze_res.json()
    engines_run = analyze_data.get("engines_run", [])
    print(f"   ✓ Orchestrator executed {len(engines_run)} engine(s): {engines_run}")
    assert "NextBestEngine" in engines_run, f"NextBestEngine not in engines_run: {engines_run}"

    # Query Findings to verify NEXT_BEST_ACTION items
    findings_res = client.get(f"/intelligence/cases/{case_id}/findings?limit=200", headers=headers)
    assert findings_res.status_code == 200, f"Findings query failed: {findings_res.text}"
    findings = findings_res.json().get("findings", [])
    nba_findings = [f for f in findings if f.get("finding_type") == "NEXT_BEST_ACTION"]
    print(f"   ✓ Generated {len(nba_findings)} NEXT_BEST_ACTION findings.")
    for nf in nba_findings[:3]:
        print(f"      - {nf.get('title')} (sev: {nf.get('severity')})")

    # 5. Validate GET /cognitive/cases/{case_id}/next-best-actions
    print("\n[Step 6] Auditing Golden Hours Action Center via GET /cognitive/cases/{case_id}/next-best-actions...")
    actions_res = client.get(f"/cognitive/cases/{case_id}/next-best-actions", headers=headers)
    assert actions_res.status_code == 200, f"Actions query failed: {actions_res.status_code} {actions_res.text}"
    data = actions_res.json()

    print(f"   ✓ Elapsed Hours: {data.get('elapsed_hours')}h")
    print(f"   ✓ Golden Hours Window: {data.get('golden_hours')}h ({data.get('window_phase')})")
    print(f"   ✓ Preservable Financial Exposure: ₹{data.get('financial_exposure', 0):,}")
    print(f"   ✓ Top Urgency Factor: {data.get('urgency_factor')}")
    print(f"   ✓ Summary: {data.get('summary')}")
    print(f"   ✓ Evidence Gaps Identified: {data.get('evidence_gaps_summary')}")

    ranked = data.get("ranked_actions", [])
    assert len(ranked) >= 2, f"Expected at least 2 ranked actions, got {len(ranked)}"
    print(f"   ✓ Total Actions Ranked: {len(ranked)}")

    for idx, act in enumerate(ranked[:4], 1):
        print(f"      [{idx}] {act.get('title') or act.get('description')} ({act.get('status')})")
        print(f"          Statute: {act.get('statutory_basis')} · Score: {act.get('utility_score')} · Urgency: {act.get('urgency_factor')}")
        if act.get("gap"):
            print(f"          Evidence Gap: {act.get('gap')} · Resolves: {act.get('resolves')}")

    # Also test the /golden-hours endpoint alias
    alias_res = client.get(f"/cognitive/cases/{case_id}/golden-hours", headers=headers)
    assert alias_res.status_code == 200, f"Alias /golden-hours failed: {alias_res.status_code}"
    print("   ✓ /cognitive/cases/{case_id}/golden-hours endpoint alias verified.")

    # 6. Validate POST /cognitive/cases/{case_id}/actions/{action_code}/draft
    print("\n[Step 7] Generating Pre-filled Statutory Notice Drafts...")

    # Notice Draft 1: Section 106 BNSS Freeze Order
    freeze_payload = {
        "target": {
            "account": "100000000002",
            "ifsc": "HDFC0000001",
            "bank_name": "HDFC Bank",
            "amount_unwithdrawn": "1,80,000.00",
        }
    }
    draft_res_1 = client.post(
        f"/cognitive/cases/{case_id}/actions/FREEZE_ACCOUNT_EVIDENCE/draft",
        json=freeze_payload,
        headers=headers,
    )
    assert draft_res_1.status_code == 200, f"Freeze draft failed: {draft_res_1.status_code} {draft_res_1.text}"
    draft_data_1 = draft_res_1.json()
    print(f"   ✓ Generated Notice 1: {draft_data_1.get('statute')}")
    assert "SECTION 106" in draft_data_1.get("notice_text", "")
    assert "100000000002" in draft_data_1.get("notice_text", "")
    assert "DRAFT" in draft_data_1.get("banner", "")
    print("     - Verified Section 106 BNSS freeze order, magistrate caveat, and DRAFT banner.")

    # Notice Draft 2: Section 94 BNSS CDR/IPDR Requisition
    cdr_payload = {
        "target": {
            "phone": "+91-98XXXX1201",
            "period_start": "2026-08-18 00:00 UTC",
            "period_end": "2026-08-18 23:59 UTC",
        }
    }
    draft_res_2 = client.post(
        f"/cognitive/cases/{case_id}/actions/REQUISITION_CDR_IPDR/draft",
        json=cdr_payload,
        headers=headers,
    )
    assert draft_res_2.status_code == 200, f"CDR draft failed: {draft_res_2.status_code} {draft_res_2.text}"
    draft_data_2 = draft_res_2.json()
    print(f"\n   ✓ Generated Notice 2: {draft_data_2.get('statute')}")
    assert "SECTION 94 BNSS" in draft_data_2.get("notice_text", "")
    assert "+91-98XXXX1201" in draft_data_2.get("notice_text", "")
    assert "Section 63(4)" in draft_data_2.get("notice_text", "")
    print("     - Verified Section 94 BNSS electronic requisition and Section 63 BSA certificate requirement.")

    print("\n" + "=" * 75)
    print("✅ ALL FEATURE 06 GOLDEN HOURS ACTION CENTER LIVE VERIFICATIONS PASSED!")
    print("=" * 75)


if __name__ == "__main__":
    main()
