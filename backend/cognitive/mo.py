"""CyberDrishti Feature 07 — Crime Script Matcher (MO Fingerprinting).

Represents a case as an ordered sequence of behavioral stage tokens (a crime script)
based on multi-modal evidence (communications, transactions, CDR call logs, network logs,
and document text) and matches that sequence against a curated playbook library
using normalized Levenshtein edit distance on stage tokens.

Theoretical Foundation:
- Procedural rational choice & crime script analysis (Cornish 1994; Leclerc 2014; Bichler 2019).
- Curated I4C / NITI Aayog / NCRP operational cyber-fraud playbooks.

Judicial & Epistemic Honesty Rules (Section 193 BNSS, Section 63 BSA, R v T [2010]):
- Output is a categorical SIMILARITY score in [0, 1] with the per-stage alignment shown.
- Script-pattern similarity does NOT constitute proof of guilt or personal culpability.
- No syndicate attribution is inferred (no verified national syndicate registry exists).
- If no playbook exceeds `match_threshold`, the engine issues "NO_CONFIDENT_MATCH".
- Every matched stage cites the specific evidence items (events, files, timestamps, text).
"""
from __future__ import annotations

import json
import re
from typing import Any, Sequence

DEFAULT_CONFIG: dict[str, Any] = {
    "match_threshold": 0.60,      # normalized similarity threshold for confident match
    "high_confidence_threshold": 0.80, # threshold for high priority severity
    "max_stage_gap_lines": 40,    # gap in sequence before starting fresh occurrence
}

JUDICIAL_NOTICE: dict[str, Any] = {
    "statutory_standard": "Section 193 BNSS, 2023 & Section 63 BSA, 2023 Forensic Protocol",
    "epistemic_tier": "TIER_SCREENING",
    "disclaimer": (
        "Crime script matching measures categorical sequence concordance against historical "
        "fraud typologies for investigative triage. It does NOT constitute legal proof of guilt, "
        "establish individual attribution to any specific suspect or syndicate, or replace "
        "independent physical, financial, or forensic evidence."
    ),
    "r_v_t_compliance": (
        "In accordance with R v T [2010] EWCA Crim 2439, sequence similarity metrics reflect "
        "procedural alignment, not an objective posterior probability of guilt or liability."
    ),
    "corroboration_required": True,
}


def load_playbooks(path: str) -> dict[str, Any]:
    """Load and validate the crime script playbook catalog."""
    with open(path, "r", encoding="utf-8") as fh:
        lib = json.load(fh)
    if "playbooks" not in lib or not isinstance(lib["playbooks"], list):
        raise ValueError("playbooks library missing 'playbooks' list")
    for pb in lib["playbooks"]:
        if not pb.get("stages") or not pb.get("detectors"):
            raise ValueError(f"playbook '{pb.get('name')}' needs stages + detectors")
    return lib


def levenshtein_distance(a: Sequence[str], b: Sequence[str]) -> int:
    """Computes exact Levenshtein edit distance between two sequences of categorical tokens."""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def normalized_levenshtein(a: Sequence[str], b: Sequence[str]) -> float:
    """1 − edit_distance / max(len) — 1.0 identical, 0.0 fully different."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    dist = levenshtein_distance(a, b)
    max_len = max(len(a), len(b))
    return max(0.0, 1.0 - (dist / max_len))


def _compile_playbook_detectors(playbook: dict[str, Any]) -> dict[str, list[re.Pattern]]:
    """Compile regex detectors for a single playbook."""
    compiled: dict[str, list[re.Pattern]] = {}
    for stage, patterns in playbook.get("detectors", {}).items():
        compiled[stage] = [re.compile(p, re.IGNORECASE) for p in patterns if p]
    return compiled


def build_behavioral_trace_from_evidence(
    evidence_items: Sequence[dict[str, Any]],
    playbook: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Trace multi-modal evidence against a single playbook's detectors.
    Per-playbook tracing ensures no stage cross-contamination between typologies.

    Each evidence_item can be:
      - Communication/chat: {type: 'message'|'chat'|'whatsapp_msg', text, sender, timestamp, event_id, evidence_file_id, filename}
      - Financial txn: {type: 'bank_txn'|'transaction', narration, amount, from_account, to_account, timestamp, event_id, ...}
      - Telecom/call: {type: 'call', caller, callee, duration_sec, timestamp, event_id, ...}
      - Network log: {type: 'network_log', service, ip, port, timestamp, event_id, ...}
      - Document text: {type: 'document_text'|'text_record'|'ocr', text, timestamp, event_id, ...}
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    detector_map = _compile_playbook_detectors(playbook)
    playbook_stages = set(playbook.get("stages", []))

    trace: list[dict[str, Any]] = []
    last_idx_by_stage: dict[str, int] = {}

    for idx, item in enumerate(evidence_items, start=1):
        source_type = str(item.get("type") or item.get("event_type") or "message").lower()

        # Combine text fields available for this evidence item
        text_corpus = " ".join(filter(None, [
            str(item.get("text") or ""),
            str(item.get("narration") or ""),
            str(item.get("description") or ""),
            str(item.get("matched_text") or ""),
            str(item.get("text_content") or ""),
        ])).strip()

        amount = item.get("amount")
        duration_sec = item.get("duration_sec") or item.get("duration")

        # Evaluate against stage detectors to collect candidate hits
        candidate_hits: list[tuple[str, str]] = []

        for stage, patterns in detector_map.items():
            if stage not in playbook_stages:
                continue

            matched_hit: str | None = None

            # 1. Text regex detection
            if text_corpus:
                for pat in patterns:
                    m = pat.search(text_corpus)
                    if m:
                        matched_hit = m.group(0)
                        break

            # 2. Structural financial heuristics if text didn't trigger
            if not matched_hit and source_type in ("bank_txn", "transaction"):
                amt_val = None
                try:
                    if amount is not None:
                        amt_val = float(str(amount).replace(",", "").replace("₹", ""))
                except (ValueError, TypeError):
                    amt_val = None

                if stage in ("LURE_SMALL_PROFIT", "MULE_RECRUITMENT") and amt_val is not None and 0 < amt_val <= 1000:
                    matched_hit = f"Small initial credit/test transfer: ₹{amt_val:,.2f}"
                elif stage in ("EXTRACTION_TRANSFER", "EXTRACTION_LARGE_DEPOSIT", "RAPID_INBOUND_BURST") and amt_val is not None and amt_val >= 10000:
                    matched_hit = f"Substantial extraction transfer: ₹{amt_val:,.2f}"

            # 3. Structural telecom heuristics
            if not matched_hit and source_type == "call":
                try:
                    dur_val = float(duration_sec) if duration_sec is not None else 0
                except (ValueError, TypeError):
                    dur_val = 0
                if stage in ("ISOLATION_VIDEO_CALL", "CALL_SPOOFING_VICTIM") and dur_val >= 600:
                    matched_hit = f"Prolonged isolation call: {int(dur_val // 60)}m {int(dur_val % 60)}s"

            if matched_hit:
                candidate_hits.append((stage, matched_hit))

        if candidate_hits:
            # If multiple stages match, prefer one that has not yet been observed in the trace
            unseen_hits = [h for h in candidate_hits if h[0] not in last_idx_by_stage]
            stage, matched_hit = unseen_hits[0] if unseen_hits else candidate_hits[0]

            prev = last_idx_by_stage.get(stage)
            if prev is not None and (idx - prev) > cfg["max_stage_gap_lines"]:
                # Far apart repeat: update to the later occurrence
                trace = [t for t in trace if t["stage"] != stage or t["line_no"] > idx]
            last_idx_by_stage[stage] = idx

            trace.append({
                "stage": stage,
                "line_no": idx,
                "event_id": str(item.get("event_id") or item.get("id") or ""),
                "evidence_file_id": str(item.get("evidence_file_id") or ""),
                "filename": str(item.get("filename") or item.get("file_name") or ""),
                "timestamp": str(item.get("timestamp") or item.get("event_timestamp") or ""),
                "sender": item.get("sender") or item.get("from_account") or item.get("caller") or "",
                "source_type": source_type,
                "matched_text": matched_hit,
                "source_playbook": playbook["name"],
            })

    trace.sort(key=lambda t: t["line_no"])

    # Extract unique ordered stage sequence (first occurrence of each stage)
    seen: set[str] = set()
    sequence: list[dict[str, Any]] = []
    for t in trace:
        if t["stage"] not in seen:
            seen.add(t["stage"])
            sequence.append(t)

    return {
        "sequence": [t["stage"] for t in sequence],
        "evidence": sequence,
        "all_hits": trace,
    }


def build_behavioral_trace(
    messages: Sequence[dict[str, Any]],
    playbooks_lib: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Legacy backward-compatible trace builder over chat messages."""
    items = [
        {
            "type": "message",
            "text": str(m.get("text", "")),
            "line_no": m.get("line_no", i + 1),
            "sender": m.get("sender"),
            "timestamp": m.get("timestamp", ""),
            "event_id": m.get("event_id", ""),
            "evidence_file_id": m.get("evidence_file_id", ""),
        }
        for i, m in enumerate(messages)
    ]
    # For legacy multi-playbook library calls, aggregate across first playbook or unified
    pbs = playbooks_lib.get("playbooks", [])
    if len(pbs) == 1:
        return build_behavioral_trace_from_evidence(items, pbs[0], config)

    # Multi-playbook unified aggregator
    all_seq: list[dict[str, Any]] = []
    seen: set[str] = set()
    all_hits: list[dict[str, Any]] = []
    for pb in pbs:
        res = build_behavioral_trace_from_evidence(items, pb, config)
        all_hits.extend(res["all_hits"])
        for hit in res["evidence"]:
            if hit["stage"] not in seen:
                seen.add(hit["stage"])
                all_seq.append(hit)
    all_seq.sort(key=lambda x: x["line_no"])
    return {
        "sequence": [x["stage"] for x in all_seq],
        "evidence": all_seq,
        "all_hits": all_hits,
    }


def match_trace(
    behavioral_trace: dict[str, Any],
    playbooks_lib: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Legacy backward-compatible matcher."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    observed = behavioral_trace.get("sequence", [])
    scored = []
    for pb in playbooks_lib["playbooks"]:
        sim = normalized_levenshtein(observed, pb["stages"])
        dist = levenshtein_distance(observed, pb["stages"])
        cov = len(set(observed) & set(pb["stages"])) / len(pb["stages"]) if pb["stages"] else 0.0

        alignment = []
        for i, s in enumerate(observed):
            in_pb = s in pb["stages"]
            alignment.append({
                "stage": s,
                "in_playbook": in_pb,
                "observed_position": i + 1,
                "playbook_position": (pb["stages"].index(s) + 1) if in_pb else None,
                "status": "MATCHED_IN_ORDER" if in_pb and (i + 1 == pb["stages"].index(s) + 1)
                          else "MATCHED_OUT_OF_ORDER" if in_pb
                          else "UNEXPECTED_STAGE",
            })

        scored.append({
            "playbook": pb["name"],
            "description": pb.get("description", ""),
            "source": pb.get("source", ""),
            "similarity": round(sim, 4),
            "levenshtein_distance": dist,
            "coverage_ratio": round(cov, 4),
            "alignment": alignment,
            "epistemic_status": "PREDICTED",
        })

    scored.sort(key=lambda s: -s["similarity"])
    confident = [s for s in scored if s["similarity"] >= cfg["match_threshold"]]
    return {
        "observed_sequence": observed,
        "matches": scored,
        "best_match": confident[0] if confident else None,
        "verdict": ("MATCHED" if confident else
                    "NO_CONFIDENT_MATCH" if observed else "INSUFFICIENT_TRACE"),
        "note": ("Similarity of behavioral stage sequences — a screening aid, "
                 "not an attribution to a specific syndicate."),
        "judicial_notice": JUDICIAL_NOTICE,
    }


def classify_case_evidence(
    evidence_items: Sequence[dict[str, Any]],
    playbooks_lib: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Core Feature 07 classifier: Evaluates multi-modal evidence against the
    curated playbook catalog using isolated per-playbook tracing and
    normalized Levenshtein sequence matching.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    threshold = float(cfg["match_threshold"])
    per_playbook = []

    for pb in playbooks_lib.get("playbooks", []):
        trace_res = build_behavioral_trace_from_evidence(evidence_items, pb, cfg)
        observed_seq = trace_res["sequence"]
        pb_stages = pb["stages"]

        sim = normalized_levenshtein(observed_seq, pb_stages)
        dist = levenshtein_distance(observed_seq, pb_stages)
        matched_stages = set(observed_seq) & set(pb_stages)
        cov = len(matched_stages) / len(pb_stages) if pb_stages else 0.0

        # Group all hits by stage for granular evidence citation
        stage_citations: dict[str, list[dict[str, Any]]] = {}
        for hit in trace_res["all_hits"]:
            st = hit["stage"]
            stage_citations.setdefault(st, []).append({
                "event_id": hit.get("event_id"),
                "evidence_file_id": hit.get("evidence_file_id"),
                "filename": hit.get("filename"),
                "timestamp": hit.get("timestamp"),
                "source_type": hit.get("source_type"),
                "sender": hit.get("sender"),
                "matched_text": hit.get("matched_text"),
                "line_no": hit.get("line_no"),
            })

        # Build detailed alignment for every stage in the playbook
        alignment = []
        for p_idx, stage_name in enumerate(pb_stages, start=1):
            if stage_name in observed_seq:
                obs_idx = observed_seq.index(stage_name) + 1
                status = "MATCHED_IN_ORDER" if obs_idx == p_idx else "MATCHED_OUT_OF_ORDER"
            else:
                obs_idx = None
                status = "MISSING"

            alignment.append({
                "stage": stage_name,
                "in_playbook": True,
                "expected_position": p_idx,
                "observed_position": obs_idx,
                "status": status,
                "evidence_count": len(stage_citations.get(stage_name, [])),
                "supporting_evidence": stage_citations.get(stage_name, [])[:5],
            })

        # Add unexpected stages that occurred in observed trace but are not in playbook
        for o_idx, s in enumerate(observed_seq, start=1):
            if s not in pb_stages:
                alignment.append({
                    "stage": s,
                    "in_playbook": False,
                    "expected_position": None,
                    "observed_position": o_idx,
                    "status": "UNEXPECTED_STAGE",
                    "evidence_count": len(stage_citations.get(s, [])),
                    "supporting_evidence": stage_citations.get(s, [])[:5],
                })

        per_playbook.append({
            "playbook": pb["name"],
            "description": pb.get("description", ""),
            "source": pb.get("source", ""),
            "similarity": round(sim, 4),
            "levenshtein_distance": dist,
            "coverage_ratio": round(cov, 4),
            "observed_sequence": observed_seq,
            "expected_sequence": pb_stages,
            "alignment": alignment,
            "stage_evidence": stage_citations,
            "trace_evidence": trace_res["evidence"],
            "all_hits": trace_res["all_hits"],
            "is_confident": sim >= threshold,
            "calculation_breakdown": {
                "formula": "1.0 - (levenshtein_distance / max(len_observed, len_expected))",
                "levenshtein_distance": dist,
                "observed_length": len(observed_seq),
                "expected_length": len(pb_stages),
                "coverage_ratio": round(cov, 4),
                "raw_similarity": round(sim, 4),
                "threshold": threshold,
                "is_confident": sim >= threshold,
            },
            "epistemic_status": "PREDICTED",
        })

    per_playbook.sort(key=lambda p: (-p["similarity"], -p["coverage_ratio"]))
    confident = [p for p in per_playbook if p["similarity"] >= threshold]
    best = confident[0] if confident else (per_playbook[0] if per_playbook and per_playbook[0]["observed_sequence"] else None)

    any_observed = any(p["observed_sequence"] for p in per_playbook)
    verdict = (
        "MATCHED" if confident else
        "NO_CONFIDENT_MATCH" if any_observed else
        "INSUFFICIENT_TRACE"
    )

    all_evidence = []
    for p in per_playbook:
        all_evidence.extend(p["trace_evidence"])

    return {
        "verdict": verdict,
        "threshold": threshold,
        "observed_sequence": best["observed_sequence"] if best else [],
        "matches": per_playbook,
        "best_match": best if (best and best["similarity"] >= threshold) else None,
        "candidate_best": best,
        "trace_evidence": best["trace_evidence"] if (best and best["similarity"] >= threshold) else all_evidence[:15],
        "all_stage_evidence": {p["playbook"]: p["stage_evidence"] for p in per_playbook},
        "judicial_notice": JUDICIAL_NOTICE,
        "note": (
            "Similarity of behavioral stage sequences — a screening aid, "
            "not an attribution to a specific syndicate or individual."
        ),
    }


def classify_case(
    messages: Sequence[dict[str, Any]],
    playbooks_lib: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Backwards-compatible classify_case wrapper.
    Accepts chat messages [{line_no, sender, text, timestamp?}] and passes
    them through the unified multi-modal classification engine.
    """
    items = []
    for idx, m in enumerate(messages, start=1):
        items.append({
            "type": "message",
            "line_no": m.get("line_no", idx),
            "sender": m.get("sender", "?"),
            "text": m.get("text", ""),
            "timestamp": m.get("timestamp", ""),
            "event_id": m.get("event_id", ""),
            "evidence_file_id": m.get("evidence_file_id", ""),
        })
    return classify_case_evidence(items, playbooks_lib, config)
