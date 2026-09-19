from __future__ import annotations

"""
NETRA 5.0 — Copilot Deterministic Query Planner

Deconstructs, normalizes, and routes investigative queries using rule-based heuristics:
1. High-entropy forensic identifier extraction (PHONE, EMAIL, UPI, ACCOUNT, IP, AMOUNT)
2. Normalized entity tagging (e.g. PHONE:+919876543210, ACCOUNT:4821)
3. Deterministic query intent detection (FACTUAL, RELATIONAL, TEMPORAL, STATUTORY, ADVERSARIAL, GENERAL)
4. Multi-modal retrieval routing (VECTOR, GRAPH, STRUCTURED, TIMELINE)
5. Unambiguous temporal window extraction
6. Atomic sub-query generation

No external LLM, vector store, or database calls belong here.
"""

import calendar
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .config import get_copilot_config
from .schemas import ModalityType, QueryIntentType, QueryPlan


# ─────────────────────────────────────────────────────────────────────────────
# Regex Patterns for Forensic Identifiers
# ─────────────────────────────────────────────────────────────────────────────

# Phone: Indian +91 prefix, 10-digit mobile, or masked phone (e.g. +91XXXXXXXXXX)
PHONE_RE = re.compile(r"(?:\+91[\-\s]?)?(?:[6-9]\d{9}|[Xx0-9]{10})\b")

# Email: Standard email pattern
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# UPI / VPA: user@bank handle
UPI_RE = re.compile(r"\b[\w.\-]{2,}@[a-zA-Z]{2,}\b")

# Bank Account: prefixed e.g. Account 4821, ACC-4821, ACCT:12345
ACCOUNT_RE = re.compile(r"\b(?:ACCT|ACC|ACCOUNT)[-:\s#]+([A-Z0-9_\-]+)\b", re.IGNORECASE)

# IP Address: IPv4
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Monetary Amounts: ₹ 50,000 / INR 50000 / Rs. 50,000.00
AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s?([0-9][\d,]*(?:\.\d{1,2})?)", re.IGNORECASE)

# Legal Sections: Section 63 BSA / Section 105 BNSS / Section 66D IT Act
STATUTE_SECTION_RE = re.compile(
    r"Section[s]?\s+(\d{1,4}[A-Z]?(?:\(\d+\)){0,3})\s*"
    r"(?:of\s+(?:the\s+)?)?(BNSS|BSA|BNS|IT\s*Act|PMLA|IPC|CrPC|IEA)?",
    re.IGNORECASE,
)

# Date Range Patterns: "between August 10 and August 15", "from 2026-08-10 to 2026-08-15"
MONTHS_MAP = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS_ABBR = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
ALL_MONTHS = {**MONTHS_MAP, **MONTHS_ABBR}

DATE_RANGE_RE = re.compile(
    r"(?:between|from)\s+([A-Za-z]+|\d{4}[-/]\d{1,2}[-/]\d{1,2})\s*(\d{1,2})?(?:st|nd|rd|th)?\s+"
    r"(?:and|to|-)\s+([A-Za-z]+|\d{4}[-/]\d{1,2}[-/]\d{1,2})?\s*(\d{1,2})?(?:st|nd|rd|th)?",
    re.IGNORECASE,
)


class QueryPlanner:
    """Deterministic investigative query analyzer and router."""

    def __init__(self):
        self.config = get_copilot_config()

    def plan(self, question: str) -> QueryPlan:
        """Parse raw investigator query into a structured, executable QueryPlan."""
        cleaned_query = question.strip()

        # 1. Extract Identifiers and normalized target entities
        entities = self._extract_entities(cleaned_query)

        # 2. Extract Statutory Citations
        statutes = self._extract_statutes(cleaned_query)

        # 3. Extract Temporal Windows
        time_start, time_end = self._extract_time_window(cleaned_query)

        # 4. Classify Investigative Intent
        intent = self._classify_intent(cleaned_query, entities, statutes, time_start is not None)

        # 5. Route to Target Modalities
        modalities = self._route_modalities(intent, entities, time_start is not None)

        # 6. Generate Sub-queries for Multi-Hop Retrieval
        sub_queries = self._generate_subqueries(cleaned_query, intent, entities, statutes, time_start, time_end)

        return QueryPlan(
            original_query=cleaned_query,
            intent=intent,
            sub_queries=sub_queries,
            target_modalities=modalities,
            target_entities=entities,
            time_window_start=time_start,
            time_window_end=time_end,
            suggested_statutes=statutes,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Entity & Identifier Extraction
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_entities(self, text: str) -> List[str]:
        """Extract and normalize high-entropy identifiers into TYPE:VALUE format."""
        entities: List[str] = []
        seen = set()

        def add_entity(etype: str, val: str):
            clean_val = val.strip().strip(",.?!:;\"'")
            if clean_val and clean_val not in seen:
                seen.add(clean_val)
                entities.append(f"{etype}:{clean_val}")

        # Bank Accounts
        for match in ACCOUNT_RE.finditer(text):
            add_entity("ACCOUNT", match.group(1))

        # Emails
        for match in EMAIL_RE.finditer(text):
            add_entity("EMAIL", match.group(0))

        # UPI Handles (exclude emails already caught)
        for match in UPI_RE.finditer(text):
            handle = match.group(0)
            if not any(handle in e for e in entities if e.startswith("EMAIL:")):
                add_entity("UPI", handle)

        # IP Addresses
        for match in IP_RE.finditer(text):
            add_entity("IP", match.group(0))

        # Phone Numbers
        for match in PHONE_RE.finditer(text):
            raw_phone = match.group(0)
            # Avoid matching standard 10 digit amounts without phone context
            if len(raw_phone) >= 10:
                add_entity("PHONE", raw_phone)

        # Monetary Amounts
        for match in AMOUNT_RE.finditer(text):
            add_entity("AMOUNT", match.group(1).replace(",", ""))

        return entities

    def _extract_statutes(self, text: str) -> List[str]:
        """Detect referenced legal sections."""
        statutes = []
        for match in STATUTE_SECTION_RE.finditer(text):
            sec = match.group(1)
            act = match.group(2)
            if act:
                statutes.append(f"Section {sec} {act.upper()}")
            else:
                statutes.append(f"Section {sec}")
        return statutes

    # ─────────────────────────────────────────────────────────────────────────
    # Temporal Window Extraction
    # ─────────────────────────────────────────────────────────────────────────

    def _extract_time_window(self, text: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Extract unambiguous date intervals."""
        match = DATE_RANGE_RE.search(text)
        if not match:
            return None, None

        part1, part2, part3, part4 = match.groups()
        current_year = 2026  # Aligned with NETRA standard timeline

        try:
            # Case A: Month Day and Month Day (e.g. August 10 and August 15)
            if part1 and part1.lower() in ALL_MONTHS and part2:
                m1 = ALL_MONTHS[part1.lower()]
                d1 = int(part2)
                t_start = datetime(current_year, m1, d1, 0, 0, 0)

                # Check second part
                if part3 and part3.lower() in ALL_MONTHS and part4:
                    m2 = ALL_MONTHS[part3.lower()]
                    d2 = int(part4)
                    t_end = datetime(current_year, m2, d2, 23, 59, 59)
                elif part4:  # "between August 10 and 15"
                    d2 = int(part4)
                    t_end = datetime(current_year, m1, d2, 23, 59, 59)
                elif part3 and part3.isdigit():
                    d2 = int(part3)
                    t_end = datetime(current_year, m1, d2, 23, 59, 59)
                else:
                    t_end = None
                return t_start, t_end

            # Case B: ISO dates (e.g. 2026-08-10 to 2026-08-15)
            if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", part1):
                clean_d1 = part1.replace("/", "-")
                t_start = datetime.strptime(clean_d1, "%Y-%m-%d")
                t_end = None
                if part3 and re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", part3):
                    clean_d2 = part3.replace("/", "-")
                    t_end = datetime.strptime(clean_d2, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                return t_start, t_end

        except Exception:
            pass

        return None, None

    # ─────────────────────────────────────────────────────────────────────────
    # Intent Classification
    # ─────────────────────────────────────────────────────────────────────────

    def _classify_intent(
        self,
        query: str,
        entities: List[str],
        statutes: List[str],
        has_time_window: bool,
    ) -> QueryIntentType:
        """Classify query intent deterministically via keyword hierarchy."""
        q_lower = query.lower()

        # 1. Adversarial / Defense Challenge (Highest priority)
        adversarial_keywords = [
            "defence", "defense", "alternative explanation", "alibi", "reasonable doubt",
            "challenge", "cross-examin", "red-team", "flaw", "weakness", "stress-test",
            "innocent explanation", "prosecution gap",
        ]
        if any(k in q_lower for k in adversarial_keywords):
            return QueryIntentType.ADVERSARIAL

        # 2. Statutory / Legal Framework
        statutory_keywords = [
            "section", "bsa", "bnss", "bns", "it act", "pmla", "crpc", "ipc", "statute",
            "statutory", "admissibility", "admissible", "certificate", "65b", "63 bsa",
            "compliance", "custody memo", "panchnama",
        ]
        if statutes or any(k in q_lower for k in statutory_keywords):
            return QueryIntentType.STATUTORY

        # 3. Temporal / Replay
        temporal_keywords = [
            "timeline", "when did", "sequence", "chronological", "replay", "what happened between",
            "what happened on", "after", "before", "during", "timeframe", "timestamps",
        ]
        if has_time_window or any(k in q_lower for k in temporal_keywords):
            return QueryIntentType.TEMPORAL

        # 4. Relational / Network
        relational_keywords = [
            "connected", "connection", "connect", "relat", "link", "hidden link", "network",
            "associate", "path between", "common neighbor", "bridge", "mule ring", "syndicate",
            "how is", "why is",
        ]
        if any(k in q_lower for k in relational_keywords) and (len(entities) >= 1 or "connected" in q_lower):
            return QueryIntentType.RELATIONAL

        # 5. Factual (Transactions, Amounts, Entities)
        factual_keywords = [
            "transaction", "transfer", "amount", "money", "deposit", "withdraw", "balance",
            "who is", "who sent", "who received", "account", "phone", "call", "message",
            "what transactions", "what evidence", "how much",
        ]
        if any(k in q_lower for k in factual_keywords) or entities:
            return QueryIntentType.FACTUAL

        # 6. General / Summary
        general_keywords = [
            "summarize", "summary", "overview", "case", "help", "hello", "hi", "namaste",
            "explain case", "what is this case", "status",
        ]
        if any(k in q_lower for k in general_keywords) or not entities:
            return QueryIntentType.GENERAL

        return QueryIntentType.FACTUAL

    # ─────────────────────────────────────────────────────────────────────────
    # Modality Routing
    # ─────────────────────────────────────────────────────────────────────────

    def _route_modalities(
        self,
        intent: QueryIntentType,
        entities: List[str],
        has_time_window: bool,
    ) -> List[str]:
        """Route query to the optimal combination of retrieval engines."""
        modalities: List[str] = []

        if intent == QueryIntentType.RELATIONAL:
            modalities = ["graph", "structured", "vector"]
        elif intent == QueryIntentType.TEMPORAL:
            modalities = ["timeline", "structured", "vector"]
        elif intent == QueryIntentType.STATUTORY:
            modalities = ["vector", "structured"]
        elif intent == QueryIntentType.ADVERSARIAL:
            modalities = ["vector", "structured", "graph"]
        elif intent == QueryIntentType.FACTUAL:
            modalities = ["structured", "vector"]
            # If multiple entities or accounts involved, add graph for relational context
            if len(entities) >= 2 or any(e.startswith("ACCOUNT:") for e in entities):
                modalities.append("graph")
        else:  # GENERAL
            modalities = ["vector", "structured", "graph"]

        # If date window explicitly present, ensure timeline is routed
        if has_time_window and "timeline" not in modalities:
            modalities.insert(0, "timeline")

        return modalities

    # ─────────────────────────────────────────────────────────────────────────
    # Sub-query Generation
    # ─────────────────────────────────────────────────────────────────────────

    def _generate_subqueries(
        self,
        original_query: str,
        intent: QueryIntentType,
        entities: List[str],
        statutes: List[str],
        time_start: Optional[datetime],
        time_end: Optional[datetime],
    ) -> List[str]:
        """Generate focused sub-queries for targeted multi-modal retrieval."""
        subqueries: List[str] = [original_query]

        # Entity-targeted sub-queries
        for ent in entities[:3]:
            etype, val = ent.split(":", 1)
            if etype in ("ACCOUNT", "UPI"):
                subqueries.append(f"transactions involving {val}")
            elif etype == "PHONE":
                subqueries.append(f"call records and messages for {val}")
            elif etype == "AMOUNT":
                subqueries.append(f"transfers of amount {val}")

        # Temporal sub-query
        if time_start and time_end:
            subqueries.append(f"events from {time_start.strftime('%Y-%m-%d')} to {time_end.strftime('%Y-%m-%d')}")

        # Statutory sub-query
        for statute in statutes[:2]:
            subqueries.append(f"{statute} requirements and evidence compliance")

        # Intent-specific sub-queries
        if intent == QueryIntentType.ADVERSARIAL:
            subqueries.append("investigative gaps reasonable doubt alternative explanation")
        elif intent == QueryIntentType.RELATIONAL and len(entities) >= 2:
            subqueries.append(f"path and shared connections between {entities[0]} and {entities[1]}")

        # Deduplicate while preserving order
        unique_subs = []
        seen = set()
        for sq in subqueries:
            sq_norm = sq.lower().strip()
            if sq_norm not in seen:
                seen.add(sq_norm)
                unique_subs.append(sq)

        return unique_subs
