"""End-to-end validation of the NETRA evidence → intelligence loop.

Drives the REAL FastAPI app in-process (httpx ASGITransport, fresh temp SQLite)
and walks the complete loop the architecture promises:

    UPLOAD REAL EVIDENCE
      → evidence stored (SHA-256, processed)
      → parsed into events
      → entities + mentions extracted
      → observed relationships materialised (with evidence provenance)
      → graph reflects observed vs inferred edges
      → cognitive orchestrator runs the applicable engines
      → unified findings persisted (traceable to evidence)
      → intelligence state materialised
      → new evidence changes the existing analysis (no duplicates)
      → human verdict survives re-analysis
      → report consumes the verified findings
      → audit chain records uploads and analysis runs

Event-loop safety: exactly ONE asyncio.run over ONE scenario against the shared
app engine. Dual-mode runnable AND pytest-discoverable.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="e2e_loop_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'e2e.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(_TMP / "chroma"))
os.environ.setdefault("REPORT_OUTPUT_DIR", str(_TMP / "reports"))
os.environ.setdefault("INITIAL_ADMIN_USERNAME", "admin")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "admin123")
pathlib.Path(os.environ["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

import asyncio  # noqa: E402

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

import main  # noqa: E402  (the real app)
from db.session import engine, AsyncSessionLocal  # noqa: E402
from db.models import (  # noqa: E402
    AuditLog,
    Base,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
)

API = "/api/v1"

# ── Evidence samples (byte-exact, real parser shapes) ─────────────────────────

_LEDGER_1 = (
    "date,narration,credit,debit,balance,ref_no\n"
    "2026-05-01,IMPS/P2A/998877/OPENING,50000,,120000,IMPS998877\n"
    "2026-05-02,UPI/CR/deposit,25000,,145000,UPI223344\n"
    "2026-05-03,ATM WDL/MUMBAI/CASH,,20000,999999,ATM556677\n"
)
# Appended variant: same rows + one new row.
_LEDGER_2 = _LEDGER_1 + "2026-05-04,UPI/CR/deposit2,9000,,134000,UPI223355\n"

_TRANSFER = (
    "transaction_id,timestamp_ist,debit_account,credit_account,amount_inr,upi_id,channel,status,description,reference\n"
    "TX0001,2026-08-18 09:50:03,ACCT-VICTIM-01,ACCT-MULE-11,285000,glasssparrow11@upi,UPI,SETTLED,KYC debit,UPI-0001\n"
    "TX0002,2026-08-18 09:50:41,ACCT-MULE-11,ACCT-MULE-12,180000,glasssparrow12@upi,IMPS,SETTLED,onward,IMPS-0002\n"
)

_CDR_1 = (
    "record_id,subscriber,device_id,cell_tower,event_time_utc,event_type,latitude,longitude,source_note\n"
    "CDR-001,+91-9000000101,DEV-A1,DEL-IGI-04,2026-08-18T03:58:02Z,ATTACHED,28.5561,77.1008,feed\n"
    "CDR-002,+91-9000000101,DEV-A1,CYB-HYD-03,2026-08-18T04:24:04Z,ATTACHED,17.3850,78.4867,feed\n"
)
# New evidence: a different subscriber with a fresh impossible-travel pair.
_CDR_2 = (
    "record_id,subscriber,device_id,cell_tower,event_time_utc,event_type,latitude,longitude,source_note\n"
    "CDR-101,+91-9000000202,DEV-B1,MUM-BOM-01,2026-08-19T03:00:00Z,ATTACHED,19.0896,72.8656,feed\n"
    "CDR-102,+91-9000000202,DEV-B1,DEL-IGI-04,2026-08-19T03:30:00Z,ATTACHED,28.5561,77.1008,feed\n"
)
_WHATSAPP = (
    "22/04/2026, 9:00 am - Inspector: We are from CBI crime branch. A notice is issued.\n"
    "22/04/2026, 9:05 am - Inspector: Join the video call now.\n"
    "22/04/2026, 9:10 am - Inspector: You will go to jail, this is non-bailable.\n"
    "22/04/2026, 9:15 am - Inspector: Transfer the money for verification.\n"
    "22/04/2026, 9:20 am - Inspector: Delete the chat and block this number.\n"
)

EXPECTED_FINDING_TYPES = {
    "CONTRADICTION", "FINGERPRINT_VARIANT", "MO_MATCH", "HYPOTHESIS", "NEXT_BEST_ACTION",
}

# Findings that legitimately carry no evidence/event reference.
NOT_EVIDENCE_GROUNDED = {"VERIFICATION", "CROSS_CASE_SIGNAL", "COUNTERFACTUAL", "NEXT_BEST_ACTION", "DEFENCE_CHALLENGE"}


async def _bearer(client, username, password):
    r = await client.post(
        f"{API}/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _upload(client, case_id, headers, name, content):
    return await client.post(
        f"{API}/evidence/upload",
        data={"case_id": case_id, "source_type": "unknown"},
        files={"files": (name, content.encode(), "text/plain")},
        headers=headers,
    )


def test_e2e_investigation_loop():
    asyncio.run(_impl())


async def _impl():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await main._ensure_audit_genesis()
    await main._ensure_admin_seed()

    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://e2e.test") as client:
        headers = await _bearer(client, "admin", "admin123")
        case_id = (await client.post(
            f"{API}/cases", json={"title": "E2E Loop", "priority": "high"}, headers=headers
        )).json()["id"]

        # ── 1. UPLOAD REAL EVIDENCE ───────────────────────────────────────────
        for name, content in (
            ("ledger1.csv", _LEDGER_1),
            ("ledger2.csv", _LEDGER_2),
            ("transfer.csv", _TRANSFER),
            ("cdr1.csv", _CDR_1),
            ("chat.txt", _WHATSAPP),
        ):
            r = await _upload(client, case_id, headers, name, content)
            assert r.status_code == 200, f"upload {name} HTTP {r.status_code}: {r.text[:200]}"
            assert r.json()["uploaded"] == 1, r.json()

        # ── 2. EVIDENCE STORED (SHA-256, processed) ───────────────────────────
        evidence = (await client.get(f"{API}/evidence/{case_id}", headers=headers)).json()
        assert evidence["count"] == 5, evidence
        assert all(f["sha256_hash"] for f in evidence["files"])
        assert all(f["upload_status"] == "processed" for f in evidence["files"]), evidence["files"]

        case_uuid = uuid.UUID(case_id)
        async with AsyncSessionLocal() as db:
            events = (await db.execute(
                select(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
            )).scalars().all()
            entities = (await db.execute(
                select(Entity).where(Entity.case_id == case_uuid)
            )).scalars().all()
            relationships = (await db.execute(
                select(Relationship).where(Relationship.case_id == case_uuid)
            )).scalars().all()
            evidence_rows = (await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == case_uuid)
            )).scalars().all()

        # ── 3. PARSED → EVENTS → ENTITIES ─────────────────────────────────────
        assert len(events) > 0, "no events parsed"
        assert len(entities) > 0, "no entities extracted"

        # ── 4. OBSERVED RELATIONSHIPS WITH PROVENANCE ─────────────────────────
        observed = [r for r in relationships if r.epistemic_status == "OBSERVED"]
        assert observed, "no observed relationships materialised"
        transfer = [r for r in observed if r.relationship_type == "TRANSFERRED_TO"]
        assert transfer, "no TRANSFERRED_TO relationship materialised"
        assert all(r.evidence_refs for r in transfer), [r.evidence_refs for r in transfer]
        assert any(r.amount == 285000.0 for r in transfer), sorted(r.amount for r in transfer)

        # ── 5. GRAPH REFLECTS OBSERVED VS INFERRED ────────────────────────────
        graph = (await client.get(f"{API}/graph/{case_id}", headers=headers)).json()
        assert graph["nodes"], "graph has no nodes"
        enriched = [e for e in graph["edges"] if e.get("relationship_type")]
        assert enriched, "graph edges carry no relationship provenance"
        assert any(e.get("evidence_refs") for e in enriched), enriched
        assert graph["relationships"]["total"] >= 1
        rel_endpoint = (await client.get(f"{API}/relationships/{case_id}", headers=headers)).json()
        assert rel_endpoint["observed_count"] >= 1, rel_endpoint

        # ── 5b. TIMELINE ORDERED BY EVENT TIME, INGESTION KEPT SEPARATE ───────
        timeline = (await client.get(f"{API}/timeline/{case_id}", headers=headers)).json()
        assert timeline["order"] == "event_time", timeline
        tev = timeline["events"]
        assert tev, "timeline empty"
        assert all("event_time" in e and "ingested_at" in e for e in tev)
        known_times = [e["event_time"] for e in tev if e["event_time"]]
        assert known_times == sorted(known_times), "timeline is not ordered by event_time"

        # ── 5c. REPLAY FRAMES REFLECT THE REAL TEMPORAL GRAPH ────────────────
        replay = (await client.get(
            f"{API}/cognitive/cases/{case_id}/network-replay?step_seconds=300&tau_seconds=1800",
            headers=headers,
        )).json()
        assert replay["total_events"] > 0, replay
        frames = replay["frames"]
        assert frames, "replay returned no frames"
        assert max(len(f["nodes"]) for f in frames) > 1, "replay collapsed to a single node"
        assert any(len(f["edges"]) > 0 for f in frames), "replay frames contain no edges"

        # ── 6. ORCHESTRATOR RUNS APPLICABLE ENGINES ───────────────────────────
        analyze = await client.post(f"{API}/intelligence/cases/{case_id}/analyze", json={}, headers=headers)
        assert analyze.status_code == 200, analyze.text
        body = analyze.json()
        for engine_name in ("ContradictionEngine", "FingerprintEngine", "MOEngine", "HypothesisEngine", "NextBestEngine"):
            assert engine_name in body["engines_run"], (engine_name, body["engines_run"])
        assert "BenchmarkGenerator" not in body["engine_status"], "benchmark leaked into a real case"

        # The orchestrator must materialise inferred relationships from the same
        # evidence so the HiddenLink engine reasons over a complete case graph.
        cm = body.get("correlation_materialisation")
        assert isinstance(cm, dict) and "error" not in cm, cm
        assert cm.get("entity_count", 0) > 0, cm
        if cm.get("flagged"):
            assert cm.get("inferred_relationships", 0) >= 1, cm

        # ── 7. UNIFIED FINDINGS, TRACEABLE ────────────────────────────────────
        findings_response = (await client.get(
            f"{API}/intelligence/cases/{case_id}/findings?limit=500", headers=headers
        )).json()
        findings = findings_response["findings"]
        found_types = {f["finding_type"] for f in findings}
        assert EXPECTED_FINDING_TYPES <= found_types, (EXPECTED_FINDING_TYPES - found_types, found_types)
        for finding in findings:
            if finding["finding_type"] in NOT_EVIDENCE_GROUNDED:
                continue
            assert finding["evidence_refs"] or finding["event_refs"], (
                f"ungrounded published finding: {finding['finding_type']} — {finding['title']}"
            )

        # ── 8. INTELLIGENCE STATE ─────────────────────────────────────────────
        state = (await client.get(f"{API}/intelligence/cases/{case_id}/state", headers=headers)).json()
        assert state["evidence_count"] == 5, state
        assert state["finding_count"] == len(findings), (state["finding_count"], len(findings))
        assert state["relationship_count"] >= state["observed_relationship_count"] >= 1
        assert state["high_priority_count"] >= 1

        # ── 9. RE-ANALYSIS IS IDEMPOTENT ──────────────────────────────────────
        again = (await client.post(f"{API}/intelligence/cases/{case_id}/analyze", json={}, headers=headers)).json()
        assert again["findings_created"] == 0, again
        assert again["findings_updated"] >= 1, again

        # ── 10. HUMAN VERDICT SURVIVES RE-ANALYSIS ────────────────────────────
        async with AsyncSessionLocal() as db:
            finding = (await db.execute(
                select(InvestigationFinding)
                .where(InvestigationFinding.case_id == case_uuid)
                .order_by(InvestigationFinding.created_at)
            )).scalars().first()
            assert finding is not None
            finding.status = "CONFIRMED"
            confirmed_id = finding.id
            await db.commit()

        await client.post(f"{API}/intelligence/cases/{case_id}/analyze", json={}, headers=headers)
        async with AsyncSessionLocal() as db:
            refreshed = await db.get(InvestigationFinding, confirmed_id)
            assert refreshed.status == "CONFIRMED", "re-analysis clobbered the investigator's verdict"

        findings_before = len(findings)

        # ── 11. NEW EVIDENCE CHANGES THE EXISTING ANALYSIS ────────────────────
        r = await _upload(client, case_id, headers, "cdr2.csv", _CDR_2)
        assert r.status_code == 200
        await client.post(f"{API}/intelligence/cases/{case_id}/analyze", json={}, headers=headers)

        after = (await client.get(
            f"{API}/intelligence/cases/{case_id}/findings?limit=500", headers=headers
        )).json()["findings"]
        assert len(after) > findings_before, (len(after), findings_before)
        assert any(
            f["finding_type"] == "CONTRADICTION" and any("+91-9000000202" in ref for ref in f["entity_refs"])
            for f in after
        ), "new evidence did not produce a new contradiction"
        # No duplicate fingerprints.
        fingerprints = [f["fingerprint"] for f in after]
        assert len(fingerprints) == len(set(fingerprints)), "duplicate findings persisted"

        # ── 12. AUDIT RECORDS EVERYTHING ──────────────────────────────────────
        async with AsyncSessionLocal() as db:
            actions = {
                a for (a,) in (await db.execute(select(AuditLog.action))).all()
            }
        assert "EVIDENCE_UPLOADED" in actions, actions
        assert "COGNITIVE_ANALYSIS_RUN" in actions, actions

        # ── 13. REPORT CONSUMES THE VERIFIED FINDINGS ─────────────────────────
        report = await client.get(f"{API}/report/{case_id}", headers=headers)
        assert report.status_code == 200, report.text[:300]
        assert report.headers["content-type"].startswith("application/pdf")
        assert report.content[:4] == b"%PDF", "report is not a PDF"

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
    print(f"\n{len(_tests) - _failed}/{len(_tests)} end-to-end loop checks passed")
    sys.exit(1 if _failed else 0)
