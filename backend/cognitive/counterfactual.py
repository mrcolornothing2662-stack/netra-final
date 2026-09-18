"""CyberDrishti Feature 8 — Counterfactual "What-If Freeze" Simulation Sandbox.

Replays the case's timed money-flow (victim → mule layers → off-ramps) under a
hypothetical intervention: "account(s) X are frozen at time T". Deterministic
discrete-event replay — network-interdiction style, no do-calculus library required.

Implements the strict 4-stage comparative model:
  Stage 1: Observed Historical State
  Stage 2: Counterfactual Intervention
  Stage 3: Simulated Downstream State (with cascade starvation of downstream mules)
  Stage 4: Comparison & Delta Analytics

Output labels itself APPROXIMATED and reports a LOWER BOUND on savings: flows
beyond the uploaded statements (cash withdrawal chains, hawala, off-ramp
activity not in evidence) are unobservable, so the engine cannot claim "this
is what would have been saved" — and it is certainly not "admissible proof of
negligence". It is decision-support with bounds under NETRA Epistemic Humility Standard.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

DEFAULT_CONFIG: dict[str, Any] = {
    "max_events": 100000,
}

# Indian Standard Time — the wall-clock of all Indian bank evidence.
# Naive timestamps from bank parsers and API inputs are IST, not UTC.
_IST = timezone(timedelta(hours=5, minutes=30))

EPISTEMIC_COUNTERFACTUAL_CAVEATS: list[str] = [
    "Flows beyond the uploaded statements (cash-out, hawala, off-platform movement) are unobservable; actual savings could be higher.",
    "This is a model-based estimate for prioritising recovery actions — NOT admissible proof of negligence or of what a bank would have done.",
    "Blocked-out events assume the freeze would have applied to debits instantly at the stated time.",
    "Counterfactual simulation strictly operates on an in-memory snapshot and DOES NOT mutate authoritative case evidence, graph edges, or DB records.",
]


def _ts(value: Any) -> datetime:
    """Parse a timestamp string into an aware datetime.

    Contract: naive timestamps (no offset) are treated as **Indian Standard
    Time** (UTC+05:30) because Indian bank evidence records IST wall-clock
    times. Aware timestamps (with offset or trailing 'Z') are kept as-is.
    This ensures identical freeze results whether the DB returns naive (SQLite)
    or offset-aware (PostgreSQL ``timestamptz``) datetimes.
    """
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    return dt


def simulate_freeze(
    transfers: Sequence[dict[str, Any]],
    freeze_account: str | Sequence[str],
    freeze_time: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """transfers: [{from, to, amount, timestamp}] (chronological order applied internally).
    freeze_account: single account string or sequence of account strings.
    freeze_time: ISO-8601 timestamp string (treated as IST if naive).

    Executes the 4-stage network-interdiction replay and returns preserved amounts,
    downstream cascade starvation audit trail, and comparative delta analytics.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if len(transfers) > cfg["max_events"]:
        raise ValueError("transfer set exceeds max_events")

    # Normalize target accounts
    if isinstance(freeze_account, str):
        target_accounts = {str(freeze_account).strip()}
    else:
        target_accounts = {str(a).strip() for a in freeze_account if str(a).strip()}

    t_freeze = _ts(freeze_time)

    # Sort transfers chronologically
    sorted_transfers = sorted(transfers, key=lambda x: _ts(x["timestamp"]))

    # ── Stage 1: Observed Historical State ─────────────────────────────────────
    total_observed_volume = 0.0
    all_observed_accounts: set[str] = set()
    for t in sorted_transfers:
        amt = float(t.get("amount", 0.0))
        total_observed_volume += amt
        all_observed_accounts.add(str(t.get("from", "")))
        all_observed_accounts.add(str(t.get("to", "")))

    first_ts = sorted_transfers[0]["timestamp"] if sorted_transfers else None
    last_ts = sorted_transfers[-1]["timestamp"] if sorted_transfers else None
    duration_hours = 0.0
    if first_ts and last_ts:
        duration_hours = max(0.0, (_ts(last_ts) - _ts(first_ts)).total_seconds() / 3600.0)

    stage_1_observed = {
        "total_transfers_count": len(sorted_transfers),
        "total_transfers": len(sorted_transfers),
        "total_observed_volume": total_observed_volume,
        "total_volume": total_observed_volume,
        "active_accounts_count": len(all_observed_accounts),
        "first_transfer_time": first_ts,
        "start_time": first_ts,
        "last_transfer_time": last_ts,
        "end_time": last_ts,
        "duration_hours": round(duration_hours, 2),
    }

    # ── Stage 2: Counterfactual Intervention ───────────────────────────────────
    stage_2_intervention = {
        "target_accounts": sorted(list(target_accounts)),
        "freeze_accounts": sorted(list(target_accounts)),
        "freeze_time": freeze_time,
        "freeze_time_ist": t_freeze.isoformat(),
        "statutory_basis": "Section 106 BNSS / CFCFRMS 1930 Emergency Freeze",
        "intervention_type": "BANK_ACCOUNT_FREEZE_106_BNSS",
        "epistemic_status": "COUNTERFACTUAL",
    }

    # ── Stage 3: Simulated Downstream State ─────────────────────────────────────
    blocked_at: dict[str, datetime] = {}
    preserved_by_account: dict[str, float] = {}
    balance: dict[str, float] = {}  # counterfactual-world balances
    blocked_out_events: list[dict[str, Any]] = []
    stopped_in_events: list[dict[str, Any]] = []
    unfunded_attempts: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    starved_accounts: set[str] = set()
    starved_recipients: set[str] = set()

    for t in sorted_transfers:
        ts = _ts(t["timestamp"])
        sender, receiver = str(t["from"]), str(t["to"])
        amount = float(t["amount"])
        rec = {
            "from": sender,
            "to": receiver,
            "amount": amount,
            "timestamp": t["timestamp"],
        }

        # Interventions become effective at freeze_time
        if sender in target_accounts and ts >= t_freeze:
            blocked_at.setdefault(sender, ts)
        if receiver in target_accounts and ts >= t_freeze:
            blocked_at.setdefault(receiver, ts)

        sender_frozen = sender in blocked_at and blocked_at[sender] <= ts
        receiver_frozen = receiver in blocked_at and blocked_at[receiver] <= ts

        if sender_frozen:
            # Funds stay in the frozen account ONLY if they are actually there
            if balance.get(sender, 0.0) >= amount:
                blocked_out_events.append({
                    **rec,
                    "reason": "sender frozen — debit blocked at freeze wall",
                    "status": "BLOCKED_DEBIT",
                    "preserved": True,
                })
                preserved_by_account[sender] = preserved_by_account.get(sender, 0.0) + amount
                balance[sender] = balance.get(sender, 0.0) - amount
                starved_recipients.add(receiver)
            else:
                unfunded_attempts.append({
                    **rec,
                    "reason": "sender frozen (unfunded attempt — funds never arrived downstream of the freeze wall)",
                    "status": "STARVED_UNFUNDED",
                    "preserved": False,
                })
                starved_accounts.add(receiver)
                starved_recipients.add(receiver)
            continue

        if receiver_frozen:
            # Money hits the freeze wall and stops there
            preserved_by_account[receiver] = preserved_by_account.get(receiver, 0.0) + amount
            stopped_in_events.append({
                **rec,
                "reason": "receiver frozen — inbound funds stopped and preserved at wall",
                "status": "STOPPED_INBOUND",
                "preserved": True,
            })
            continue

        # Check downstream starvation cascade:
        # If sender was supposed to receive funds that were blocked or starved upstream,
        # and its counterfactual balance is insufficient to cover this transfer:
        if sender in starved_recipients and balance.get(sender, 0.0) < amount:
            unfunded_attempts.append({
                **rec,
                "reason": f"unfunded downstream debit — sender {sender} starved of funds due to upstream freeze wall (INSUFFICIENT_FUNDS_DUE_TO_UPSTREAM_FREEZE)",
                "status": "STARVED_UNFUNDED",
                "preserved": False,
            })
            starved_accounts.add(sender)
            starved_recipients.add(receiver)
            continue

        completed.append({**rec, "status": "COMPLETED_UNTOUCHED"})
        balance[sender] = balance.get(sender, 0.0) - amount  # negative = external funds
        balance[receiver] = balance.get(receiver, 0.0) + amount

    preserved_total = round(sum(preserved_by_account.values()), 2)
    dissipated_total = round(max(0.0, total_observed_volume - preserved_total), 2)
    preservation_ratio = round(preserved_total / total_observed_volume, 4) if total_observed_volume > 0 else 0.0

    # Classify nodes in the counterfactual network
    node_classifications: dict[str, str] = {}
    for acc in all_observed_accounts:
        if acc in target_accounts:
            node_classifications[acc] = "INTERVENTION_POINT"
        elif preserved_by_account.get(acc, 0.0) > 0:
            node_classifications[acc] = "PRESERVED_CAPITAL"
        elif acc in starved_accounts:
            node_classifications[acc] = "STARVED_DOWNSTREAM"
        else:
            node_classifications[acc] = "UNAFFECTED"

    stage_3_simulated = {
        "blocked_out_events": blocked_out_events,
        "blocked_debits": blocked_out_events,
        "stopped_in_events": stopped_in_events,
        "stopped_credits": stopped_in_events,
        "unfunded_attempts": unfunded_attempts,
        "starved_transfers": unfunded_attempts,
        "completed_transfers_count": len(completed),
        "simulated_balances": {k: round(v, 2) for k, v in balance.items()},
        "node_classifications": node_classifications,
    }

    # ── Stage 4: Comparison & Delta Analytics ──────────────────────────────────
    stage_4_comparison = {
        "preserved_total": preserved_total,
        "preserved_capital": preserved_total,
        "dissipated_total": dissipated_total,
        "dissipated_capital": dissipated_total,
        "preservation_ratio": preservation_ratio,
        "preservation_percentage": round(preservation_ratio * 100.0, 1),
        "preservation_efficiency_pct": round(preservation_ratio * 100.0, 1),
        "blocked_debits_count": len(blocked_out_events),
        "stopped_credits_count": len(stopped_in_events),
        "starved_attempts_count": len(unfunded_attempts),
        "starved_accounts": sorted(list(starved_accounts)),
        "completed_count": len(completed),
        "capital_delta_preserved": preserved_total,
        "capital_delta_lost": dissipated_total,
    }

    # Format account intervention for backward compatibility
    intervention_compat = {
        "account": sorted(list(target_accounts))[0] if len(target_accounts) == 1 else sorted(list(target_accounts)),
        "freeze_time": freeze_time,
    }

    return {
        # Strict legacy backward compatibility keys (do not change types or remove)
        "intervention": intervention_compat,
        "preserved_total": preserved_total,
        "preserved_by_account": {k: round(v, 2) for k, v in preserved_by_account.items()},
        "stopped_in_events": stopped_in_events,
        "blocked_out_events": blocked_out_events,
        "unfunded_attempts": unfunded_attempts,
        "starved_downstream_events": unfunded_attempts,
        "completed_transfers": len(completed),
        "assessment_type": "APPROXIMATED_LOWER_BOUND",
        "epistemic_status": "APPROXIMATED",
        "epistemic_notice": "COUNTERFACTUAL SIMULATION ONLY — Evaluates potential capital preservation under Section 106 BNSS / CFCFRMS 1930 emergency freeze procedures. Model-based heuristic; does not guarantee bank compliance or unobserved cash-out retention.",
        "confidence_score": 0.95,
        "caveats": EPISTEMIC_COUNTERFACTUAL_CAVEATS,
        # Feature 08 Enhanced 4-Stage Architecture
        "stage_1_observed": stage_1_observed,
        "stage_2_intervention": stage_2_intervention,
        "stage_3_simulated": stage_3_simulated,
        "stage_4_comparison": stage_4_comparison,
        "node_classifications": node_classifications,
    }


def simulate_timeliness_sweep(
    transfers: Sequence[dict[str, Any]],
    freeze_account: str | Sequence[str] | None = None,
    reference_time: str | None = None,
    offsets_minutes: Sequence[int] = (15, 30, 60, 120, 360, 1440),
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Evaluates the counterfactual capital preservation decay curve by simulating
    interventions across a schedule of time offsets (e.g. +15m, +30m, +1h, +2h, +6h, +24h).

    Demonstrates empirically to investigators how rapid Golden-Hours action prevents
    fund dissipation compared to delayed response.
    """
    target = freeze_account or kwargs.get("freeze_accounts") or kwargs.get("freeze_account")
    if not target:
        raise ValueError("freeze_account or freeze_accounts is required")

    horizons = kwargs.get("horizons_minutes") or offsets_minutes
    if not transfers:
        return []

    sorted_transfers = sorted(transfers, key=lambda x: _ts(x["timestamp"]))
    base_dt = _ts(reference_time) if reference_time else _ts(sorted_transfers[0]["timestamp"])

    sweep_results: list[dict[str, Any]] = []
    for offset in sorted(horizons):
        t_sim = base_dt + timedelta(minutes=offset)
        sim_iso = t_sim.isoformat()

        res = simulate_freeze(
            transfers=transfers,
            freeze_account=target,
            freeze_time=sim_iso,
        )

        label = f"+{offset}m" if offset < 60 else f"+{offset // 60}h"
        sweep_results.append({
            "offset_minutes": offset,
            "horizon_minutes": offset,
            "offset_label": label,
            "freeze_time": sim_iso,
            "preserved_total": res["preserved_total"],
            "dissipated_total": res["stage_4_comparison"]["dissipated_total"],
            "preservation_ratio": res["stage_4_comparison"]["preservation_ratio"],
            "preservation_percentage": res["stage_4_comparison"]["preservation_percentage"],
            "preservation_rate_pct": res["stage_4_comparison"]["preservation_percentage"],
            "blocked_debits": len(res["blocked_out_events"]),
            "stopped_credits": len(res["stopped_in_events"]),
            "starved_attempts": len(res["unfunded_attempts"]),
            "status": "CRITICAL" if offset <= 120 else "EXTENDED" if offset <= 1440 else "DECAYED",
        })

    return sweep_results


def generate_counterfactual_frames(
    transfers: Sequence[dict[str, Any]],
    simulation_result_or_freeze_account: dict[str, Any] | str | Sequence[str],
    freeze_time_or_step_seconds: Any = 120,
    step_seconds: int = 120,
) -> list[dict[str, Any]]:
    """Generates CTDG counterfactual animation frames compatible with Feature 10
    Network Replay infrastructure.

    Annotates edges and nodes with their counterfactual interdiction state:
      • Blocked transfers: is_blocked=True, style='dashed', stroke='var(--critical)'
      • Stopped transfers: is_stopped=True, stroke='var(--warning)'
      • Starved nodes: is_starved=True
      • Preserved nodes: is_preserved=True
    """
    if not transfers:
        return []

    sorted_transfers = sorted(transfers, key=lambda x: _ts(x["timestamp"]))

    if isinstance(simulation_result_or_freeze_account, dict):
        sim_res = simulation_result_or_freeze_account
    else:
        freeze_target = simulation_result_or_freeze_account
        freeze_t = str(freeze_time_or_step_seconds)
        sim_res = simulate_freeze(sorted_transfers, freeze_target, freeze_t)

    # Build lookup for transfer outcomes
    blocked_keys = {
        f"{e['from']}->{e['to']}@{e['timestamp']}" for e in sim_res.get("blocked_out_events", [])
    }
    stopped_keys = {
        f"{e['from']}->{e['to']}@{e['timestamp']}" for e in sim_res.get("stopped_in_events", [])
    }
    unfunded_keys = {
        f"{e['from']}->{e['to']}@{e['timestamp']}" for e in sim_res.get("unfunded_attempts", [])
    }
    node_cls = sim_res.get("node_classifications", {})

    frames: list[dict[str, Any]] = []
    cum_preserved = 0.0
    active_nodes: set[str] = set()
    active_edges: list[dict[str, Any]] = []

    for i, t in enumerate(sorted_transfers):
        sender, receiver = str(t["from"]), str(t["to"])
        amount = float(t["amount"])
        active_nodes.add(sender)
        active_nodes.add(receiver)

        k = f"{sender}->{receiver}@{t['timestamp']}"
        is_blocked = k in blocked_keys
        is_stopped = k in stopped_keys
        is_unfunded = k in unfunded_keys
        is_interdicted = is_blocked or is_stopped or is_unfunded

        if is_blocked:
            action = "BLOCKED"
            cum_preserved += amount
        elif is_stopped:
            action = "STOPPED"
            cum_preserved += amount
        elif is_unfunded:
            action = "STARVED"
        else:
            action = "COMPLETED"

        edge_entry = {
            "from": sender,
            "to": receiver,
            "amount": amount,
            "timestamp": t["timestamp"],
            "is_blocked": is_blocked,
            "is_stopped": is_stopped,
            "is_unfunded": is_unfunded,
            "is_interdicted": is_interdicted,
            "cf_status": action,
        }
        active_edges.append(edge_entry)

        frames.append({
            "t": t["timestamp"],
            "frame_index": i + 1,
            "transfer": t,
            "action": action,
            "is_interdicted": is_interdicted,
            "cumulative_preserved": cum_preserved,
            "active_nodes": sorted(list(active_nodes)),
            "active_edges": list(active_edges),
            "node_states": {n: node_cls.get(n, "UNAFFECTED") for n in active_nodes},
            "summary": {
                "active_nodes_count": len(active_nodes),
                "active_edges_count": len(active_edges),
                "blocked_edges_count": sum(1 for e in active_edges if e["is_blocked"]),
                "starved_edges_count": sum(1 for e in active_edges if e["is_unfunded"]),
                "cumulative_preserved": cum_preserved,
            },
        })

    return frames
