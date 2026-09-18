"""
CyberDrishti AI / Netra 3.0 — FULL FEATURE AUDIT

Boots the REAL FastAPI app in-process (httpx ASGITransport) against a fresh
isolated temp SQLite DB + temp upload/chroma dirs, then drives EVERY router
group over HTTP exactly as the frontend would, on ONE realistic case built
from real evidence CSVs (transfers + ledger + CDR).

Router coverage (from main.py):
  auth · cases · analytics · evidence · graph · timeline · query · copilot
  report · audit · officers · agent · intel · events · correlations
  intelligence · cognitive

No mocks, no fabricated forensic data. Deterministic engines only (no network /
no LLM download — the app's designed graceful fallbacks are exercised). Prints a
PASS/FAIL line per feature and exits non-zero on any failure. Self-cleans temp.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import shutil
import sys
import tempfile

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="feature_audit_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'audit.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(_TMP / "chroma"))
os.environ.setdefault("INITIAL_ADMIN_USERNAME", "admin")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "admin123")
pathlib.Path(os.environ["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

import httpx  # noqa: E402

import main  # noqa: E402
from db.session import engine, AsyncSessionLocal  # noqa: E402
from db.models import Base, User, EvidenceFile  # noqa: E402
from routes.auth import _hash_password  # noqa: E402
from sqlalchemy import select  # noqa: E402

API = "/api/v1"

# ── Real evidence (byte-exact, same as the acceptance harness) ────────────────
_TRANSFER_CSV = (
    "transaction_id,timestamp_ist,debit_account,credit_account,amount_inr,upi_id,channel,status,description,reference\n"
    "TX0001,2026-08-18 09:50:03,ACCT-VICTIM-01,ACCT-MULE-11,285000,glasssparrow11@upi,UPI,SETTLED,KYC verification debit,UPI-0001\n"
    "TX0002,2026-08-18 09:50:41,ACCT-MULE-11,ACCT-MULE-12,180000,glasssparrow12@upi,IMPS,SETTLED,rapid onward transfer,IMPS-0002\n"
    "TX0003,2026-08-18 09:51:02,ACCT-MULE-11,ACCT-MULE-13,95000,glasssparrow13@upi,IMPS,SETTLED,rapid onward transfer,IMPS-0003\n"
    "TX0004,2026-08-18 09:52:10,ACCT-MULE-12,ACCT-MULE-14,120000,glasssparrow14@upi,UPI,SETTLED,layering,UPI-0004\n"
    "TX0005,2026-08-18 09:53:44,ACCT-MULE-13,ACCT-MULE-14,70000,glasssparrow14@upi,UPI,SETTLED,layering,UPI-0005\n"
    "TX0006,2026-08-18 09:56:21,ACCT-MULE-14,ATM-CASH-01,90000,CASH,ATM,SETTLED,cash withdrawal,ATM-0006\n"
    "TX0007,2026-08-18 10:02:14,ACCT-MULE-12,ACCT-SHELL-01,30000,shell01@upi,UPI,SETTLED,layering,UPI-0007\n"
    "TX0008,2026-08-18 10:07:31,ACCT-SHELL-01,ACCT-SHELL-02,29000,shell02@upi,IMPS,SETTLED,layering,IMPS-0008\n"
    "TX0009,2026-08-18 10:09:18,ACCT-SHELL-02,ATM-CASH-02,28000,CASH,ATM,SETTLED,cash withdrawal,ATM-0009\n"
)
_LEDGER_CSV = (
    "date,narration,credit,debit,balance,ref_no\n"
    "2026-05-01,IMPS/P2A/998877/TRANSFER,50000,,120000,IMPS998877\n"
    "2026-05-02,UPI/CR/mule99@upi/DEPOSIT,25000,,145000,UPI223344\n"
    "2026-05-03,ATM WDL/MUMBAI/CASH,,20000,125000,ATM556677\n"
)
_CDR_CSV = (
    "record_id,subscriber,device_id,cell_tower,event_time_utc,event_type,latitude,longitude,source_note\n"
    "CDR-001,+91-9000000101,DEV-A1,DEL-IGI-04,2026-08-18T03:58:02Z,ATTACHED,28.5561,77.1008,carrier_feed\n"
    "CDR-002,+91-9000000101,DEV-A1,DEL-CNT-11,2026-08-18T04:07:14Z,ATTACHED,28.6315,77.2167,carrier_feed\n"
    "CDR-003,+91-9000000101,DEV-A1,DEL-NOI-02,2026-08-18T04:21:09Z,ATTACHED,28.5355,77.3910,carrier_feed\n"
    "CDR-004,+91-9000000101,DEV-A1,DEL-CNT-11,2026-08-18T04:23:55Z,ATTACHED,28.6315,77.2167,carrier_feed\n"
    "CDR-005,+91-9000000101,DEV-A1,CYB-HYD-03,2026-08-18T04:24:04Z,ATTACHED,17.3850,78.4867,carrier_feed\n"
    "CDR-006,+91-9000000101,DEV-A1,CYB-HYD-03,2026-08-18T04:25:21Z,SMS,17.3850,78.4867,carrier_feed\n"
    "CDR-007,+91-9000000101,DEV-A1,DEL-NOI-02,2026-08-18T04:28:11Z,ATTACHED,28.5355,77.3910,carrier_feed\n"
    "CDR-008,+91-9000000101,DEV-A1,DEL-IGI-04,2026-08-18T04:30:00Z,DETACHED,28.5561,77.1008,carrier_feed\n"
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, evidence: str = "") -> bool:
    results.append((name, bool(ok), evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {evidence}" if evidence else ""))
    return ok


async def _bearer(client, username, password):
    r = await client.post(f"{API}/auth/login",
                          data={"username": username, "password": password},
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    if r.status_code != 200:
        return {}
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _await_processing(case_uuid, expected, timeout_s=25.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case_uuid))).scalars().all()
            done = [r for r in rows if r.upload_status in ("processed", "failed")]
            if len(rows) >= expected and len(done) >= len(rows):
                return rows
        if asyncio.get_event_loop().time() > deadline:
            return rows
        await asyncio.sleep(0.4)


async def _read_first_sse_frame(app, path, token, timeout_s=8.0):
    """Verify an infinite text/event-stream emits its connection-ack frame.

    httpx.ASGITransport BUFFERS the whole response body and cannot stream an
    endpoint whose generator never returns (it hangs forever), so we drive the
    ASGI app directly: feed a scope, capture response.start + the first non-empty
    body frame, then cancel. Returns (ok, detail). Hard-bounded by wait_for."""
    captured: dict = {"status": None, "ct": None, "frame": None}

    async def receive():
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            captured["status"] = msg["status"]
            for k, v in msg.get("headers", []):
                if k.lower() == b"content-type":
                    captured["ct"] = v.decode()
        elif msg["type"] == "http.response.body":
            body = msg.get("body", b"")
            if body.strip():
                captured["frame"] = body
                raise asyncio.CancelledError  # got the ack — stop the infinite generator

    scope = {
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"authorization", token.encode()), (b"host", b"audit.test"),
                    (b"accept-encoding", b"identity")],
        "server": ("audit.test", 80), "scheme": "http",
        "client": ("127.0.0.1", 1234), "http_version": "1.1",
    }
    try:
        await asyncio.wait_for(app(scope, receive, send), timeout=timeout_s)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception as e:  # noqa: BLE001
        return False, f"stream error: {e!r}"

    ok = (captured["status"] == 200
          and (captured["ct"] or "").startswith("text/event-stream")
          and captured["frame"] is not None)
    if ok:
        return True, f"ack frame {len(captured['frame'])}B"
    return False, f"status={captured['status']} ct={captured['ct']} frame={captured['frame'] is not None}"


async def run():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await main._ensure_audit_genesis()
    await main._ensure_admin_seed()

    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://audit.test", timeout=60.0) as client:

        # ── AUTH ──────────────────────────────────────────────────────────────
        admin_h = await _bearer(client, "admin", "admin123")
        check("auth: admin login issues JWT", bool(admin_h))
        r = await client.get(f"{API}/auth/me", headers=admin_h)
        check("auth: /me returns identity", r.status_code == 200 and r.json().get("role") == "admin",
              f"role={r.json().get('role') if r.status_code==200 else r.status_code}")
        r = await client.post(f"{API}/auth/login", data={"username": "admin", "password": "wrong"})
        check("auth: bad password rejected (401)", r.status_code == 401, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/auth/me")
        check("auth: unauthenticated /me rejected (401)", r.status_code == 401, f"HTTP {r.status_code}")

        # ── OFFICERS (admin creates an IO) ─────────────────────────────────────
        r = await client.post(f"{API}/officers",
                              json={"username": "io_demo", "email": "io_demo@cyberdrishti.gov.in",
                                    "password": "passw0rd!", "full_name": "IO Demo", "role": "io"},
                              headers=admin_h)
        check("officers: admin creates IO (201)", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
        r = await client.get(f"{API}/officers", headers=admin_h)
        check("officers: list returns officers", r.status_code == 200 and len(r.json()) >= 1,
              f"count={len(r.json()) if r.status_code==200 else r.status_code}")
        io_h = await _bearer(client, "io_demo", "passw0rd!")
        check("officers: new IO can authenticate", bool(io_h))

        # ── CASES ───────────────────────────────────────────────────────────────
        r = await client.post(f"{API}/cases", json={"title": "Feature Audit Case", "priority": "high",
                                                     "description": "full-surface feature audit"}, headers=io_h)
        check("cases: create (201)", r.status_code == 201, f"HTTP {r.status_code}")
        case_id = r.json()["id"]; case_no = r.json()["case_number"]
        import uuid as _uuid
        case_uuid = _uuid.UUID(case_id)
        r = await client.get(f"{API}/cases/{case_id}", headers=io_h)
        check("cases: get by id", r.status_code == 200 and r.json()["id"] == case_id, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cases", headers=io_h)
        check("cases: list", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.patch(f"{API}/cases/{case_id}", json={"status": "in_progress"}, headers=io_h)
        check("cases: patch status", r.status_code == 200 and r.json().get("status") == "in_progress", f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cases/stats/summary", headers=io_h)
        check("cases: stats summary", r.status_code == 200, f"HTTP {r.status_code}")

        # ── EVIDENCE upload + parse ─────────────────────────────────────────────
        files = [
            ("files", ("transfers.csv", _TRANSFER_CSV.encode(), "text/csv")),
            ("files", ("ledger.csv",    _LEDGER_CSV.encode(),   "text/csv")),
            ("files", ("cdr.csv",       _CDR_CSV.encode(),      "text/csv")),
        ]
        r = await client.post(f"{API}/evidence/upload", data={"case_id": case_id}, files=files, headers=io_h)
        check("evidence: upload 3 files (200)", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
        ev_files = await _await_processing(case_uuid, 3)
        n_proc = sum(1 for f in ev_files if f.upload_status == "processed")
        check("evidence: all 3 processed", n_proc == 3, f"{ {f.original_name: f.upload_status for f in ev_files} }")
        r = await client.get(f"{API}/evidence/{case_id}", headers=io_h)
        check("evidence: list case evidence", r.status_code == 200, f"HTTP {r.status_code}")

        # ── ANALYTICS ─────────────────────────────────────────────────────────
        r = await client.get(f"{API}/cases/{case_id}/summary", headers=io_h)
        check("analytics: case summary", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cases/{case_id}/communications", headers=io_h)
        check("analytics: communications", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cases/{case_id}/transactions", headers=io_h)
        ok = r.status_code == 200
        check("analytics: financial transactions", ok, f"HTTP {r.status_code}" +
              (f", txns={len(r.json().get('transactions', []))}" if ok else ""))

        # ── EVENTS (SSE stream) ─────────────────────────────────────────────────
        # GET /events/cases/{id} is an infinite text/event-stream (connection ack
        # + 5s heartbeats). Read only the first frame as a stream, then close.
        ev_ok, ev_detail = await _read_first_sse_frame(
            main.app, f"{API}/events/cases/{case_id}", io_h["Authorization"])
        check("events: SSE stream ack frame", ev_ok, ev_detail)

        # ── TIMELINE ────────────────────────────────────────────────────────────
        r = await client.get(f"{API}/timeline/{case_id}", headers=io_h)
        check("timeline: case timeline", r.status_code == 200, f"HTTP {r.status_code}")

        # ── QUERY (TF-IDF retrieval) ────────────────────────────────────────────
        r = await client.post(f"{API}/query/{case_id}", json={"question": "cash withdrawal ATM", "top_k": 5}, headers=io_h)
        check("query: TF-IDF retrieval", r.status_code == 200, f"HTTP {r.status_code}")

        # ── CORRELATIONS ────────────────────────────────────────────────────────
        r = await client.post(f"{API}/correlations/{case_id}/run", headers=io_h)
        check("correlations: run analysis", r.status_code == 200,
              f"HTTP {r.status_code}" + (f", flagged={r.json().get('flagged')}" if r.status_code==200 else ""))
        r = await client.get(f"{API}/correlations/{case_id}", headers=io_h)
        check("correlations: list flagged", r.status_code == 200,
              f"count={r.json().get('count') if r.status_code==200 else r.status_code}")

        # ── GRAPH ─────────────────────────────────────────────────────────────
        r = await client.get(f"{API}/graph/{case_id}", headers=io_h)
        ok = r.status_code == 200
        check("graph: network graph JSON", ok,
              f"HTTP {r.status_code}" + (f", nodes={len(r.json().get('nodes', []))}" if ok else ""))

        # ── COGNITIVE (11 engines) ──────────────────────────────────────────────
        r = await client.get(f"{API}/cognitive/cases/{case_id}/contradictions", headers=io_h)
        cj = r.json() if r.status_code == 200 else {}
        check("cognitive: contradictions (ledger+travel)", r.status_code == 200,
              f"travel_findings={len(cj.get('impossible_travel',{}).get('findings',[]))}")
        check("cognitive: analysis_status observability present",
              cj.get("ledger_audit",{}).get("analysis_status") in ("completed","insufficient_input")
              and cj.get("impossible_travel",{}).get("analysis_status") in ("completed","insufficient_input"),
              f"ledger={cj.get('ledger_audit',{}).get('analysis_status')}, travel={cj.get('impossible_travel',{}).get('analysis_status')}")
        r = await client.get(f"{API}/cognitive/cases/{case_id}/hypotheses", headers=io_h)
        check("cognitive: hypotheses", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cognitive/cases/{case_id}/next-best-actions", headers=io_h)
        check("cognitive: next-best-actions", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cognitive/cases/{case_id}/mo-fingerprint", headers=io_h)
        check("cognitive: MO fingerprint", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.post(f"{API}/cognitive/cases/{case_id}/counterfactual-freeze",
                              json={"freeze_account": "ACCT-MULE-11", "freeze_time": "2026-08-18T09:50:30"}, headers=io_h)
        ok = r.status_code == 200
        check("cognitive: counterfactual freeze", ok,
              f"HTTP {r.status_code}" + (f", preserved=Rs.{r.json().get('preserved_total',0):,.0f}" if ok else ""))
        r = await client.get(f"{API}/cognitive/cases/{case_id}/network-replay", headers=io_h)
        check("cognitive: network replay", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/cognitive/cross-case/collisions", headers=io_h)
        check("cognitive: cross-case collisions", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.post(f"{API}/cognitive/verify-draft",
                              json={"draft_text": "Suspect transferred Rs.285000 via UPI.", "case_id": case_id}, headers=io_h)
        check("cognitive: verify-draft (CRAG firewall)", r.status_code == 200, f"HTTP {r.status_code}")

        # ── INTELLIGENCE (communication + financial) ────────────────────────────
        r = await client.get(f"{API}/intelligence/communication/{case_id}", headers=io_h)
        check("intelligence: communication intel", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/intelligence/financial/{case_id}", headers=io_h)
        check("intelligence: financial intel", r.status_code == 200, f"HTTP {r.status_code}")

        # ── INTEL (syndicates + cross-match) ────────────────────────────────────
        r = await client.get(f"{API}/intel/syndicates", headers=io_h)
        check("intel: syndicate list", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/intel/cross-match", headers=io_h)
        check("intel: cross-match", r.status_code == 200, f"HTTP {r.status_code}")

        # ── COPILOT (RAG) ───────────────────────────────────────────────────────
        r = await client.post(f"{API}/copilot/{case_id}",
                              json={"question": "Summarise the money trail", "top_k": 5}, headers=io_h)
        check("copilot: RAG investigation query", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/copilot/status", headers=io_h)
        check("copilot: status", r.status_code == 200, f"HTTP {r.status_code}")

        # ── AGENT (autonomous investigation) ────────────────────────────────────
        r = await client.post(f"{API}/agent/{case_id}/run", headers=io_h)
        ok = r.status_code == 200 and "session_id" in r.json()
        sess = r.json().get("session_id") if ok else None
        check("agent: launch autonomous investigation", ok, f"HTTP {r.status_code}")
        if sess:
            for _ in range(20):
                s = await client.get(f"{API}/agent/{case_id}/status?session_id={sess}", headers=io_h)
                if s.status_code == 200 and s.json().get("status") in ("completed", "awaiting_approval", "failed", "error"):
                    break
                await asyncio.sleep(0.5)
            check("agent: status reachable", s.status_code == 200, f"status={s.json().get('status') if s.status_code==200 else s.status_code}")
        r = await client.get(f"{API}/agent/{case_id}/actions", headers=io_h)
        check("agent: action ledger", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/agent/sandbox/rules", headers=io_h)
        check("agent: sandbox rules", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/agent/holds", headers=io_h)
        check("agent: holds queue", r.status_code == 200, f"HTTP {r.status_code}")

        # ── REPORT (Section 65B PDF) ────────────────────────────────────────────
        r = await client.get(f"{API}/report/{case_id}/section65b", headers=io_h)
        ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf")
        check("report: Section 65B PDF generated", ok, f"HTTP {r.status_code}, {len(r.content)} bytes")

        # ── AUDIT (tamper-evident chain) ────────────────────────────────────────
        r = await client.get(f"{API}/audit/verify", headers=admin_h)
        aj = r.json() if r.status_code == 200 else {}
        check("audit: chain verify intact", r.status_code == 200 and aj.get("intact") is True, f"status={aj.get('status')}")
        check("audit: real genesis + last hash (64-hex)",
              isinstance(aj.get("genesis_hash"), str) and len(aj.get("genesis_hash",""))==64
              and isinstance(aj.get("last_hash"), str) and len(aj.get("last_hash",""))==64)
        r = await client.get(f"{API}/audit", headers=admin_h)
        check("audit: log listing", r.status_code == 200, f"HTTP {r.status_code}")
        r = await client.get(f"{API}/audit/verify/{case_id}", headers=admin_h)
        check("audit: per-case verify", r.status_code == 200, f"HTTP {r.status_code}")

        print(f"\nAudit case: {case_no} ({case_id})")

    await engine.dispose()


def main_entry():
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    try:
        asyncio.run(run())
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 70)
    print(f"NETRA 3.0 FEATURE AUDIT — {passed}/{total} features passed")
    if passed != total:
        print("FAILED:")
        for n, ok, ev in results:
            if not ok:
                print(f"  ✗ {n}  ({ev})")
    print("=" * 70)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main_entry()
