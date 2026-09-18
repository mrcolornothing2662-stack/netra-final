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

        max_lh = max(dist.values())
        min_lh = min(dist.values())
        diagnosticity = round(max_lh - min_lh, 4)

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

    used.sort(key=lambda x: -x["diagnosticity"])

    max_log = max(log_post.values()) if log_post else 0.0
    exp_post = {lbl: math.exp(v - max_log) for lbl, v in log_post.items()}
    total_exp = sum(exp_post.values())
    posteriors = {lbl: exp_post[lbl] / total_exp for lbl in labels}

    ranked_labels = sorted(labels, key=lambda l: -posteriors[l])
    hyp_descriptions = {h["label"]: h.get("description", "") for h in hypotheses}
    per_hypothesis: list[dict[str, Any]] = []

    for rank_idx, lbl in enumerate(ranked_labels, start=1):
        refuting = min(used, key=lambda u: u["likelihoods"][lbl]) if used else None
        supporting = max(used, key=lambda u: u["likelihoods"][lbl]) if used else None
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
