"""
NETRA 5.0 — Live End-to-End Verification of Pre-Hash Inspection & Sealing Workflow
Tests the running server at http://localhost:8000
"""
import sys
import httpx
import hashlib
from pathlib import Path

BASE_URL = "http://localhost:8000/api/v1"

def main():
    print("=== NETRA 5.0: LIVE PRE-HASH PREVIEW & SEALING WORKFLOW TEST ===")
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # 1. Login
    login_resp = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("1. [PASS] Authenticated as admin.")

    # 2. Get active case
    cases_resp = client.get("/cases", headers=headers)
    assert cases_resp.status_code == 200, f"Failed to list cases: {cases_resp.text}"
    cases_data = cases_resp.json()
    cases = cases_data.get("items", []) if isinstance(cases_data, dict) else cases_data
    assert len(cases) > 0, "No cases found"
    case_id = cases[0]["id"]
    print(f"2. [PASS] Retrieved case: {case_id} ({cases[0].get('case_number')})")

    # 3. Test Preview Before Hashing on CSV
    csv_file = Path("/Users/shubhamrana/netra5.0/scratch/test_bank_statement.csv")
    csv_bytes = csv_file.read_bytes()
    expected_csv_sha = hashlib.sha256(csv_bytes).hexdigest()

    preview_resp = client.post(
        "/evidence/preview",
        headers=headers,
        data={"case_id": case_id, "source_type": "bank_txn"},
        files={"file": (csv_file.name, csv_bytes, "text/csv")}
    )
    assert preview_resp.status_code == 200, f"Preview failed: {preview_resp.text}"
    preview_data = preview_resp.json()
    preview_id = preview_data["preview_id"]
    assert preview_data["status"] == "unhashed_preview"
    assert "PRE-HASH PREVIEW" in preview_data["warning"]
    assert preview_data["metadata"]["column_names"] == [
        "txn_id", "timestamp", "sender_account", "receiver_account", "amount_inr", "narration", "ip_address"
    ]
    assert len(preview_data["metadata"]["sample_rows"]) == 5
    print(f"3. [PASS] CSV Pre-Hash Preview successful:")
    print(f"   - Preview ID: {preview_id}")
    print(f"   - Status: {preview_data['status']}")
    print(f"   - Warning: {preview_data['warning']}")
    print(f"   - Columns: {preview_data['metadata']['column_names']}")
    print(f"   - Sample Rows Extracted: {len(preview_data['metadata']['sample_rows'])}")

    # 4. Test Cancel & Discard Workflow
    cancel_resp = client.post(
        "/evidence/preview/cancel",
        headers=headers,
        data={"case_id": case_id, "preview_id": preview_id}
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "discarded"
    print(f"4. [PASS] Preview cancellation & volatile purge verified.")

    # 5. Verify that confirm on cancelled preview fails with 404
    cancelled_confirm = client.post(
        "/evidence/confirm",
        headers=headers,
        data={"case_id": case_id, "preview_id": preview_id}
    )
    assert cancelled_confirm.status_code == 404
    print(f"5. [PASS] Confirming purged preview correctly rejected with HTTP 404.")

    # 6. Stage fresh file and Confirm & Seal
    stage_resp = client.post(
        "/evidence/preview",
        headers=headers,
        data={"case_id": case_id, "source_type": "bank_txn"},
        files={"file": (csv_file.name, csv_bytes, "text/csv")}
    )
    assert stage_resp.status_code == 200
    new_preview_id = stage_resp.json()["preview_id"]

    confirm_resp = client.post(
        "/evidence/confirm",
        headers=headers,
        data={"case_id": case_id, "preview_id": new_preview_id, "source_type": "bank_txn"}
    )
    assert confirm_resp.status_code == 200, f"Confirm failed: {confirm_resp.text}"
    confirm_data = confirm_resp.json()
    assert confirm_data["status"] == "sealed"
    actual_hash = confirm_data["sha256_hash"]
    assert actual_hash == expected_csv_sha, f"Hash mismatch: expected {expected_csv_sha}, got {actual_hash}"
    print(f"6. [PASS] Section 63 BSA Confirmation & Cryptographic Sealing verified:")
    print(f"   - Sealed ID: {confirm_data['id']}")
    print(f"   - Filename: {confirm_data['filename']}")
    print(f"   - Server Calculated SHA-256: {actual_hash}")
    print(f"   - Expected Exact Byte SHA-256: {expected_csv_sha}")
    print(f"   - Status: {confirm_data['status']}")

    # 7. Verify file appears in evidence list
    ev_list_resp = client.get(f"/evidence/{case_id}", headers=headers)
    assert ev_list_resp.status_code == 200
    ev_files = ev_list_resp.json().get("files", [])
    matching = [f for f in ev_files if f["sha256_hash"] == expected_csv_sha]
    assert len(matching) >= 1, "Sealed file not found in case evidence list"
    print(f"7. [PASS] File verified in Case Evidence Locker (Total files in case: {len(ev_files)})")

    print("\n=== ALL LIVE INTEGRATION CHECKS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    main()
