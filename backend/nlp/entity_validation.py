from __future__ import annotations
"""
CyberDrishti AI — Canonical Entity Validation Firewall
Single, authoritative gatekeeper that validates candidate entity predictions
(Regex, CRF, HingBERT, spaCy, Hinglish NER) before persistence into PostgreSQL.
"""
import re
from typing import Any

# Generic UI terms, document labels, and uninformative placeholders
_GENERIC_NON_ENTITIES = {
    "UNKNOWN",
    "UNK",
    "N/A",
    "NA",
    "NULL",
    "NONE",
    "SYSTEM",
    "UNKNOWN SENDER",
    "UNKNOWN PARTICIPANT",
    "RECEIVED",
    "SENT",
    "CONFIRMED",
    "COMMUNICATION",
    "NETWORK",
    "NETWORK ANALYSIS",
    "ANALYSIS",
    "CONVERSATION",
    "PARTICIPANTS",
    "PARTICIPANT",
    "MESSAGE",
    "MESSAGES",
    "TRANSACTION",
    "TRANSACTIONS",
    "EVIDENCE",
    "DOCUMENT",
    "SUMMARY",
    "CALL LOG",
    "CALLS",
    "DETAILS",
    "STATUS",
    "VERIFICATION",
    "BANK",
    "POLICE",
    "POLICE RECORD",
    "SYNTHETIC",
    "TRAINING DATA",
    "DISCLAIMER",
    "SUCCESS",
    "FAILED",
    "PENDING",
    "COMPLETED",
}

# Known countries/states/cities often mislabeled by statistical NER as PERSON
_COMMON_LOCATIONS = {
    "INDIA", "DELHI", "MUMBAI", "CHANDIGARH", "MOHALI", "BENGALURU", "BANGALORE",
    "HYDERABAD", "KOLKATA", "CHENNAI", "PUNE", "AHMEDABAD", "JAIPUR",
    "SURAT", "LUCKNOW", "KANPUR", "NAGPUR", "INDORE", "THANE", "BHOPAL",
    "VISAKHAPATNAM", "PATNA", "VADODARA", "GHAZIABAD", "LUDHIANA", "AGRA",
    "NASHIK", "FARIDABAD", "MEERUT", "RAJKOT", "VARANASI", "SRINAGAR",
    "AMRITSAR", "ALLAHABAD", "RANCHI", "HOWRAH", "COIMBATORE", "JABALPUR",
    "GWALIOR", "VIJAYAWADA", "JODHPUR", "MADURAI", "RAIPUR", "KOTA",
    "GUWAHATI", "CHANDIGARH, INDIA", "NEW DELHI", "NOIDA", "GURUGRAM",
    "GURGAON", "PUNJAB", "HARYANA", "MAHARASHTRA", "UTTAR PRADESH",
}


def _looks_like_date_or_time(value: str) -> bool:
    value = value.strip()
    patterns = (
        r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}",
        r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}",
        r"^\d{1,2}:\d{2}(?::\d{2})?$",
        r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}",
    )
    return any(re.match(pattern, value) for pattern in patterns)


def _looks_like_ipv4(value: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value.strip()))


def _looks_like_phone(value: str) -> bool:
    if _looks_like_ipv4(value):
        return False
    compact = re.sub(r"[\s().-]", "", value)
    if compact.startswith("+") and sum(c.isdigit() for c in compact) >= 8:
        return True
    digits = sum(c.isdigit() for c in value)
    return digits >= 10


def _looks_like_identifier(value: str) -> bool:
    digits = sum(c.isdigit() for c in value)
    if digits >= 4 and digits / max(len(value), 1) > 0.65:
        return True
    return False


def _looks_like_structured_account(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"(?:ACCT|ACC)-[A-Z0-9_\-]+", value))


def _looks_like_structured_phone(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"(?:PH|PHONE)-[A-Z0-9_\-]+", value))


def _looks_like_structured_device(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"(?:DEV|DEVICE)-[A-Z0-9_\-]+", value))


def _looks_like_structured_chat(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"(?:CHAT|CONV)-[A-Z0-9_\-]+", value))


def _looks_like_structured_txn(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"(?:TXN|TX)-[A-Z0-9_\-]+", value))


def _looks_like_structured_cell_tower(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"[A-Z]{2,6}-CELL-\d{1,4}", value))


def validate_entity_candidate(
    entity_type: str,
    raw_value: Any,
) -> bool:
    """
    Final semantic gate before an extracted candidate can be
    materialised as an Entity / EntityMention in PostgreSQL.
    """
    value = str(raw_value or "").strip()
    if not value or len(value) < 2:
        return False

    etype = str(entity_type or "").upper().strip()
    if not etype:
        return False

    normalized = value.upper().strip(" /.,:;")

    # Evidence inventory identifiers (e.g. EVD-BANK-001) are custody/exhibit IDs, not entities
    if "EVD-" in normalized:
        return False

    # Synthetic hash must not be materialised as an entity
    if "TEST-HASH" in normalized or "DO-NOT-TREAT-AS-REAL" in normalized:
        return False

    # Never materialise placeholder or generic document terms
    if normalized in _GENERIC_NON_ENTITIES:
        return False

    # Stripped prefixes/suffixes (e.g. "/ Communication" -> "COMMUNICATION")
    clean_words = re.sub(r"[^\w\s]", "", normalized).strip()
    if clean_words in _GENERIC_NON_ENTITIES:
        return False

    # Split into constituent words
    tokens = [t.strip(" /.,:;!?\"'()[]{}") for t in normalized.split()]
    tokens = [t for t in tokens if t]

    # If any word in candidate is UNKNOWN, SYSTEM, or placeholder, reject immediately
    if any(t in {"UNKNOWN", "UNK", "N/A", "NA", "NULL", "NONE", "SYSTEM"} for t in tokens):
        return False

    # If all constituent tokens are in generic document words, reject
    if tokens and all(t in _GENERIC_NON_ENTITIES for t in tokens):
        return False

    # Structured account protection: e.g. ACCT-MULE-11 must ONLY be ACCOUNT
    if _looks_like_structured_account(value):
        if etype != "ACCOUNT":
            return False

    # Structured phone protection: e.g. PH-002, PH-003 must ONLY be PHONE
    if _looks_like_structured_phone(value):
        if etype != "PHONE":
            return False

    # Structured device protection: e.g. DEV-002 must ONLY be DEVICE
    if _looks_like_structured_device(value):
        if etype != "DEVICE":
            return False

    # Structured chat protection: e.g. CHAT-001 must ONLY be CHAT
    if _looks_like_structured_chat(value):
        if etype != "CHAT":
            return False

    # Structured transaction reference protection: e.g. TXN-005 must ONLY be TRANSACTION
    if _looks_like_structured_txn(value):
        if etype not in {"TRANSACTION", "TXN"}:
            return False

    # Structured cell tower protection: e.g. CHD-CELL-17 must ONLY be CELL_TOWER
    if _looks_like_structured_cell_tower(value):
        if etype != "CELL_TOWER":
            return False

    # UPI protection: e.g. user@bank must be UPI or EMAIL, never KEYWORD or PERSON
    if re.fullmatch(r"[\w.\-]{2,256}@[a-zA-Z]{2,64}", value.strip()):
        if etype not in {"UPI", "EMAIL"}:
            return False

    # IFSC protection: 4 letters + 0 + 6 alphanumeric
    if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", value.strip().upper()):
        if etype != "IFSC":
            return False

    # IPv4 protection
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value.strip()):
        if etype != "IP":
            return False

    # Temporal patterns: dates/times must not be named entity identities
    if _looks_like_date_or_time(value):
        if etype in {"PERSON", "PER", "ORG", "AMOUNT", "ACCOUNT", "PHONE", "UPI"}:
            return False

    # Phone numbers: must ONLY be PHONE
    if _looks_like_phone(value):
        if etype != "PHONE":
            return False

    # KEYWORD validation: must be a clean domain concept, not punctuation/code fragments or stop/meta words
    if etype == "KEYWORD":
        if any(c in value for c in ('"', "'", ",", "{", "}", "[", "]", "(", ")", ":", ";", "|")):
            return False
        if value.upper().startswith("NETRA") or value.upper().startswith("EVD-"):
            return False
        if len(value) < 3:
            return False
        keyword_stops = {
            "NOT", "AND", "THE", "FOR", "WITH", "FROM", "THIS", "THAT", "THESE", "THOSE",
            "DATA", "TRAINING", "TEST", "SAMPLE", "RECORD", "RECORDS", "FIELD", "VALUE",
            "ACTUAL", "DOCUMENT", "DOCUMENTS", "SUMMARY", "REPORT", "REPORTS", "MEMO",
            "POLICE", "OFFICER", "SYSTEM", "NOTICE", "WARNING", "NOTE", "DISCLAIMER",
            "SYNTHETIC", "INTERNAL", "OBSERVED", "INTEGRITY", "METHOD", "TOOLING",
            "SUCCESS", "FAILED", "PENDING", "COMPLETED", "TLS_SESSION", "TLS", "SESSION",
            "GPS", "CELL-SITE", "ASSOCIATION", "CSV", "TXT", "PDF", "XLSX", "LOG",
            "EXPORT", "COPY", "DIGITAL", "EXTRACTION", "ITEM", "SOURCE", "CONDITION",
        }
        if normalized in keyword_stops or (tokens and all(t in keyword_stops for t in tokens)):
            return False

    # BANK validation
    if etype == "BANK":
        if any(t in {"ACTUAL", "POLICE", "RECORD", "RECORDS", "EXTRACTION", "SUMMARY", "MEMO", "REPORT", "DISCLAIMER", "SYNTHETIC", "TRAINING", "STATEMENT", "SEIZURE", "CUSTODY"} for t in tokens):
            return False
        has_bank_word = any(t in {"BANK", "COOPERATIVE", "PAYMENTS"} for t in tokens)
        known_banks = {"SBI", "HDFC", "ICICI", "PNB", "BOB", "AXIS", "KOTAK", "CANARA", "INDUSIND", "YES BANK"}
        if not (has_bank_word or normalized in known_banks):
            return False

    # PERSON validation
    if etype in {"PERSON", "PER"}:
        if _looks_like_identifier(value):
            return False

        # Reject if any token is an action verb or document term often joined by CRF
        if any(t in {
            "RECEIVED", "SENT", "CONFIRMED", "TRANSFERRED", "INVEST", "BLOCKED", "VERIFICATION",
            "FIELD", "VALUE", "PLATFORM", "ANDROID", "OBSERVED", "RECORD", "RECORDS",
            "TIMESTAMP", "ACTIVITY", "OUTGOING", "INCOMING", "APPLICATION", "TRANSACTION",
            "EXTRACTION", "SUMMARY", "DEVICE", "INTEGRITY", "METHOD", "CUSTODY", "EXAMINER", "TOOLING",
            "TIME", "REFERENCE", "PAYER", "PAYEE", "AMOUNT", "STATUS", "SUCCESS", "FAILED",
            "PHONE", "LOCATION", "CELL", "TOWER", "TIMELINE", "OBSERVATION",
            "ITEM", "SOURCE", "CONDITION", "STATEMENT", "FINANCIAL", "WORKSTATION", "DIGITAL",
            "NETWORK", "LOG", "INVENTORY", "SEIZURE", "PURPOSE",
        } for t in tokens):
            return False

        # If it looks like a known location or has geographic pattern (e.g. "City, Country")
        if normalized in _COMMON_LOCATIONS:
            return False
        if re.search(r"\b(India|State|City|District|Road|Sector|Nagar)\b", value, re.IGNORECASE) and "," in value:
            return False

        # Reject dialogue prefixes like "Name:" or "Sender:"
        if ":" in value:
            return False

        # Reject common sentences or verbs misclassified as people (e.g. "Confirmed. I")
        if re.search(r"[.!?]\s+[A-Z]", value):
            return False

        # Reject tokens starting with non-alphabetic characters
        if not value[0].isalpha():
            return False

    # AMOUNT validation
    if etype == "AMOUNT":
        if not re.search(r"\d", value):
            return False

        # Bare 4-digit years (e.g. 2026, 2024.0) are NOT amounts
        if re.fullmatch(r"[12]\d{3}(?:\.0+)?", value.strip()):
            return False

        # Obvious financial status words
        if normalized in {"RECEIVED", "SENT", "CREDIT", "DEBIT", "AMOUNT", "BALANCE"}:
            return False

    # ACCOUNT validation: must have substantive alphanumeric identity
    if etype == "ACCOUNT":
        if len(value) < 3:
            return False
        if normalized in _GENERIC_NON_ENTITIES:
            return False

    # CELL_TOWER validation
    if etype == "CELL_TOWER":
        return _looks_like_structured_cell_tower(value)

    return True
