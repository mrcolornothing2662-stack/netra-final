from __future__ import annotations

"""
CyberDrishti AI — Relationship Vocabulary

Single source of truth for the semantic edge types and epistemic statuses used
by the unified case graph. Observed relationships are directly supported by
evidence; inferred relationships are produced by cognitive analysis.

Nothing here touches the database or third-party libraries — it is a pure
vocabulary module so both the ingestion pipeline and the cognitive layer can
import it without creating cycles.
"""

# ── Epistemic status ──────────────────────────────────────────────────────────

OBSERVED = "OBSERVED"   # directly present in evidence (bank row, CDR record, chat)
INFERRED = "INFERRED"   # produced by a cognitive engine (hidden link, etc.)

EPISTEMIC_STATUSES = frozenset({OBSERVED, INFERRED})


# ── Direction ─────────────────────────────────────────────────────────────────

OUTBOUND = "OUTBOUND"
INBOUND = "INBOUND"
BIDIRECTIONAL = "BIDIRECTIONAL"

DIRECTIONS = frozenset({OUTBOUND, INBOUND, BIDIRECTIONAL})


# ── Semantic relationship types ───────────────────────────────────────────────
# Mirrors the target data model. CO_OCCURRENCE is the honest fallback for an
# event that co-locates two entities without a stronger, typed meaning.

OWNS = "OWNS"
USES = "USES"
CALLED = "CALLED"
MESSAGED = "MESSAGED"
TRANSFERRED_TO = "TRANSFERRED_TO"
TRANSFERRED_FROM = "TRANSFERRED_FROM"
LOCATED_AT = "LOCATED_AT"
LOGGED_IN_FROM = "LOGGED_IN_FROM"
ASSOCIATED_WITH = "ASSOCIATED_WITH"
MENTIONED_IN = "MENTIONED_IN"
PARTICIPATED_IN = "PARTICIPATED_IN"
CONNECTED_TO = "CONNECTED_TO"
CO_OCCURRENCE = "CO_OCCURRENCE"

RELATIONSHIP_TYPES = frozenset({
    OWNS,
    USES,
    CALLED,
    MESSAGED,
    TRANSFERRED_TO,
    TRANSFERRED_FROM,
    LOCATED_AT,
    LOGGED_IN_FROM,
    ASSOCIATED_WITH,
    MENTIONED_IN,
    PARTICIPATED_IN,
    CONNECTED_TO,
    CO_OCCURRENCE,
})


# ── Event type → primary observed relationship ────────────────────────────────

EVENT_TYPE_RELATIONSHIP: dict[str, str] = {
    "bank_txn":          TRANSFERRED_TO,
    "call":              CALLED,
    "whatsapp_msg":      MESSAGED,
    "network_log":       CONNECTED_TO,
    "location_timeline": LOCATED_AT,
}

DEFAULT_OBSERVED_RELATIONSHIP = CO_OCCURRENCE


def relationship_for_event(event_type: str | None) -> str:
    """Return the primary semantic relationship a given event type expresses."""
    return EVENT_TYPE_RELATIONSHIP.get(event_type or "", DEFAULT_OBSERVED_RELATIONSHIP)


def is_valid_relationship_type(value: str | None) -> bool:
    return value in RELATIONSHIP_TYPES


def is_valid_epistemic_status(value: str | None) -> bool:
    return value in EPISTEMIC_STATUSES


def is_valid_direction(value: str | None) -> bool:
    return value in DIRECTIONS
