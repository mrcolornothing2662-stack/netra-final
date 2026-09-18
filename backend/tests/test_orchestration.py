"""Regression guards for the Phase-2 intelligence foundation.

Covers:
  • CognitiveResult contract (validation + stable fingerprint)
  • EngineSpec applicability selection (run vs skipped)
  • Orchestrator run: findings persisted, deduplicated, engine status recorded
  • Human review status (CONFIRMED/DISMISSED) preserved across re-analysis
  • AnalysisRun + IntelligenceState materialisation
  • The real Contradiction engine adapter end-to-end (ledger break + impossible travel)

Each DB test owns an isolated async SQLite engine so it never shares a pool or
event loop with the other regression files. Dual-mode runnable AND pytest.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="orch_test_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'orch.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from db.models import (  # noqa: E402
    AnalysisRun,
    Base,
    Case,
    CaseIntelligenceState,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
)
from orchestration.contracts import (  # noqa: E402
    CONTRADICTION,
    CROSS_CASE_SIGNAL,
    HYPOTHESIS,
    SEVERITY_CRITICAL,
    SEVERITY_MEDIUM,
    STATUS_CONFIRMED,
    STATUS_OPEN,
    VERIFICATION,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)
from orchestration.investigation_orchestrator import InvestigationOrchestrator  # noqa: E402
from orchestration.verification import verify_results  # noqa: E402


# ── Pure contract tests ───────────────────────────────────────────────────────

def test_cognitive_result_validation_and_fingerprint():
    result = CognitiveResult(
        finding_type=HYPOTHESIS, title="Direct involvement",
        confidence=1.7, severity=SEVERITY_MEDIUM, source_engine="HypothesisEngine",
    )
    assert result.confidence == 1.0, "confidence must clamp to [0,1]"
    again = CognitiveResult(
        finding_type=HYPOTHESIS, title="Direct involvement",
        severity=SEVERITY_MEDIUM, source_engine="HypothesisEngine",
    )
    assert result.fingerprint() == again.fingerprint(), "fingerprint must be stable"

    changed = CognitiveResult(
        finding_type=HYPOTHESIS, title="Direct involvement",
        severity=SEVERITY_MEDIUM, source_engine="HypothesisEngine",
        entity_refs=["PERSON-1"],
    )
    assert changed.fingerprint() != result.fingerprint()

    try:
        CognitiveResult(finding_type="NOT_A_TYPE", title="x")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid finding_type must raise")


def test_engine_spec_applicability():
    always = EngineSpec(name="Always", version="1", runner=lambda ctx: [])
    whatsapp = EngineSpec(
        name="WA", version="1", runner=lambda ctx: [],
        requires_event_types=frozenset({"whatsapp_msg"}),
    )
    ctx = CaseContext(case_id="c1", events=[{"event_type": "bank_txn"}])
    assert always.applies(ctx) is True
    assert whatsapp.applies(ctx) is False
    ctx.events.append({"event_type": "whatsapp_msg"})
    assert whatsapp.applies(ctx) is True


def test_verification_flags_ungrounded_findings():
    context = CaseContext(case_id="c1", evidence_files=[{"id": "ev-1"}])
    grounded = CognitiveResult(finding_type=HYPOTHESIS, title="grounded",
                               evidence_refs=["ev-1"], source_engine="X")
    ungrounded = CognitiveResult(finding_type=HYPOTHESIS, title="ungrounded",
                                 source_engine="X")
    bad_ref = CognitiveResult(finding_type=HYPOTHESIS, title="bad ref",
                              evidence_refs=["ev-999"], source_engine="X")
    zero_knowledge = CognitiveResult(finding_type=CROSS_CASE_SIGNAL,
                                     title="zero-knowledge", source_engine="CrossCaseEngine")

    flags = verify_results(context, [grounded, ungrounded, bad_ref, zero_knowledge])
    assert len(flags) == 2, flags
    assert all(f.finding_type == VERIFICATION for f in flags)
    assert all(f.source_engine == "OutputVerifier" for f in flags)
    assert any("UNGROUNDED_ASSERTION" in f.reason_codes for f in flags)
    assert any("UNKNOWN_EVIDENCE_REFERENCE" in f.reason_codes for f in flags)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _stub_result(evidence_refs=None) -> CognitiveResult:
    return CognitiveResult(
        finding_type=HYPOTHESIS, title="Stub hypothesis", description="deterministic",
        confidence=0.5, severity=SEVERITY_MEDIUM,
        source_engine="StubEngine", engine_version="1.0",
        evidence_refs=list(evidence_refs or []),
        reason_codes=["stub"], dedup_key="stub:one",
    )


async def _fresh_session():
    engine = create_async_engine(f"sqlite+aiosqlite:///{_TMP / uuid.uuid4().hex}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _make_case(Session, title: str) -> Case:
    async with Session() as db:
        case = Case(case_number=f"ORCH-{uuid.uuid4().hex[:8]}", title=title,
                    priority="high", status="open")
        db.add(case)
        await db.commit()
        await db.refresh(case)
        return case


async def _add_bank_events(Session, case_id, rows, evidence_id=None):
    async with Session() as db:
        for i, row in enumerate(rows):
            db.add(EvidenceEvent(
                case_id=case_id, evidence_file_id=evidence_id, event_type="bank_txn",
                event_timestamp=datetime(2026, 8, 18, 9, 50, tzinfo=timezone.utc),
                event_metadata=row,
            ))
        await db.commit()


async def _add_evidence_file(Session, case_id) -> uuid.UUID:
    async with Session() as db:
        f = EvidenceFile(case_id=case_id, filename="stmt.csv", original_name="stmt.csv",
                         file_type="csv", source_type="bank_statement",
                         sha256_hash=uuid.uuid4().hex, storage_path="/tmp/stmt.csv",
                         upload_status="processed")
        db.add(f)
        await db.commit()
        await db.refresh(f)
        return f.id


# ── Registry / dedup / state ──────────────────────────────────────────────────

def test_orchestrator_registry_dedup_and_state():
    asyncio.run(_registry_impl())


async def _registry_impl():
    engine, Session = await _fresh_session()
    try:
        case = await _make_case(Session, "Registry")
        await _add_bank_events(Session, case.id, [{"credit": 100.0, "debit": 0.0, "balance": 100.0}])
        evidence_id = await _add_evidence_file(Session, case.id)

        skipped_spec = EngineSpec(
            name="WhatsAppEngine", version="1.0", runner=lambda ctx: [],
            requires_event_types=frozenset({"whatsapp_msg"}),
        )
        specs = [
            EngineSpec(
                name="StubEngine", version="1.0",
                runner=lambda ctx: [_stub_result([str(evidence_id)])],
            ),
            skipped_spec,
        ]
        orchestrator = InvestigationOrchestrator(specs=specs)

        async with Session() as db:
            first = await orchestrator.run(db, case.id, trigger="manual")
            await db.commit()
        assert first["engines_run"] == ["StubEngine"], first
        assert first["engines_skipped"] == ["WhatsAppEngine"], first
        assert first["findings_created"] == 1 and first["findings_updated"] == 0
        assert first["state"]["finding_count"] == 1
        assert first["engine_status"]["StubEngine"]["status"] == "ok"
        assert first["engine_status"]["WhatsAppEngine"]["status"] == "skipped"

        # Re-run: same finding updated, never duplicated.
        async with Session() as db:
            second = await orchestrator.run(db, case.id, trigger="manual")
            await db.commit()
        assert second["findings_created"] == 0 and second["findings_updated"] == 1

        async with Session() as db:
            findings = (await db.execute(
                select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
            )).scalars().all()
            assert len(findings) == 1, "duplicate finding created"
            assert findings[0].status == STATUS_OPEN
            # Investigator confirms it; re-analysis must not erase the verdict.
            findings[0].status = STATUS_CONFIRMED
            await db.commit()

        async with Session() as db:
            third = await orchestrator.run(db, case.id, trigger="manual")
            await db.commit()
        async with Session() as db:
            finding = (await db.execute(
                select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
            )).scalar_one()
            assert finding.status == STATUS_CONFIRMED, "re-analysis clobbered human verdict"
            assert len((await db.execute(
                select(AnalysisRun).where(AnalysisRun.case_id == case.id)
            )).scalars().all()) == 3
            state = (await db.execute(
                select(CaseIntelligenceState).where(CaseIntelligenceState.case_id == case.id)
            )).scalar_one()
            assert state.finding_count == 1
            assert state.evidence_count == 1
            assert state.last_run_id is not None
    finally:
        await engine.dispose()


# ── Real contradiction engine end-to-end ──────────────────────────────────────

def test_contradiction_engine_through_orchestrator():
    asyncio.run(_contradiction_impl())


async def _contradiction_impl():
    engine, Session = await _fresh_session()
    try:
        case = await _make_case(Session, "Contradiction")
        evidence_id = await _add_evidence_file(Session, case.id)

        # Ledger with a balance break on the last row.
        await _add_bank_events(Session, case.id, [
            {"credit": 50000.0, "debit": 0.0, "balance": 120000.0, "model": "ledger"},
            {"credit": 25000.0, "debit": 0.0, "balance": 145000.0, "model": "ledger"},
            {"credit": 0.0, "debit": 20000.0, "balance": 999999.0, "model": "ledger"},
        ], evidence_id=evidence_id)

        # Two CDR rows: same phone in Delhi then Hyderabad 26 min later.
        async with Session() as db:
            db.add_all([
                EvidenceEvent(
                    case_id=case.id, evidence_file_id=evidence_id, event_type="call",
                    event_timestamp=datetime(2026, 8, 18, 3, 58, 2, tzinfo=timezone.utc),
                    event_metadata={"caller": "+91-9000000101", "callee": "+91-9000000102",
                                    "cell_id": "DEL-IGI-04", "lat": 28.5561, "lon": 77.1008},
                ),
                EvidenceEvent(
                    case_id=case.id, evidence_file_id=evidence_id, event_type="call",
                    event_timestamp=datetime(2026, 8, 18, 4, 24, 4, tzinfo=timezone.utc),
                    event_metadata={"caller": "+91-9000000101", "callee": "+91-9000000103",
                                    "cell_id": "CYB-HYD-03", "lat": 17.3850, "lon": 78.4867},
                ),
            ])
            await db.commit()

        orchestrator = InvestigationOrchestrator()  # default registry
        async with Session() as db:
            result = await orchestrator.run(db, case.id, trigger="manual")
            await db.commit()

        assert "ContradictionEngine" in result["engines_run"], result
        assert result["findings_created"] >= 2, result
        # Benchmark must never run inside a real case analysis.
        assert "BenchmarkGenerator" not in result["engine_status"], result["engine_status"]
        # Multi-modal CDR/Bank evidence may trigger MO engine (F07); otherwise skipped.
        assert result["engine_status"]["MOEngine"]["status"] in ("skipped", "ok")
        # Cross-case stays gated off by default.
        assert result["engine_status"]["CrossCaseEngine"]["status"] == "skipped"

        async with Session() as db:
            findings = (await db.execute(
                select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
            )).scalars().all()
            contradiction = [f for f in findings if f.finding_type == CONTRADICTION]
            assert contradiction, [(f.finding_type, f.title) for f in findings]
            assert all(f.source_engine == "ContradictionEngine" for f in contradiction)
            # Every contradiction is traceable to evidence.
            assert all(f.evidence_refs for f in contradiction), [f.evidence_refs for f in contradiction]

            ledger = [f for f in contradiction if "Ledger" in f.title]
            travel = [f for f in contradiction if "Travel" in f.title]
            assert ledger and travel, [(f.title, f.reason_codes) for f in contradiction]
            assert any("MISSING_ROWS_OR_EDITED_BLOCK" in (f.reason_codes or []) or
                       "ALTERED_BALANCE" in (f.reason_codes or []) for f in ledger)
            assert any("+91-9000000101" in (f.entity_refs or []) for f in travel)
            assert any(f.severity == SEVERITY_CRITICAL for f in contradiction)

            state = (await db.execute(
                select(CaseIntelligenceState).where(CaseIntelligenceState.case_id == case.id)
            )).scalar_one()
            assert state.finding_count == len(findings)
            assert state.high_priority_count >= 1
            assert state.evidence_count == 1 and state.processed_evidence_count == 1
            assert state.entity_count == 0
            assert state.findings_by_type.get(CONTRADICTION) == len(contradiction)
    finally:
        await engine.dispose()


# ── Engine adapters (pure, context in → findings out) ─────────────────────────

def test_default_registry_connects_engines_and_isolates_benchmark():
    names = {spec.name for spec in InvestigationOrchestrator().specs}
    expected = {
        "ContradictionEngine", "HiddenLinkEngine", "FingerprintEngine", "MOEngine",
        "HypothesisEngine", "NextBestEngine", "ReplayEngine", "CrossCaseEngine",
        "CounterfactualEngine",
    }
    assert expected <= names, expected - names
    assert "BenchmarkGenerator" not in names, "benchmark must stay out of real-case analysis"


def test_hidden_link_adapter_surfaces_inferred_edge():
    from orchestration.engines.hidden_link import SPEC as HL
    ctx = CaseContext(case_id="c", relationships=[{
        "id": "r1", "source_value": "PHONE-1", "target_value": "ACCT-1",
        "relationship_type": "ASSOCIATED_WITH", "epistemic_status": "INFERRED",
        "confidence": 0.87, "evidence_refs": ["ev1"], "event_refs": ["e1"],
        "component_scores": {"temporal": 0.4}, "reason_codes": ["temporal proximity"],
        "source_engine": "HiddenLinkEngine", "engine_version": "2.0",
    }])
    assert HL.applies(ctx) is True
    results = HL.runner(ctx)
    assert len(results) == 1
    finding = results[0]
    assert finding.finding_type == "HIDDEN_LINK"
    assert finding.confidence == 0.87
    assert finding.evidence_refs == ["ev1"]
    assert "INFERRED_RELATIONSHIP" in finding.reason_codes


def test_fingerprint_adapter_detects_variant():
    from orchestration.engines.fingerprint import SPEC as FP

    def _event(file_id, event_id, ref):
        return {
            "id": event_id, "event_type": "bank_txn",
            "event_timestamp": "2026-01-01T00:00:00", "evidence_file_id": file_id,
            "event_metadata": {"amount": 100, "ref_no": ref}, "text_content": "row",
        }
    ctx = CaseContext(case_id="c", evidence_files=[{"id": "f1"}, {"id": "f2"}], events=[
        _event("f1", "e1", "A"), _event("f1", "e2", "B"),
        _event("f2", "e3", "A"), _event("f2", "e4", "B"), _event("f2", "e5", "C"),
    ])
    results = FP.runner(ctx)
    assert results and results[0].finding_type == "FINGERPRINT_VARIANT"
    assert sorted(results[0].evidence_refs) == ["f1", "f2"]


def test_mo_adapter_matches_digital_arrest_script():
    from orchestration.engines.mo import SPEC as MO
    script = [
        "We are from CBI crime branch. A notice is issued.",
        "Join the video call now.",
        "You will go to jail, this is non-bailable.",
        "Transfer the money for verification.",
        "Delete the chat and block this number.",
    ]
    events = [{
        "id": f"e{i}", "event_type": "whatsapp_msg", "evidence_file_id": "ev1",
        "event_timestamp": "2026-04-22T09:00:00", "text_content": text,
        "event_metadata": {"sender": "Inspector"},
    } for i, text in enumerate(script)]
    ctx = CaseContext(case_id="c", events=events)
    assert MO.applies(ctx) is True
    results = MO.runner(ctx)
    assert results and results[0].finding_type == "MO_MATCH"
    assert results[0].confidence == 1.0
    assert results[0].event_refs, "MO finding must cite the triggering messages"


def test_hypothesis_and_nextbest_adapters_from_bank_context():
    from orchestration.engines.hypothesis import SPEC as HY
    from orchestration.engines.nextbest import SPEC as NB
    events = [
        {"id": "e1", "event_type": "bank_txn", "evidence_file_id": "ev1",
         "event_timestamp": "2026-05-01T10:00:00",
         "event_metadata": {"credit": 50000.0, "debit": 0.0, "balance": 50000.0, "account": "ACCT-1"},
         "text_content": "credit"},
        {"id": "e2", "event_type": "bank_txn", "evidence_file_id": "ev1",
         "event_timestamp": "2026-05-01T10:04:00",
         "event_metadata": {"credit": 0.0, "debit": 49000.0, "balance": 1000.0, "account": "ACCT-1"},
         "text_content": "debit"},
    ]
    ctx = CaseContext(
        case_id="c", case_created_at="2026-05-01T09:00:00",
        events=events, entities=[{"canonical_value": "+919000000001", "entity_type": "PHONE"}],
    )
    hypothesis_results = HY.runner(ctx)
    assert any(r.finding_type == HYPOTHESIS for r in hypothesis_results)
    assert all(r.confidence is None for r in hypothesis_results), "rule-based, not calibrated"

    nextbest_results = NB.runner(ctx)
    assert nextbest_results
    assert all(r.finding_type == "NEXT_BEST_ACTION" for r in nextbest_results)


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
    print(f"\n{len(_tests) - _failed}/{len(_tests)} orchestration checks passed")
    sys.exit(1 if _failed else 0)
