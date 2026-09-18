"""Integration fixes: agent hard stops, governance classification, timestamp
separation, and transaction-parser validation.

These tests pin the behaviours the investigation loop depends on:

  • the agent STOPS when a case cannot be loaded (zero investigative actions)
  • the agent NEVER acts on a null/None target
  • a genuine out-of-plan action is a GOVERNANCE BLOCK (hold), while a tool
    failure is an ACTION_FAILED — the two are never conflated
  • the timeline is ordered by event_time and keeps ingested_at distinct
  • malformed transaction rows become PARSE_ERROR, never corrupted display text
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="integration_fixes_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'fixes.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(_TMP / "chroma"))
os.environ.setdefault("REPORT_OUTPUT_DIR", str(_TMP / "reports"))
os.environ.setdefault("INITIAL_ADMIN_USERNAME", "admin")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "admin123")

import asyncio  # noqa: E402

from armoriq.client import StubIntentMismatch  # noqa: E402
from db.models import Base, Case  # noqa: E402
from db.session import AsyncSessionLocal, engine  # noqa: E402


# ── Transaction parser validation (pure unit) ────────────────────────────────

def test_transaction_parser_rejects_corrupted_narration():
    from parsers.bank_csv_parser import parse_bank_csv

    path = _TMP / "corrupt_ledger.csv"
    path.write_text(
        "date,narration,credit,debit,balance\n"
        "2026-08-18 09:53:44,509:53:44,14.00,,1000\n"
    )
    events = parse_bank_csv(path, source_doc="corrupt_ledger.csv")
    assert events, "row should still be captured, not silently dropped"
    ev = events[0]
    assert ev["metadata"]["parser_status"] == "PARSE_ERROR", ev["metadata"]
    assert "corrupt_narration" in ev["metadata"]["parse_errors"], ev["metadata"]
    # The corrupted parser artifact must never reach investigator-facing text.
    assert "509:53:44" not in ev["text"], ev["text"]
    assert ev["text"].startswith("Unparsed transaction"), ev["text"]
    # No manufactured amount is presented for a parse error.
    assert ev["metadata"]["amount"] is None


def test_transaction_parser_accepts_clean_transfer():
    from parsers.bank_csv_parser import parse_bank_csv

    path = _TMP / "clean_transfer.csv"
    path.write_text(
        "transaction_id,timestamp_ist,debit_account,credit_account,amount_inr,upi_id,channel,status,description,reference\n"
        "TX0001,2026-08-18 09:50:03,ACCT-VICTIM-01,ACCT-MULE-11,285000,glasssparrow11@upi,UPI,SETTLED,KYC debit,UPI-0001\n"
    )
    events = parse_bank_csv(path, source_doc="clean_transfer.csv")
    assert len(events) == 1
    ev = events[0]
    assert ev["metadata"]["parser_status"] == "OK", ev["metadata"]
    assert ev["metadata"]["amount"] == 285000.0
    assert ev["metadata"]["from_account"] == "ACCT-VICTIM-01"
    assert ev["metadata"]["to_account"] == "ACCT-MULE-11"
    assert "ACCT-VICTIM-01 -> ACCT-MULE-11" in ev["text"]


# ── Finding lifecycle: revision + supersession ───────────────────────────────

def test_finding_revision_and_supersession():
    asyncio.run(_lifecycle_impl())


async def _lifecycle_impl():
    from sqlalchemy import select

    from db.models import Base, Case, InvestigationFinding
    from orchestration.contracts import HYPOTHESIS, CognitiveResult
    from orchestration.finding_service import supersede_stale_findings, upsert_findings

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        case = Case(case_number=f"LIFE-{uuid.uuid4().hex[:8]}", title="Lifecycle", priority="high")
        db.add(case)
        await db.commit()
        await db.refresh(case)
        case_id = case.id

        def _result(title, confidence, reasoning="", key="lifecycle:one"):
            return CognitiveResult(
                finding_type=HYPOTHESIS, title=title, confidence=confidence, reasoning=reasoning,
                source_engine="LifecycleEngine", dedup_key=key,
            )

        async def _row():
            return (await db.execute(
                select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
            )).scalars().all()

        await upsert_findings(db, case_id, [_result("v1", 0.4, "r1")])
        await db.commit()

        # ── TEST A: identical re-run → update, no duplicate, no revision bump ──
        counts = await upsert_findings(db, case_id, [_result("v1", 0.4, "r1")])
        await db.commit()
        assert counts["created"] == 0 and counts["updated"] == 1
        row = (await _row())[0]
        assert (row.component_scores.get("revision_count") or 0) == 0
        assert "REVISED" not in row.reason_codes

        # ── TEST B: changed confidence → revision, previous value preserved ────
        await upsert_findings(db, case_id, [_result("v1", 0.9, "r1")])
        await db.commit()
        row = (await _row())[0]
        assert row.component_scores["revision_count"] == 1
        assert row.component_scores["previous"]["confidence"] == 0.4, row.component_scores["previous"]
        assert "REVISED" in row.reason_codes

        # ── TEST A2: identical re-run must not erase revision metadata ─────────
        await upsert_findings(db, case_id, [_result("v1", 0.9, "r1")])
        await db.commit()
        row = (await _row())[0]
        assert row.component_scores["revision_count"] == 1
        assert row.component_scores.get("previous") is not None

        # ── TEST C: changed title + reasoning → previous snapshot + history ────
        await upsert_findings(db, case_id, [_result("v2", 0.9, "r2")])
        await db.commit()
        row = (await _row())[0]
        assert row.title == "v2"
        assert row.component_scores["revision_count"] == 2
        assert row.component_scores["previous"]["title"] == "v1"
        assert row.component_scores["previous"]["reasoning"] == "r1"
        history = row.component_scores.get("revision_history") or []
        assert len(history) == 2, history
        assert history[0]["confidence"] == 0.4 and history[1]["confidence"] == 0.9
        # The snapshot and the history entry must be independent copies, never
        # the same mutable object.
        assert row.component_scores["previous"] is not history[-1]

        # ── TEST D: CONFIRMED survives changed analysis ────────────────────────
        row.status = "CONFIRMED"
        await db.commit()
        await upsert_findings(db, case_id, [_result("v3", 0.1, "r3")])
        await db.commit()
        row = (await _row())[0]
        assert row.status == "CONFIRMED", "human verdict must survive re-analysis"

        # ── TEST E: DISMISSED survives changed analysis ────────────────────────
        await upsert_findings(db, case_id, [_result("d1", 0.5, "d", key="lifecycle:two")])
        await db.commit()
        dismissed = [r for r in await _row() if r.fingerprint != row.fingerprint][0]
        dismissed.status = "DISMISSED"
        await db.commit()
        await upsert_findings(db, case_id, [_result("d2", 0.8, "d2", key="lifecycle:two")])
        await db.commit()
        dismissed = await db.get(InvestigationFinding, dismissed.id)
        assert dismissed.status == "DISMISSED", "dismissed finding must not be resurrected"

        # ── TEST F: successfully-run engine that stops emitting → SUPERSEDED ───
        db.add(InvestigationFinding(
            case_id=case_id, fingerprint="stale-fp", finding_type=HYPOTHESIS,
            title="stale", severity="MEDIUM", status="OPEN", source_engine="OtherEngine",
        ))
        await db.commit()
        n = await supersede_stale_findings(db, case_id, "OtherEngine", set())
        await db.commit()
        assert n == 1
        stale = (await db.execute(
            select(InvestigationFinding).where(
                InvestigationFinding.case_id == case_id,
                InvestigationFinding.fingerprint == "stale-fp",
            )
        )).scalar_one()
        assert stale.status == "SUPERSEDED"
        assert "SUPERSEDED_BY_REANALYSIS" in stale.reason_codes

        # Human verdicts are never superseded.
        n2 = await supersede_stale_findings(db, case_id, "LifecycleEngine", set())
        await db.commit()
        assert n2 == 0
        assert (await db.get(InvestigationFinding, row.id)).status == "CONFIRMED"

    await engine.dispose()


# ── Lifecycle: failed/skipped engines must NOT supersede (PART 6 G/H) ────────

def test_orchestrator_does_not_supersede_on_failure_or_skip():
    asyncio.run(_orchestrator_lifecycle_impl())


async def _orchestrator_lifecycle_impl():
    from sqlalchemy import select

    from db.models import Base, Case, InvestigationFinding
    from orchestration.contracts import HYPOTHESIS, EngineSpec
    from orchestration.investigation_orchestrator import InvestigationOrchestrator

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        case = Case(case_number=f"ORCHLF-{uuid.uuid4().hex[:8]}", title="OrchLifecycle", priority="high")
        db.add(case)
        await db.commit()
        await db.refresh(case)
        case_id = case.id

        for eng, fp in (("FlakyEngine", "flaky-fp"), ("SkippedEngine", "skipped-fp")):
            db.add(InvestigationFinding(
                case_id=case_id, fingerprint=fp, finding_type=HYPOTHESIS,
                title="old", severity="MEDIUM", status="OPEN", source_engine=eng,
            ))
        await db.commit()

        def _boom(ctx):
            raise RuntimeError("engine failure")

        # G: engine raises. H: engine skipped (no whatsapp evidence).
        orch = InvestigationOrchestrator(specs=[
            EngineSpec(name="FlakyEngine", version="1.0", runner=_boom),
            EngineSpec(name="SkippedEngine", version="1.0", runner=lambda ctx: [],
                       requires_event_types=frozenset({"whatsapp_msg"})),
        ])
        res = await orch.run(db, case_id, trigger="test")
        await db.commit()
        assert res["engine_status"]["FlakyEngine"]["status"] == "error"
        assert res["engine_status"]["SkippedEngine"]["status"] == "skipped"

        rows = {r.fingerprint: r for r in (await db.execute(
            select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
        )).scalars().all()}
        assert rows["flaky-fp"].status == "OPEN", "failed engine must not supersede its findings"
        assert rows["skipped-fp"].status == "OPEN", "skipped engine must not supersede its findings"

        # F: the same engine now succeeds but emits nothing → stale OPEN is superseded.
        orch2 = InvestigationOrchestrator(specs=[
            EngineSpec(name="FlakyEngine", version="1.0", runner=lambda ctx: []),
        ])
        await orch2.run(db, case_id, trigger="test")
        await db.commit()
        rows = {r.fingerprint: r for r in (await db.execute(
            select(InvestigationFinding).where(InvestigationFinding.case_id == case_id)
        )).scalars().all()}
        assert rows["flaky-fp"].status == "SUPERSEDED"
        assert rows["skipped-fp"].status == "OPEN"

    await engine.dispose()


# ── Confidence must be labelled honestly ─────────────────────────────────────

def test_confidence_status_is_honest():
    from orchestration.finding_service import confidence_status_for

    # Similarity measures are not probabilities.
    assert confidence_status_for("MO_MATCH", 0.25) == "SCREENING"
    assert confidence_status_for("HIDDEN_LINK", 0.87) == "INFERRED"
    assert confidence_status_for("CROSS_CASE_SIGNAL", None) == "INFERRED"
    # Hand-set / heuristic rankings.
    assert confidence_status_for("HYPOTHESIS", None) == "NOT_CALIBRATED"
    assert confidence_status_for("NEXT_BEST_ACTION", None) == "NOT_CALIBRATED"
    # Deterministic rule outputs.
    assert confidence_status_for("CONTRADICTION", 1.0) == "RULE_BASED"
    assert confidence_status_for("VERIFICATION", None) == "RULE_BASED"
    assert confidence_status_for("FINGERPRINT_VARIANT", 0.9) == "RULE_BASED"
    # Simulations are never observations.
    assert confidence_status_for("COUNTERFACTUAL", None) == "SIMULATION"


# ── Verifier: deterministic graph contradiction ──────────────────────────────

def test_verifier_flags_unknown_event_and_entity_refs():
    from orchestration.contracts import HYPOTHESIS, CaseContext, CognitiveResult
    from orchestration.verification import verify_results

    ctx = CaseContext(
        case_id="c",
        evidence_files=[{"id": "ev1"}],
        events=[{"id": "e1"}],
        entities=[{"id": "ent1", "canonical_value": "ACCT-1"}],
    )
    bad = CognitiveResult(
        finding_type=HYPOTHESIS, title="bad refs", evidence_refs=["ev1"],
        event_refs=["e-999"], entity_refs=["ACCT-MISSING"], source_engine="X",
    )
    flags = verify_results(ctx, [bad])
    assert flags
    codes = set(flags[0].reason_codes)
    assert "UNKNOWN_EVENT_REFERENCE" in codes
    assert "UNKNOWN_ENTITY_REFERENCE" in codes
    # Every check exposes claim/check/result/reason.
    assert flags[0].citations and flags[0].citations[0]["result"] == "FAILED"
    assert flags[0].component_scores.get("checks")

    # A claim referencing only real evidence/events/entities passes.
    good = CognitiveResult(
        finding_type=HYPOTHESIS, title="good", evidence_refs=["ev1"],
        event_refs=["e1"], entity_refs=["ACCT-1"], source_engine="X",
    )
    assert verify_results(ctx, [good]) == []


def test_verifier_flags_terminal_claim_contradicted_by_graph():
    from orchestration.contracts import HYPOTHESIS, CaseContext, CognitiveResult
    from orchestration.verification import verify_results

    ctx = CaseContext(
        case_id="c",
        evidence_files=[{"id": "ev1"}],
        entities=[{"id": "e1", "canonical_value": "ACCT-MULE-14"}],
        relationships=[{
            "id": "r1", "source_value": "ACCT-MULE-14", "target_value": "ATM-CASH-01",
            "relationship_type": "TRANSFERRED_TO", "epistemic_status": "OBSERVED",
            "evidence_refs": ["ev1"], "event_refs": ["e1"],
        }],
    )
    claim = CognitiveResult(
        finding_type=HYPOTHESIS,
        title="MULE-14 is the final destination",
        description="The observed trail terminates at MULE-14.",
        entity_refs=["ACCT-MULE-14"],
        evidence_refs=["ev1"],
        source_engine="StubEngine",
    )
    flags = verify_results(ctx, [claim])
    assert flags, "terminal claim contradicted by the graph must be flagged"
    assert any("TERMINAL_CLAIM_CONTRADICTED_BY_GRAPH" in f.reason_codes for f in flags)
    # A deterministic rule result is not a calibrated probability.
    assert flags[0].confidence is None


# ── Routine-event detection (timeline collapsing) ────────────────────────────

def test_routine_event_detection():
    from routes.graph import _is_routine_event

    # Only an explicit structured marker counts.
    assert _is_routine_event({"routine": True}) is True
    assert _is_routine_event({"is_routine": True}) is True
    assert _is_routine_event({"event_category": "routine"}) is True
    # NEVER inferred from narration/description text — doing so could hide real
    # evidence.
    assert _is_routine_event({"description": "routine vendor settlement"}) is False
    assert _is_routine_event({"narration": "Routine payment"}) is False
    assert _is_routine_event({"purpose": "routine"}) is False
    assert _is_routine_event({"amount": 1000}) is False
    assert _is_routine_event({}) is False
    assert _is_routine_event(None) is False


# ── Next-Best derives from actual evidence gaps ──────────────────────────────

def test_nextbest_actions_derive_from_evidence_gaps():
    from orchestration.contracts import CaseContext
    from orchestration.engines.nextbest import SPEC as NB

    events = [
        {"id": "e1", "event_type": "bank_txn", "evidence_file_id": "ev1",
         "event_timestamp": "2026-08-18T09:50:03",
         "event_metadata": {"from_account": "ACCT-VICTIM-01", "to_account": "ACCT-MULE-11",
                            "amount": 285000.0}},
        {"id": "e2", "event_type": "whatsapp_msg", "evidence_file_id": "ev2",
         "event_timestamp": "2026-08-18T09:40:00",
         "event_metadata": {"sender": "+91-9000000101"}},  # no recipient → unknown endpoint
    ]
    ctx = CaseContext(
        case_id="c",
        events=events,
        entities=[
            {"id": "x", "canonical_value": "ACCT-MULE-11", "entity_type": "ACCOUNT"},
            {"id": "y", "canonical_value": "ACCT-VICTIM-01", "entity_type": "ACCOUNT"},
        ],
        relationships=[{
            "id": "r1", "source_value": "ACCT-MULE-11", "target_value": "+91-9000000101",
            "epistemic_status": "INFERRED", "confidence": 0.8,
            "evidence_refs": ["ev1", "ev2"], "event_refs": ["e1", "e2"],
        }],
    )
    results = NB.runner(ctx)
    assert results
    assert all(r.finding_type == "NEXT_BEST_ACTION" for r in results)

    gaps = {r.component_scores.get("evidence_gap") for r in results}
    assert "ENTITY_ATTRIBUTION" in gaps, gaps
    assert "UNKNOWN_ENDPOINT" in gaps, gaps
    assert "TEMPORAL_RECONCILIATION" in gaps, gaps
    assert "INFERRED_LINK_CORROBORATION" in gaps, gaps

    # Every gap-derived action names its gap, its information value and the
    # evidence/entities that evidence the gap.
    gap_actions = [r for r in results if r.component_scores.get("evidence_gap")]
    assert gap_actions
    for r in gap_actions:
        assert "EVIDENCE_GAP" in r.reason_codes
        assert r.component_scores.get("information_value") in ("HIGH", "MEDIUM", "LOW")
        assert r.component_scores.get("resolves")
        assert r.evidence_refs or r.event_refs or r.entity_refs


# ── Financial endpoint tolerates empty/corrupt narration (was HTTP 500) ───────

def test_financial_endpoint_handles_empty_narration():
    asyncio.run(_financial_impl())


async def _financial_impl():
    import httpx

    import main
    from db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await main._ensure_audit_genesis()
    await main._ensure_admin_seed()

    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://fin.test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        case_id = (await client.post(
            "/api/v1/cases", json={"title": "Fin Narration", "priority": "high"}, headers=headers
        )).json()["id"]

        # Row 1: empty narration (parser stores None). Row 2: corrupt narration.
        csv = (
            "date,narration,credit,debit,balance\n"
            "2026-08-18,,5000,,15000\n"
            "2026-08-18 09:53:44,509:53:44,14.00,,1000\n"
        )
        up = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": case_id, "source_type": "unknown"},
            files={"files": ("narr.csv", csv.encode(), "text/csv")},
            headers=headers,
        )
        assert up.status_code == 200, up.text

        # The financial endpoint previously raised because `meta['narration']`
        # was present with value None and `.strip()` was called on it.
        fin = await client.get(f"/api/v1/intelligence/financial/{case_id}", headers=headers)
        assert fin.status_code == 200, fin.text

        txs = await client.get(f"/api/v1/cases/{case_id}/transactions", headers=headers)
        assert txs.status_code == 200, txs.text

        timeline = (await client.get(f"/api/v1/timeline/{case_id}", headers=headers)).json()
        # This data has no explicit routine marker → nothing marked routine.
        assert timeline["routine_count"] == 0, timeline

    await engine.dispose()


# ── Agent hard stops + governance classification ─────────────────────────────

def test_agent_hard_stops_and_governance():
    asyncio.run(_agent_impl())


class _FakeClient:
    """Minimal ArmorIQ stand-in: blocks one action, authorizes the rest."""

    def __init__(self, blocked: str | None = None):
        self.blocked = blocked
        self.calls = 0

    def capture_plan(self, llm, prompt, plan, metadata=None):
        class _PlanCapture:
            _plan_hash = "test-plan"

        return _PlanCapture()

    def get_intent_token(self, plan_capture, validity_seconds=3600):
        return {"success": True, "simulated": True, "_plan_hash": "test-plan"}

    def invoke(self, mcp, action, intent_token=None, params=None):
        self.calls += 1
        if self.blocked and action == self.blocked:
            raise StubIntentMismatch(f"action '{action}' not declared")
        return {"success": True, "simulated": True}


async def _fast_assessment(case_id, entities, correlations, actions_taken, db):
    return {"assessment": "deterministic test assessment", "case_id": case_id}


async def _agent_impl():
    from armoriq import agent as agent_module
    from armoriq.agent import AutonomousInvestigationAgent

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Keep the assessment step deterministic/fast (no LLM dependency).
    agent_module.TOOL_DESCRIPTIONS["generate_incident_assessment"]["fn"] = _fast_assessment

    async with AsyncSessionLocal() as db:
        case = Case(case_number=f"FIX-{uuid.uuid4().hex[:8]}", title="Fixes Case", priority="high")
        db.add(case)
        await db.commit()
        await db.refresh(case)
        case_id = str(case.id)

        # ── 1. Case-load failure → hard stop, zero investigative actions ─────
        ghost = AutonomousInvestigationAgent(case_id=str(uuid.uuid4()), triggered_by="tester", db=db)
        result = await ghost.run()
        assert result["status"] == "failed_case_load", result["status"]
        action_types = [a["action_type"] for a in result["actions"]]
        assert action_types == ["CASE_LOAD_FAILED"], action_types
        assert "collect_security_logs" not in action_types
        assert result["pending_hold"] is None
        await db.rollback()

        # ── 2. No confirmed target → quarantine is NEVER requested ───────────
        live = AutonomousInvestigationAgent(case_id=case_id, triggered_by="tester", db=db)
        live._client = _FakeClient()
        live._IntentMismatch = StubIntentMismatch
        summary = await live.run()
        executed = [
            a for a in summary["actions"]
            if a["action_type"] == "ACTION_EXECUTED"
        ]
        assert not any(a["details"].get("action") == "quarantine_account" for a in executed), executed
        assert summary["pending_hold"] is None
        assert summary["skipped_actions"]["quarantine_account"] == "no_confirmed_target", summary["skipped_actions"]

        # ── 2b. Investigation plan + final report from the shared case state ──
        assert summary["investigation_plan"], "agent must declare an investigation plan"
        assert len(summary["investigation_plan"]) >= 5
        assert any(a["action_type"] == "INVESTIGATION_PLAN" for a in summary["actions"])
        assert summary["case_snapshot"]["findings"] >= 0
        assert summary["final_report"] is not None
        assert "governance" in summary["final_report"]
        assert summary["final_report"]["governance"]["high_impact_actions_executed"] == 0
        assert isinstance(summary["final_report"]["recommended_next_actions"], list)

        # ── 3. Governance block (out-of-plan) vs tool failure are distinct ───
        gov = AutonomousInvestigationAgent(case_id=case_id, triggered_by="tester", db=db)
        gov._client = _FakeClient(blocked="modify_network_control_config")
        gov._IntentMismatch = StubIntentMismatch
        gov.intent_token = {"_plan_hash": "test"}

        async def _should_not_run(**_):
            raise AssertionError("out-of-plan tool must not execute before approval")

        intercepted = await gov._dispatch_with_armoriq(
            action="modify_network_control_config",
            description="block ip",
            tool_fn=_should_not_run,
            tool_params={"rule_id": "fwr-002", "suspect_ip": "1.2.3.4", "modification_type": "add_block"},
            ai_thought="perimeter block recommended",
        )
        assert intercepted is True
        assert gov.status == "awaiting_approval"
        assert gov.pending_hold and gov.pending_hold["governance_outcome"] == "blocked_by_design"
        assert any(a["action_type"] == "GOVERNANCE_BLOCK" for a in gov.actions)

        # A tool failure on an AUTHORIZED action must never become a hold.
        tool = AutonomousInvestigationAgent(case_id=case_id, triggered_by="tester", db=db)
        tool._client = _FakeClient()
        tool._IntentMismatch = StubIntentMismatch
        tool.intent_token = {"_plan_hash": "test"}

        async def _boom(**_):
            raise RuntimeError("tool exploded")

        intercepted = await tool._dispatch_with_armoriq(
            action="collect_security_logs",
            description="collect",
            tool_fn=_boom,
            tool_params={},
            ai_thought="collect logs",
        )
        assert intercepted is False, "tool failure must not be reported as a governance block"
        assert tool.pending_hold is None
        assert any(a["action_type"] == "ACTION_FAILED" for a in tool.actions)
        assert not any(a["action_type"] == "GOVERNANCE_BLOCK" for a in tool.actions)

        # ── 4. Exception class matches the active client ─────────────────────
        from armoriq.client import _LocalStubClient, get_intent_mismatch_exception
        assert get_intent_mismatch_exception(_LocalStubClient()) is StubIntentMismatch

    await engine.dispose()


if __name__ == "__main__":
    _tests = [(n, f) for n, f in sorted(globals().items())
              if n.startswith("test_") and callable(f)]
    _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            print(f"[PASS] {_name}")
        except Exception as _e:  # noqa: BLE001
            _failed += 1
            import traceback
            print(f"[FAIL] {_name}: {_e!r}")
            traceback.print_exc()
    print(f"\n{len(_tests) - _failed}/{len(_tests)} integration-fix checks passed")
    sys.exit(1 if _failed else 0)
