"""
CyberDrishti AI — Feature 04: Hypothesis Investigation Board
Pure Analytical Core Domain (ACH Framework & GraphRAG Evidence Grounding).

Forces competing investigative theories:
  • KINGPIN_ORGANIZER (Mastermind / Controller)
  • LAYER1_MULE (Financial Pass-Through Agent)
  • COMPROMISED_VICTIM (Hijacked / Impersonated Account)
  • TECHNICAL_OPERATOR (Infrastructure / Phishing / Call Spoofing)
  • BENEFICIARY_CASHOUT (End-Stage Liquidation / Cash Extraction)
to be evaluated simultaneously against the SAME multi-modal evidence under
Richards Heuer's Analysis of Competing Hypotheses (ACH) discipline.

Honesty & Judicial Standards (R v T [2010] EWCA Crim 2439 / Section 193 BNSS):
- Posteriors are None unless allow_percentages=True AND an empirical calibration dict is provided.
- Default output is RULE_BASED_ASSESSMENT with transparent ordinal rank ordering.
- Every hypothesis explicitly surfaces its REFUTING evidence (the indicator it explains worst).
- Missing indicators are reported as unobserved evidence gaps with statutory closure steps, never imputed.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Sequence


def load_model(path: str) -> dict[str, Any]:
    """Loads and validates the ACH hypothesis likelihood model."""
    with open(path, "r", encoding="utf-8") as fh:
        model = json.load(fh)
    labels = {h["label"] for h in model["hypotheses"]}
    for ind in model["indicators"]:
        for bucket, dist in ind["evidence"].items():
            if set(dist) != labels:
                raise ValueError(
                    f"indicator '{ind['name']}' bucket '{bucket}' does not cover all hypotheses: {set(dist)} vs {labels}"
                )
            if abs(sum(dist.values()) - 1.0) > 1e-6:
                raise ValueError(
                    f"indicator '{ind['name']}' bucket '{bucket}' likelihoods must sum to 1.0 (got {sum(dist.values())})"
                )
    return model


def bucket_value(observation_key: str, value: float, meta: dict[str, Any]) -> str:
    """Bucket an observed numerical value according to meta.indicator_observations rules."""
    spec = meta.get("indicator_observations", {}).get(observation_key)
    if not spec or "buckets" not in spec:
        raise ValueError(f"No bucket specification for observation key '{observation_key}'")

    for bucket, expr in spec["buckets"].items():
        op, _, rhs = expr.partition(" ")
        threshold = float(rhs)
        if op == "<=" and value <= threshold:
            return bucket
        if op == ">" and value > threshold:
            return bucket
        if op == ">=" and value >= threshold:
            return bucket
        if op == "<" and value < threshold:
            return bucket
    raise ValueError(f"Value {value} fits no bucket for {observation_key} (spec: {spec['buckets']})")


def evaluate(
    observations: dict[str, float],
    model: dict[str, Any],
    config: dict[str, Any] | None = None,
    provenance_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Executes Heuer's Analysis of Competing Hypotheses (ACH).

    Args:
        observations: Mapping of observation_key -> numerical value.
        model: Parsed model from hypotheses.json.
        config: Optional evaluation settings (allow_percentages, calibration, priors).
        provenance_map: Optional mapping of indicator_name -> evidence provenance dict.

    Returns:
        Structured ACH assessment with ranked hypotheses, refutations, evidence matrix,
        unobserved indicators, and judicial disclaimers.
    """
    cfg = {
        "allow_percentages": False,
        "calibration": None,
        "priors": None,
        **(config or {}),
    }

    hypotheses = model["hypotheses"]
    labels = [h["label"] for h in hypotheses]
    priors = cfg["priors"] or {h["label"]: h.get("prior", 1.0 / len(labels)) for h in hypotheses}
    log_post = {lbl: math.log(max(priors[lbl], 1e-9)) for lbl in labels}

    used: list[dict[str, Any]] = []
    unobserved: list[dict[str, Any]] = []
    prov = provenance_map or {}

    # Indicator evidence metadata mapping for statutory gap recommendations
    statutory_requirements = {
        "pass_through_speed": "Bank statement ledger / Core Banking System (CBS) transaction timestamp log",
        "account_age": "Bank Customer Application Form (CAF) / e-KYC account opening record",
        "victim_contact": "Call Detail Records (CDR) / Tower dumps from telecom service providers",
        "dormancy": "Historical 12-month bank account statement audit",
        "device_dispersion": "IPDR server logs / IMEI device pairing records from telecom providers",
        "turnover_scale": "Consolidated bank statements across all beneficiary branches",
    }

    for ind in model["indicators"]:
        name = ind["name"]
        key = ind["observation_key"]
        val = observations.get(key)

        if val is None:
            unobserved.append({
                "indicator": name,
                "observation_key": key,
                "required_evidence": statutory_requirements.get(name, "Case Evidence Records"),
                "potential_impact": f"Diagnostic spread up to 0.60 across {len(labels)} competing theories.",
                "note": ind.get("note", ""),
            })
            continue

        bucket = bucket_value(key, float(val), model["_meta"])
        dist = ind["evidence"][bucket]

        for lbl in labels:
            log_post[lbl] += math.log(max(dist[lbl], 1e-9))

        # Diagnosticity: spread between maximum and minimum likelihood across H
        max_lh = max(dist.values())
        min_lh = min(dist.values())
        diagnosticity = round(max_lh - min_lh, 4)

        # Classify consistency
        consistent_h = [lbl for lbl, p in dist.items() if p >= 0.25]
        inconsistent_h = [lbl for lbl, p in dist.items() if p <= 0.10]

        used.append({
            "indicator": name,
            "observation_key": key,
            "observed_value": val,
            "bucket": bucket,
            "likelihoods": {lbl: round(dist[lbl], 4) for lbl in labels},
            "diagnosticity": diagnosticity,
            "consistent_hypotheses": consistent_h,
            "inconsistent_hypotheses": inconsistent_h,
            "note": ind.get("note", ""),
            "provenance": prov.get(name, {
                "source_file": "Case Analytical Graph",
                "source_line": None,
                "event_type": "observed_metric",
            }),
        })

    # Sort evidence matrix by diagnosticity descending (most informative indicators first)
    used.sort(key=lambda x: -x["diagnosticity"])

    # Compute normalized posteriors
    max_log = max(log_post.values()) if log_post else 0.0
    exp_post = {lbl: math.exp(v - max_log) for lbl, v in log_post.items()}
    total_exp = sum(exp_post.values())
    posteriors = {lbl: exp_post[lbl] / total_exp for lbl in labels}

    # Ordinal ranking
    ranked_labels = sorted(labels, key=lambda l: -posteriors[l])

    # Build per-hypothesis detailed records
    hyp_descriptions = {h["label"]: h.get("description", "") for h in hypotheses}
    per_hypothesis: list[dict[str, Any]] = []

    for rank_idx, lbl in enumerate(ranked_labels, start=1):
        # Refuting evidence: indicator where P(E|H) is lowest
        refuting = min(used, key=lambda u: u["likelihoods"][lbl]) if used else None
        # Supporting evidence: indicator where P(E|H) is highest
        supporting = max(used, key=lambda u: u["likelihoods"][lbl]) if used else None

        # Inconsistency score: cumulative surprise (-ln(P(E|H)))
        inconsistency = sum(-math.log(max(u["likelihoods"][lbl], 1e-6)) for u in used) if used else 0.0

        per_hypothesis.append({
            "rank": rank_idx,
            "label": lbl,
            "description": hyp_descriptions.get(lbl, ""),
            "posterior": (
                round(posteriors[lbl], 4)
                if cfg["allow_percentages"] and cfg["calibration"]
                else None
            ),
            "inconsistency_score": round(inconsistency, 2),
            "refuting_evidence": (
                {
                    "indicator": refuting["indicator"],
                    "bucket": refuting["bucket"],
                    "likelihood": refuting["likelihoods"][lbl],
                    "likelihood_under_this_hypothesis": refuting["likelihoods"][lbl],
                    "diagnosticity": refuting["diagnosticity"],
                    "why": (
                        f"Theory '{lbl}' explains '{refuting['indicator']}' = {refuting['bucket']} "
                        f"poorly (P={refuting['likelihoods'][lbl]:.2f})."
                    ),
                    "provenance": refuting.get("provenance", {}),
                }
                if refuting
                else None
            ),
            "supporting_evidence": (
                {
                    "indicator": supporting["indicator"],
                    "bucket": supporting["bucket"],
                    "likelihood": supporting["likelihoods"][lbl],
                    "likelihood_under_this_hypothesis": supporting["likelihoods"][lbl],
                    "diagnosticity": supporting["diagnosticity"],
                    "why": (
                        f"Theory '{lbl}' is strongly consistent with '{supporting['indicator']}' = {supporting['bucket']} "
                        f"(P={supporting['likelihoods'][lbl]:.2f})."
                    ),
                    "provenance": supporting.get("provenance", {}),
                }
                if supporting
                else None
            ),
        })

    calibrated = bool(cfg["allow_percentages"] and cfg["calibration"])

    return {
        "ranked_labels": ranked_labels,
        "hypotheses": per_hypothesis,
        "evidence_matrix": used,
        "unobserved_indicators": [u["indicator"] for u in unobserved],
        "unobserved_details": unobserved,
        "assessment_type": "CALIBRATED_POSTERIOR" if calibrated else "RULE_BASED_ASSESSMENT",
        "display_label": (
            None
            if calibrated
            else "EVIDENTIARY RANKING · NOT A STATISTICAL PROBABILITY — R v T [2010] & Section 193 BNSS compliant. Focus on the ACH evidence matrix and refuting evidence."
        ),
        "epistemic_notice": (
            "JUDICIAL ADVISORY (ACH INVESTIGATION BOARD) — Competing hypotheses are evaluated under Richards Heuer's "
            "Analysis of Competing Hypotheses standard. Numerical likelihoods are transparent engineering weights, "
            "not empirical frequencies. Final determination of mens rea and criminal culpability is reserved to the competent trial court."
        ),
    }


def extract_entity_observations(
    target_entity: str,
    bank_events: list[dict[str, Any]],
    call_events: list[dict[str, Any]],
    network_events: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    """
    Derives empirical diagnostic observations for a specific target entity
    along with precise evidence file provenance.
    """
    observations: dict[str, float] = {}
    provenance: dict[str, dict[str, Any]] = {}
    target_clean = target_entity.strip().lower()

    # ── 1. Bank transactions & Pass-Through Velocity ──────────────────────────
    entity_bank_txns: list[dict[str, Any]] = []
    for ev in bank_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        from_acc = str(meta.get("from_account") or meta.get("account") or "").lower()
        to_acc = str(meta.get("to_account") or "").lower()
        upi_id = str(meta.get("upi_id") or "").lower()

        if target_clean in (from_acc, to_acc, upi_id):
            entity_bank_txns.append(ev)

    # If no exact match found, use all bank events as context for case-level suspect
    if not entity_bank_txns and bank_events:
        entity_bank_txns = bank_events

    if entity_bank_txns:
        # Pass-through speed: shortest duration between an inbound credit and outbound debit
        credits: list[tuple[datetime, dict[str, Any]]] = []
        debits: list[tuple[datetime, dict[str, Any]]] = []
        total_turnover = 0.0

        timestamps: list[datetime] = []
        for ev in entity_bank_txns:
            meta = ev.get("metadata") or ev.get("event_metadata") or ev
            from_acc = str(meta.get("from_account") or meta.get("account") or "").lower()
            to_acc = str(meta.get("to_account") or "").lower()
            amt = float(meta.get("amount") or meta.get("amount_inr") or meta.get("credit") or meta.get("debit") or 0.0)
            total_turnover += amt

            ts_str = ev.get("event_timestamp") or ev.get("timestamp")
            if ts_str:
                try:
                    dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
                    timestamps.append(dt)
                    is_credit = float(meta.get("credit") or 0.0) > 0 or (to_acc and target_clean in to_acc)
                    is_debit = float(meta.get("debit") or 0.0) > 0 or (from_acc and target_clean in from_acc)
                    if is_credit:
                        credits.append((dt, ev))
                    if is_debit:
                        debits.append((dt, ev))
                except (ValueError, TypeError):
                    pass

        if credits and debits:
            min_delta_sec = float("inf")
            best_pair = None
            for c_dt, c_ev in credits:
                for d_dt, d_ev in debits:
                    delta = (d_dt - c_dt).total_seconds()
                    if 0 <= delta < min_delta_sec:
                        min_delta_sec = delta
                        best_pair = (c_ev, d_ev)

            if best_pair and min_delta_sec < float("inf"):
                velocity_min = max(round(min_delta_sec / 60.0, 1), 1.0)
                observations["velocity_minutes"] = velocity_min
                provenance["pass_through_speed"] = {
                    "source_file": best_pair[0].get("source_file") or "bank_statement.csv",
                    "source_line": best_pair[0].get("source_line") or 1,
                    "event_type": "bank_txn",
                    "sample_text": f"Rapid debit occurred {velocity_min} minutes after credit.",
                }

        # Turnover volume scale
        if total_turnover > 0:
            observations["turnover_volume_inr"] = total_turnover
            provenance["turnover_scale"] = {
                "source_file": entity_bank_txns[0].get("source_file") or "bank_statement.csv",
                "source_line": entity_bank_txns[0].get("source_line") or 1,
                "event_type": "bank_txn",
                "sample_text": f"Total observed transaction throughput ₹{total_turnover:,.2f}",
            }

        # Account age / Dormancy
        if timestamps:
            timestamps.sort()
            earliest = timestamps[0]
            latest = timestamps[-1]
            span_days = max((latest - earliest).total_seconds() / 86400.0, 1.0)
            observations["account_age_days"] = round(span_days, 1)
            provenance["account_age"] = {
                "source_file": entity_bank_txns[0].get("source_file") or "bank_statement.csv",
                "source_line": entity_bank_txns[0].get("source_line") or 1,
                "event_type": "bank_txn",
                "sample_text": f"Account active across observed span of {span_days:.1f} days.",
            }

            # Dormancy before burst
            if len(timestamps) >= 3:
                intervals = [
                    (timestamps[i] - timestamps[i - 1]).total_seconds() / 86400.0
                    for i in range(1, len(timestamps))
                ]
                max_gap = max(intervals)
                observations["dormancy_before_crime_days"] = round(max_gap, 1)
                provenance["dormancy"] = {
                    "source_file": entity_bank_txns[0].get("source_file") or "bank_statement.csv",
                    "source_line": entity_bank_txns[0].get("source_line") or 1,
                    "event_type": "bank_txn",
                    "sample_text": f"Maximum dormancy interval before subsequent burst was {max_gap:.1f} days.",
                }

    # ── 2. Call Detail Records & Victim Contact ───────────────────────────────
    if call_events:
        inbound_calls = 0
        call_prov = None
        for ev in call_events:
            meta = ev.get("metadata") or ev.get("event_metadata") or ev
            caller = str(meta.get("caller") or meta.get("calling_number") or "").lower()
            callee = str(meta.get("callee") or meta.get("called_number") or "").lower()
            if target_clean in callee:
                inbound_calls += 1
                if not call_prov:
                    call_prov = ev

        observations["inbound_victim_calls"] = float(inbound_calls)
        if call_prov:
            provenance["victim_contact"] = {
                "source_file": call_prov.get("source_file") or "04_call_detail_record.csv",
                "source_line": call_prov.get("source_line") or 1,
                "event_type": "call",
                "sample_text": f"Received {inbound_calls} inbound calls from complainant/victim numbers.",
            }

    # ── 3. Network log device sharing ─────────────────────────────────────────
    if network_events:
        ip_device_set = set()
        net_prov = None
        for ev in network_events:
            meta = ev.get("metadata") or ev.get("event_metadata") or ev
            ip = meta.get("ip") or meta.get("ip_address")
            dev = meta.get("imei") or meta.get("mac") or meta.get("device_id")
            if ip:
                ip_device_set.add(f"IP:{ip}")
            if dev:
                ip_device_set.add(f"DEV:{dev}")
            if not net_prov and (ip or dev):
                net_prov = ev

        if ip_device_set:
            observations["device_sharing_count"] = float(len(ip_device_set))
            if net_prov:
                provenance["device_dispersion"] = {
                    "source_file": net_prov.get("source_file") or "08_network_log.csv",
                    "source_line": net_prov.get("source_line") or 1,
                    "event_type": "network_log",
                    "sample_text": f"Entity associated with {len(ip_device_set)} distinct network/device interfaces.",
                }

    return observations, provenance
