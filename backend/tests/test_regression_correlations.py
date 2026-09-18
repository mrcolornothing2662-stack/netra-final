"""HTTP-boundary regression guards for correlation verification.

Runs the REAL FastAPI app in-process (httpx ASGITransport, fresh temp SQLite)
and drives POST /correlations/{id}/verify exactly as the frontend would. Locks
down two root causes fixed during the pipeline-repair campaign:

  (c) UUID route coercion at the API boundary — the path id arrives as a STRING.
      The route coerces uuid.UUID(str(id)) before db.get; the cross-dialect UUID
      column binds via value.hex on SQLite and 500s on a raw string. Guarded:
      malformed string → 404, well-formed-but-absent → 404, and a REAL id string
      → 200 (coercion works, no 500). Plus the db.get half: a typed uuid.UUID
      object round-trips.  [routes/correlations.py::verify_correlation]

  (e) Decision-constraint mapping + verdict preservation — decision is
      CHECK-constrained to IN ('flagged','not_flagged'); it is NOT the human
      verdict. confirmed→flagged, disputed→not_flagged (drops out of the flagged
      list), and the raw human verdict is preserved verbatim in the tamper-
      evident audit entry. An invalid verdict is rejected (400) BEFORE any DB
      write, so the CHECK is never violated.  [db.models Correlation.decision]

Event-loop safety: async engines bind their pool to the loop that created the
connections, so this file performs exactly ONE asyncio.run over ONE scenario
against the shared app engine. Dual-mode runnable AND pytest-discoverable.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate ALL state to a temp dir BEFORE importing the app (config captures env
# at import; UPLOAD_DIR is read at module import). DEBUG=false silences echo.
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="corr_reg_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'corr.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(_TMP / "chroma"))
os.environ.setdefault("INITIAL_ADMIN_USERNAME", "admin")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "admin123")
pathlib.Path(os.environ["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

import asyncio  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import main  # noqa: E402  (the real app)
from db.session import engine, AsyncSessionLocal  # noqa: E402
from db.models import Base, User, Case, Entity, Correlation, AuditLog  # noqa: E402
from routes.auth import _hash_password  # noqa: E402

API = "/api/v1"


async def _bearer(client, username, password):
    r = await client.post(
        f"{API}/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_officer(username: str, role: str = "io") -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if existing:
            return existing.id
        u = User(username=username, email=f"{username}@cyberdrishti.gov.in",
                 hashed_password=_hash_password("passw0rd!"), full_name=username.title(),
                 role=role, is_active=True)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


# ── One HTTP scenario, one asyncio.run ────────────────────────────────────────

def test_correlation_verify_uuid_coercion_and_decision_mapping():
    asyncio.run(_impl())


async def _impl():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await main._ensure_audit_genesis()
    await main._ensure_admin_seed()

    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://corr.test") as client:
        await _bearer(client, "admin", "admin123")          # self-seed admin
        owner_id = await _seed_officer("corr_owner")
        owner_h = await _bearer(client, "corr_owner", "passw0rd!")

        # Owner creates the case (creator becomes assigned_officer_id).
        r = await client.post(f"{API}/cases", json={"title": "Corr Regression Case", "priority": "high"}, headers=owner_h)
        assert r.status_code == 201, f"case create HTTP {r.status_code}: {r.text[:200]}"
        case_id = r.json()["id"]
        case_uuid = uuid.UUID(case_id)

        # Scaffold two entities + one flagged correlation on the owner's case.
        async with AsyncSessionLocal() as db:
            ea = Entity(case_id=case_uuid, canonical_value="ACCT-MULE-11", entity_type="ACCOUNT")
            eb = Entity(case_id=case_uuid, canonical_value="glasssparrow12@upi", entity_type="UPI")
            db.add_all([ea, eb])
            await db.flush()
            corr = Correlation(case_id=case_uuid, entity_a_id=ea.id, entity_b_id=eb.id,
                               link_type="hidden_link", final_score=0.71, threshold=0.30, decision="flagged")
            db.add(corr)
            await db.commit()
            await db.refresh(corr)
            corr_id = str(corr.id)
            corr_uuid = corr.id

        # ── (c) UUID route coercion at the API boundary ───────────────────────
        # Malformed path string → coercion raises ValueError → 404 (NOT 500).
        r = await client.post(f"{API}/correlations/not-a-uuid/verify", json={"verdict": "confirmed"}, headers=owner_h)
        assert r.status_code == 404, f"malformed id expected 404, got {r.status_code}"
        # Well-formed but non-existent UUID string → db.get miss → 404.
        r = await client.post(f"{API}/correlations/{uuid.uuid4()}/verify", json={"verdict": "confirmed"}, headers=owner_h)
        assert r.status_code == 404, f"absent id expected 404, got {r.status_code}"
        # db.get half of the fix: a typed uuid.UUID object binds cleanly on SQLite.
        async with AsyncSessionLocal() as db:
            got = await db.get(Correlation, corr_uuid)
            assert got is not None and isinstance(got.id, uuid.UUID)

        # ── (e) confirmed → flagged, verdict preserved verbatim in audit ──────
        r = await client.post(f"{API}/correlations/{corr_id}/verify",
                              json={"verdict": "confirmed", "notes": "matches KYC evidence"}, headers=owner_h)
        assert r.status_code == 200, f"confirmed verify expected 200 (real id string → coerced), got {r.status_code}: {r.text[:200]}"
        body = r.json()
        assert body["verdict"] == "confirmed" and body["id"] == corr_id

        async with AsyncSessionLocal() as db:
            row = await db.get(Correlation, corr_uuid)
            assert row.decision == "flagged", f"confirmed must map to flagged, got {row.decision!r}"
            assert row.verified_by == owner_id, "verified_by not recorded"
            assert row.verified_at is not None, "verified_at not recorded"
            # Human verdict preserved verbatim in the tamper-evident audit entry.
            audits = (await db.execute(
                select(AuditLog).where(AuditLog.action == "CORRELATION_VERIFIED").order_by(AuditLog.id)
            )).scalars().all()
            assert audits, "no CORRELATION_VERIFIED audit entry written"
            assert audits[-1].details_json.get("verdict") == "confirmed", audits[-1].details_json
            assert audits[-1].details_json.get("notes") == "matches KYC evidence"

        # ── (e) disputed → not_flagged, drops out of the flagged list ─────────
        r = await client.post(f"{API}/correlations/{corr_id}/verify",
                              json={"verdict": "disputed"}, headers=owner_h)
        assert r.status_code == 200, f"disputed verify expected 200, got {r.status_code}"
        async with AsyncSessionLocal() as db:
            row = await db.get(Correlation, corr_uuid)
            assert row.decision == "not_flagged", f"disputed must map to not_flagged, got {row.decision!r}"
            audits = (await db.execute(
                select(AuditLog).where(AuditLog.action == "CORRELATION_VERIFIED").order_by(AuditLog.id)
            )).scalars().all()
            assert audits[-1].details_json.get("verdict") == "disputed", "second verdict not preserved"
        # A disputed (not_flagged) correlation is excluded from the flagged list.
        r = await client.get(f"{API}/correlations/{case_id}", headers=owner_h)
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["correlations"]]
        assert corr_id not in ids, "disputed correlation still surfaced as flagged"

        # ── (e) invalid verdict rejected BEFORE any DB write (CHECK never hit) ─
        r = await client.post(f"{API}/correlations/{corr_id}/verify",
                              json={"verdict": "maybe"}, headers=owner_h)
        assert r.status_code == 400, f"invalid verdict expected 400, got {r.status_code}"
        async with AsyncSessionLocal() as db:
            row = await db.get(Correlation, corr_uuid)
            assert row.decision == "not_flagged", "invalid verdict must not mutate decision"

    await engine.dispose()


# ── Dual-mode runner ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    _tests = [(n, f) for n, f in sorted(globals().items())
              if n.startswith("test_") and callable(f)]
    _failed = 0
    try:
        for _name, _fn in _tests:
            try:
                _fn()
                print(f"[PASS] {_name}")
            except Exception as _e:  # noqa: BLE001
                _failed += 1
                import traceback
                print(f"[FAIL] {_name}: {_e!r}")
                traceback.print_exc()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{len(_tests) - _failed}/{len(_tests)} correlation-regression checks passed")
    sys.exit(1 if _failed else 0)
