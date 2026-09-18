from __future__ import annotations

"""
Next-Best Action Adapter

Turns the Golden-Hours action ranking into NEXT_BEST_ACTION findings so the
investigator sees the highest-value next step (and the evidence gap it closes)
alongside every other finding. Drafts keep their DRAFT banner.
"""
from datetime import datetime, timezone

from cognitive import data_path
from cognitive.nextbest import load_catalog, rank_actions
from orchestration.contracts import (
    NEXT_BEST_ACTION,
    UNCERTAINTY,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "NextBestEngine"
ENGINE_VERSION = "1.1"
_TOP_N = 3
_MAX_GAP_ACTIONS = 6
_SEVERITY_BY_RANK = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)

IV_HIGH = "HIGH"
IV_MEDIUM = "MEDIUM"
IV_LOW = "LOW"


def _closing_balance(context: CaseContext) -> float:
    balances = [
        float(meta["balance"]) for meta in (
            (e.get("event_metadata") or {}) for e in context.events_of_type("bank_txn")
        ) if meta.get("balance") not in (None, "")
    ]
    if balances:
        return balances[-1]
    amounts = [
        float(meta.get("amount") or meta.get("credit") or meta.get("debit") or 0.0)
        for meta in ((e.get("event_metadata") or {}) for e in context.events_of_type("bank_txn"))
    ]
    return max(amounts, default=0.0)


def _build_case_state(context: CaseContext) -> dict:
    bank_events = context.events_of_type("bank_txn")
    elapsed_hours = 0.0
    if context.case_created_at:
        try:
            created = datetime.fromisoformat(context.case_created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            elapsed_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    accounts = []
    if bank_events:
        last_meta = bank_events[-1].get("event_metadata") or {}
        accounts.append({
            "account": last_meta.get("account") or last_meta.get("to_account") or "UNKNOWN",
            "ifsc": None,
            "bank_name": None,
            "amount_unwithdrawn": _closing_balance(context),
        })

    phones = [e["canonical_value"] for e in context.entities if e.get("entity_type") == "PHONE"]
    return {
        "elapsed_hours_since_first_credit": elapsed_hours,
        "complaint_ref": context.case_fir_number,
        "accounts_at_risk": accounts,
        "unresolved_phones": [{"phone": p, "_resolves": 1} for p in phones[:5]],
        "crime_window_cells": [],
    }


def applies(context: CaseContext) -> bool:
    return bool(context.events_of_type("bank_txn")) or bool(context.entities)


# ── Evidence-gap driven actions ──────────────────────────────────────────────
# The catalog ranking above is prescriptive/statutory. The actions below are
# derived from *actual unresolved questions in this case* — each one names the
# gap it closes and the entities/events/evidence that evidence the gap, so the
# investigator can see why it was generated.

def _account_evidence(context: CaseContext) -> dict[str, dict[str, list[str]]]:
    """Map account value → event/evidence refs where the account appears."""
    mapping: dict[str, dict[str, list[str]]] = {}
    for ev in context.events:
        meta = ev.get("event_metadata") or {}
        for acc in (meta.get("from_account"), meta.get("to_account"), meta.get("account")):
            if not acc:
                continue
            entry = mapping.setdefault(str(acc), {"events": [], "evidence": []})
            if ev.get("id"):
                entry["events"].append(str(ev["id"]))
            if ev.get("evidence_file_id"):
                entry["evidence"].append(str(ev["evidence_file_id"]))
    return mapping


def _gap_action(
    *,
    gap: str,
    title: str,
    why: str,
    resolves: str,
    information_value: str,
    severity: str,
    entity_refs: list[str] | None = None,
    event_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    component_scores: dict | None = None,
    reason_codes: list[str] | None = None,
) -> CognitiveResult:
    entity_refs = list(dict.fromkeys(entity_refs or []))
    event_refs = list(dict.fromkeys(event_refs or []))
    evidence_refs = list(dict.fromkeys(evidence_refs or []))
    dedup_seed = "|".join(sorted(entity_refs)) + ":" + "|".join(sorted(event_refs)[:3])
    return CognitiveResult(
        finding_type=NEXT_BEST_ACTION,
        title=title,
        description=(
            f"Evidence gap: {gap} · information value {information_value} · resolves: {resolves}"
        ),
        confidence=None,  # heuristic prioritisation, not a calibrated VoI
        severity=severity,
        source_engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        entity_refs=entity_refs,
        event_refs=event_refs,
        evidence_refs=evidence_refs,
        component_scores={
            "evidence_gap": gap,
            "information_value": information_value,
            "resolves": resolves,
            **(component_scores or {}),
        },
        reason_codes=["NEXT_BEST_ACTION", "EVIDENCE_GAP", gap] + list(reason_codes or []),
        reasoning=why,
        dedup_key=f"gap:{gap}:{dedup_seed}",
    )


def _evidence_gap_actions(context: CaseContext) -> list[CognitiveResult]:
    """Generate actions from actual unresolved evidence questions in the case."""
    results: list[CognitiveResult] = []
    account_ev = _account_evidence(context)
    account_entities = [e for e in context.entities if e.get("entity_type") == "ACCOUNT"]
    has_device = any(e.get("entity_type") == "DEVICE" for e in context.entities)
    bank_events = context.events_of_type("bank_txn")
    comm_events = context.events_of_type("call", "whatsapp_msg", "sms")
    inferred = [
        r for r in context.relationships
        if str(r.get("epistemic_status", "")).upper() == "INFERRED"
    ]

    # 1. Account ownership / KYC unresolved (financial movement established,
    #    control/ownership not established).
    for ent in account_entities[:2]:
        acc = str(ent.get("canonical_value"))
        refs = account_ev.get(acc, {"events": [], "evidence": []})
        results.append(_gap_action(
            gap="ENTITY_ATTRIBUTION",
            title=f"Obtain account ownership/KYC record for {acc}",
            why=("Financial movement involving this account is established, but "
                 "ownership and control are not. The account-control hypothesis "
                 "remains unresolved."),
            resolves="Account-control hypothesis",
            information_value=IV_HIGH,
            severity=SEVERITY_HIGH,
            entity_refs=[acc],
            event_refs=refs["events"],
            evidence_refs=refs["evidence"],
            reason_codes=["ACCOUNT_CONTROL_UNRESOLVED"],
        ))
        if len(results) >= _MAX_GAP_ACTIONS:
            return results[:_MAX_GAP_ACTIONS]

    # 2. Account ↔ device/session linkage unresolved.
    if account_entities and not has_device:
        ev_ids = [str(e["id"]) for e in bank_events if e.get("id")]
        evd = [str(e["evidence_file_id"]) for e in bank_events if e.get("evidence_file_id")]
        results.append(_gap_action(
            gap="DEVICE_ATTRIBUTION",
            title="Obtain authenticated device/session records for the transaction window",
            why=("No device or session entity is linked to the accounts. The "
                 "account↔device relationship is unresolved."),
            resolves="Account/device relationship hypothesis",
            information_value=IV_HIGH,
            severity=SEVERITY_MEDIUM,
            entity_refs=[str(e.get("canonical_value")) for e in account_entities[:3]],
            event_refs=ev_ids,
            evidence_refs=evd,
            reason_codes=["DEVICE_LINKAGE_UNRESOLVED"],
        ))

    # 3. Communication events with no resolvable counterparty. The endpoint is
    #    never invented; the gap is recorded instead.
    unknown = []
    for ev in comm_events:
        meta = ev.get("event_metadata") or {}
        counterparty = meta.get("callee") or meta.get("recipient")
        if not counterparty or str(counterparty).strip().upper() in ("UNKNOWN", "?"):
            unknown.append(ev)
    if unknown:
        results.append(_gap_action(
            gap="UNKNOWN_ENDPOINT",
            title="Resolve unknown communication endpoints",
            why=(f"{len(unknown)} communication event(s) have no identifiable "
                 "counterparty. The endpoint must not be invented — it requires "
                 "CDR/IPDR evidence."),
            resolves="Communication counterparty resolution",
            information_value=IV_MEDIUM,
            severity=SEVERITY_MEDIUM,
            event_refs=[str(e["id"]) for e in unknown if e.get("id")],
            evidence_refs=[str(e["evidence_file_id"]) for e in unknown if e.get("evidence_file_id")],
            reason_codes=["COUNTERPARTY_UNKNOWN"],
        ))

    # 4. Cross-stream temporal reconciliation (correlation only, never causation).
    if bank_events and comm_events:
        sample = comm_events[:2] + bank_events[:2]
        results.append(_gap_action(
            gap="TEMPORAL_RECONCILIATION",
            title="Reconcile communication and financial timestamps",
            why=("Communication and financial evidence both exist. Their clocks must be "
                 "reconciled before any temporal claim; this establishes correlation, "
                 "not causation."),
            resolves="Communication/transaction temporal correlation",
            information_value=IV_MEDIUM,
            severity=SEVERITY_LOW,
            event_refs=[str(e["id"]) for e in sample if e.get("id")],
            evidence_refs=[str(e["evidence_file_id"]) for e in sample if e.get("evidence_file_id")],
            reason_codes=["TEMPORAL_CORRELATION_ONLY"],
        ))

    # 5. Corroborate inferred (not observed) links.
    if len(results) >= _MAX_GAP_ACTIONS:
        return results[:_MAX_GAP_ACTIONS]
    for rel in inferred[:2]:
        a, b = rel.get("source_value"), rel.get("target_value")
        conf = float(rel.get("confidence") or 0.0)
        results.append(_gap_action(
            gap="INFERRED_LINK_CORROBORATION",
            title=f"Corroborate inferred link {a} ↔ {b}",
            why=("This relationship is INFERRED from multiple signals, not directly "
                 "observed. Independent evidence is required to confirm or refute it."),
            resolves="Inferred relationship corroboration",
            information_value=IV_HIGH if conf >= 0.7 else IV_MEDIUM,
            severity=SEVERITY_HIGH if conf >= 0.7 else SEVERITY_MEDIUM,
            entity_refs=[str(a), str(b)],
            event_refs=[str(x) for x in (rel.get("event_refs") or [])],
            evidence_refs=[str(x) for x in (rel.get("evidence_refs") or [])],
            component_scores={"inferred_confidence": rel.get("confidence")},
            reason_codes=["INFERRED_RELATIONSHIP"],
        ))
        if len(results) >= _MAX_GAP_ACTIONS:
            return results[:_MAX_GAP_ACTIONS]

    # 6. Actions that would close a persisted UNCERTAINTY finding.
    for finding in context.findings:
        if len(results) >= _MAX_GAP_ACTIONS:
            break
        if finding.get("finding_type") != UNCERTAINTY:
            continue
        results.append(_gap_action(
            gap="OPEN_UNCERTAINTY",
            title=f"Resolve uncertainty: {finding.get('title')}",
            why=(finding.get("description") or "An unresolved uncertainty finding remains open."),
            resolves="Open uncertainty finding",
            information_value=IV_MEDIUM,
            severity=SEVERITY_MEDIUM,
            entity_refs=[str(x) for x in (finding.get("entity_refs") or [])],
            event_refs=[str(x) for x in (finding.get("event_refs") or [])],
            evidence_refs=[str(x) for x in (finding.get("evidence_refs") or [])],
            component_scores={
                "generated_by_finding": finding.get("fingerprint") or finding.get("title"),
            },
            reason_codes=["OPEN_UNCERTAINTY"],
        ))
        if len(results) >= _MAX_GAP_ACTIONS:
            break

    return results[:_MAX_GAP_ACTIONS]


def run(context: CaseContext) -> list[CognitiveResult]:
    catalog = load_catalog(data_path("action_catalog.json"))
    case_state = _build_case_state(context)
    ranking = rank_actions(case_state, catalog)

    evidence_refs = list(dict.fromkeys(
        str(e["evidence_file_id"]) for e in context.events_of_type("bank_txn")
        if e.get("evidence_file_id")
    ))

    results: list[CognitiveResult] = []
    # rank_actions orders 'ready' first, then blocked (missing-input) actions.
    # Blocked actions are surfaced too: they name the information gap that must
    # be closed before the action can proceed.
    for rank, action in enumerate(ranking.get("ranked_actions", [])[:_TOP_N]):
        target = action.get("target") or {}
        target_key = "|".join(f"{k}={v}" for k, v in sorted(target.items()))
        is_ready = action.get("status") == "ready"
        missing = action.get("missing_fields") or []
        if is_ready:
            description = (
                f"{action['statutory_basis']} · urgency "
                f"{round(float(action.get('urgency_factor') or 0), 2)} · utility {action.get('utility_score')}"
            )
            reasoning = (action.get("draft") or "") + " " + (action.get("banner") or "")
            reason_codes = ["NEXT_BEST_ACTION", action.get("category", ""), action["action_code"]]
        else:
            description = (
                f"{action['statutory_basis']} · blocked — obtain: "
                + ", ".join(str(m) for m in missing)
            )
            reasoning = "Action blocked until the named evidence gap is closed."
            reason_codes = ["NEXT_BEST_ACTION", "MISSING_FIELDS", action["action_code"]]

        results.append(CognitiveResult(
            finding_type=NEXT_BEST_ACTION,
            title=f"Next best action — {action['description']}",
            description=description,
            confidence=None,  # transparent weighted heuristic, not a calibrated VoI
            severity=_SEVERITY_BY_RANK[rank],
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            entity_refs=[str(v) for v in target.values() if isinstance(v, str)],
            evidence_refs=evidence_refs,
            component_scores={
                "status": action.get("status"),
                "missing_fields": missing,
                "utility_score": action.get("utility_score"),
                "components": action.get("components") or {},
                "urgency_factor": action.get("urgency_factor"),
                "decay_half_life_hours": action.get("decay_half_life_hours"),
                "time_remaining_hours": action.get("time_remaining_hours"),
                "window_phase": action.get("window_phase"),
            },
            reason_codes=reason_codes,
            reasoning=reasoning,
            citations=[{"statutory_basis": action.get("statutory_basis"), "target": target}],
            dedup_key=f"nba:{action['action_code']}:{target_key}",
        ))
    # Case-grounded actions derived from actual unresolved evidence questions.
    results.extend(_evidence_gap_actions(context))
    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Golden-Hours next-best investigative actions.",
    applicability=applies,
    skip_reason="no_actionable_targets",
)
