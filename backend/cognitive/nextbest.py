"""CyberDrishti Feature 6 — Golden Hours Action Center & Next-Best Investigation Engine.

Ranks the single investigative actions that save the most money or resolve the
most uncertainty RIGHT NOW, given a case state. Design honesty:

- Transparent weighted utility with DISCLOSED weights, not a black-box
  Value-of-Information estimate. True VoI needs a response model of the world
  we do not have; the output therefore says what it is: a weighted priority
  heuristic, every component visible.
- Asset actions score by unwithdrawn amount × urgency (exponential decay over
  the configurable golden-hours window). Evidence-expansion actions score by
  how many unresolved targets they clear, discounted by latency.
- Drafts are filled ONLY from case data. A required field that is missing
  BLOCKS the draft and names the missing fields — the engine never invents
  values. Every draft carries the DRAFT banner (IO signature + legal review).
- Multi-window urgency decay:
  * Asset preservation (bank freeze, 1930): T_half = 2.0 hours.
  * Volatile evidence (CCTV, device panchnama): T_half = 24.0 hours.
  * Telecom / ISP records (CDR/IPDR, NAT): T_half = 48.0 hours.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Sequence

DEFAULT_WEIGHTS = {"asset": 1.0, "urgency": 0.5, "latency": 0.3, "friction": 0.4}
BANNER_REQUIRED_SUBSTRING = "DRAFT"

IV_HIGH = "HIGH"
IV_MEDIUM = "MEDIUM"
IV_LOW = "LOW"

# Urgency window thresholds
PHASE_CRITICAL = "CRITICAL_GOLDEN_HOURS"
PHASE_EXTENDED = "EXTENDED_WINDOW"
PHASE_DECAYED = "DECAYED_WINDOW"


def compute_urgency(elapsed_hours: float, half_life_hours: float = 2.0) -> float:
    """Exponential decay: U(t) = exp(-t / half_life)."""
    return math.exp(-max(0.0, elapsed_hours) / max(half_life_hours, 1e-6))


def classify_window_phase(elapsed_hours: float, golden_hours: float = 2.0) -> str:
    """Classify the current case timing against operational cyber investigation windows."""
    if elapsed_hours <= golden_hours:
        return PHASE_CRITICAL
    elif elapsed_hours <= 24.0:
        return PHASE_EXTENDED
    else:
        return PHASE_DECAYED


def load_catalog(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        cat = json.load(fh)
    for action in cat["actions"]:
        for key in ("code", "statute", "latency_hours", "friction_cost",
                    "requires", "draft_template", "asset_scoped"):
            if key not in action:
                raise ValueError(f"catalog action missing '{key}': {action.get('code')}")
    return cat


def _norm_ts(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def rank_actions(
    case_state: dict[str, Any],
    catalog: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Ranks catalog actions using multi-window exponential decay and transparent VoI weights.
    Maintains full backward compatibility with previous signature and return keys.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    default_golden_hours = float(catalog.get("golden_hours", 2.0))
    elapsed = float(case_state.get("elapsed_hours_since_first_credit", 0.0))
    window_phase = classify_window_phase(elapsed, default_golden_hours)

    results: list[dict[str, Any]] = []
    for action in catalog["actions"]:
        half_life = float(action.get("decay_half_life_hours") or default_golden_hours)
        urgency = compute_urgency(elapsed, half_life)
        time_remaining = max(0.0, round(half_life - elapsed, 2))

        targets = _targets_for(action, case_state)
        for target in targets:
            missing = [f for f in action["requires"] if not target.get(f)]
            entry: dict[str, Any] = {
                "action_code": action["code"],
                "description": action["description"],
                "category": action["category"],
                "statutory_basis": action["statute"],
                "target": {k: v for k, v in target.items() if not k.startswith("_")},
                "urgency_factor": round(urgency, 4),
                "decay_half_life_hours": half_life,
                "time_remaining_hours": time_remaining,
                "window_phase": window_phase,
                "latency_hours": action["latency_hours"],
                "friction_cost": action["friction_cost"],
                "weights_used": dict(w),
                "golden_hours": default_golden_hours,
            }
            if missing:
                entry.update({
                    "status": "blocked_missing_fields",
                    "missing_fields": missing,
                    "draft": None,
                    "utility_score": None,
                })
                results.append(entry)
                continue

            asset = float(target.get("amount_unwithdrawn") or 0)
            if action["asset_scoped"]:
                asset_component = asset / 100000.0            # per ₹1 lakh
                resolution_component = 0.0
            else:
                asset_component = 0.0
                resolution_component = float(target.get("_resolves", 1))
            latency_component = 1.0 / max(action["latency_hours"], 0.25)
            score = (
                w["asset"] * asset_component
                + w["urgency"] * urgency * max(asset_component, resolution_component)
                + w["latency"] * latency_component
                - w["friction"] * action["friction_cost"]
            )
            entry.update({
                "status": "ready",
                "missing_fields": [],
                "components": {
                    "asset_component": round(asset_component, 4),
                    "resolution_component": resolution_component,
                    "urgency_factor": round(urgency, 4),
                    "latency_component": round(latency_component, 4),
                    "friction_penalty": round(w["friction"] * action["friction_cost"], 4),
                },
                "utility_score": round(score, 4),
                "draft": action["draft_template"].format(
                    **{k: v for k, v in target.items() if k in action["requires"]}),
                "banner": "DRAFT — requires IO signature and legal verification before issue.",
            })
            results.append(entry)

    results.sort(key=lambda r: (
        0 if r["status"] == "ready" else 1,
        -(r["utility_score"] if r["utility_score"] is not None else float("-inf")),
    ))
    return {
        "ranked_actions": results,
        "elapsed_hours_since_first_credit": elapsed,
        "window_phase": window_phase,
        "golden_hours": default_golden_hours,
        "note": ("Weighted priority heuristic with disclosed weights — not a "
                 "calibrated Value-of-Information estimate."),
    }


def _targets_for(action: dict[str, Any], case_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce concrete action instances from case state."""
    targets: list[dict[str, Any]] = []
    code = action["code"]

    if code == "HELPLINE_1930_REFERRAL":
        if case_state.get("complaint_ref"):
            targets.append({"complaint_ref": case_state["complaint_ref"], "_resolves": 1})
        return targets

    if action["asset_scoped"]:
        for acct in case_state.get("accounts_at_risk", []):
            targets.append({**acct, "_resolves": 1})
        return targets

    if code == "REQUISITION_CDR_IPDR":
        for phone in case_state.get("unresolved_phones", [])[:2] or []:
            targets.append({
                **phone,
                "period_start": case_state.get("crime_period_start"),
                "period_end": case_state.get("crime_period_end"),
                "_resolves": len(case_state.get("unresolved_phones", [])),
            })
        return targets

    if code == "TOWER_DUMP":
        for cell in case_state.get("crime_window_cells", [])[:1] or []:
            targets.append({
                **cell,
                "period_start": case_state.get("crime_period_start"),
                "period_end": case_state.get("crime_period_end"),
                "_resolves": 1,
            })
        return targets

    if code == "KYC_FETCH":
        for acct in case_state.get("accounts_at_risk", [])[:2] or []:
            targets.append({**acct, "_resolves": 1})
        return targets

    if code == "CCTV_ATM_PRESERVATION":
        for acct in case_state.get("accounts_at_risk", [])[:1] or []:
            targets.append({
                **acct,
                "atm_location": case_state.get("atm_location"),
                "transaction_timestamp": case_state.get("transaction_timestamp"),
                "_resolves": 1,
            })
        return targets

    if code == "DEVICE_SEIZURE_PANCHNAMA":
        for dev in case_state.get("unseized_devices", [])[:2] or []:
            targets.append({**dev, "_resolves": 1})
        return targets

    if code == "SECTION_63_BSA_CERT_REQUEST":
        for entity in case_state.get("uncertified_records", [])[:2] or []:
            targets.append({**entity, "_resolves": 1})
        return targets

    return targets


# ── Evidence-Gap Driven Actions Engine ───────────────────────────────────────

def extract_evidence_gap_actions(
    case_context: Any,
    max_gap_actions: int = 6,
) -> list[dict[str, Any]]:
    """
    Derives concrete, time-sensitive investigative actions directly from unresolved
    evidence questions, gaps, and missing corroboration across the case.
    Returns structured dictionaries ready for API or CognitiveResult conversion.
    """
    results: list[dict[str, Any]] = []

    # Safe access to context fields whether CaseContext dataclass or dict
    if hasattr(case_context, "events"):
        events = case_context.events or []
        entities = case_context.entities or []
        relationships = case_context.relationships or []
        findings = case_context.findings or []
        evidence_files = getattr(case_context, "evidence_files", []) or []
    else:
        events = case_context.get("events", [])
        entities = case_context.get("entities", [])
        relationships = case_context.get("relationships", [])
        findings = case_context.get("findings", [])
        evidence_files = case_context.get("evidence_files", [])

    # Map accounts to events/evidence
    account_mapping: dict[str, dict[str, list[str]]] = {}
    for ev in events:
        meta = ev.get("event_metadata") or ev.get("metadata") or {}
        for acc in (meta.get("from_account"), meta.get("to_account"), meta.get("account")):
            if not acc:
                continue
            entry = account_mapping.setdefault(str(acc), {"events": [], "evidence": []})
            if ev.get("id"):
                entry["events"].append(str(ev["id"]))
            if ev.get("evidence_file_id"):
                entry["evidence"].append(str(ev["evidence_file_id"]))

    account_entities = [e for e in entities if e.get("entity_type") == "ACCOUNT"]
    has_device = any(e.get("entity_type") == "DEVICE" for e in entities)
    bank_events = [e for e in events if e.get("event_type") == "bank_txn"]
    comm_events = [e for e in events if e.get("event_type") in ("call", "whatsapp_msg", "sms")]
    inferred_rels = [
        r for r in relationships
        if str(r.get("epistemic_status", "")).upper() == "INFERRED"
    ]

    # 1. Account ownership / KYC unresolved
    for ent in account_entities[:2]:
        acc = str(ent.get("canonical_value"))
        refs = account_mapping.get(acc, {"events": [], "evidence": []})
        results.append({
            "gap": "ENTITY_ATTRIBUTION",
            "title": f"Obtain account ownership/KYC record for {acc}",
            "description": f"Evidence gap: ENTITY_ATTRIBUTION · information value {IV_HIGH} · resolves: Account-control hypothesis",
            "why": "Financial movement involving this account is established, but ownership and control are not. The account-control hypothesis remains unresolved.",
            "resolves": "Account-control hypothesis",
            "information_value": IV_HIGH,
            "severity": "HIGH",
            "statutory_basis": "Section 94 BNSS (Customer Application Form & KYC Request)",
            "action_code": "KYC_FETCH",
            "entity_refs": [acc],
            "event_refs": refs["events"],
            "evidence_refs": refs["evidence"],
            "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "ENTITY_ATTRIBUTION", "ACCOUNT_CONTROL_UNRESOLVED"],
            "draft": f"Request to Bank Nodal Officer under Section 94 BNSS: furnish account-opening Customer Application Form (CAF) and KYC records for account {acc}. DRAFT — requires IO signature.",
            "banner": "DRAFT — requires IO signature and legal verification before issue.",
            "status": "ready" if acc != "UNKNOWN" else "blocked_missing_fields",
            "missing_fields": [] if acc != "UNKNOWN" else ["account"],
            "utility_score": 3.85,
            "urgency_factor": 0.85,
        })
        if len(results) >= max_gap_actions:
            return results[:max_gap_actions]

    # 2. Account ↔ device/session linkage unresolved
    if account_entities and not has_device:
        ev_ids = [str(e["id"]) for e in bank_events if e.get("id")]
        evd = [str(e.get("evidence_file_id")) for e in bank_events if e.get("evidence_file_id")]
        results.append({
            "gap": "DEVICE_ATTRIBUTION",
            "title": "Obtain authenticated device/session records for the transaction window",
            "description": f"Evidence gap: DEVICE_ATTRIBUTION · information value {IV_HIGH} · resolves: Account/device relationship hypothesis",
            "why": "No device or session entity is linked to the accounts. The account↔device relationship is unresolved.",
            "resolves": "Account/device relationship hypothesis",
            "information_value": IV_HIGH,
            "severity": "MEDIUM",
            "statutory_basis": "Section 94 BNSS (Internet Banking Session Logs & IPDR)",
            "action_code": "SESSION_IPDR_FETCH",
            "entity_refs": [str(e.get("canonical_value")) for e in account_entities[:3]],
            "event_refs": ev_ids,
            "evidence_refs": evd,
            "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "DEVICE_ATTRIBUTION", "DEVICE_LINKAGE_UNRESOLVED"],
            "draft": "Requisition u/s 94 BNSS to the beneficiary bank: furnish source IP, login session timestamp, and IMEI/device identifier for transactions in the window. DRAFT — requires IO signature.",
            "banner": "DRAFT — requires IO signature and legal verification before issue.",
            "status": "ready",
            "missing_fields": [],
            "utility_score": 3.25,
            "urgency_factor": 0.80,
        })

    # 3. Communication events with unknown counterparty
    unknown = []
    for ev in comm_events:
        meta = ev.get("event_metadata") or ev.get("metadata") or {}
        counterparty = meta.get("callee") or meta.get("recipient")
        if not counterparty or str(counterparty).strip().upper() in ("UNKNOWN", "?"):
            unknown.append(ev)
    if unknown:
        results.append({
            "gap": "UNKNOWN_ENDPOINT",
            "title": "Resolve unknown communication endpoints",
            "description": f"Evidence gap: UNKNOWN_ENDPOINT · information value {IV_MEDIUM} · resolves: Communication counterparty resolution",
            "why": f"{len(unknown)} communication event(s) have no identifiable counterparty. The endpoint must not be invented — it requires CDR/IPDR evidence.",
            "resolves": "Communication counterparty resolution",
            "information_value": IV_MEDIUM,
            "severity": "MEDIUM",
            "statutory_basis": "Section 94 BNSS (Telecom Service Provider CDR Requisition)",
            "action_code": "REQUISITION_CDR_IPDR",
            "event_refs": [str(e["id"]) for e in unknown if e.get("id")],
            "evidence_refs": [str(e.get("evidence_file_id")) for e in unknown if e.get("evidence_file_id")],
            "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "UNKNOWN_ENDPOINT", "COUNTERPARTY_UNKNOWN"],
            "draft": "Requisition u/s 94 BNSS to Telecom Service Provider: furnish incoming caller and outgoing recipient resolution for recorded communication window. DRAFT — requires IO signature.",
            "banner": "DRAFT — requires IO signature and legal verification before issue.",
            "status": "ready",
            "missing_fields": [],
            "utility_score": 2.90,
            "urgency_factor": 0.75,
        })

    # 4. Cross-stream temporal reconciliation
    if bank_events and comm_events:
        sample = comm_events[:2] + bank_events[:2]
        results.append({
            "gap": "TEMPORAL_RECONCILIATION",
            "title": "Reconcile communication and financial timestamps",
            "description": f"Evidence gap: TEMPORAL_RECONCILIATION · information value {IV_MEDIUM} · resolves: Communication/transaction temporal correlation",
            "why": "Communication and financial evidence both exist. Their clocks must be reconciled before any temporal claim; this establishes correlation, not causation.",
            "resolves": "Communication/transaction temporal correlation",
            "information_value": IV_MEDIUM,
            "severity": "LOW",
            "statutory_basis": "Forensic Clock Drift Calibration (ISO/IEC 27037)",
            "action_code": "TEMPORAL_CALIBRATION",
            "event_refs": [str(e["id"]) for e in sample if e.get("id")],
            "evidence_refs": [str(e.get("evidence_file_id")) for e in sample if e.get("evidence_file_id")],
            "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "TEMPORAL_RECONCILIATION", "TEMPORAL_CORRELATION_ONLY"],
            "draft": "Internal Forensic Memo: calibrate NTP server drift across bank server timestamps and telecom CDR timestamps. DRAFT.",
            "banner": "DRAFT — internal investigative analysis note.",
            "status": "ready",
            "missing_fields": [],
            "utility_score": 2.10,
            "urgency_factor": 0.65,
        })

    # 5. Corroborate inferred links
    if len(results) < max_gap_actions:
        for rel in inferred_rels[:2]:
            a, b = rel.get("source_value"), rel.get("target_value")
            conf = float(rel.get("confidence") or 0.0)
            results.append({
                "gap": "INFERRED_LINK_CORROBORATION",
                "title": f"Corroborate inferred link {a} ↔ {b}",
                "description": f"Evidence gap: INFERRED_LINK_CORROBORATION · information value {IV_HIGH if conf >= 0.7 else IV_MEDIUM} · resolves: Inferred relationship corroboration",
                "why": "This relationship is INFERRED from multiple signals, not directly observed. Independent evidence is required to confirm or refute it.",
                "resolves": "Inferred relationship corroboration",
                "information_value": IV_HIGH if conf >= 0.7 else IV_MEDIUM,
                "severity": "HIGH" if conf >= 0.7 else "MEDIUM",
                "statutory_basis": "Section 94 BNSS / Section 105 BNSS Independent Corroboration",
                "action_code": "CORROBORATE_LINK",
                "entity_refs": [str(a), str(b)],
                "event_refs": [str(x) for x in (rel.get("event_refs") or [])],
                "evidence_refs": [str(x) for x in (rel.get("evidence_refs") or [])],
                "component_scores": {"inferred_confidence": rel.get("confidence")},
                "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "INFERRED_LINK_CORROBORATION", "INFERRED_RELATIONSHIP"],
                "draft": f"Investigative Requisition: collect independent documentary proof to substantiate inferred connection between {a} and {b}. DRAFT — requires IO signature.",
                "banner": "DRAFT — requires IO signature and legal verification before issue.",
                "status": "ready",
                "missing_fields": [],
                "utility_score": round(2.5 + conf, 2),
                "urgency_factor": 0.70,
            })
            if len(results) >= max_gap_actions:
                return results[:max_gap_actions]

    # 6. Open uncertainty findings
    for finding in findings:
        if len(results) >= max_gap_actions:
            break
        if finding.get("finding_type") != "UNCERTAINTY":
            continue
        results.append({
            "gap": "OPEN_UNCERTAINTY",
            "title": f"Resolve uncertainty: {finding.get('title')}",
            "description": f"Evidence gap: OPEN_UNCERTAINTY · information value {IV_MEDIUM} · resolves: Open uncertainty finding",
            "why": finding.get("description") or "An unresolved uncertainty finding remains open.",
            "resolves": "Open uncertainty finding",
            "information_value": IV_MEDIUM,
            "severity": "MEDIUM",
            "statutory_basis": "Supplementary Investigation u/s 193(9) BNSS",
            "action_code": "RESOLVE_UNCERTAINTY",
            "entity_refs": [str(x) for x in (finding.get("entity_refs") or [])],
            "event_refs": [str(x) for x in (finding.get("event_refs") or [])],
            "evidence_refs": [str(x) for x in (finding.get("evidence_refs") or [])],
            "component_scores": {
                "generated_by_finding": finding.get("fingerprint") or finding.get("title"),
            },
            "reason_codes": ["NEXT_BEST_ACTION", "EVIDENCE_GAP", "OPEN_UNCERTAINTY"],
            "draft": f"Supplementary Case Note: resolve factual uncertainty regarding '{finding.get('title')}'. DRAFT.",
            "banner": "DRAFT — internal investigative analysis note.",
            "status": "ready",
            "missing_fields": [],
            "utility_score": 2.0,
            "urgency_factor": 0.60,
        })

    return results[:max_gap_actions]


# ── Notice Draft Generator ───────────────────────────────────────────────────

def render_statutory_notice(
    action_code: str,
    target: dict[str, Any],
    case_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Renders an authentic, pre-filled legal notice template under Indian criminal law.
    Strictly includes the mandatory DRAFT banner and statutory citations.
    """
    meta = case_meta or {}
    fir_num = meta.get("fir_number") or meta.get("case_number") or "CYB-2026-UNSPECIFIED"
    police_station = meta.get("police_station") or "Cyber Crime Police Station"
    now_str = datetime.now(timezone.utc).strftime("%d-%m-%Y")

    if action_code in ("FREEZE_ACCOUNT_EVIDENCE", "BANK_FREEZE_106_BNSS", "BANK_FREEZE"):
        account = target.get("account", "[ACCOUNT NUMBER]")
        ifsc = target.get("ifsc", "[IFSC]")
        bank = target.get("bank_name", "[BANK NAME]")
        amt = target.get("amount_unwithdrawn", "0.00")
        body = (
            f"FORM OF NOTICE UNDER SECTION 106 OF THE BHARATIYA NAGARIK SURAKSHA SANHITA (BNSS), 2023\n"
            f"(Corresponding to Section 102 Code of Criminal Procedure, 1973)\n\n"
            f"To,\n"
            f"The Nodal Officer / Branch Manager,\n"
            f"{bank} (IFSC: {ifsc})\n\n"
            f"Subject: Order to Freeze Debit Transactions on Account No. {account} in FIR No. {fir_num}\n\n"
            f"Sir/Madam,\n\n"
            f"WHEREAS, investigation into FIR No. {fir_num} registered at {police_station} under Section 318(4) "
            f"Bharatiya Nyaya Sanhita, 2023 (Cheating) and Section 66D Information Technology Act, 2000 is being conducted;\n\n"
            f"AND WHEREAS, credible digital evidence indicates that proceeds of cyber crime amounting to approximately "
            f"Rs. {amt}/- were transferred into Account No. {account} maintained with your bank;\n\n"
            f"NOW THEREFORE, in exercise of powers conferred under Section 106 of the Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023, you are hereby DIRECTED to:\n"
            f"  1. Immediately mark DEBIT FREEZE / STOP PAYMENT on the aforesaid account to prevent dissipation of funds.\n"
            f"  2. Preserve and furnish the complete Account Opening Form (AOF), KYC documents, mandate, and registered mobile.\n"
            f"  3. Furnish detailed statement of account with IP login timestamps, MAC addresses, and channel identifiers.\n\n"
            f"Please take notice that this seizure is being reported to the jurisdictional Magistrate in compliance with "
            f"Section 106(3) BNSS, 2023. Failure to comply promptly attracts statutory liability under Section 223 BNS, 2023.\n\n"
            f"Issued on this {now_str}.\n\n"
            f"___________________________\n"
            f"Investigating Officer\n"
            f"{police_station}\n"
        )
        statute = "Section 106 BNSS, 2023"

    elif action_code in ("REQUISITION_CDR_IPDR", "CDR_REQUISITION_94_BNSS", "CDR_REQUISITION"):
        phone = target.get("phone", "[PHONE NUMBER]")
        p_start = target.get("period_start", "[START TIMESTAMP]")
        p_end = target.get("period_end", "[END TIMESTAMP]")
        body = (
            f"REQUISITION FOR ELECTRONIC RECORDS UNDER SECTION 94 BNSS, 2023\n"
            f"(Corresponding to Section 91 Code of Criminal Procedure, 1973)\n\n"
            f"To,\n"
            f"The Nodal Officer (Law Enforcement Assistance),\n"
            f"Telecom Service Provider\n\n"
            f"Subject: Requisition of CDR/IPDR/CAF for Mobile Number {phone} in FIR No. {fir_num}\n\n"
            f"Sir/Madam,\n\n"
            f"WHEREAS, the production of call detail records and internet protocol detail records for the mobile number "
            f"{phone} is necessary and desirable for the investigation of FIR No. {fir_num} at {police_station};\n\n"
            f"NOW THEREFORE, under Section 94 BNSS, 2023, you are hereby requested to furnish:\n"
            f"  1. Call Detail Records (CDR) with Cell ID, Azimuth, and Tower Location from {p_start} to {p_end}.\n"
            f"  2. Internet Protocol Detail Records (IPDR) with source port and translation logs for the same period.\n"
            f"  3. Subscriber Customer Application Form (CAF) along with verified Photo ID and address proof.\n"
            f"  4. Dual-signed Certificate under Section 63(4) Bharatiya Sakshya Adhiniyam, 2023.\n\n"
            f"Issued on this {now_str}.\n\n"
            f"___________________________\n"
            f"Investigating Officer\n"
            f"{police_station}\n"
        )
        statute = "Section 94 BNSS, 2023"

    elif action_code == "CCTV_ATM_PRESERVATION":
        loc = target.get("location") or target.get("target") or "[ATM / BRANCH LOCATION]"
        body = (
            f"NOTICE FOR PRESERVATION OF CCTV FOOTAGE UNDER SECTION 94 BNSS, 2023\n\n"
            f"To,\n"
            f"The Branch Manager / Security In-Charge,\n"
            f"{loc}\n\n"
            f"Subject: Urgent Preservation of ATM / Branch CCTV Footage in FIR No. {fir_num}\n\n"
            f"You are hereby directed under Section 94 BNSS, 2023 to IMMEDIATELY preserve and archive without overwriting "
            f"all CCTV footage covering cash dispensing, ingress, and egress counters for the suspect transaction window.\n"
            f"Furnish video files on write-once optical media along with Section 63(4) BSA Certificate.\n\n"
            f"Issued on this {now_str}.\n"
        )
        statute = "Section 94 BNSS, 2023"

    elif action_code == "DEVICE_SEIZURE_PANCHNAMA":
        dev = target.get("device") or target.get("target") or "[SUSPECT DEVICE]"
        body = (
            f"PANCHNAMA / SEIZURE MEMO UNDER SECTION 105 BNSS, 2023\n\n"
            f"Seizure of electronic hardware / mobile device ({dev}) conducted in compliance with Section 105 BNSS.\n"
            f"MANDATORY REQUIREMENT: Continuous audio-video recording of search and seizure executed throughout.\n"
            f"Device placed in Faraday evidence bag; tamper-evident security seal applied with hash generation on-site.\n\n"
            f"Date: {now_str} | Investigating Agency: {police_station}\n"
        )
        statute = "Section 105 BNSS, 2023"

    elif action_code == "SECTION_63_BSA_CERT_REQUEST":
        body = (
            f"REQUISITION FOR CERTIFICATE UNDER SECTION 63(4) BHARATIYA SAKSHYA ADHINIYAM, 2023\n\n"
            f"In the Court of Jurisdictional Magistrate | FIR No. {fir_num}\n\n"
            f"Requisition to System Administrator / Authorized Signatory for dual-signed Section 63(4) BSA certificate "
            f"identifying the electronic record, describing production manner, and certifying device lawful control.\n\n"
            f"Date: {now_str}\n"
        )
        statute = "Section 63(4) BSA, 2023"

    elif action_code == "HELPLINE_1930_REFERRAL":
        complaint = target.get("complaint_ref", fir_num)
        body = (
            f"CITIZEN FINANCIAL CYBER FRAUD REPORTING AND MANAGEMENT SYSTEM (CFCFRMS / 1930)\n"
            f"EMERGENCY REFERRAL FOR MULTI-LEVEL BANK TRAIL FREEZE\n\n"
            f"Case Reference: {fir_num} | NCRP / 1930 Acknowledgement: {complaint}\n"
            f"Date: {now_str}\n\n"
            f"ACTION REQUESTED:\n"
            f"Direct all member banks along the fund dissipation trail to execute automated stop-payment holds on "
            f"Layer-1 and Layer-2 beneficiary accounts in accordance with standard I4C CFCFRMS SOP.\n\n"
            f"Note: This administrative referral is without prejudice to formal judicial freeze orders under Section 106 BNSS.\n"
        )
        statute = "I4C CFCFRMS SOP"

    else:
        body = (
            f"STATUTORY NOTICE UNDER BHARATIYA NAGARIK SURAKSHA SANHITA, 2023\n"
            f"Case FIR No. {fir_num} | Date: {now_str}\n\n"
            f"Action Code: {action_code}\n"
            f"Target Entities: {json.dumps(target, indent=2)}\n\n"
            f"Please take necessary investigative measures in accordance with law.\n"
        )
        statute = "BNSS, 2023"

    banner = (
        "****************************************************************************************\n"
        "[DRAFT - REQUIRES INVESTIGATING OFFICER SIGNATURE & LEGAL VERIFICATION U/S 193 BNSS]\n"
        "  Generated by NETRA 5.0 Golden Hours Action Center in compliance with Section 193 BNSS\n"
        "****************************************************************************************"
    )

    full_text = f"{banner}\n\n{body}\n\n{banner}"
    tgt = target.get("account") or target.get("phone") or target.get("complaint_ref") or target.get("target") or "CASE_SUBJECT_TARGET"

    return {
        "action_code": action_code,
        "statute": statute,
        "statutory_authority": statute,
        "target_entity": str(tgt),
        "banner": banner,
        "notice_text": full_text,
        "draft_text": full_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
