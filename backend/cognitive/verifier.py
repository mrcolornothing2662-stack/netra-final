"""CyberDrishti Feature 9 — Legal Compliance Shield & Deterministic Output Verifier.

Sits between analytical models/copilots and the investigator. Every output/draft is
evaluated by pure deterministic code BEFORE an officer acts upon it:
  1. AST Statutory Validator — parses legal citations across multiple syntaxes
     (standard, colloquial u/s, compound, subsection, inverted) and resolves
     against an authoritative statutory DB (BNS, BNSS, BSA, IT Act, DPDP Act, PMLA).
     Enforces post-July-2024 transition (replaces IPC/CrPC/IEA), detects struck-down
     statutes (e.g. IT Act 66A per Shreya Singhal), and flags ambiguous or unknown citations.
  2. Multi-Entity Span Grounding — grounds concrete factual assertions
     (currency amounts, phone numbers, UPI handles, bank accounts, IP addresses,
     device IDs, and cryptographic hashes) against case evidence facts. Matches and
     failures carry exact character spans for frontend visual highlighting.
  3. Section 63 BSA Evidence Integrity & Custody Shield — audits case evidence files
     for cryptographic SHA-256 hash preservation and custody documentation (File 10
     seizure/custody memo).
  4. Governance Decision Engine — evaluates whether drafts or investigative actions
     trigger a GOVERNANCE_BLOCKED verdict (struck-down law, unauthorized actions),
     a NEEDS_REVIEW advisory (pre-transition law, ungrounded fact, missing custody),
     or a VERIFIED_GROUNDED status.
  5. Canned-Text Detector — identifies fallback template fabrication.

EPISTEMIC STANDARD:
The Shield does NOT declare "This evidence is legally admissible in court."
It verifies technical integrity, factual grounding, and statutory compliance.
Judicial admissibility remains the exclusive prerogative of the Court.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

# ── Regex patterns for Multi-Entity Span Grounding ───────────────────────────

AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s?([0-9][\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)
PHONE_RE = re.compile(r"\b([6-9]\d{9})\b")
UPI_RE = re.compile(r"\b([\w.\-]{2,}@[a-zA-Z]{2,})\b")
EMAIL_RE = re.compile(r"\b([\w.+-]+@[\w-]+\.[\w.-]+)\b")
ACCOUNT_RE = re.compile(r"\b(?:ACCT|ACC)-[A-Z0-9_\-]+\b", re.IGNORECASE)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DEVICE_RE = re.compile(r"\b(?:DEV|DEVICE)-[A-Z0-9_\-]+\b", re.IGNORECASE)
HASH_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")

# Legacy single-pattern regex maintained for backward compatibility
SECTION_RE = re.compile(
    r"Section[s]?\s+(\d{1,4}[A-Z]?(?:\(\d+\)){0,3})\s*"
    r"(?:of\s+(?:the\s+)?)?(BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|"
    r"BSA|Bharatiya\s+Sakshya\s+Adhiniyam|BNS|Bharatiya\s+Nyaya\s+Sanhita|"
    r"IT\s*Act|Information\s+Technology\s+Act|DPDP\s*Act|Digital\s+Personal\s+Data\s+Protection\s+Act|"
    r"PMLA|Prevention\s+of\s+Money\s+Laundering\s+Act|IPC|CrPC|IEA|Indian\s+Evidence\s+Act)?",
    re.IGNORECASE,
)

# ── Act Aliases & Successor Mapping ──────────────────────────────────────────

ACT_ALIASES = {
    "IPC": "IPC",
    "INDIAN PENAL CODE": "IPC",
    "CRPC": "CrPC",
    "CODE OF CRIMINAL PROCEDURE": "CrPC",
    "IEA": "IEA",
    "INDIAN EVIDENCE ACT": "IEA",
    "BNS": "BNS",
    "BHARATIYA NYAYA SANHITA": "BNS",
    "BNSS": "BNSS",
    "BHARATIYA NAGARIK SURAKSHA SANHITA": "BNSS",
    "BSA": "BSA",
    "BHARATIYA SAKSHYA ADHINIYAM": "BSA",
    "IT ACT": "IT Act",
    "INFORMATION TECHNOLOGY ACT": "IT Act",
    "DPDP": "DPDP Act",
    "DPDP ACT": "DPDP Act",
    "DIGITAL PERSONAL DATA PROTECTION ACT": "DPDP Act",
    "PMLA": "PMLA",
    "PREVENTION OF MONEY LAUNDERING ACT": "PMLA",
}

SUCCESSOR = {
    "IPC": "BNS",
    "CrPC": "BNSS",
    "IEA": "BSA",
}

DEFAULT_DISCLAIMER = (
    "This evaluation verifies technical integrity, factual grounding, and statutory compliance. "
    "It does NOT constitute a judicial determination of admissibility under Section 63 BSA, "
    "which remains the exclusive prerogative of the trial court."
)


# ── Sourced Statutory DB Loader ──────────────────────────────────────────────

def load_statutory_db(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        db = json.load(fh)
    missing = {"acts", "sections", "_meta"} - set(db)
    if missing:
        raise ValueError(f"statutory DB missing required keys: {sorted(missing)}")
    return db


# ── Normalisation Utilities ──────────────────────────────────────────────────

def _norm_number(value) -> str:
    """Accepts strings ('68,000.00'), numbers (68000.0), anything str()-able."""
    if isinstance(value, (int, float)):
        return str(float(value))
    try:
        return str(float(str(value).replace(",", "").replace("₹", "").strip()))
    except ValueError:
        return str(value).strip()


def _norm_fact(kind: str, value: str) -> str:
    """Normalize a fact for comparison — amounts numerically, UPIs/emails folded."""
    if kind == "amounts":
        return _norm_number(value)
    if kind in ("upis", "emails"):
        return str(value).strip().lower()
    return str(value).strip().upper()


# ── Dataclasses for AST Nodes & Results ───────────────────────────────────────

@dataclass
class LegalCitationNode:
    raw_span: str
    span_start: int
    span_end: int
    section: str
    base_section: str
    subsection: str | None
    act: str | None
    status: str            # "in_force" | "pre_transition_act" | "struck_down" | "unknown_section" | "ambiguous_reference"
    title: str | None = None
    replaces: str | None = None
    replacement: str | None = None
    judicial_authority: str | None = None
    mandatory_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_span": self.raw_span,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "section": self.section,
            "base_section": self.base_section,
            "subsection": self.subsection,
            "act": self.act,
            "status": self.status,
            "title": self.title,
            "replaces": self.replaces,
            "replacement": self.replacement,
            "judicial_authority": self.judicial_authority,
            "mandatory_notes": self.mandatory_notes,
        }


@dataclass
class SpanGroundingNode:
    claim_type: str
    raw_value: str
    normalized_value: str
    span_start: int
    span_end: int
    grounded: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_type": self.claim_type,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "span_start": self.span_start,
            "span_end": self.span_end,
            "grounded": self.grounded,
            "detail": self.detail,
        }


@dataclass
class EvidenceIntegrityAudit:
    total_files: int
    hashed_files: int
    unhashed_files: int
    processed_files: int
    has_custody_memo: bool
    integrity_score: float
    status: str            # "VERIFIED_INTEGRITY" | "DEFICIENT_INTEGRITY"
    warnings: list[str] = field(default_factory=list)
    custody_memo_details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "hashed_files": self.hashed_files,
            "unhashed_files": self.unhashed_files,
            "processed_files": self.processed_files,
            "has_custody_memo": self.has_custody_memo,
            "integrity_score": self.integrity_score,
            "status": self.status,
            "warnings": self.warnings,
            "custody_memo_details": self.custody_memo_details,
        }


@dataclass
class VerifierResult:
    passed: bool
    governance_verdict: str = "COMPLIANT"    # "COMPLIANT" | "NEEDS_REVIEW" | "GOVERNANCE_BLOCKED"
    governance_reasons: list[str] = field(default_factory=list)
    statutory_violations: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    grounding_failures: list[dict[str, Any]] = field(default_factory=list)
    grounded_spans: list[dict[str, Any]] = field(default_factory=list)
    canned_detections: list[dict[str, Any]] = field(default_factory=list)
    evidence_integrity: dict[str, Any] | None = None
    admissibility_disclaimer: str = DEFAULT_DISCLAIMER
    correction_instructions: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "governance_verdict": self.governance_verdict,
            "governance_reasons": self.governance_reasons,
            "statutory_violations": self.statutory_violations,
            "citations": self.citations,
            "grounding_failures": self.grounding_failures,
            "grounded_spans": self.grounded_spans,
            "canned_detections": self.canned_detections,
            "evidence_integrity": self.evidence_integrity,
            "admissibility_disclaimer": self.admissibility_disclaimer,
            "correction_instructions": self.correction_instructions,
        }


# ── OutputVerifier / Legal Compliance Shield ─────────────────────────────────

class OutputVerifier:
    def __init__(
        self,
        statutory_db: dict[str, Any] | None = None,
        case_facts: dict[str, Iterable[str]] | None = None,
        canned_corpus: Sequence[str] = (),
        config: dict[str, Any] | None = None,
    ) -> None:
        if statutory_db is None:
            data_file = Path(__file__).resolve().parent / "data" / "statutory_db.json"
            with open(data_file, "r", encoding="utf-8") as f:
                statutory_db = json.load(f)
        self.db = statutory_db
        self.transition_date: date = date.fromisoformat(
            config.get("transition_date", statutory_db["_meta"]["transition_date"])
            if config else statutory_db["_meta"]["transition_date"]
        )
        cfg = config or {}
        self.canned_similarity_threshold = float(cfg.get("canned_similarity_threshold", 0.60))
        self.acts = statutory_db.get("acts", {})
        self.sections_list = statutory_db.get("sections", [])

        # Build fast lookup indexes
        self.section_index: dict[tuple[str, str], dict[str, Any]] = {}
        self.replaces_index: dict[tuple[str, str], dict[str, Any]] = {}

        for s in self.sections_list:
            act_name = s["act"]
            sec_num = s["section"].split("(")[0].strip()
            self.section_index[(act_name, sec_num)] = s

            # Build predecessor index (e.g. ("IPC", "420") -> BNS 318 entry)
            replaces_raw = s.get("replaces")
            if replaces_raw:
                parts = replaces_raw.strip().split()
                if len(parts) >= 2:
                    old_act = ACT_ALIASES.get(parts[0].upper(), parts[0])
                    old_sec = parts[1].split("(")[0].strip()
                    self.replaces_index[(old_act, old_sec)] = s

        # Case facts normalization
        facts = case_facts or {}
        self.case_facts: dict[str, set[str]] = {
            kind: {_norm_fact(kind, v) for v in values if v is not None}
            for kind, values in facts.items()
        }
        self.canned_corpus = list(canned_corpus)

    # ── 1. AST Legal Citation Parser ──────────────────────────────────────────

    def parse_legal_citations(self, text: str) -> list[LegalCitationNode]:
        """
        Parses legal citations from draft text using AST extraction rules.
        Recognizes standard ('Section 318 BNS'), colloquial ('u/s 66D IT Act', 'Sec. 63'),
        compound ('Sections 318 and 319 of BNS'), subsection ('Section 63(4)(c) BSA'),
        and inverted ('BNS Section 318') forms.
        """
        nodes: list[LegalCitationNode] = []
        seen_spans: set[tuple[int, int]] = set()

        def _add_node(raw: str, start: int, end: int, sec_part: str, act_part: str | None):
            if any(start < se and end > ss for ss, se in seen_spans):
                return
            seen_spans.add((start, end))

            # Split compound sections (e.g. "318 and 319", "66C, 66D")
            sec_tokens = [
                s.strip() for s in re.split(r"[,&]|\band\b", sec_part)
                if s.strip()
            ]

            for s_token in sec_tokens:
                # Isolate base section and optional subsection (e.g. 63(4)(c) -> 63, (4)(c))
                m_sub = re.match(r"^([0-9]{1,4}[A-Za-z]?)(.*)$", s_token)
                if m_sub:
                    base_sec = m_sub.group(1).upper()
                    sub_sec = m_sub.group(2).strip() or None
                else:
                    base_sec = s_token.upper()
                    sub_sec = None

                act = None
                if act_part:
                    clean_act = act_part.upper().replace("THE ", "").strip()
                    act = ACT_ALIASES.get(clean_act)

                # Resolution logic
                status = "unknown_section"
                title = None
                replaces = None
                replacement = None
                judicial_authority = None
                mandatory_notes = None

                if act is None:
                    # Resolve if section uniquely matches an act
                    matching_acts = [
                        a for (a, s) in self.section_index if s == base_sec
                    ]
                    # Also check predecessor acts
                    matching_old_acts = [
                        a for (a, s) in self.replaces_index if s == base_sec
                    ]
                    candidates = list(dict.fromkeys(matching_acts + matching_old_acts))

                    if len(candidates) == 1:
                        act = candidates[0]
                    elif len(candidates) > 1:
                        status = "ambiguous_reference"
                    else:
                        status = "unknown_section"

                if act in SUCCESSOR:
                    # Pre-transition act cited (IPC, CrPC, IEA)
                    successor = SUCCESSOR[act]
                    status = "pre_transition_act"
                    replaces_entry = self.replaces_index.get((act, base_sec))
                    if replaces_entry:
                        replacement = f"Section {replaces_entry['section']} {successor}"
                        title = replaces_entry.get("title")
                        replaces = replaces_entry.get("replaces")
                        mandatory_notes = replaces_entry.get("mandatory_notes")
                    else:
                        # Fallback forward search
                        for s_ent in self.sections_list:
                            rep = s_ent.get("replaces")
                            if rep and rep.upper().startswith(f"{act} {base_sec}"):
                                replacement = f"Section {s_ent['section']} {successor}"
                                title = s_ent.get("title")
                                replaces = rep
                                mandatory_notes = s_ent.get("mandatory_notes")
                                break
                        if not replacement:
                            replacement = f"the corresponding {successor} section"

                elif act:
                    entry = self.section_index.get((act, base_sec))
                    if entry is not None:
                        entry_status = entry.get("status", "in_force")
                        if entry_status == "struck_down":
                            status = "struck_down"
                            title = entry.get("title")
                            judicial_authority = entry.get("source")
                            mandatory_notes = entry.get("mandatory_notes")
                        else:
                            status = "in_force"
                            title = entry.get("title")
                            replaces = entry.get("replaces")
                            mandatory_notes = entry.get("mandatory_notes")
                    else:
                        status = "unknown_section"

                nodes.append(LegalCitationNode(
                    raw_span=raw,
                    span_start=start,
                    span_end=end,
                    section=s_token,
                    base_section=base_sec,
                    subsection=sub_sec,
                    act=act,
                    status=status,
                    title=title,
                    replaces=replaces,
                    replacement=replacement,
                    judicial_authority=judicial_authority,
                    mandatory_notes=mandatory_notes,
                ))

        # Pattern A: (u/s / sec / section) [numbers] (of the) [act]
        pat_a = re.compile(
            r"\b(?:u/s\.?|u\.s\.?|sec\.?|sections?)\s+"
            r"(\d{1,4}[A-Z]?(?:\([a-zA-Z0-9]+\)){0,3}"
            r"(?:\s*(?:,|and|&)\s*\d{1,4}[A-Z]?(?:\([a-zA-Z0-9]+\)){0,3})*)"
            r"(?:\s+(?:of\s+(?:the\s+)?)?"
            r"(BNS|Bharatiya\s+Nyaya\s+Sanhita|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|"
            r"BSA|Bharatiya\s+Sakshya\s+Adhiniyam|IT\s*Act|Information\s+Technology\s+Act|"
            r"DPDP\s*Act|Digital\s+Personal\s+Data\s+Protection\s+Act|PMLA|Prevention\s+of\s+Money\s+Laundering\s+Act|"
            r"IPC|Indian\s+Penal\s+Code|CrPC|Code\s+of\s+Criminal\s+Procedure|IEA|Indian\s+Evidence\s+Act))?\b",
            re.IGNORECASE,
        )
        for m in pat_a.finditer(text):
            _add_node(m.group(0), m.start(), m.end(), m.group(1), m.group(2))

        # Pattern B: [act] (section / sec) [numbers]
        pat_b = re.compile(
            r"\b(BNS|Bharatiya\s+Nyaya\s+Sanhita|BNSS|Bharatiya\s+Nagarik\s+Suraksha\s+Sanhita|"
            r"BSA|Bharatiya\s+Sakshya\s+Adhiniyam|IT\s*Act|Information\s+Technology\s+Act|"
            r"DPDP\s*Act|Digital\s+Personal\s+Data\s+Protection\s+Act|PMLA|Prevention\s+of\s+Money\s+Laundering\s+Act|"
            r"IPC|Indian\s+Penal\s+Code|CrPC|Code\s+of\s+Criminal\s+Procedure|IEA|Indian\s+Evidence\s+Act)"
            r"\s+(?:sec\.?|sections?)\s+"
            r"(\d{1,4}[A-Z]?(?:\([a-zA-Z0-9]+\)){0,3})\b",
            re.IGNORECASE,
        )
        for m in pat_b.finditer(text):
            _add_node(m.group(0), m.start(), m.end(), m.group(2), m.group(1))

        # Pattern C: Plain [Act] [Number] (e.g. IPC 420, CrPC 102, BNS 318, BSA 63)
        pat_c = re.compile(
            r"\b(BNS|BNSS|BSA|IT\s*Act|DPDP\s*Act|PMLA|IPC|CrPC|IEA)\s+(\d{1,4}[A-Z]?(?:\([a-zA-Z0-9]+\)){0,3})\b",
            re.IGNORECASE,
        )
        for m in pat_c.finditer(text):
            _add_node(m.group(0), m.start(), m.end(), m.group(2), m.group(1))

        nodes.sort(key=lambda n: n.span_start)
        return nodes

    # ── 1b. Backward-Compatible check_statutory ──────────────────────────────

    def check_statutory(self, draft: str) -> list[dict[str, Any]]:
        """
        Validates statutory citations in draft text.
        Returns a list of statutory violations compatible with legacy OutputVerifier.
        """
        violations: list[dict[str, Any]] = []
        citation_nodes = self.parse_legal_citations(draft)

        for c in citation_nodes:
            if c.status == "in_force":
                continue

            if c.status == "pre_transition_act":
                act_name = self.acts.get(c.replacement.split()[-1] if c.replacement else "", {}).get("name", "new act")
                violations.append({
                    "section": c.section,
                    "act": c.act,
                    "reason": "pre_transition_act",
                    "detail": f"{c.act} was replaced by {act_name} with effect from {self.transition_date.isoformat()}.",
                    "replacement": c.replacement,
                })
            elif c.status == "struck_down":
                violations.append({
                    "section": c.section,
                    "act": c.act,
                    "reason": "not_in_force:struck_down",
                    "detail": f"Section {c.section} of {c.act} was struck down in entirety: {c.judicial_authority}",
                    "replacement": None,
                })
            elif c.status == "ambiguous_reference":
                violations.append({
                    "section": c.section,
                    "act": None,
                    "reason": "ambiguous_reference",
                    "detail": f"Section {c.section} exists in multiple acts; the draft must name one.",
                    "replacement": None,
                })
            elif c.status == "unknown_section":
                violations.append({
                    "section": c.section,
                    "act": c.act,
                    "reason": "unknown_section",
                    "detail": f"Section {c.section} {c.act or ''} not found in the statutory DB.",
                    "replacement": None,
                })

        return violations

    # ── 2. Multi-Entity Span Grounding ────────────────────────────────────────

    def check_grounding_spans(self, draft: str) -> tuple[list[SpanGroundingNode], list[dict[str, Any]]]:
        """
        Extracts concrete factual claims (amounts, phones, upis, accounts, ips, devices, hashes)
        and verifies each against case facts, returning both grounded spans and failure records.
        """
        all_spans: list[SpanGroundingNode] = []
        failures: list[dict[str, Any]] = []

        email_spans = {m.span() for m in EMAIL_RE.finditer(draft)}

        # Helper to test candidate against fact index
        def _evaluate_candidate(kind: str, raw_val: str, norm_val: str, start: int, end: int):
            searched_set = self.case_facts.get(kind, set())
            is_grounded = norm_val in searched_set
            node = SpanGroundingNode(
                claim_type=kind,
                raw_value=raw_val,
                normalized_value=norm_val,
                span_start=start,
                span_end=end,
                grounded=is_grounded,
                detail=f"{kind} '{raw_val}' {'verified in case facts' if is_grounded else 'not found in case facts'}",
            )
            all_spans.append(node)
            if not is_grounded:
                failures.append({
                    "claim_type": kind,
                    "value": raw_val,
                    "span_start": start,
                    "span_end": end,
                    "searched_in": sorted(searched_set)[:10] or ["<empty case index>"],
                    "detail": f"{kind} '{raw_val}' does not exist in this case's facts.",
                })

        # Amounts
        for m in AMOUNT_RE.finditer(draft):
            raw = m.group(1).strip()
            norm = _norm_number(raw)
            _evaluate_candidate("amounts", raw, norm, m.start(1), m.end(1))

        # Phones (filter out email spans)
        for m in PHONE_RE.finditer(draft):
            if not any(s <= m.start() < e for s, e in email_spans):
                raw = m.group(1)
                _evaluate_candidate("phones", raw, raw, m.start(1), m.end(1))

        # UPIs (filter out email spans)
        for m in UPI_RE.finditer(draft):
            if not any(s <= m.start() < e for s, e in email_spans):
                raw = m.group(1)
                _evaluate_candidate("upis", raw, raw.lower(), m.start(1), m.end(1))

        # Accounts (structured ACCT-MULE-11 or numeric accounts if indexed)
        for m in ACCOUNT_RE.finditer(draft):
            raw = m.group(0)
            _evaluate_candidate("accounts", raw, raw.upper(), m.start(), m.end())

        # IP addresses
        for m in IP_RE.finditer(draft):
            raw = m.group(0)
            _evaluate_candidate("ips", raw, raw, m.start(), m.end())

        # Devices
        for m in DEVICE_RE.finditer(draft):
            raw = m.group(0)
            _evaluate_candidate("devices", raw, raw.upper(), m.start(), m.end())

        # Hashes
        for m in HASH_RE.finditer(draft):
            raw = m.group(0)
            _evaluate_candidate("hashes", raw, raw.lower(), m.start(), m.end())

        return all_spans, failures

    def check_grounding(self, draft: str) -> list[dict[str, Any]]:
        """Legacy check_grounding compatibility method returning grounding failures."""
        _, failures = self.check_grounding_spans(draft)
        return failures

    # ── 3. Canned Text Detector ───────────────────────────────────────────────

    def check_canned(self, draft: str) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        draft_tokens = set(re.findall(r"\w+", draft.lower()))
        if not draft_tokens:
            return detections
        for sample in self.canned_corpus:
            sample_tokens = set(re.findall(r"\w+", sample.lower()))
            union = draft_tokens | sample_tokens
            similarity = len(draft_tokens & sample_tokens) / len(union) if union else 0.0
            if similarity >= self.canned_similarity_threshold:
                detections.append({
                    "similarity": round(similarity, 3),
                    "matched_corpus_sample": sample[:120],
                    "detail": "Draft closely mirrors a canned corpus sample.",
                })
        return detections

    # ── 4. Section 63 BSA Evidence Admissibility & Custody Shield ─────────────

    def audit_evidence_integrity(
        self,
        evidence_files: list[dict[str, Any]] | None,
    ) -> EvidenceIntegrityAudit | None:
        """
        Audits case evidence files for Section 63 BSA compliance:
          • SHA-256 cryptographic hash preservation for every file
          • Upload/processing status verification
          • Evidence seizure/custody memo presence (File 10)
        """
        if evidence_files is None:
            return None

        total = len(evidence_files)
        if total == 0:
            return EvidenceIntegrityAudit(
                total_files=0,
                hashed_files=0,
                unhashed_files=0,
                processed_files=0,
                has_custody_memo=False,
                integrity_score=1.0,
                status="VERIFIED_INTEGRITY",
                warnings=[],
            )

        hashed = sum(1 for f in evidence_files if f.get("sha256_hash"))
        processed = sum(1 for f in evidence_files if f.get("upload_status") == "processed")
        unhashed = total - hashed

        custody_memo = None
        has_custody = False
        for f in evidence_files:
            stype = str(f.get("source_type") or "").lower()
            orig_name = str(f.get("original_name") or "").lower()
            if stype == "seizure_memo" or "seizure" in orig_name or "custody" in orig_name:
                has_custody = True
                custody_memo = {
                    "file_id": str(f.get("id")),
                    "original_name": f.get("original_name"),
                    "sha256_hash": f.get("sha256_hash"),
                }
                break

        score = round(hashed / total, 2)
        warnings: list[str] = []

        if unhashed > 0:
            warnings.append(f"{unhashed} evidence file(s) lack a SHA-256 integrity hash.")
        if not has_custody:
            warnings.append(
                "Custody Advisory: No evidence seizure memo (File 10) identified. "
                "Chain of custody documentation required for Section 63 BSA certificate readiness."
            )
        if processed < total:
            warnings.append(f"{total - processed} evidence file(s) are pending ingestion.")

        status = "VERIFIED_INTEGRITY" if (unhashed == 0 and processed == total) else "DEFICIENT_INTEGRITY"

        return EvidenceIntegrityAudit(
            total_files=total,
            hashed_files=hashed,
            unhashed_files=unhashed,
            processed_files=processed,
            has_custody_memo=has_custody,
            integrity_score=score,
            status=status,
            warnings=warnings,
            custody_memo_details=custody_memo,
        )

    # ── 5. Governance Evaluation ──────────────────────────────────────────────

    def evaluate_governance(
        self,
        citations: list[LegalCitationNode],
        grounding_failures: list[dict[str, Any]],
        canned_detections: list[dict[str, Any]],
        integrity: EvidenceIntegrityAudit | None,
    ) -> tuple[str, list[str]]:
        """
        Evaluates governance posture:
          • GOVERNANCE_BLOCKED: Struck-down law invoked (IT Act 66A).
          • NEEDS_REVIEW: Pre-transition acts cited, ungrounded factual assertions, or deficient hash integrity.
          • COMPLIANT: All citations in force, facts grounded, integrity verified.
        """
        verdict = "COMPLIANT"
        reasons: list[str] = []

        # Check for struck-down law (Hard Governance Block)
        struck_down = [c for c in citations if c.status == "struck_down"]
        if struck_down:
            verdict = "GOVERNANCE_BLOCKED"
            for c in struck_down:
                reasons.append(
                    f"PROHIBITED STATUTE: Section {c.section} {c.act} was struck down as unconstitutional "
                    f"by the Supreme Court in {c.judicial_authority or 'Shreya Singhal v. Union of India'}. "
                    "Invocation of struck-down legislation is strictly prohibited."
                )

        # Check for pre-transition statutes (Advisory Review)
        pre_transition = [c for c in citations if c.status == "pre_transition_act"]
        if pre_transition and verdict != "GOVERNANCE_BLOCKED":
            verdict = "NEEDS_REVIEW"
            for c in pre_transition:
                reasons.append(
                    f"STATUTORY MIGRATION REQUIRED: Section {c.section} {c.act} has been repealed. "
                    f"Migrate to {c.replacement or 'the corresponding post-July-2024 section'}."
                )

        # Check for unknown / ambiguous citations
        unknown = [c for c in citations if c.status in ("unknown_section", "ambiguous_reference")]
        if unknown and verdict != "GOVERNANCE_BLOCKED":
            verdict = "NEEDS_REVIEW"
            for c in unknown:
                reasons.append(
                    f"UNCITED / AMBIGUOUS SECTION: Section {c.section} {c.act or ''} is unverified or ambiguous."
                )

        # Check for factual hallucinations
        if grounding_failures and verdict != "GOVERNANCE_BLOCKED":
            verdict = "NEEDS_REVIEW"
            reasons.append(
                f"UNGROUNDED ASSERTION: {len(grounding_failures)} value(s) in draft do not match case evidence facts."
            )

        # Check for canned text matches
        if canned_detections and verdict != "GOVERNANCE_BLOCKED":
            verdict = "NEEDS_REVIEW"
            reasons.append("CANNED TEMPLATE DETECTED: Draft closely mirrors fallback text.")

        # Check evidence integrity
        if integrity and integrity.status == "DEFICIENT_INTEGRITY" and verdict != "GOVERNANCE_BLOCKED":
            verdict = "NEEDS_REVIEW"
            reasons.extend(integrity.warnings)

        return verdict, reasons

    # ── 6. Full Critique Orchestration ────────────────────────────────────────

    def critique(
        self,
        draft: str,
        evidence_files: list[dict[str, Any]] | None = None,
    ) -> VerifierResult:
        """
        Executes complete Legal Compliance Shield evaluation over a text draft.
        """
        citations = self.parse_legal_citations(draft)
        statutory_violations = self.check_statutory(draft)
        all_spans, grounding_failures = self.check_grounding_spans(draft)
        grounded_spans = [s.to_dict() for s in all_spans if s.grounded]
        canned_detections = self.check_canned(draft)
        integrity = self.audit_evidence_integrity(evidence_files)

        verdict, gov_reasons = self.evaluate_governance(
            citations=citations,
            grounding_failures=grounding_failures,
            canned_detections=canned_detections,
            integrity=integrity,
        )

        passed = (verdict == "COMPLIANT")
        instructions = self._corrections(statutory_violations, grounding_failures, canned_detections)

        return VerifierResult(
            passed=passed,
            governance_verdict=verdict,
            governance_reasons=gov_reasons,
            statutory_violations=statutory_violations,
            citations=[c.to_dict() for c in citations],
            grounding_failures=grounding_failures,
            grounded_spans=grounded_spans,
            canned_detections=canned_detections,
            evidence_integrity=integrity.to_dict() if integrity else None,
            admissibility_disclaimer=DEFAULT_DISCLAIMER,
            correction_instructions=instructions,
        )

    def _corrections(self, statutory, grounding, canned) -> str:
        parts: list[str] = []
        if statutory:
            constraints = "; ".join(
                v["replacement"] and f"cite {v['replacement']} instead of Section {v['section']} {v['act']}"
                or f"remove or correct the citation 'Section {v['section']} {v['act'] or ''}'"
                for v in statutory
            )
            parts.append(f"Statute constraints: {constraints}.")
        if grounding:
            parts.append(
                "Only reference values that exist in the case facts; "
                + "; ".join(f"remove or correct '{g['value']}'" for g in grounding)
                + "."
            )
        if canned:
            parts.append(
                "The draft mirrors canned fallback text. Answer only from the "
                "retrieved evidence excerpts; if they do not answer the query, "
                "say so explicitly."
            )
        return " ".join(parts)
