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
INVESTIGATOR_ADDED = "INVESTIGATOR_ADDED"  # introduced explicitly by investigator

EPISTEMIC_STATUSES = frozenset({OBSERVED, INFERRED, INVESTIGATOR_ADDED})


# ── Review status ────────────────────────────────────────────────────────────

REVIEW_UNREVIEWED = "UNREVIEWED"
REVIEW_ACCEPTED   = "ACCEPTED"
REVIEW_REJECTED   = "REJECTED"

REVIEW_STATUSES = frozenset({REVIEW_UNREVIEWED, REVIEW_ACCEPTED, REVIEW_REJECTED})


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
SHARED_DEVICE = "SHARED_DEVICE"
TRAVELLED_WITH = "TRAVELLED_WITH"
REGISTERED_TO = "REGISTERED_TO"
SAME_AS = "SAME_AS"
COMMUNICATED_WITH = "COMMUNICATED_WITH"

RELATIONSHIP_TYPES = frozenset({
    SAME_AS,
    REGISTERED_TO,
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
    SHARED_DEVICE,
    TRAVELLED_WITH,
    REGISTERED_TO,
    COMMUNICATED_WITH,
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


def is_valid_review_status(value: str | None) -> bool:
    return value in REVIEW_STATUSES


def is_valid_direction(value: str | None) -> bool:
    return value in DIRECTIONS


def is_canonical_eligible(epistemic_status: str | None, review_status: str | None = REVIEW_UNREVIEWED) -> bool:
    """
    Determine whether an edge is eligible to form the canonical graph topology.
    Canonical rules:
      - OBSERVED + UNREVIEWED or ACCEPTED (rejected edges excluded)
      - INVESTIGATOR_ADDED + ACCEPTED (or UNREVIEWED pending explicit confirmation)
      - INFERRED edges ONLY if explicitly ACCEPTED by an investigator
    """
    if review_status == REVIEW_REJECTED:
        return False
    if epistemic_status == OBSERVED:
        return True
    if epistemic_status == INVESTIGATOR_ADDED:
        return True
    if epistemic_status == INFERRED and review_status == REVIEW_ACCEPTED:
        return True
    return False

