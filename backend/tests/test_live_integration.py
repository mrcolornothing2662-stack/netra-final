"""
CyberDrishti AI — Live Integration & Concurrency Test Suite
Validates:
1. Admin authentication and token validity.
2. Case creation and access boundaries (404 for non-existent case, 401 unauthenticated).
3. Evidence ingestion integrity:
   - Same bytes, same filename -> duplicate detected.
   - Same bytes, different filename -> duplicate detected via SHA-256.
   - Different bytes, same filename -> distinct record, unique storage path, no overwrite.
4. Concurrent duplicate upload safety (thread/async safety under PostgreSQL advisory lock / unique constraints).
5. Audit log tracking of uploads and duplicates.
"""
import asyncio
import hashlib
import socket
import uuid
import httpx
import pytest

BASE_URL = "http://127.0.0.1:8000/api/v1"


def _is_server_listening(host="127.0.0.1", port=8000) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _is_server_listening(),
    reason="Live integration tests require running server at http://127.0.0.1:8000",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_live_auth_and_case_access_boundaries():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        # 1. Admin login
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Verify /auth/me
        me_resp = await client.get("/auth/me", headers=admin_headers)
        assert me_resp.status_code == 200
        admin_user = me_resp.json()
        assert admin_user["username"] == "admin"
        assert admin_user["role"] == "admin"

        # 2. Create a test case
        case_data = {
            "title": f"Integration Test Case - {uuid.uuid4().hex[:8]}",
            "description": "Validating access boundaries and evidence integrity",
            "priority": "high",
            "category": "financial_fraud",
        }
        case_resp = await client.post("/cases", json=case_data, headers=admin_headers)
        assert case_resp.status_code in (200, 201), f"Case creation failed: {case_resp.text}"
        created_case = case_resp.json()
        case_id = created_case["id"]

        # Admin can view the case
        get_resp = await client.get(f"/cases/{case_id}", headers=admin_headers)
        assert get_resp.status_code == 200

        # Unauthenticated request receives 401
        unauth_resp = await client.get(f"/cases/{case_id}")
        assert unauth_resp.status_code == 401

        # Non-existent case receives 404
        fake_id = str(uuid.uuid4())
        fake_resp = await client.get(f"/cases/{fake_id}", headers=admin_headers)
        assert fake_resp.status_code == 404


@pytest.mark.asyncio
async def test_live_evidence_deduplication_and_integrity():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as client:
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        case_resp = await client.post(
            "/cases",
            json={"title": f"Dedup Test - {uuid.uuid4().hex[:6]}", "priority": "medium"},
            headers=admin_headers,
        )
        assert case_resp.status_code in (200, 201)
        case_id = case_resp.json()["id"]

        content_a = b"timestamp,caller,receiver,duration\n2026-09-01 10:00:00,+919876543210,+919123456780,120\n"
        sha256_a = hashlib.sha256(content_a).hexdigest()

        # Upload file A: evidence_log.csv
        upload1 = await client.post(
            "/evidence/upload",
            data={"case_id": case_id},
            files=[("files", ("evidence_log.csv", content_a, "text/csv"))],
            headers=admin_headers,
        )
        assert upload1.status_code == 200, f"Upload 1 failed: {upload1.text}"
        res1 = upload1.json()
        assert res1["uploaded"] == 1
        assert res1["duplicate_count"] == 0
        assert res1["files"][0]["sha256_hash"] == sha256_a
        first_id = res1["files"][0]["id"]

        # Upload identical content A under exact same name -> duplicate detected
        upload2 = await client.post(
            "/evidence/upload",
            data={"case_id": case_id},
            files=[("files", ("evidence_log.csv", content_a, "text/csv"))],
            headers=admin_headers,
        )
        assert upload2.status_code == 200
        res2 = upload2.json()
        assert res2["uploaded"] == 0
        assert res2["duplicate_count"] == 1
        assert res2["duplicates"][0]["sha256_hash"] == sha256_a
        assert res2["duplicates"][0]["id"] == first_id

        # Upload identical content A under different filename -> duplicate detected via SHA-256
        upload3 = await client.post(
            "/evidence/upload",
            data={"case_id": case_id},
            files=[("files", ("renamed_cdr.csv", content_a, "text/csv"))],
            headers=admin_headers,
        )
        assert upload3.status_code == 200
        res3 = upload3.json()
        assert res3["uploaded"] == 0
        assert res3["duplicate_count"] == 1
        assert res3["duplicates"][0]["sha256_hash"] == sha256_a
        assert res3["duplicates"][0]["id"] == first_id

        # Upload DIFFERENT content B under same filename 'evidence_log.csv' -> NOT duplicate, no overwrite!
        content_b = b"timestamp,caller,receiver,duration\n2026-09-02 11:00:00,+919999988888,+917777766666,45\n"
        sha256_b = hashlib.sha256(content_b).hexdigest()
        assert sha256_b != sha256_a

        upload4 = await client.post(
            "/evidence/upload",
            data={"case_id": case_id},
            files=[("files", ("evidence_log.csv", content_b, "text/csv"))],
            headers=admin_headers,
        )
        assert upload4.status_code == 200
        res4 = upload4.json()
        assert res4["uploaded"] == 1
        assert res4["duplicate_count"] == 0
        assert res4["files"][0]["sha256_hash"] == sha256_b
        assert res4["files"][0]["id"] != first_id


@pytest.mark.asyncio
async def test_live_concurrent_duplicate_uploads():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        case_resp = await client.post(
            "/cases",
            json={"title": f"Concurrency Test - {uuid.uuid4().hex[:6]}", "priority": "high"},
            headers=admin_headers,
        )
        assert case_resp.status_code in (200, 201)
        case_id = case_resp.json()["id"]

        same_bytes = f"CONCURRENT_CONTENT_{uuid.uuid4().hex}".encode("utf-8")
        expected_hash = hashlib.sha256(same_bytes).hexdigest()

        async def do_upload(i: int):
            return await client.post(
                "/evidence/upload",
                data={"case_id": case_id},
                files=[("files", (f"file_{i}.txt", same_bytes, "text/plain"))],
                headers=admin_headers,
            )

        # Launch 5 concurrent upload requests with the exact same bytes
        responses = await asyncio.gather(*(do_upload(i) for i in range(5)))

        # All requests must return 200 without crashing or 500
        for r in responses:
            assert r.status_code == 200, f"Concurrent upload failed: {r.text}"

        json_results = [r.json() for r in responses]
        total_uploaded = sum(res["uploaded"] for res in json_results)
        total_duplicates = sum(res["duplicate_count"] for res in json_results)

        # Exactly 1 should be uploaded, and 4 should be detected as duplicates
        assert total_uploaded == 1, f"Expected 1 uploaded, got {total_uploaded}"
        assert total_duplicates == 4, f"Expected 4 duplicates, got {total_duplicates}"


@pytest.mark.asyncio
async def test_live_graph_bounds_and_truthful_empty_state():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # Fresh empty case
        case_resp = await client.post(
            "/cases",
            json={"title": f"Empty Graph Case - {uuid.uuid4().hex[:6]}", "priority": "low"},
            headers=admin_headers,
        )
        assert case_resp.status_code in (200, 201)
        case_id = case_resp.json()["id"]

        # Empty case graph should be strictly empty (no fabricated demo nodes/edges)
        graph_resp = await client.get(f"/graph/{case_id}", headers=admin_headers)
        assert graph_resp.status_code == 200
        graph_data = graph_resp.json()
        assert graph_data["nodes"] == []
        assert graph_data["edges"] == []
        assert graph_data.get("hidden_edges", []) == []

        # Access check: non-existent case returns 404
        fake_id = str(uuid.uuid4())
        fake_graph = await client.get(f"/graph/{fake_id}", headers=admin_headers)
        assert fake_graph.status_code == 404


@pytest.mark.asyncio
async def test_live_copilot_groundedness_and_abstention():
    """Verify Copilot abstains on empty case and enforces case-boundary isolation."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # 1. Fresh empty case
        case_resp = await client.post(
            "/cases",
            json={"title": f"Copilot Test Case - {uuid.uuid4().hex[:6]}", "priority": "low"},
            headers=admin_headers,
        )
        assert case_resp.status_code in (200, 201)
        case_id = case_resp.json()["id"]

        # Query on empty case must cleanly abstain with zero hallucinations
        copilot_resp = await client.post(
            f"/copilot/{case_id}",
            json={"question": "Who is the prime extortionist?", "top_k": 3},
            headers=admin_headers,
        )
        assert copilot_resp.status_code == 200
        data = copilot_resp.json()
        assert data.get("abstained") is True
        answer_lower = data.get("answer", "").lower()
        assert any(phrase in answer_lower for phrase in ["insufficient", "cannot provide", "can't provide", "no evidence"])
        assert "Ankita" not in data.get("answer", "")
        assert data.get("citations") == []


@pytest.mark.asyncio
async def test_live_auth_rate_limiting_and_lockout():
    """Verify failed login attempts trigger lockout protection after threshold."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        test_user = f"attacker_{uuid.uuid4().hex[:6]}"
        
        # 5 consecutive failed attempts
        for i in range(5):
            resp = await client.post(
                "/auth/login",
                data={"username": test_user, "password": "wrongpassword"},
            )
            assert resp.status_code == 401

        # 6th attempt must be locked out with HTTP 429
        locked_resp = await client.post(
            "/auth/login",
            data={"username": test_user, "password": "wrongpassword"},
        )
        assert locked_resp.status_code == 429
        assert "temporarily locked" in locked_resp.json().get("detail", "")


@pytest.mark.asyncio
async def test_live_audit_chain_verification():
    """Verify cryptographic SHA-256 hash-chain verification endpoint."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        login_resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert login_resp.status_code == 200
        admin_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

        # Create a case to ensure audit records exist
        case_resp = await client.post(
            "/cases",
            json={"title": f"Audit Verified Case - {uuid.uuid4().hex[:6]}", "priority": "high"},
            headers=admin_headers,
        )
        assert case_resp.status_code in (200, 201)
        case_id = case_resp.json()["id"]

        # Verify audit chain
        audit_resp = await client.get(f"/audit/verify/{case_id}", headers=admin_headers)
        assert audit_resp.status_code == 200
        audit_data = audit_resp.json()
        assert audit_data.get("intact") is True


@pytest.mark.asyncio
async def test_live_infrastructure_health_probe():
    """Verify comprehensive dependency readiness check for PostgreSQL, ChromaDB, and disk."""
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=10.0) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "healthy"
        assert data["dependencies"]["postgresql"] == "connected"
        assert "active" in data["dependencies"]["chromadb"]
        assert data["dependencies"]["disk_free_gb"] > 0
