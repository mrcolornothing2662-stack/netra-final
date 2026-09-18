from __future__ import annotations
"""
CyberDrishti AI — Upgraded Deterministic & Normalized Extractors (Phase 5)
Handles:
- Spaced and hyphenated phone numbers (+91 98765 43210, 98765-12345).
- OCR character confusion (e.g. O for 0, l for 1, SBINOOO1234).
- Indic colloquial currency terms (hazar, lakh, peti, crore, khokha).
- Indian Scheduled Banks and Cooperative Banks.
- High-signal cyber fraud modus operandi keywords.
- Person names with titles/cues.
"""
import re
from dataclasses import dataclass
from typing import Any, Optional, Union


# ── Suffix multiplier map ─────────────────────────────────────────────────────

_SUFFIX_MAP: dict[str, float] = {
    "k":       1_000.0,
    "K":       1_000.0,
    "hazar":   1_000.0,
    "hazar ":  1_000.0,
    "lakh":    1_00_000.0,
    "L":       1_00_000.0,
    "peti":    1_00_000.0,
    "crore":   1_00_00_000.0,
    "Cr":      1_00_00_000.0,
    "khokha":  1_00_00_000.0,
}


def normalise_amount(numeric_str: str, suffix: Optional[str]) -> Optional[float]:
    """Convert amount string + optional suffix to a canonical float (INR)."""
    if not numeric_str:
        return None
    try:
        # Normalize OCR typo: letter O/o to 0
        clean_num = (
            numeric_str.replace(",", "")
            .replace("O", "0")
            .replace("o", "0")
            .replace("l", "1")
            .strip()
        )
        val = float(clean_num)
        s = (suffix or "").lower().strip()
        multiplier = _SUFFIX_MAP.get(s, 1.0)
        return val * multiplier
    except ValueError:
        return None


def normalise_phone(raw: str) -> str:
    """Normalize phone number to E.164-style Indian standard (+91XXXXXXXXXX)."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f"+91{digits}"
    elif len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return raw.strip()


# ── Regex Patterns ─────────────────────────────────────────────────────────────

# Phone: allows internal spaces or hyphens, masked synthetic format (+91-98XXXX1201), or standard 10-digit
PHONE_RE = re.compile(
    r'(?:\+91[\s\-]?)?[6-9]\d(?:X{4}|\d{4})[\s\-]?\d{4}\b|'
    r'(?:\+91[\s\-]?)?[6-9]\d{4}[\s\-]?\d{5}\b|'
    r'(?:\+91[\s\-]?)?[6-9]\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b|'
    r'(?:\+91\s?)?[6-9]\d{9}\b',
    re.IGNORECASE,
)

# Structured phone identifiers (e.g. PH-002, PH-003, PHONE-01)
STRUCTURED_PHONE_RE = re.compile(r'(?<![\w\-])(?:PH|PHONE)-[A-Z0-9_\-]{2,32}\b', re.IGNORECASE)

# Cell-site / Tower identifiers (e.g. CHD-CELL-17, MOH-CELL-04)
CELL_TOWER_RE = re.compile(r'(?<![\w\-])[A-Z]{2,6}-CELL-\d{1,4}\b', re.IGNORECASE)

# Device identifiers (e.g. DEV-002, DEVICE-01)
DEVICE_RE = re.compile(r'(?<![\w\-])(?:DEV|DEVICE)-[A-Z0-9_\-]{2,32}\b', re.IGNORECASE)

# Chat / Conversation identifiers (e.g. CHAT-001, CONV-01)
CHAT_RE = re.compile(r'(?<![\w\-])(?:CHAT|CONV)-[A-Z0-9_\-]{2,32}\b', re.IGNORECASE)

# Transaction reference identifiers (e.g. TXN-005, TX-01)
TXN_RE = re.compile(r'(?<![\w\-])(?:UPI-TXN|TXN|TX)-[A-Z0-9_\-]{2,32}\b', re.IGNORECASE)

# UPI Virtual Payment Address (e.g. name@okhdfc, 9876543210@paytm)
UPI_RE = re.compile(r'\b[\w.\-]{2,256}@[a-zA-Z]{2,64}\b')

# Account numbers: 9-18 continuous digits or structured account codes (e.g. ACCT-MULE-11, ACC-001)
ACCOUNT_RE = re.compile(r'\b\d{9,18}\b|\b[0-9Ool]{11,18}\b|(?<![\w\-])(?:ACCT|ACC)-[A-Z0-9_\-]{3,32}\b', re.IGNORECASE)

# Amounts: standard currency symbols, numbers, and colloquial multipliers
AMOUNT_RE = re.compile(
    r'(?:₹|Rs\.?|INR)\s?([0-9Ool]{1,3}(?:,[0-9Ool]{2,3})*(?:\.\d{1,2})?)\s?(k|K|hazar|lakh|L|peti|crore|Cr|khokha)?\b'
    r'|\b([1-9][0-9Ool]{1,3})\s?(k|K|hazar|lakh|L|peti|crore|Cr|khokha)\b',
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

# IFSC: 4 letters + 0 or O + 6 alphanumeric
IFSC_RE = re.compile(r'\b[A-Z]{4}[0O][A-Z0-9]{6}\b')

# OTP: 4-8 digits near OTP/code keywords
OTP_RE = re.compile(r'\b(?:OTP|code|pin)\D*(\d{4,8})\b', re.IGNORECASE)

URL_RE = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+|bit\.ly/[^\s<>"]+', re.IGNORECASE)

# Indian Banks (Major PSUs, Private, Cooperative, Payments)
BANK_RE = re.compile(
    r'\b(?:State\s+Bank\s+of\s+India|SBI|HDFC\s+Bank|HDFC|ICICI\s+Bank|ICICI|Axis\s+Bank|'
    r'Punjab\s+National\s+Bank|PNB|Canara\s+Bank|Bank\s+of\s+Baroda|BOB|Union\s+Bank\s+of\s+India|'
    r'Kotak\s+Mahindra\s+Bank|IndusInd\s+Bank|Yes\s+Bank|Pragati\s+Cooperative\s+Bank|'
    r'Paytm\s+Payments\s+Bank|Airtel\s+Payments\s+Bank)\b',
    re.IGNORECASE,
)

# Cyber Fraud Indicators
KEYWORD_RE = re.compile(
    r'\b(?:digital\s+arrest|customs\s+clearance|customs|drugs\s+in\s+parcel|MDMA|CBI\s+verification|CBI|'
    r'Cyber\s+Crime\s+Cell|electricity\s+power\s+will\s+be\s+disconnected|disconnected|penalty|'
    r'KYC\s+expired|SIM\s+blocked|FIR\s+\d+/\d+|FIR|VIP\s+Level|task\s+completed|'
    r'refundable\s+tax|sextortion|loan\s+app|recovery\s+agent)\b',
    re.IGNORECASE,
)

# Person Name Cues — generic title/honorific heuristic only.
# Hardcoded demo person-names were removed: they would auto-tag known demo names
# (e.g. "Ankita Verma") as PER inside real cases, fabricating entities that aren't
# grounded in the evidence. Broader PER recall is deferred to a later sprint.
PER_RE = re.compile(
    r'\b(?:DSP|Inspector|Officer|Dr\.|Mr\.|Mrs\.|Ms\.)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b',
    re.IGNORECASE,
)


@dataclass
class Extraction:
    entity_type:  str
    raw_value:    str
    norm_value:   Union[str, float, None]
    span_start:   int
    span_end:     int
    extractor:    str = "regex_upgraded"
    confidence:   float = 1.0


class RegexExtractor:
    """Deterministic, normalized regex extractor for Indian cyber fraud investigations."""

    def extract(self, text: str) -> list[Extraction]:
        results: list[Extraction] = []
        seen_spans: set[tuple[int, int]] = set()

        def _add(entity_type: str, raw: str, norm: Any, start: int, end: int, conf: float = 1.0):
            for s, e in list(seen_spans):
                if start < e and end > s:
                    if (end - start) <= (e - s):
                        return
                    seen_spans.discard((s, e))
            seen_spans.add((start, end))
            results.append(Extraction(
                entity_type=entity_type,
                raw_value=raw,
                norm_value=norm,
                span_start=start,
                span_end=end,
                extractor="regex_upgraded",
                confidence=conf,
            ))

        # 1. URL
        for m in URL_RE.finditer(text):
            _add("URL", m.group(), m.group().lower(), m.start(), m.end())

        # 2. EMAIL (before UPI)
        for m in EMAIL_RE.finditer(text):
            _add("EMAIL", m.group(), m.group().lower(), m.start(), m.end())

        # 3. UPI
        for m in UPI_RE.finditer(text):
            raw = m.group()
            if any(raw.lower() in str(e.raw_value).lower() for e in results if e.entity_type == "EMAIL"):
                continue
            _add("UPI", raw, raw.lower().strip(), m.start(), m.end())

        # 4. PHONE (matches standard + spaced/hyphenated + structured PH-xxx)
        for m in PHONE_RE.finditer(text):
            raw = m.group()
            _add("PHONE", raw, normalise_phone(raw), m.start(), m.end())
        for m in STRUCTURED_PHONE_RE.finditer(text):
            raw = m.group()
            _add("PHONE", raw, raw.upper().strip(), m.start(), m.end())

        # 4b. DEVICE
        for m in DEVICE_RE.finditer(text):
            raw = m.group()
            _add("DEVICE", raw, raw.upper().strip(), m.start(), m.end())

        # 4c. CHAT
        for m in CHAT_RE.finditer(text):
            raw = m.group()
            _add("CHAT", raw, raw.upper().strip(), m.start(), m.end())

        # 4d. TRANSACTION
        for m in TXN_RE.finditer(text):
            raw = m.group()
            _add("TRANSACTION", raw, raw.upper().strip(), m.start(), m.end())

        # 4e. CELL_TOWER
        for m in CELL_TOWER_RE.finditer(text):
            raw = m.group()
            _add("CELL_TOWER", raw, raw.upper().strip(), m.start(), m.end())

        # 5. IFSC (normalizes OCR O -> 0)
        for m in IFSC_RE.finditer(text):
            raw = m.group()
            norm = raw[:4].upper() + "0" + raw[5:].upper().replace("O", "0")
            _add("IFSC", raw, norm, m.start(), m.end())

        # 6. BANK
        for m in BANK_RE.finditer(text):
            raw = m.group()
            _add("BANK", raw, raw.strip(), m.start(), m.end())

        # 7. ACCOUNT (after PHONE and IFSC to avoid overlap)
        for m in ACCOUNT_RE.finditer(text):
            raw = m.group()
            raw_upper = raw.upper()
            if raw_upper.startswith("ACCT-") or raw_upper.startswith("ACC-"):
                _add("ACCOUNT", raw, raw_upper.strip(), m.start(), m.end())
                continue
            norm_acc = raw.replace("O", "0").replace("o", "0").replace("l", "1")
            if not norm_acc.isdigit():
                continue
            # Skip if already claimed by PHONE
            if len(raw) == 10 and any(raw in e.raw_value for e in results if e.entity_type == "PHONE"):
                continue
            _add("ACCOUNT", raw, norm_acc, m.start(), m.end())

        # 8. AMOUNT
        for m in AMOUNT_RE.finditer(text):
            raw_match = m.group()
            numeric = m.group(1) or m.group(3)
            suffix = m.group(2) or m.group(4)
            if not numeric:
                continue
            norm = normalise_amount(numeric, suffix)
            if norm is None:
                continue
            _add("AMOUNT", raw_match.strip(), norm, m.start(), m.end())

        # 9. OTP
        for m in OTP_RE.finditer(text):
            digits = m.group(1) if m.lastindex else m.group()
            _add("OTP", digits, digits, m.start(), m.end())

        # 10. KEYWORD
        for m in KEYWORD_RE.finditer(text):
            raw = m.group()
            _add("KEYWORD", raw, raw.strip(), m.start(), m.end())

        # 11. PER (Person Names)
        for m in PER_RE.finditer(text):
            raw = m.group()
            if raw.lower() not in {"call", "line", "date", "status", "success", "failed", "amount", "bank", "account", "transfer", "verification", "digital", "arrest"}:
                _add("PER", raw, raw.strip(), m.start(), m.end())

        # 12. IP
        for m in IP_RE.finditer(text):
            raw = m.group()
            if all(0 <= int(o) <= 255 for o in raw.split(".")):
                _add("IP", raw, raw, m.start(), m.end())

        results.sort(key=lambda x: x.span_start)
        return results


_extractor = RegexExtractor()


def extract(text: str) -> list[Extraction]:
    return _extractor.extract(text)
