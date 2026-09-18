"""
Unit tests for Feature 03 — Syndicate Radar (Cross-Case Blind Index Intelligence).

Tests:
1. Canonicalization variants (Indian phone normalization +91/0, UPI lowercase, account digits, email, IP).
2. Deterministic one-way HMAC-SHA256 blind indexing and missing key rejection.
3. Multi-case collision detection without PII leakage.
4. Bipartite syndicate clustering linking multi-case networks into cohesive syndicates.
5. Ingress threat scoring with multi-case acceleration multipliers.
6. Polar radar geometry (r, θ) generating concentric threat bands.
7. Strict zero-knowledge privacy boundary enforcement (local plaintext anchor vs foreign redacted tokens).
"""
from __future__ import annotations

import pytest
from cognitive.crosscase import (
    BlindIndex,
    MissingKeyError,
    canonicalize,
    build_index,
    find_collisions,
    cluster_syndicates,
    syndicate_ingress_score,
    generate_radar_blips,
    analyze_case_syndicate_radar,
)

TEST_DEPT_KEY = "test-secret-department-key-cyberdrishti-2026"


# ── 1. Canonicalization Variants ──────────────────────────────────────────────

def test_canonicalize_phone_number_variants():
    """All Indian numbering variants (+91, 0, plain, punctuation) must collapse to the identical 10 digits."""
    variants = [
        "+919876543210",
        "+91 98765 43210",
        "09876543210",
        "919876543210",
        "9876543210",
        "+91-9876-543-210",
    ]
    canonical_results = {canonicalize("PHONE", v) for v in variants}
    assert canonical_results == {"9876543210"}, f"Expected single canonical representation, got: {canonical_results}"


def test_canonicalize_financial_and_technical_identifiers():
    """Validates normalization across UPI, Accounts, IFSC, Email, and IP."""
    assert canonicalize("UPI", "Rohan.Mule@OkHdfcBank ") == "rohan.mule@okhdfcbank"
    assert canonicalize("ACCOUNT", "  9190-1004-5678-901  ") == "919010045678901"
    assert canonicalize("IFSC", "  hdfc0001234 ") == "HDFC0001234"
    assert canonicalize("EMAIL", "Operative_X@Proton.ME ") == "operative_x@proton.me"
    assert canonicalize("IP", " 192.168.1.100 ") == "192.168.1.100"


# ── 2. Deterministic HMAC-SHA256 Blind Index ──────────────────────────────────

def test_blind_index_requires_key():
    """Missing or empty department key must raise MissingKeyError."""
    with pytest.raises(MissingKeyError):
        BlindIndex("")
    with pytest.raises(MissingKeyError):
        BlindIndex(None)  # type: ignore


def test_blind_index_deterministic_tokenization():
    """Same canonical value + key produces identical token; different values produce distinct tokens."""
    index = BlindIndex(TEST_DEPT_KEY)
    tok1 = index.token("PHONE", "+91 98765 43210")
    tok2 = index.token("PHONE", "09876543210")
    tok3 = index.token("PHONE", "9999999999")

    assert tok1 == tok2, "Formatting variants must yield identical blind tokens"
    assert tok1 != tok3, "Different identifiers must yield distinct blind tokens"
    assert len(tok1) == 64, "Token must be a 64-char hex string (HMAC-SHA256)"


# ── 3. Cross-Case Collisions ──────────────────────────────────────────────────

def test_find_collisions_across_distinct_cases():
    """A token present in >= 2 distinct cases produces an active collision."""
    index = BlindIndex(TEST_DEPT_KEY)
    entries = [
        {"case_id": "CASE-001", "entity_type": "UPI", "value": "rohan@upi", "degree": 4, "severity": 1.0},
        {"case_id": "CASE-002", "entity_type": "UPI", "value": "ROHAN@UPI", "degree": 3, "severity": 1.0},
        {"case_id": "CASE-001", "entity_type": "PHONE", "value": "9876543210", "degree": 2, "severity": 1.0},
    ]
    store = build_index(entries, index)
    collisions = find_collisions(store)

    assert len(collisions) == 1
    col = collisions[0]
    assert col["entity_type"] == "UPI"
    assert col["case_count"] == 2
    assert set(col["case_ids"]) == {"CASE-001", "CASE-002"}
    assert col["syndicate_score"] > 0


# ── 4. Bipartite Syndicate Clustering ─────────────────────────────────────────

def test_bipartite_syndicate_clustering():
    """
    Scenario:
    Case 1 & Case 2 share Mule Account A.
    Case 2 & Case 3 share Controller Phone P.
    Case 4 is completely isolated with distinct accounts.
    Expectation:
    Cases 1, 2, and 3 are grouped into a single connected Syndicate Cluster!
    Case 4 is not in any multi-case syndicate.
    """
    index = BlindIndex(TEST_DEPT_KEY)
    entries = [
        # Mule Account A in Case 1 & Case 2
        {"case_id": "CASE-001", "case_number": "CYB-001", "entity_type": "ACCOUNT", "value": "ACC-MULE-999", "degree": 3},
        {"case_id": "CASE-002", "case_number": "CYB-002", "entity_type": "ACCOUNT", "value": "ACC-MULE-999", "degree": 5},
        # Controller Phone P in Case 2 & Case 3
        {"case_id": "CASE-002", "case_number": "CYB-002", "entity_type": "PHONE", "value": "9876543210", "degree": 4},
        {"case_id": "CASE-003", "case_number": "CYB-003", "entity_type": "PHONE", "value": "+91 98765 43210", "degree": 2},
        # Isolated Case 4
        {"case_id": "CASE-004", "case_number": "CYB-004", "entity_type": "ACCOUNT", "value": "ISOLATED-ACCOUNT-123", "degree": 1},
    ]
    store = build_index(entries, index)
    syndicates = cluster_syndicates(store)

    assert len(syndicates) == 1, f"Expected 1 connected syndicate cluster, got {len(syndicates)}"
    syn = syndicates[0]
    assert syn["case_count"] == 3
    assert syn["token_count"] == 2
    member_cids = {c["case_id"] for c in syn["cases"]}
    assert member_cids == {"CASE-001", "CASE-002", "CASE-003"}
    assert syn["risk_level"] == "CRITICAL"
    assert "SHARED_BANK_MULE_NETWORK" in syn["threat_indicators"]
    assert "COMMON_CONTROLLER_COMMUNICATION" in syn["threat_indicators"]


# ── 5. Ingress Threat Scoring ─────────────────────────────────────────────────

def test_syndicate_ingress_score_multi_case_acceleration():
    """Score must increase with case breadth and degree."""
    occ_2_cases = [
        {"case_id": "C1", "degree": 2, "severity": 1.0},
        {"case_id": "C2", "degree": 2, "severity": 1.0},
    ]
    occ_4_cases = [
        {"case_id": "C1", "degree": 2, "severity": 1.0},
        {"case_id": "C2", "degree": 2, "severity": 1.0},
        {"case_id": "C3", "degree": 2, "severity": 1.0},
        {"case_id": "C4", "degree": 2, "severity": 1.0},
    ]
    score_2 = syndicate_ingress_score(occ_2_cases)
    score_4 = syndicate_ingress_score(occ_4_cases)

    assert score_4 > score_2 * 2.0, "Multi-case acceleration multiplier must boost compound risk"


# ── 6. Polar Radar Geometry Generation ───────────────────────────────────────

def test_generate_radar_blips_geometry():
    """Blips must have valid polar coordinates r in [0.15, 0.90] and theta in [0, 360]."""
    index = BlindIndex(TEST_DEPT_KEY)
    entries = [
        {"case_id": "C1", "entity_type": "UPI", "value": "mule@upi", "degree": 5},
        {"case_id": "C2", "entity_type": "UPI", "value": "mule@upi", "degree": 4},
        {"case_id": "C3", "entity_type": "UPI", "value": "mule@upi", "degree": 3},
    ]
    store = build_index(entries, index)
    collisions = find_collisions(store)
    syndicates = cluster_syndicates(store)
    blips = generate_radar_blips(syndicates, collisions, target_case_id="C1")

    assert len(blips) >= 1
    for blip in blips:
        assert 0.15 <= blip["r"] <= 0.95, f"Radius {blip['r']} out of radar range"
        assert 0.0 <= blip["theta"] <= 360.0, f"Angle {blip['theta']} out of 360° range"
        assert blip["risk_level"] in ("CRITICAL", "ELEVATED", "MONITORED")


# ── 7. Zero-Knowledge Privacy Boundary ────────────────────────────────────────

def test_zero_knowledge_privacy_boundary_enforcement():
    """
    CRITICAL STATUTORY GUARANTEE:
    When Case 1 is analyzed:
    - Case 1's own entities have their plaintext value revealed as the Local Anchor.
    - Case 2's matching entities MUST NOT expose their raw value (redacted with blind token).
    """
    index = BlindIndex(TEST_DEPT_KEY)
    all_entries = [
        {"case_id": "CASE-101", "case_number": "CYB-101", "entity_type": "PHONE", "value": "+919876543210", "degree": 3},
        {"case_id": "CASE-202", "case_number": "CYB-202", "entity_type": "PHONE", "value": "09876543210", "degree": 4},
    ]
    local_entities = [
        {
            "id": "entity-uuid-1",
            "entity_type": "PHONE",
            "canonical_value": "9876543210",
            "degree": 3,
            "provenance": {"source_file": "04_call_detail_record.csv", "source_page": 1, "source_line": 42},
        }
    ]

    radar_res = analyze_case_syndicate_radar(
        target_case_id="CASE-101",
        local_entities=local_entities,
        all_case_entries=all_entries,
        index=index,
    )

    assert radar_res["total_collisions"] == 1
    col = radar_res["collisions"][0]

    # Local Anchor check: plaintext present with provenance
    assert col["local_anchor"]["has_local_anchor"] is True
    assert col["local_anchor"]["plaintext_value"] == "9876543210"
    assert col["local_anchor"]["provenance"]["source_file"] == "04_call_detail_record.csv"

    # Foreign Cases check: ZERO-KNOWLEDGE REDACTION
    assert len(col["foreign_cases"]) == 1
    fc = col["foreign_cases"][0]
    assert fc["case_number"] == "CYB-202", fc["case_number"]
    assert "ZERO_KNOWLEDGE_BLIND_TOKEN" in fc["redacted_value"]
    # Ensure raw foreign value "09876543210" is NOT leaked in the foreign case record
    assert "09876543210" not in str(fc)
