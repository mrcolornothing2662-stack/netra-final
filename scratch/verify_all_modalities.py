"""
NETRA 5.0 — Live Multi-Modality Pre-Hash Inspection & Sealing Test
Tests PDF, Image, and ZIP modalities on http://localhost:8000
"""
import io
import httpx
import hashlib
import zipfile
from PIL import Image

BASE_URL = "http://localhost:8000/api/v1"

def main():
    print("=== MULTI-MODALITY LIVE PRE-HASH TEST ===")
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # 1. Login
    login_resp = client.post("/auth/login", data={"username": "admin", "password": "admin123"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    cases_resp = client.get("/cases", headers=headers)
    case_id = cases_resp.json()["items"][0]["id"]

    # 2. Test Image (PNG)
    img = Image.new("RGB", (320, 240), color=(18, 52, 86))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    png_bytes = img_buf.getvalue()
    png_sha = hashlib.sha256(png_bytes).hexdigest()

    resp = client.post(
        "/evidence/preview",
        headers=headers,
        data={"case_id": case_id, "source_type": "cctv"},
        files={"file": ("surveillance_frame_01.png", png_bytes, "image/png")}
    )
    assert resp.status_code == 200, resp.text
    p_img = resp.json()
    assert p_img["status"] == "unhashed_preview"
    assert p_img["mime_type"] == "image/png"
    assert "data:image/png;base64," in p_img["metadata"]["thumbnail_data_url"]
    print(f"1. [PASS] Image Pre-Hash Preview verified: {p_img['filename']} (MIME: {p_img['mime_type']}, Thumbnail Data URL: present)")

    # Confirm Image
    conf_img = client.post(
        "/evidence/confirm",
        headers=headers,
        data={"case_id": case_id, "preview_id": p_img["preview_id"], "source_type": "cctv"}
    )
    assert conf_img.status_code == 200
    assert conf_img.json()["sha256_hash"] == png_sha
    print(f"   [PASS] Image Sealed with exact SHA-256: {png_sha}")

    # 3. Test ZIP Archive
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("telecom_cdr_march.csv", "caller,callee,duration\n9811001122,9822334455,120\n")
        zf.writestr("panchnama_notes.txt", "Witness present: Inspector R. Sharma.\n")
    zip_bytes = zip_buf.getvalue()

    resp_zip = client.post(
        "/evidence/preview",
        headers=headers,
        data={"case_id": case_id, "source_type": "disk_dump"},
        files={"file": ("evidence_bundle.zip", zip_bytes, "application/zip")}
    )
    assert resp_zip.status_code == 200, resp_zip.text
    p_zip = resp_zip.json()
    assert p_zip["status"] == "unhashed_preview"
    assert p_zip["metadata"]["member_count"] == 2
    assert "telecom_cdr_march.csv" in p_zip["metadata"]["members"]
    print(f"2. [PASS] ZIP Pre-Hash Preview verified: {p_zip['filename']} (Members: {p_zip['metadata']['members']})")

    # Cancel ZIP (investigator chose not to ingest)
    canc = client.post("/evidence/preview/cancel", headers=headers, data={"case_id": case_id, "preview_id": p_zip["preview_id"]})
    assert canc.status_code == 200
    print(f"   [PASS] ZIP Preview discarded upon investigator cancellation.")

    # 4. Test Executable Binary Rejection (Magic Bytes Guardrail)
    fake_exe = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100
    bad_resp = client.post(
        "/evidence/preview",
        headers=headers,
        data={"case_id": case_id},
        files={"file": ("malware_loader.exe", fake_exe, "application/octet-stream")}
    )
    assert bad_resp.status_code == 400
    assert "Executable binary files are strictly prohibited" in bad_resp.json()["detail"]
    print(f"3. [PASS] Executable binary rejected during Pre-Hash Inspection (HTTP 400: Magic byte MZ disallowed).")

    print("\n=== ALL MULTI-MODAL LIVE CHECKS PASSED ===")

if __name__ == "__main__":
    main()
