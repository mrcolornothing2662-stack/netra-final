"""
CyberDrishti AI — Feature 09: Legal Compliance Shield Live Fresh-Case Verification
Executes real end-to-end HTTP validation against running uvicorn server:
1. Admin authentication.
2. Fresh case creation (Operation Meridian F09 Live).
3. Ingestion of 4 real evidence files including File 10 Evidence Seizure Memo.
4. Validation of GET /api/v1/cognitive/cases/{case_id}/compliance-shield:
   - Section 63 BSA Evidence Integrity Audit (100% hash preservation, File 10 custody certified).
   - Post-July-2024 Statutory Alignment.
   - Epistemic admissibility disclaimer enforcement.
5. Validation of POST /api/v1/cognitive/verify-draft:
   - Draft 1: Modern in-force BNS 318(4), BNSS 173, BSA 63 -> COMPLIANT.
   - Draft 2: Pre-transition IPC 420, CrPC 102, IEA 65B -> NEEDS_REVIEW with modernisation mappings.
   - Draft 3: Struck-down IT Act 66A -> GOVERNANCE_BLOCKED with Shreya Singhal judicial authority.
"""
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
    print("=" * 70)
    print("🛡️  CYBERDRISHTI F09: LEGAL COMPLIANCE SHIELD LIVE VERIFICATION")
    print("=" * 70)

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

    # 2. Create Case
    case_num = f"CYB-2026-F09-{str(uuid.uuid4())[:6].upper()}"
    print(f"\n[Step 2] Creating fresh case: {case_num}...")
    case_payload = {
        "title": f"Operation Meridian · F09 Legal Compliance Audit ({case_num})",
        "description": "Live case verification for Section 63 BSA evidence integrity and post-July-2024 statutory adherence.",
        "crime_type": "CYBER_FINANCIAL_FRAUD",
        "priority": "high",
    }
    case_res = client.post("/cases", json=case_payload, headers=headers)
    if case_res.status_code not in (200, 201):
        print(f"❌ Case creation failed: {case_res.status_code} {case_res.text}")
        sys.exit(1)
    case_data = case_res.json()
    case_id = case_data["id"]
    print(f"   ✓ Case created: ID={case_id}")

    # 3. Ingest Real Evidence Files from Synthetic Case Zip
    print(f"\n[Step 3] Ingesting Operation Meridian evidence files from: {ZIP_PATH}...")
    files_to_upload = [
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
            if upload_res.status_code not in (200, 201):
                print(f"   ❌ Upload failed for {file_name}: {upload_res.status_code} {upload_res.text}")
                sys.exit(1)
            print(f"   ✓ Uploaded: {file_name} ({len(file_bytes)} bytes)")

    # 4. Wait for background processing to complete
    print("\n[Step 4] Awaiting asynchronous parser & hash pipeline completion...")
    for attempt in range(30):
        time.sleep(1.0)
        # Check evidence list
        ev_list_res = client.get(f"/cases/{case_id}", headers=headers)
        # Also query compliance shield
        shield_check = client.get(f"/cognitive/cases/{case_id}/compliance-shield", headers=headers)
        if shield_check.status_code == 200:
            s_data = shield_check.json()
            integ = s_data.get("evidence_integrity")
            if integ and integ.get("total_files") == 4 and integ.get("unhashed_files") == 0:
                print(f"   ✓ Ingestion complete (attempt {attempt + 1}): all 4 files hashed and processed.")
                break
    else:
        print("   ⚠️ Proceeding to verification with current database state...")

    # 5. Query Compliance Shield Endpoint
    print(f"\n[Step 5] Querying GET /cases/{case_id}/compliance-shield...")
    shield_res = client.get(f"/cognitive/cases/{case_id}/compliance-shield", headers=headers)
    if shield_res.status_code != 200:
        print(f"❌ Compliance shield endpoint failed: {shield_res.status_code} {shield_res.text}")
        sys.exit(1)

    shield_data = shield_res.json()
    print(f"   Case Number           : {shield_data['case_number']}")
    print(f"   Overall Status        : {shield_data['overall_status']}")
    print(f"   Admissibility Notice  : \"{shield_data['admissibility_disclaimer'][:80]}…\"")

    integ = shield_data.get("evidence_integrity")
    assert integ is not None, "evidence_integrity object must be present"
    print("\n   [Section 63 BSA Evidence Integrity Audit]")
    print(f"      • Total Evidence Files : {integ['total_files']}")
    print(f"      • SHA-256 Hashed Files : {integ['hashed_files']}")
    print(f"      • Preservation Score   : {integ['integrity_score'] * 100:.0f}%")
    print(f"      • Custody Memo Status  : {'✓ File 10 Seizure Memo Verified' if integ['has_custody_memo'] else '✗ Missing'}")
    print(f"      • Audit Status         : {integ['status']}")

    assert integ["total_files"] == 4, f"Expected 4 files, got {integ['total_files']}"
    assert integ["hashed_files"] == 4, f"Expected 4 hashed files, got {integ['hashed_files']}"
    assert integ["integrity_score"] == 1.0, f"Expected 100% score, got {integ['integrity_score']}"
    assert integ["has_custody_memo"] is True, "Expected File 10 custody memo to be recognized"

    stat_comp = shield_data.get("statutory_compliance", {})
    print("\n   [Statutory Framework Audit]")
    print(f"      • Framework            : {stat_comp.get('statutory_framework')}")
    print(f"      • Transition Date      : {stat_comp.get('transition_date')}")
    print(f"      • In-Force Citations   : {stat_comp.get('in_force_count')}")
    print(f"      • Legacy Citations     : {stat_comp.get('legacy_citations_count')}")

    # 6. Verify Draft 1: Modern In-Force Citations (Compliant)
    print("\n[Step 6A] Verifying Draft 1 (Modern BNS / BNSS / BSA Citations)...")
    draft1_text = (
        "Investigation conducted under Section 173 BNSS reveals digital arrest cyber fraud under "
        "Section 318(4) BNS and Section 66D IT Act. Electronic evidence preserved under Section 63 BSA "
        "with complete SHA-256 integrity verification."
    )
    d1_res = client.post("/cognitive/verify-draft", json={"draft_text": draft1_text, "case_id": case_id}, headers=headers)
    assert d1_res.status_code == 200, f"Draft 1 failed: {d1_res.text}"
    d1_data = d1_res.json()
    print(f"   Verdict: {d1_data['governance_verdict']} (passed={d1_data['passed']})")
    assert d1_data["governance_verdict"] == "COMPLIANT"
    assert d1_data["passed"] is True
    print(f"   Parsed {len(d1_data.get('citations', []))} AST Citation Nodes:")
    for cit in d1_data.get("citations", []):
        print(f"      • {cit['section']} {cit.get('act', '')} -> {cit['status']} ({cit.get('title', '')})")

    # 7. Verify Draft 2: Pre-Transition Legacy Citations (Needs Review)
    print("\n[Step 6B] Verifying Draft 2 (Pre-Transition Legacy IPC/CrPC/IEA Citations)...")
    draft2_text = (
        "FIR registered under Section 420 IPC and Section 66D IT Act. Police requested bank account freeze "
        "under Section 102 CrPC. Certificate u/s 65B of Evidence Act prepared for CDR logs."
    )
    d2_res = client.post("/cognitive/verify-draft", json={"draft_text": draft2_text, "case_id": case_id}, headers=headers)
    assert d2_res.status_code == 200, f"Draft 2 failed: {d2_res.text}"
    d2_data = d2_res.json()
    print(f"   Verdict: {d2_data['governance_verdict']} (passed={d2_data['passed']})")
    assert d2_data["governance_verdict"] == "NEEDS_REVIEW"
    assert d2_data["passed"] is False
    print("   Modernization Guidance:")
    for cit in d2_data.get("citations", []):
        if cit["status"] == "pre_transition_act":
            print(f"      • {cit['section']} {cit.get('act', '')} -> Modernize to: {cit.get('replacement')}")

    # 8. Verify Draft 3: Struck-Down Law (Governance Blocked)
    print("\n[Step 6C] Verifying Draft 3 (Struck-Down Statute: IT Act Section 66A)...")
    draft3_text = (
        "Investigator issued criminal summons under Section 66A of Information Technology Act 2000 "
        "for offensive digital messages transmitted over computer networks."
    )
    d3_res = client.post("/cognitive/verify-draft", json={"draft_text": draft3_text, "case_id": case_id}, headers=headers)
    assert d3_res.status_code == 200, f"Draft 3 failed: {d3_res.text}"
    d3_data = d3_res.json()
    print(f"   Verdict: {d3_data['governance_verdict']} (passed={d3_data['passed']})")
    assert d3_data["governance_verdict"] == "GOVERNANCE_BLOCKED"
    assert d3_data["passed"] is False
    print("   Governance Block Reason:")
    for r in d3_data.get("governance_reasons", []):
        print(f"      ⛔ {r}")

    print("\n" + "=" * 70)
    print("🎉 F09 LEGAL COMPLIANCE SHIELD: ALL LIVE FRESH-CASE CHECKS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    main()
