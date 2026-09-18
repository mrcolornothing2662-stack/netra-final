from __future__ import annotations

"""
Counterfactual Engine Adapter

Counterfactual freeze analysis is investigator-driven: it needs an explicit
account and freeze time, and its output is a simulation, not observed evidence.
It therefore registers with the orchestrator (so it appears in engine status)
but never runs automatically during passive analysis — it is served by
POST /cognitive/cases/{id}/counterfactual-freeze.
"""
from typing import Any
from orchestration.contracts import (
    COUNTERFACTUAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "CounterfactualEngine"
ENGINE_VERSION = "1.1"


def run(context: CaseContext) -> list[CognitiveResult]:
    """Automated runner yields no passive findings because what-if simulation
    requires investigator-supplied intervention parameters."""
    return []


def build_counterfactual_result(
    simulation_result: dict[str, Any],
    case_context: CaseContext | None = None,
) -> CognitiveResult:
    """Transforms a 4-stage simulation result into a standardized CognitiveResult
    carrying complete provenance, component scores, and explicit COUNTERFACTUAL tags."""
    interv = simulation_result.get("stage_2_intervention", {})
    comp = simulation_result.get("stage_4_comparison", {})

    target_accounts = interv.get("target_accounts", [])
    acc_str = ", ".join(target_accounts) if target_accounts else "TARGET_ACCOUNT"
    freeze_time = interv.get("freeze_time", "UNSPECIFIED")
    preserved_total = comp.get("preserved_total", simulation_result.get("preserved_total", 0.0))
    pct = comp.get("preservation_percentage", 0.0)
    blocked_count = comp.get("blocked_debits_count", len(simulation_result.get("blocked_out_events", [])))
    starved_count = comp.get("starved_attempts_count", len(simulation_result.get("unfunded_attempts", [])))

    severity = SEVERITY_HIGH if preserved_total >= 50000.0 else SEVERITY_MEDIUM
    dedup_seed = f"{acc_str}:{freeze_time}:{preserved_total}"

    return CognitiveResult(
        finding_type=COUNTERFACTUAL,
        title=f"What-If Simulation: Preserved ₹{preserved_total:,.2f} ({pct}%) via Debit Freeze on {acc_str}",
        description=(
            f"Counterfactual intervention at {freeze_time}: blocked {blocked_count} outbound debits, "
            f"retaining ₹{preserved_total:,.2f} in victim funds and starving {starved_count} downstream mule transfers."
        ),
        confidence=None,  # Model-based network interdiction estimate, not a statistical certainty
        severity=severity,
        source_engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        entity_refs=target_accounts,
        event_refs=[],
        evidence_refs=[],
        component_scores={
            "preserved_total": preserved_total,
            "dissipated_total": comp.get("dissipated_total", 0.0),
            "preservation_ratio": comp.get("preservation_ratio", 0.0),
            "preservation_percentage": pct,
            "blocked_debits_count": blocked_count,
            "starved_attempts_count": starved_count,
            "epistemic_status": "COUNTERFACTUAL",
        },
        reason_codes=["COUNTERFACTUAL", "WHAT_IF_FREEZE", "SIMULATION_SANDBOX"],
        reasoning=(
            f"If accounts {acc_str} had been frozen under Section 106 BNSS at {freeze_time}, "
            f"a lower bound of ₹{preserved_total:,.2f} would have been prevented from dissipating "
            f"into Layer-2 mule off-ramps."
        ),
        dedup_key=f"cf_freeze:{dedup_seed}",
    )


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="What-if account-freeze simulation (investigator-driven).",
    applicability=lambda context: False,
    skip_reason="requires_intervention_parameters",
)
