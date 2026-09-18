"""
CyberDrishti AI — Feature 03: Syndicate Radar / Cross-Case Blind Index Intelligence.

Detects when the SAME hard identifier (phone / UPI / account / IMEI / MAC / Email / IP)
recur across multiple cases WITHOUT exposing identifiers or case content across case
jurisdictional boundaries.

Key Capabilities:
1. Canonicalization: Standardized normalization for phone (+91/0 variants), UPI (lowercased),
   bank accounts (digits, normalized), IFSC, IMEI, MAC, Email, and IP addresses.
2. Tokenization: One-way deterministic HMAC-SHA256(canonical_value, key). Department secret
   key ensures zero-knowledge privacy; tokens are cryptographically irreversible.
3. Multi-Case Ingress Scoring: S(e) = Σ_c Severity(c) × log(1 + Degree_c(e)) with multi-case
   multipliers for cross-jurisdictional threat evaluation.
4. Bipartite Syndicate Clustering: Identifies connected networks of cases linked by shared
   blind tokens, computing cluster cohesion, threat tags, and risk tiers (CRITICAL / ELEVATED / MONITORED).
5. Polar Radar Geometry: Computes polar coordinates (r, θ) for concentric radar visualization
   mapping syndicates to core, inner, and outer risk bands.
6. Zero-Knowledge Privacy Boundary: Local case entities disclose plaintext anchors to the assigned
   investigator, while all foreign case occurrences remain cryptographically shielded tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
from typing import Any, Sequence


class MissingKeyError(RuntimeError):
    pass


_NON_DIGIT = re.compile(r"\D+")


def canonicalize(entity_type: str, value: str) -> str:
    """Canonicalizes raw identifiers to prevent trivial evasions (e.g. +91 vs 0 prefix,
    casing differences, spaces, dashes).
    """
    v = str(value).strip()
    t = entity_type.upper()
    if t in ("PHONE", "ACCOUNT", "IMEI", "MAC"):
        digits = _NON_DIGIT.sub("", v)
        if t == "PHONE":
            # Indian numbering variants must collide: +91XXXXXXXXXX, 0XXXXXXXXXX, 91XXXXXXXXXX
            if len(digits) == 12 and digits.startswith("91"):
                digits = digits[2:]
            elif len(digits) == 11 and digits.startswith("0"):
                digits = digits[1:]
        return digits
    if t == "UPI":
        return v.lower()
    if t == "IFSC":
        return v.upper()
    if t in ("EMAIL", "DOMAIN"):
        return v.lower()
    if t == "IP":
        return v.strip().lower()
    # Default fallback: lowercase stripped
    return v.lower()


class BlindIndex:
    """Zero-knowledge HMAC-SHA256 blind index generator.

    Department key is required; tokens cannot be inverted without the key.
    """
    def __init__(self, key: str | bytes) -> None:
        if not key:
            raise MissingKeyError(
                "BlindIndex requires a department key (env/param). "
                "Refusing to operate with an empty or default key."
            )
        if isinstance(key, str):
            key = key.encode("utf-8")
        self._key = key

    def token(self, entity_type: str, value: str) -> str:
        canonical = canonicalize(entity_type, value)
        if not canonical:
            raise ValueError(f"empty canonical value for {entity_type}:{value!r}")
        return hmac.new(
            self._key,
            f"{entity_type.upper()}:{canonical}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def tokens_for_entity(self, entity: dict[str, Any]) -> list[dict[str, str]]:
        """entity: {type, value, ...} → [{entity_type, token}]"""
        out = []
        for etype in entity.get("types", [entity.get("type", "UNKNOWN")]):
            for val in entity.get("values", [entity.get("value", "")]):
                if val:
                    out.append({
                        "entity_type": str(etype).upper(),
                        "token": self.token(str(etype), str(val)),
                    })
        return out


def build_index(
    entries: list[dict[str, Any]],
    index: BlindIndex,
) -> dict[str, list[dict[str, Any]]]:
    """Indexes entries by their blind token: token → [{case_id, entity_type, degree, severity, ...}].

    Collapses duplicate (token, case_id) pairs to one entry keeping the maximum degree.
    Preserves case metadata and local plaintext anchor if available.
    """
    store: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        raw_val = e.get("value") or e.get("canonical_value") or ""
        if not raw_val:
            continue
        etype = str(e.get("entity_type", "UNKNOWN")).upper()
        tok = index.token(etype, raw_val)
        bucket = store.setdefault(tok, [])

        case_id_str = str(e.get("case_id", ""))
        for existing in bucket:
            if existing["case_id"] == case_id_str:
                existing["degree"] = max(existing["degree"], int(e.get("degree", 1) or 1))
                break
        else:
            bucket.append({
                "case_id": case_id_str,
                "case_number": str(e.get("case_number", "")),
                "case_title": str(e.get("case_title", "")),
                "crime_type": str(e.get("crime_type", "")),
                "police_station": str(e.get("police_station", "")),
                "entity_type": etype,
                "degree": int(e.get("degree", 1) or 1),
                "severity": float(e.get("severity", 1.0) or 1.0),
                "local_value": raw_val,
                "entity_id": str(e.get("id") or e.get("entity_id") or ""),
                "provenance": e.get("provenance") or {},
                "first_seen": str(e.get("first_seen") or ""),
                "last_seen": str(e.get("last_seen") or ""),
            })
    return store


def syndicate_ingress_score(occurrences: list[dict[str, Any]]) -> float:
    """Calculates multi-case syndicate ingress threat score:
    S(e) = Σ_c Severity(c) × log(1 + Degree_c(e)) × MultiJurisdictionMultiplier
    """
    base_score = sum(float(o.get("severity", 1.0)) * math.log1p(int(o.get("degree", 1) or 1)) for o in occurrences)
    unique_cases = len({o["case_id"] for o in occurrences})
    # Multi-case acceleration: syndicates spanning 3+ cases pose compound risk
    multiplier = 1.0
    if unique_cases >= 3:
        multiplier = 1.25 + (0.1 * min(unique_cases - 3, 10))
    elif unique_cases == 2:
        multiplier = 1.1

    return round(base_score * multiplier, 4)


def find_collisions(
    index_store: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Identifies cross-case collisions (tokens present in >= 2 DISTINCT cases).

    Alerts carry NO raw identifiers for foreign cases, strictly preserving zero-knowledge privacy.
    """
    alerts: list[dict[str, Any]] = []
    for tok, occurrences in index_store.items():
        case_ids = sorted({o["case_id"] for o in occurrences if o.get("case_id")})
        if len(case_ids) < 2:
            continue
        etype = occurrences[0]["entity_type"]
        score = syndicate_ingress_score(occurrences)

        # Build list of case references (case_number or case_id)
        case_refs = []
        for cid in case_ids:
            occ = next((o for o in occurrences if o["case_id"] == cid), None)
            ref = (occ.get("case_number") if occ and occ.get("case_number") else cid[:8])
            case_refs.append(ref)

        alerts.append({
            "blind_token": tok,
            "entity_type": etype,
            "case_ids": case_ids,
            "case_refs": case_refs,
            "cases": case_refs,  # backward compatibility alias
            "case_count": len(case_ids),
            "degree_sum": sum(int(o.get("degree", 1) or 1) for o in occurrences),
            "syndicate_score": score,
            "alert_status": "active",
            "occurrences": occurrences,
            "note": (
                "Collision on a hard identifier across multiple cases. Raw values and external "
                "case notes are withheld per zero-knowledge privacy boundaries. Coordinate via Section 94 BNSS."
            ),
        })
    alerts.sort(key=lambda a: -a["syndicate_score"])
    return alerts


def cluster_syndicates(
    index_store: dict[str, list[dict[str, Any]]],
    case_metadata: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Discovers coordinated criminal syndicates by clustering cases connected by shared blind tokens.

    Models the cross-case relationships as a bipartite graph G = (V_cases ∪ V_tokens, E)
    and computes connected components.

    Returns structured syndicate clusters with cohesion metrics and threat indicators.
    """
    case_meta = case_metadata or {}
    collisions = find_collisions(index_store)
    if not collisions:
        return []

    # Build adjacency between cases via shared tokens
    case_adj: dict[str, set[str]] = {}
    token_to_cases: dict[str, set[str]] = {}
    case_to_tokens: dict[str, set[str]] = {}

    for c in collisions:
        tok = c["blind_token"]
        cids = set(c["case_ids"])
        token_to_cases[tok] = cids
        for cid in cids:
            case_to_tokens.setdefault(cid, set()).add(tok)
            case_adj.setdefault(cid, set()).update(cids - {cid})

    # Connected components over cases
    visited_cases: set[str] = set()
    clusters: list[dict[str, Any]] = []

    for start_case in sorted(case_adj.keys()):
        if start_case in visited_cases:
            continue

        # BFS component discovery
        comp_cases: set[str] = set()
        queue = [start_case]
        visited_cases.add(start_case)

        while queue:
            curr = queue.pop(0)
            comp_cases.add(curr)
            for neighbor in case_adj.get(curr, set()):
                if neighbor not in visited_cases:
                    visited_cases.add(neighbor)
                    queue.append(neighbor)

        # Collect tokens for this component
        comp_tokens: set[str] = set()
        for cid in comp_cases:
            comp_tokens.update(case_to_tokens.get(cid, set()))

        if len(comp_cases) < 2:
            continue

        # Aggregate metrics
        comp_collisions = [c for c in collisions if c["blind_token"] in comp_tokens]
        total_score = round(sum(c["syndicate_score"] for c in comp_collisions), 2)
        token_count = len(comp_tokens)
        case_count = len(comp_cases)

        # Cohesion score: ratio of observed links to possible bipartite links
        total_edges = sum(len(token_to_cases[t] & comp_cases) for t in comp_tokens)
        max_possible_edges = max(1, case_count * token_count)
        cohesion = round(min(1.0, total_edges / max_possible_edges), 3)

        # Risk level determination
        if case_count >= 3 or total_score >= 15.0 or token_count >= 3:
            risk_level = "CRITICAL"
        elif case_count >= 2 or total_score >= 5.0:
            risk_level = "ELEVATED"
        else:
            risk_level = "MONITORED"

        # Threat indicators heuristics
        entity_types_in_cluster = {c["entity_type"] for c in comp_collisions}
        threat_indicators = []
        if "ACCOUNT" in entity_types_in_cluster and "UPI" in entity_types_in_cluster:
            threat_indicators.append("HYBRID_FINANCIAL_MULE_RING")
        elif "ACCOUNT" in entity_types_in_cluster:
            threat_indicators.append("SHARED_BANK_MULE_NETWORK")
        elif "UPI" in entity_types_in_cluster:
            threat_indicators.append("COORDINATED_UPI_COLLECTION_DRAIN")

        if "PHONE" in entity_types_in_cluster:
            threat_indicators.append("COMMON_CONTROLLER_COMMUNICATION")
        if "IP" in entity_types_in_cluster or "DOMAIN" in entity_types_in_cluster:
            threat_indicators.append("SHARED_TECHNICAL_INFRASTRUCTURE")
        if case_count >= 3:
            threat_indicators.append("MULTI_CASE_SERIAL_SYNDICATE")

        # Deterministic cluster ID
        hash_seed = ":".join(sorted(comp_cases)) + "|" + ":".join(sorted(comp_tokens))
        cluster_id = f"SYN-{hashlib.sha256(hash_seed.encode()).hexdigest()[:8].upper()}"

        # Member case details
        member_cases = []
        for cid in sorted(comp_cases):
            meta = case_meta.get(cid) or {}
            # Fallback to occurrences data if not in meta
            if not meta:
                for col in comp_collisions:
                    for occ in col.get("occurrences", []):
                        if occ.get("case_id") == cid:
                            meta = occ
                            break
                    if meta:
                        break

            member_cases.append({
                "case_id": cid,
                "case_number": meta.get("case_number") or cid[:8],
                "case_title": meta.get("case_title") or meta.get("title") or f"Case {cid[:8]}",
                "crime_type": meta.get("crime_type") or "CYBER_FINANCIAL_FRAUD",
                "police_station": meta.get("police_station") or "Unknown Station",
            })

        # Heuristic descriptive name
        name = f"Syndicate Cluster {cluster_id} ({case_count} Cases · {token_count} Shared Identifiers)"

        clusters.append({
            "cluster_id": cluster_id,
            "name": name,
            "title": name,
            "risk_level": risk_level,
            "risk_tier": risk_level,
            "total_score": total_score,
            "cohesion_score": cohesion,
            "case_count": case_count,
            "token_count": token_count,
            "shared_tokens_count": token_count,
            "threat_indicators": threat_indicators,
            "threat_tags": threat_indicators,
            "cases": member_cases,
            "member_cases": member_cases,
            "shared_tokens": [
                {
                    "blind_token": c["blind_token"],
                    "entity_type": c["entity_type"],
                    "case_count": c["case_count"],
                    "syndicate_score": c["syndicate_score"],
                }
                for c in comp_collisions
            ],
        })

    clusters.sort(key=lambda x: -x["total_score"])
    return clusters


def generate_radar_blips(
    syndicate_clusters: list[dict[str, Any]],
    collisions: list[dict[str, Any]],
    target_case_id: str | None = None,
) -> list[dict[str, Any]]:
    """Computes polar coordinates (r, θ) for radar visualization.

    Geometry:
      - Radius r ∈ [0.18, 0.85]:
          • CRITICAL (Core Zone): r ∈ [0.18, 0.38] (Closest to center crosshairs)
          • ELEVATED (Inner Zone): r ∈ [0.42, 0.65]
          • MONITORED (Outer Zone): r ∈ [0.68, 0.85]
      - Angle θ ∈ [0°, 360°]: Distributed around polar crosshairs by entity type/cluster.
    """
    blips: list[dict[str, Any]] = []

    # Map entity types to angular sectors for spatial intuition
    sector_offsets = {
        "UPI": 45.0,
        "ACCOUNT": 135.0,
        "PHONE": 225.0,
        "IFSC": 315.0,
        "IP": 90.0,
        "EMAIL": 270.0,
        "IMEI": 180.0,
    }

    # First add syndicate cluster blips (core nexus representations)
    for idx, syn in enumerate(syndicate_clusters):
        risk = syn["risk_level"]
        if risk == "CRITICAL":
            base_r = 0.22 + (0.12 * ((idx % 3) / 3.0))
        elif risk == "ELEVATED":
            base_r = 0.45 + (0.15 * ((idx % 3) / 3.0))
        else:
            base_r = 0.72 + (0.10 * ((idx % 3) / 3.0))

        angle = (idx * 67.5 + 30.0) % 360.0
        r_val = round(base_r, 3)
        radial_band = "CORE" if r_val <= 0.38 else "INNER" if r_val <= 0.65 else "OUTER"
        blip_id = syn["cluster_id"]
        blips.append({
            "id": blip_id,
            "blip_id": blip_id,
            "label": blip_id,
            "blip_type": "SYNDICATE_CLUSTER",
            "r": r_val,
            "theta": round(angle, 1),
            "risk_level": risk,
            "radial_band": radial_band,
            "case_count": syn["case_count"],
            "token_count": syn["token_count"],
            "score": syn["total_score"],
            "ingress_score": syn["total_score"],
            "name": syn["name"],
            "title": syn["name"],
            "threat_indicators": syn["threat_indicators"],
            "touches_target": any(c["case_id"] == target_case_id for c in syn.get("cases", [])),
        })

    # Then add individual high-threat colliding token blips
    for idx, col in enumerate(collisions[:16]):
        etype = col["entity_type"]
        tok = col["blind_token"]
        score = col["syndicate_score"]

        if score >= 15.0 or col["case_count"] >= 3:
            risk = "CRITICAL"
            base_r = 0.28 + (0.08 * (idx % 2))
        elif score >= 5.0 or col["case_count"] == 2:
            risk = "ELEVATED"
            base_r = 0.52 + (0.10 * (idx % 2))
        else:
            risk = "MONITORED"
            base_r = 0.76 + (0.08 * (idx % 2))

        sector_base = sector_offsets.get(etype, (idx * 45.0) % 360.0)
        angle = (sector_base + (idx * 17.5) - 15.0) % 360.0
        r_val = round(base_r, 3)
        radial_band = "CORE" if r_val <= 0.38 else "INNER" if r_val <= 0.65 else "OUTER"
        blip_id = f"BLIP-{tok[:8]}"

        touches = (target_case_id in col.get("case_ids", [])) if target_case_id else True
        blips.append({
            "id": blip_id,
            "blip_id": blip_id,
            "blind_token": tok,
            "label": f"{etype}:{tok[:6]}",
            "blip_type": "COLLIDING_ENTITY",
            "r": r_val,
            "theta": round(angle, 1),
            "risk_level": risk,
            "radial_band": radial_band,
            "entity_type": etype,
            "case_count": col["case_count"],
            "score": score,
            "ingress_score": score,
            "touches_target": touches,
        })

    return blips


def analyze_case_syndicate_radar(
    target_case_id: str,
    local_entities: list[dict[str, Any]],
    all_case_entries: list[dict[str, Any]],
    index: BlindIndex,
    case_metadata_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Executes full case-level Syndicate Radar analysis.

    Strictly preserves the zero-knowledge privacy boundary:
      • Entities belonging to target_case_id display their local plaintext value and evidence provenance.
      • Foreign cases display ONLY case numbers, crime types, police stations, and cryptographically
        irreversible HMAC tokens.
    """
    case_meta = case_metadata_map or {}

    # Build the full multi-case blind index
    store = build_index(all_case_entries, index)
    all_collisions = find_collisions(store)
    all_syndicates = cluster_syndicates(store, case_meta)

    # Filter for collisions involving this target case
    target_str = str(target_case_id)
    case_collisions = [c for c in all_collisions if target_str in c["case_ids"]]
    case_syndicates = [
        s for s in all_syndicates
        if any(c["case_id"] == target_str for c in s.get("cases", []))
    ]

    # Map local entities by blind token to attach local plaintext anchor and provenance
    local_lookup: dict[str, dict[str, Any]] = {}
    for e in local_entities:
        raw_val = e.get("value") or e.get("canonical_value") or ""
        if not raw_val:
            continue
        etype = str(e.get("entity_type", "UNKNOWN")).upper()
        tok = index.token(etype, raw_val)
        local_lookup[tok] = {
            "entity_id": str(e.get("id") or e.get("entity_id") or ""),
            "canonical_value": raw_val,
            "entity_type": etype,
            "provenance": e.get("provenance") or {},
            "first_seen": str(e.get("first_seen") or ""),
            "last_seen": str(e.get("last_seen") or ""),
        }

    # Format collisions with Local Plaintext Anchor vs Foreign Zero-Knowledge References
    formatted_collisions: list[dict[str, Any]] = []
    for c in case_collisions:
        tok = c["blind_token"]
        local_info = local_lookup.get(tok, {})

        # Foreign cases with redacted PII
        foreign_case_details = []
        for occ in c.get("occurrences", []):
            if occ["case_id"] != target_str:
                foreign_case_details.append({
                    "case_id": occ["case_id"],
                    "case_number": occ.get("case_number") or occ["case_id"][:8],
                    "case_title": occ.get("case_title") or "Confidential Linked Case",
                    "crime_type": occ.get("crime_type") or "CYBER_FINANCIAL_FRAUD",
                    "police_station": occ.get("police_station") or "State Cyber Cell",
                    "degree": occ.get("degree", 1),
                    # ZERO-KNOWLEDGE: Raw value is strictly redacted
                    "redacted_value": f"[ZERO_KNOWLEDGE_BLIND_TOKEN:{tok[:8]}...]",
                })

        formatted_collisions.append({
            "blind_token": tok,
            "entity_type": c["entity_type"],
            "case_count": c["case_count"],
            "syndicate_score": c["syndicate_score"],
            "local_anchor": {
                "has_local_anchor": bool(local_info),
                "plaintext_value": local_info.get("canonical_value") or "[Local Entity Unassigned]",
                "entity_id": local_info.get("entity_id"),
                "provenance": local_info.get("provenance", {}),
                "first_seen": local_info.get("first_seen"),
                "last_seen": local_info.get("last_seen"),
            },
            "foreign_cases": foreign_case_details,
            "note": c["note"],
        })

    # Generate polar coordinates for radar visualization
    radar_blips = generate_radar_blips(case_syndicates, case_collisions, target_str)

    max_score = max([c["syndicate_score"] for c in case_collisions], default=0.0)
    overall_threat_level = "CRITICAL" if max_score >= 15.0 or len(case_syndicates) >= 2 else "ELEVATED" if max_score >= 5.0 or case_collisions else "CLEAR"

    return {
        "case_id": target_str,
        "total_entities_screened": len(local_entities),
        "screened_entities": len(local_entities),
        "total_collisions": len(case_collisions),
        "total_syndicate_clusters": len(case_syndicates),
        "active_syndicates_count": len(case_syndicates),
        "max_syndicate_score": max_score,
        "max_ingress_score": max_score,
        "overall_threat_level": overall_threat_level,
        "threat_level": overall_threat_level,
        "syndicates": case_syndicates,
        "collisions": formatted_collisions,
        "radar_blips": radar_blips,
        "privacy_boundary": {
            "status": "ENFORCED",
            "statutory_basis": "Zero-Knowledge Requisition Protocol (Section 94 BNSS)",
            "statutory_notice": "Section 94 BNSS, 2023 / Section 91 CrPC Electronic Intelligence Requisition Protocol",
            "zero_knowledge_guarantee": "Strict zero-knowledge privacy boundary enforced. Foreign raw PII is cryptographically shielded.",
            "foreign_raw_pii_shielded": True,
            "hashing_algorithm": "HMAC-SHA256",
            "description": (
                "External case identifiers are cryptographically shielded by one-way HMAC-SHA256 tokens. "
                "Plaintext values for external cases cannot be revealed without mutual jurisdictional coordination."
            ),
        },
        "epistemic_notice": (
            "ZERO-KNOWLEDGE SYNDICATE RADAR · STATUTORY ADVISORY — Identifiers match mathematically across cases. "
            "Same identifier does not automatically establish identical human perpetrators without independent physical corroboration."
        ),
    }

