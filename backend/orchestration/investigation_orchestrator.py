from __future__ import annotations

"""
CyberDrishti AI — Investigation Orchestrator

The central controller of the cognitive layer. Given a case it:

  1. snapshots the case state once (CaseContext)
  2. selects only the engines applicable to the available evidence
  3. runs them and collects CognitiveResults
  4. persists findings through the Finding Service (deduplicated)
  5. refreshes the materialised Intelligence State
  6. records an AnalysisRun for the audit trail

Engines that do not apply are recorded as skipped, never silently ignored.
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import AnalysisRun, Case
from orchestration import intelligence_state
from orchestration.contracts import CaseContext, EngineSpec, resolve_results
from orchestration.context import load_case_context
from orchestration.finding_service import supersede_stale_findings, upsert_findings
from orchestration.verification import verify_results
from utils.audit import append_audit

import logging

logger = logging.getLogger(__name__)


def default_engine_specs() -> list[EngineSpec]:
    """
    Engines wired into the orchestrator.

    Benchmark deliberately does NOT appear here — it is system validation and
    must never contaminate a real case. The verifier is not a producer either;
    it runs at the output boundary (see orchestration/verification.py).
    """
    from orchestration.engines.contradiction import SPEC as contradiction_spec
    from orchestration.engines.anomaly import SPEC as anomaly_spec
    from orchestration.engines.counterfactual import SPEC as counterfactual_spec
    from orchestration.engines.crosscase import SPEC as crosscase_spec
    from orchestration.engines.fingerprint import SPEC as fingerprint_spec
    from orchestration.engines.hidden_link import SPEC as hidden_link_spec
    from orchestration.engines.hypothesis import SPEC as hypothesis_spec
    from orchestration.engines.mo import SPEC as mo_spec
    from orchestration.engines.nextbest import SPEC as nextbest_spec
    from orchestration.engines.defence import SPEC as defence_spec
    from orchestration.engines.replay import SPEC as replay_spec

    return [
        contradiction_spec,
        anomaly_spec,
        hidden_link_spec,
        fingerprint_spec,
        mo_spec,
        hypothesis_spec,
        nextbest_spec,
        defence_spec,
        replay_spec,
        crosscase_spec,
        counterfactual_spec,
    ]


class InvestigationOrchestrator:
    def __init__(self, specs: Sequence[EngineSpec] | None = None):
        self._specs: list[EngineSpec] = []
        self._by_name: dict[str, EngineSpec] = {}
        for spec in (list(specs) if specs is not None else default_engine_specs()):
            self.register(spec)

    def register(self, spec: EngineSpec) -> None:
        if spec.name in self._by_name:
            self._specs[self._specs.index(self._by_name[spec.name])] = spec
        else:
            self._specs.append(spec)
        self._by_name[spec.name] = spec

    @property
    def specs(self) -> list[EngineSpec]:
        return list(self._specs)

    def select(
        self,
        context: CaseContext,
        engine_names: Sequence[str] | None = None,
    ) -> tuple[list[EngineSpec], list[EngineSpec]]:
        """Return (applicable, skipped) engines; names filter is optional."""
        if engine_names is not None:
            wanted = set(engine_names)
            candidates = [s for s in self._specs if s.name in wanted]
        else:
            candidates = list(self._specs)
        run = [s for s in candidates if s.applies(context)]
        skipped = [s for s in candidates if not s.applies(context)]
        return run, skipped

    async def run(
        self,
        db: AsyncSession,
        case_id,
        *,
        trigger: str = "manual",
        engine_names: Sequence[str] | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        started = time.perf_counter()
        run_row = AnalysisRun(
            case_id=case_uuid,
            trigger=trigger,
            status="running",
            engines_requested=list(engine_names) if engine_names else [s.name for s in self._specs],
        )
        db.add(run_row)
        await db.flush()

        try:
            # Materialise inferred (hidden) relationships from the current
            # evidence first, so the HiddenLink engine and every downstream
            # consumer reason over a complete case graph — the same scan as
            # POST /correlations/{case_id}/run. Failures here never abort the run;
            # they are recorded and the deterministic engines still execute.
            correlation_summary: dict[str, Any] = {}
            try:
                from correlation.runner import run_case_correlations
                case_row = await db.get(Case, case_uuid)
                if case_row is not None:
                    correlation_summary = await run_case_correlations(db, case_row)
                else:
                    correlation_summary = {"error": "case_not_found"}
            except Exception as exc:
                logger.warning(f"[Orchestrator] correlation materialisation failed: {exc}")
                correlation_summary = {"error": str(exc)}

            context = await load_case_context(db, case_uuid)
            if settings.enable_cross_case_analysis:
                from orchestration.engines.crosscase import load_cross_case_collisions
                context.cross_case_collisions = await load_cross_case_collisions(db, case_uuid)
            selected, skipped = self.select(context, engine_names)

            engine_status: dict[str, Any] = {}
            results = []
            for spec in selected:
                try:
                    engine_results = await resolve_results(spec, context)
                    results.extend(engine_results)
                    engine_status[spec.name] = {
                        "status": "ok",
                        "version": spec.version,
                        "findings": len(engine_results),
                    }
                except Exception as exc:  # one engine must not fail the run
                    engine_status[spec.name] = {
                        "status": "error",
                        "version": spec.version,
                        "error": str(exc),
                    }
            for spec in skipped:
                engine_status.setdefault(spec.name, {
                    "status": "skipped",
                    "version": spec.version,
                    "reason": spec.skip_reason,
                })

            # Output boundary: the verifier flags any ungrounded finding before
            # it is published (evidence / inference / conclusion stay separate).
            verification_flags = verify_results(context, results)
            if verification_flags:
                results.extend(verification_flags)
                engine_status["OutputVerifier"] = {
                    "status": "ok",
                    "version": "1.0",
                    "findings": len(verification_flags),
                }

            counts = await upsert_findings(db, case_uuid, results)

            # Lifecycle: a successfully-run engine that no longer produces a
            # previously-OPEN finding means that finding is stale → SUPERSEDED.
            # Findings the engine still emits are updated in place; human
            # CONFIRMED/DISMISSED verdicts are never touched.
            emitted_by_engine: dict[str, set[str]] = {}
            for r in results:
                emitted_by_engine.setdefault(r.source_engine, set()).add(r.fingerprint())
            superseded_total = 0
            for name, status in engine_status.items():
                if isinstance(status, dict) and status.get("status") == "ok":
                    superseded_total += await supersede_stale_findings(
                        db, case_uuid, name, emitted_by_engine.get(name, set())
                    )
            counts["superseded"] = superseded_total

            state = await intelligence_state.compute_state(db, case_uuid, engine_status=engine_status)
            await intelligence_state.persist_state(db, case_uuid, state, last_run_id=run_row.id)

            duration_ms = int((time.perf_counter() - started) * 1000)
            run_row.status = "completed"
            run_row.completed_at = datetime.now(timezone.utc)
            run_row.duration_ms = duration_ms
            run_row.engines_run = [s.name for s in selected]
            run_row.engines_skipped = [s.name for s in skipped]
            run_row.findings_created = counts["created"]
            run_row.findings_updated = counts["updated"]
            run_row.summary = {
                "engines_run": len(selected),
                "engines_skipped": len(skipped),
                "results": counts["total"],
                "state": state,
            }
            await db.flush()

            await append_audit(
                db,
                action="COGNITIVE_ANALYSIS_RUN",
                resource_type="case",
                resource_id=str(case_uuid),
                details={
                    "run_id": str(run_row.id),
                    "trigger": trigger,
                    "engines_run": [s.name for s in selected],
                    "engines_skipped": [s.name for s in skipped],
                    "findings_created": counts["created"],
                    "findings_updated": counts["updated"],
                    "duration_ms": duration_ms,
                    "correlation_materialisation": correlation_summary,
                },
                user_id=actor_id,
            )

            return {
                "run_id": str(run_row.id),
                "case_id": str(case_uuid),
                "status": "completed",
                "trigger": trigger,
                "duration_ms": duration_ms,
                "engines_run": [s.name for s in selected],
                "engines_skipped": [s.name for s in skipped],
                "engine_status": engine_status,
                "findings_created": counts["created"],
                "findings_updated": counts["updated"],
                "findings_total": counts["total"],
                "correlation_materialisation": correlation_summary,
                "state": state,
            }
        except Exception as exc:
            run_row.status = "failed"
            run_row.completed_at = datetime.now(timezone.utc)
            run_row.duration_ms = int((time.perf_counter() - started) * 1000)
            run_row.error = str(exc)
            await db.flush()
            try:
                await append_audit(
                    db,
                    action="COGNITIVE_ANALYSIS_FAILED",
                    resource_type="case",
                    resource_id=str(case_uuid),
                    details={"run_id": str(run_row.id), "trigger": trigger, "error": str(exc)},
                    user_id=actor_id,
                )
            except Exception:
                pass
            raise


async def run_case_orchestration(
    db: AsyncSession,
    case_id,
    *,
    trigger: str = "manual",
    engine_names: Sequence[str] | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Convenience entry point using the default engine registry."""
    orchestrator = InvestigationOrchestrator()
    return await orchestrator.run(
        db, case_id, trigger=trigger, engine_names=engine_names, actor_id=actor_id
    )
