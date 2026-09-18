from __future__ import annotations

"""
CyberDrishti AI — Defence Bot Core (Adversarial Hypothesis Stress-Testing)

Analyzes case context, findings, evidence files, and hypotheses to simulate
courtroom defense scrutiny and red-team the prosecution case file.

Key Capabilities:
  1. Formulates plausible innocent counter-hypotheses (account compromise,
     bona fide commercial transfer, shared device, tower radius alibi).
  2. Identifies critical evidentiary gaps required for proof beyond reasonable doubt
     (missing KYC/CAF, unauthenticated IPs, absent device seizure memos).
  3. Audits digital evidence chain of custody vulnerabilities under Section 63 BSA, 2023
     and bank freeze reporting under Section 106 BNSS, 2023.
  4. Formulates concrete, proactive prosecution rebuttal strategies before chargesheet
     filing under Section 193 BNSS, 2023.
  5. Strictly adheres to NETRA's Epistemic Humility Standard: never asserts guilt
     or innocence; frames all evaluations as adversarial defensibility tests.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any, Sequence


EPISTEMIC_DEFENCE_NOTICE = (
    "Adversarial Red-Team Notice: Defence Bot simulates defense counsel cross-examination "
    "and audits evidentiary vulnerabilities to harden the prosecution case file before chargesheet "
    "filing under Section 193 BNSS, 2023. It does NOT determine legal guilt, innocence, or judicial "
    "admissibility, which remains exclusively within the purview of the competent trial court."
)


@dataclass
class DefenceChallenge:
    """A single grounded adversarial red-team challenge against an investigative theory."""
    challenge_id: str
    target_hypothesis: str
    target_entity: str
    defense_counter_hypothesis: str
    reasonable_doubts: list[str] = field(default_factory=list)
    missing_evidence: list[dict[str, str]] = field(default_factory=list)
    statutory_vulnerabilities: list[dict[str, str]] = field(default_factory=list)
    rebuttal_strategy: list[dict[str, str]] = field(default_factory=list)
    vulnerability_severity: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW
    epistemic_status: str = "ADVERSARIAL_TEST"
    confidence: float = 0.85
    evidence_refs: list[str] = field(default_factory=list)
    event_refs: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DefenceAuditReport:
    """Case-level adversarial defensibility audit and red-team evaluation."""
    case_id: str
    defensibility_score: float  # 0.0 to 1.0 (higher = more defensible against cross-examination)
    risk_level: str  # HIGH_RISK, MODERATE_RISK, LOW_RISK
    total_hypotheses_tested: int
    challenges: list[DefenceChallenge] = field(default_factory=list)
    missing_evidence_summary: list[dict[str, Any]] = field(default_factory=list)
    bsa_compliance_status: dict[str, Any] = field(default_factory=dict)
    rebuttal_action_plan: list[dict[str, str]] = field(default_factory=list)
    epistemic_notice: str = EPISTEMIC_DEFENCE_NOTICE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["challenges"] = [c if isinstance(c, dict) else c.to_dict() for c in self.challenges]
        return data


# ── Core Adversarial Auditor ─────────────────────────────────────────────────

def audit_case_defensibility(
    case_id: str,
    evidence_files: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    findings: Sequence[dict[str, Any]],
    entity_profiles: dict[str, Any] | None = None,
) -> DefenceAuditReport:
    """
    Perform a comprehensive adversarial defensibility audit on a case.
    Evaluates active hypotheses, evidence completeness, and statutory integrity.
    """
    challenges: list[DefenceChallenge] = []
    missing_items: list[dict[str, Any]] = []
    rebuttal_actions: list[dict[str, str]] = []

    # 1. Inventory available evidence types and file statuses
    filenames = [f.get("filename") or f.get("original_name") or "" for f in evidence_files]
    file_types = {str(f.get("file_type", "")).lower() for f in evidence_files}
    source_types = {str(f.get("source_type", "")).lower() for f in evidence_files}

    has_seizure_memo = any("seizure" in fn.lower() or "memo" in fn.lower() for fn in filenames)
    has_cdr = any("cdr" in fn.lower() or "call" in fn.lower() or "phone" in fn.lower() for fn in filenames)
    has_bank = any("bank" in fn.lower() or "upi" in fn.lower() or "statement" in fn.lower() for fn in filenames)
    has_location = any("location" in fn.lower() or "timeline" in fn.lower() for fn in filenames)
    has_network_log = any("network" in fn.lower() or "log" in fn.lower() or "ip" in fn.lower() for fn in filenames)

    # 2. Section 63 BSA & Evidence Integrity Check
    total_files = len(evidence_files)
    hashed_files = sum(1 for f in evidence_files if f.get("sha256_hash") and len(f["sha256_hash"]) == 64)
    preservation_score = round(hashed_files / max(1, total_files), 2)

    bsa_status = {
        "preservation_score": preservation_score,
        "total_files": total_files,
        "hashed_files": hashed_files,
        "has_seizure_memo": has_seizure_memo,
        "compliant_with_bsa_63": bool(preservation_score >= 1.0 and has_seizure_memo),
    }

    if preservation_score < 1.0 or not has_seizure_memo:
        sec63_vulns = []
        if preservation_score < 1.0:
            sec63_vulns.append({
                "statute": "Section 63(4)(c) BSA, 2023",
                "issue": "Missing or incomplete cryptographic hash computation at the threshold of evidence ingestion.",
                "defense_challenge": "Defense will move to exclude digital records under Section 63 BSA for broken hash chain.",
            })
        if not has_seizure_memo:
            sec63_vulns.append({
                "statute": "Section 105 BNSS, 2023 & Section 63 BSA, 2023",
                "issue": "Absence of formal Evidence Seizure Memo with independent punch witnesses.",
                "defense_challenge": "Defense will argue digital artifacts were tampered or fabricated in police custody without witness attestation.",
            })

        challenges.append(DefenceChallenge(
            challenge_id=f"dc_bsa_{case_id[:8]}",
            target_hypothesis="DIGITAL_EVIDENCE_AUTHENTICITY",
            target_entity="Case Evidence Chain",
            defense_counter_hypothesis="Digital records were harvested without contemporaneous hash attestation or independent panchnama.",
            reasonable_doubts=[
                "Failure to document unbroken chain of custody under Section 63 BSA leaves room for reasonable doubt regarding file integrity.",
                "Lack of independent witness attestation on digital extraction violates procedural safeguard mandates under BNSS Section 105.",
            ],
            missing_evidence=[
                {
                    "item": "Section 63 BSA Certificate",
                    "reason": "Mandatory statutory prerequisite for trial court admissibility of electronic records.",
                    "statutory_rule": "Section 63(4) BSA, 2023",
                },
                {
                    "item": "Seizure Panchnama / Memo with 2 Witnesses",
                    "reason": "Proves uncontaminated physical/digital custody transfer.",
                    "statutory_rule": "Section 105 BNSS, 2023",
                },
            ],
            statutory_vulnerabilities=sec63_vulns,
            rebuttal_strategy=[
                {
                    "action_code": "PRODUCE_BSA_CERTIFICATE",
                    "statute": "Section 63 BSA",
                    "recommendation": "Procure signed Section 63 BSA Certificate from system administrator/service provider nodal officer with SHA-256 verification.",
                },
                {
                    "action_code": "RECORD_SEIZURE_WITNESSES",
                    "statute": "Section 105 BNSS",
                    "recommendation": "Record supplementary statements of seizure panch witnesses under Section 180 BNSS.",
                },
            ],
            vulnerability_severity="CRITICAL",
            evidence_refs=[str(f.get("id") or "") for f in evidence_files if f.get("id")],
        ))

    # 3. Cross-Examine Active Behavioral Anomalies & Pass-Through Findings
    anomaly_findings = [f for f in findings if f.get("finding_type") in ("BEHAVIORAL_ANOMALY", "RAPID_PASS_THROUGH")]
    pass_through_targets = set()
    for af in anomaly_findings:
        ent = af.get("entity") or (af.get("component_scores") or {}).get("entity") or ""
        if ent:
            pass_through_targets.add(ent)

    # If pass-through found (e.g. rohan@upi), construct targeted adversarial mule defense
    for ent in pass_through_targets:
        challenges.append(DefenceChallenge(
            challenge_id=f"dc_mule_{hashlib.md5(ent.encode()).hexdigest()[:8]}",
            target_hypothesis="LAYER1_MULE_ACCUSATION",
            target_entity=ent,
            defense_counter_hypothesis=(
                f"Account {ent} was operated without the owner's knowledge (credential phishing, SIM swap, or "
                f"unauthorized access), or represented a legitimate commercial invoice settlement / peer-to-peer transaction."
            ),
            reasonable_doubts=[
                f"Prosecution has not established mens rea or knowledge that funds received by {ent} were proceeds of crime.",
                f"No direct chat, call, or email communication has been proved between {ent} and the complainant prior to the transfer.",
                f"Rapid turnaround velocity (pass-through) is equally consistent with automated commercial clearing or account compromise.",
            ],
            missing_evidence=[
                {
                    "item": f"Authenticated Device Login Logs for {ent}",
                    "reason": "Proves the account was physically accessed from suspect's known device/IP rather than a remote compromise.",
                    "statutory_rule": "Section 94 BNSS, 2023",
                },
                {
                    "item": f"Beneficiary Account Opening KYC & Customer Application Form (CAF)",
                    "reason": "Verifies true identity of account opener and associated registered contact number.",
                    "statutory_rule": "Section 94 BNSS, 2023",
                },
                {
                    "item": "Victim-Beneficiary Direct Communication Record",
                    "reason": "Establishes inducement or conspiracy element under BNS Section 318(4) / 61(2).",
                    "statutory_rule": "Section 318(4) BNS, 2023",
                },
            ],
            statutory_vulnerabilities=[
                {
                    "statute": "Section 318(4) BNS, 2023 (Cheating)",
                    "issue": "Dishonest inducement requires intentional deception from inception, not mere receipt of money.",
                    "defense_challenge": "Defense will cite Supreme Court precedent (*Uma Shankar Gopalika v. State of Bihar*) that mere monetary transfer without fraudulent intent is not cheating.",
                },
            ],
            rebuttal_strategy=[
                {
                    "action_code": "NOTICE_94_BNSS_BANK_LOGS",
                    "statute": "Section 94 BNSS",
                    "recommendation": f"Issue Notice u/s 94 BNSS to bank nodal officer for session IP logs, IMEI/device fingerprint, and KYC form of {ent}.",
                },
                {
                    "action_code": "SUMMON_ACCOUNT_HOLDER",
                    "statute": "Section 179 BNSS",
                    "recommendation": f"Summon account holder of {ent} for examination under Section 179 BNSS to establish physical possession of device/credentials.",
                },
            ],
            vulnerability_severity="HIGH",
            evidence_refs=[str(af.get("evidence_refs", [""])[0]) if af.get("evidence_refs") else ""],
            event_refs=list(af.get("event_refs", [])),
        ))

    # 4. Cross-Examine Call Detail Records / Kingpin Organizer Theories
    call_events = [e for e in events if e.get("event_type") == "call"]
    cdr_files = [str(f.get("id")) for f in evidence_files if f.get("id") and any(k in (f.get("filename") or f.get("original_name") or "").lower() for k in ("cdr", "call", "phone"))]
    all_file_ids = [str(f.get("id")) for f in evidence_files if f.get("id")]

    if has_cdr and call_events:
        # Check telecom suspect vulnerabilities
        caller_counts: dict[str, int] = {}
        for ce in call_events:
            meta = ce.get("metadata") or ce.get("event_metadata") or ce
            caller = meta.get("caller") or meta.get("phone")
            if caller and caller != "?":
                caller_counts[caller] = caller_counts.get(caller, 0) + 1

        top_caller = max(caller_counts.items(), key=lambda x: x[1])[0] if caller_counts else None
        if top_caller:
            challenges.append(DefenceChallenge(
                challenge_id=f"dc_telecom_{hashlib.md5(top_caller.encode()).hexdigest()[:8]}",
                target_hypothesis="COMMUNICATION_CONSPIRACY",
                target_entity=top_caller,
                defense_counter_hypothesis=(
                    f"Number {top_caller} was used by multiple persons or spoofed; cell tower observation covers a wide "
                    f"geographical radius (1.5–3 km) and does not establish physical presence at the scene of crime."
                ),
                reasonable_doubts=[
                    f"Call Detail Record (CDR) proves only signal connectivity through tower, not physical identity of speaker.",
                    "Absence of contemporaneous voice recording or voice biometric comparison creates reasonable doubt on user identity.",
                    "Cell tower triangulation error margin in urban environments prevents pinpoint location attribution.",
                ],
                missing_evidence=[
                    {
                        "item": f"Telecom Customer Acquisition Form (CAF) & Photo ID for {top_caller}",
                        "reason": "Proves legal subscriber identity for the SIM card.",
                        "statutory_rule": "Section 94 BNSS, 2023",
                    },
                    {
                        "item": "Handset Physical Seizure & IMEI Examination Memo",
                        "reason": "Links SIM to physical mobile device seized from suspect's personal custody.",
                        "statutory_rule": "Section 105 BNSS, 2023",
                    },
                ],
                statutory_vulnerabilities=[
                    {
                        "statute": "Section 63 BSA, 2023",
                        "issue": "Telecom CDR printout without telecom nodal officer's Section 63 BSA Certificate is legally inadmissible.",
                        "defense_challenge": "Defense will cite *Anvar P.V. v. P.K. Basheer* and Section 63 BSA to exclude CDR printouts lacking statutory certificates.",
                    },
                ],
                rebuttal_strategy=[
                    {
                        "action_code": "REQUISITION_CAF_AND_CERTIFICATE",
                        "statute": "Section 94 BNSS & 63 BSA",
                        "recommendation": f"Procure attested CAF, Aadhaar/ID proof, and Section 63 BSA Certificate from telecom service provider for {top_caller}.",
                    },
                    {
                        "action_code": "SEIZE_HANDSET_IMEI",
                        "statute": "Section 105 BNSS",
                        "recommendation": f"Seize mobile handset matching CDR IMEI with video recording under Section 105 BNSS.",
                    },
                ],
                vulnerability_severity="MEDIUM",
                evidence_refs=cdr_files or all_file_ids,
                event_refs=[str(ce.get("id")) for ce in call_events if ce.get("id")],
            ))

    # 5. Cross-Examine IP & Network Logs (if present)
    if has_network_log:
        net_files = [str(f.get("id")) for f in evidence_files if f.get("id") and any(k in (f.get("filename") or f.get("original_name") or "").lower() for k in ("network", "log", "ip"))]
        challenges.append(DefenceChallenge(
            challenge_id=f"dc_ip_{case_id[:8]}",
            target_hypothesis="IP_ADDRESS_ATTRIBUTION",
            target_entity="Network IP Logs",
            defense_counter_hypothesis=(
                "Observed IP addresses represent dynamic NAT IP allocations, public VPN endpoints, or open Wi-Fi networks "
                "accessible to multiple non-suspect third parties."
            ),
            reasonable_doubts=[
                "IP address alone does not establish personal human culpability without subscriber port allocation records (NAT/CGNAT).",
                "Possibility of malware, proxy chaining, or unauthorized Wi-Fi access creates reasonable doubt on perpetrator identity.",
            ],
            missing_evidence=[
                {
                    "item": "ISP Subscriber Attribution with Source Port Allocation (NAT IPDR)",
                    "reason": "Dynamic IP resolution without source port is inconclusive in court.",
                    "statutory_rule": "Section 94 BNSS, 2023",
                },
            ],
            statutory_vulnerabilities=[
                {
                    "statute": "Section 66 IT Act, 2000 & Section 63 BSA, 2023",
                    "issue": "Server log exports require system administrator certification regarding tamper-proof storage.",
                    "defense_challenge": "Defense will argue server logs were stored in modifiable text format without cryptographic audit trails.",
                },
            ],
            rebuttal_strategy=[
                {
                    "action_code": "REQUISITION_CGNAT_IPDR",
                    "statute": "Section 94 BNSS",
                    "recommendation": "Requisition ISP for destination IP, source port, and subscriber CAF for the exact UTC timestamp window.",
                },
            ],
            vulnerability_severity="MEDIUM",
            evidence_refs=net_files or all_file_ids,
            event_refs=[str(e.get("id")) for e in events if e.get("id") and str(e.get("event_type", "")).lower() in ("network", "log", "ip")],
        ))

    # 6. Aggregate Missing Evidence and Rebuttals
    all_missing_items: list[dict[str, Any]] = []
    seen_missing = set()
    for ch in challenges:
        for m in ch.missing_evidence:
            item_name = m.get("item", "")
            if item_name not in seen_missing:
                seen_missing.add(item_name)
                all_missing_items.append({
                    "item": item_name,
                    "reason": m.get("reason", ""),
                    "statutory_rule": m.get("statutory_rule", ""),
                    "severity": ch.vulnerability_severity,
                    "target_entity": ch.target_entity,
                })
        for r in ch.rebuttal_strategy:
            rebuttal_actions.append(r)

    # 7. Compute Defensibility Score and Risk Rating
    score = 1.0
    for ch in challenges:
        if ch.vulnerability_severity == "CRITICAL":
            score -= 0.18
        elif ch.vulnerability_severity == "HIGH":
            score -= 0.12
        elif ch.vulnerability_severity == "MEDIUM":
            score -= 0.07
        elif ch.vulnerability_severity == "LOW":
            score -= 0.03

    final_score = round(max(0.25, min(0.95, score)), 2)

    if final_score < 0.55:
        risk_level = "HIGH_RISK"
    elif final_score < 0.75:
        risk_level = "MODERATE_RISK"
    else:
        risk_level = "LOW_RISK"

    return DefenceAuditReport(
        case_id=str(case_id),
        defensibility_score=final_score,
        risk_level=risk_level,
        total_hypotheses_tested=len(challenges),
        challenges=challenges,
        missing_evidence_summary=all_missing_items,
        bsa_compliance_status=bsa_status,
        rebuttal_action_plan=rebuttal_actions,
        epistemic_notice=EPISTEMIC_DEFENCE_NOTICE,
    )


# ── Interactive On-Demand Stress Tester ──────────────────────────────────────

def stress_test_claim(
    claim: str,
    case_context: dict[str, Any] | None = None,
    statutory_db: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    On-demand adversarial cross-examination of an arbitrary investigator theory or draft claim.
    Returns defense counter-arguments, reasonable doubts, and missing proof checklist.
    """
    c_lower = claim.lower()
    claim_hash = hashlib.md5(claim.encode()).hexdigest()[:8]

    is_mule = any(w in c_lower for w in ("mule", "transfer", "launder", "upi", "bank", "account", "received"))
    is_kingpin = any(w in c_lower for w in ("kingpin", "mastermind", "organizer", "leader", "syndicate", "head"))
    is_telecom = any(w in c_lower for w in ("call", "cdr", "tower", "phone", "mobile", "sim", "location"))
    is_forensic = any(w in c_lower for w in ("device", "evidence", "hash", "memo", "seizure", "certificate", "tamper"))

    counter_hypotheses = []
    reasonable_doubts = []
    missing_proof = []
    rebuttal_strategy = []

    if is_mule:
        counter_hypotheses.append(
            "Defense Position: The account holder was a bona fide business vendor, casual acquaintance, or "
            "compromised victim whose banking credentials/VPA were accessed without personal intent or criminal knowledge."
        )
        reasonable_doubts.extend([
            "Receipt of funds alone does not establish mens rea under BNS Section 318(4) without pre-existing conspiracy.",
            "No contemporaneous communication between the accused and complainant has been proved by the prosecution.",
        ])
        missing_proof.extend([
            "Device login IP and session identifiers linking account operation to the accused's physical device.",
            "Account Customer Application Form (CAF) verifying who originally opened and funded the account.",
        ])
        rebuttal_strategy.append("Issue Notice u/s 94 BNSS to the beneficiary bank for IP login session trails and ATM CCTV footage.")

    if is_kingpin or is_telecom:
        counter_hypotheses.append(
            "Defense Position: The phone number was subscribed under forged documents or operated by third parties; "
            "cell tower presence covers a multi-kilometer radius and does not prove personal physical involvement."
        )
        reasonable_doubts.extend([
            "A cell tower connection proves device signal range, not personal identity of the speaker.",
            "Without voice biometric analysis or contemporaneous call audio, caller identity remains uncorroborated.",
        ])
        missing_proof.extend([
            "Physical mobile handset seizure matching the IMEI with unbroken panchnama u/s 105 BNSS.",
            "Attested Section 63 BSA Certificate from the telecom service provider's nodal officer.",
        ])
        rebuttal_strategy.append("Procure subscriber CAF and attested Section 63 BSA Certificate from the telecom provider.")

    if is_forensic or not (is_mule or is_kingpin or is_telecom):
        counter_hypotheses.append(
            "Defense Position: Digital records were extracted without independent witness attestation, leaving "
            "unresolved reasonable doubt regarding digital chain of custody under Section 63 BSA, 2023."
        )
        reasonable_doubts.extend([
            "Uncertified digital evidence is vulnerable to exclusion under Section 63 BSA.",
            "Absence of independent punch witnesses on extraction leaves custody transfer unsubstantiated.",
        ])
        missing_proof.extend([
            "Dual-signed Section 63 BSA Certificate stating computer system hash and operating condition.",
            "Contemporary seizure panchnama signed by independent punch witnesses under Section 105 BNSS.",
        ])
        rebuttal_strategy.append("Obtain signed Section 63 BSA Certificate from the forensic laboratory and record panch witness statements u/s 180 BNSS.")

    return {
        "claim_id": f"st_{claim_hash}",
        "tested_claim": claim,
        "adversarial_posture": "RED_TEAM_CHALLENGE",
        "counter_hypotheses": counter_hypotheses,
        "reasonable_doubts": reasonable_doubts,
        "missing_proof_checklist": missing_proof,
        "rebuttal_recommendations": rebuttal_strategy,
        "epistemic_status": "ADVERSARIAL_SIMULATION",
        "epistemic_notice": EPISTEMIC_DEFENCE_NOTICE,
    }
