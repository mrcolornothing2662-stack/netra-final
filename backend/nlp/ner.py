from __future__ import annotations
"""
CyberDrishti AI — NLP Named Entity Recognition Layer
Extracts contextual entities: PERSON, ORG, LOCATION, DATE.

Priority order:
1. spaCy `en_core_web_sm` (if installed)
2. Built-in Hinglish keyword + pattern NER (always available, no deps)

Hard identifiers (PHONE, UPI, ACCOUNT, EMAIL, IP, IFSC, URL, AMOUNT)
remain under the authoritative regex layer in correlation/regex_extractors.py.
"""
import logging
import re
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

# ── spaCy optional import ─────────────────────────────────────────────────────

_spacy_nlp = None

try:
    import spacy
    for _model in ("en_core_web_sm", "xx_ent_wiki_sm", "en_core_web_md"):
        try:
            _spacy_nlp = spacy.load(_model)
            logger.info("[NER] Loaded spaCy model '%s'", _model)
            break
        except Exception:
            continue
    if _spacy_nlp is None:
        logger.warning("[NER] spaCy installed but no model found. Run: python -m spacy download en_core_web_sm")
except ImportError:
    logger.info("[NER] spaCy not installed — using built-in Hinglish keyword NER fallback.")


# ── Entity dataclass ──────────────────────────────────────────────────────────

@dataclass
class NEREntity:
    entity_type: str       # PERSON | ORG | LOCATION | DATE
    raw_value: str
    canonical_value: str
    span_start: int
    span_end: int
    confidence: float = 0.80
    extractor: str = "spacy_ner"


# ── Label mapper ─────────────────────────────────────────────────────────────

_LABEL_MAP = {
    "PERSON": "PERSON",
    "PER": "PERSON",
    "ORG": "ORG",
    "ORGANIZATION": "ORG",
    "NORP": "ORG",           # nationalities / groups
    "FAC": "LOCATION",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "LOCATION": "LOCATION",
    "DATE": "DATE",
    "TIME": "DATE",
}


# ── Built-in Hinglish keyword NER ─────────────────────────────────────────────

# Common Indian titles that precede PERSON names
_PERSON_TITLES = re.compile(
    r'\b(shri|smt|dr|mr|mrs|ms|sir|inspector|si|sho|ips|ias|ifs|adv|advocate|'
    r'constable|havildar|subedar|commandant|director|officer|accused|victim|suspect)\s+',
    re.IGNORECASE,
)

# Common Indian organisation keywords
_ORG_KEYWORDS = re.compile(
    r'\b(bank|paytm|phonepe|gpay|googlepay|bhim|neft|rtgs|imps|npci|rbi|sebi|'
    r'police|court|fir|cybercrime|ed|cbi|ncb|income\s*tax|enforcement|'
    r'pvt\.?\s*ltd|limited|llp|foundation|trust|society|department|ministry|'
    r'hospital|school|college|university|institute|academy)\b',
    re.IGNORECASE,
)

# Common date patterns (Indian format)
_DATE_RE = re.compile(
    r'\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|'
    r'\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{2,4})\b',
    re.IGNORECASE,
)

# Common Indian state / city names for LOCATION detection
_LOCATIONS = re.compile(
    r'\b(delhi|mumbai|kolkata|chennai|bangalore|bengaluru|hyderabad|pune|ahmedabad|'
    r'jaipur|lucknow|kanpur|nagpur|patna|bhopal|agra|varanasi|surat|gurgaon|noida|'
    r'chandigarh|mohali|amritsar|ludhiana|indore|bhopal|visakhapatnam|coimbatore|'
    r'kochi|thiruvananthapuram|rajasthan|maharashtra|gujarat|kerala|karnataka|'
    r'tamilnadu|tamil\s+nadu|andhra|telangana|odisha|bihar|jharkhand|west\s+bengal|'
    r'uttar\s+pradesh|madhya\s+pradesh|himachal|uttarakhand|assam|meghalaya|'
    r'manipur|nagaland|mizoram|tripura|arunachal|goa|punjab|haryana|india)\b',
    re.IGNORECASE,
)


def _hinglish_ner(text: str) -> List[NEREntity]:
    """
    Built-in keyword/pattern NER for Hinglish cybercrime text.
    Always available — no external dependencies required.
    """
    results: List[NEREntity] = []
    covered: set[tuple[int, int]] = set()

    def _add(etype: str, m: re.Match, value: str, conf: float = 0.72):
        start, end = m.start(), m.end()
        # Avoid overlapping with already covered spans
        for cs, ce in covered:
            if start < ce and end > cs:
                return
        covered.add((start, end))
        results.append(NEREntity(
            entity_type=etype,
            raw_value=value.strip(),
            canonical_value=value.strip(),
            span_start=start,
            span_end=end,
            confidence=conf,
            extractor="hinglish_ner",
        ))

    # 1. DATE — highest specificity
    for m in _DATE_RE.finditer(text):
        _add("DATE", m, m.group(), conf=0.90)

    # 2. LOCATION
    for m in _LOCATIONS.finditer(text):
        _add("LOCATION", m, m.group(), conf=0.85)

    # 3. ORG keywords — use only the matched keyword, not surrounding context
    for m in _ORG_KEYWORDS.finditer(text):
        _add("ORG", m, m.group().strip(), conf=0.75)

    # 4. PERSON — title-prefixed names
    for m in _PERSON_TITLES.finditer(text):
        # Capture title + following capitalized word(s) as PERSON name
        after = text[m.end():]
        name_m = re.match(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})', after)
        if name_m:
            full = m.group().strip() + " " + name_m.group().strip()
            # Create a fake match-like span
            span_start = m.start()
            span_end = m.end() + name_m.end()
            already = any(cs <= span_start < ce for cs, ce in covered)
            if not already:
                covered.add((span_start, span_end))
                results.append(NEREntity(
                    entity_type="PERSON",
                    raw_value=full,
                    canonical_value=full,
                    span_start=span_start,
                    span_end=span_end,
                    confidence=0.78,
                    extractor="hinglish_ner",
                ))

    return results


# ── Main extraction function ──────────────────────────────────────────────────

def extract_entities(text: str) -> List[NEREntity]:
    """
    Extract named entities from text.

    Uses spaCy if available (primary), falls back to built-in Hinglish NER.
    Always returns a list (never raises, never returns None).
    """
    if not text or not text.strip():
        return []

    if _spacy_nlp is not None:
        return _extract_spacy(text)

    return _hinglish_ner(text)


def _extract_spacy(text: str) -> List[NEREntity]:
    """Extract entities using the loaded spaCy model."""
    results: List[NEREntity] = []
    try:
        doc = _spacy_nlp(text)
        for ent in doc.ents:
            etype = _LABEL_MAP.get(ent.label_)
            if not etype:
                continue
            raw = ent.text.strip()
            if not raw or len(raw) < 2:
                continue
            # Filter numbers misclassified as PERSON
            if etype == "PERSON" and (raw.replace(" ", "").isdigit() or raw.startswith("+")):
                continue
            results.append(NEREntity(
                entity_type=etype,
                raw_value=raw,
                canonical_value=raw,
                span_start=ent.start_char,
                span_end=ent.end_char,
                confidence=0.85,
                extractor="spacy_ner",
            ))
    except Exception as exc:
        logger.error("[NER] spaCy extraction error: %s", exc)
        return _hinglish_ner(text)  # fallback

    # If spaCy found nothing, supplement with Hinglish NER
    if not results:
        return _hinglish_ner(text)

    return results
