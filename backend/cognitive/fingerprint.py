"""CyberDrishti Feature 1 — Resilient Document Fingerprinting (isolated build).

Detects near-duplicate evidence documents even when renamed, re-saved, or
appended-to, and computes the structural diff so only genuinely new rows are
ingested as new evidence.

Three tiers (SHA-256 stays untouched — it is the chain-of-custody / Section 63
BSA backbone, NOT the dedup mechanism):
  Tier 1  SHA-256            exact byte identity (already exists upstream)
  Tier 2  TLSH (optional)    binary-level fuzzy similarity (import-guarded;
                             production build swaps in py-tlsh)
  Tier 3  MinHash over       content-level similarity on normalized
          canonical tuples   evidence tuples — the deciding tier

No case data, names, or magic numbers are hardcoded: every threshold is a
constructor/config parameter with a documented default. Nothing here writes
to disk or deletes evidence — callers decide what to do with a near-dup.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Sequence

try:  # optional binary-fuzzy tier; production build should provide py-tlsh
    import tlsh as _tlsh  # type: ignore
except Exception:  # pragma: no cover - exercised implicitly when lib absent
    _tlsh = None

DEFAULT_CONFIG: dict[str, Any] = {
    "num_perm": 128,              # MinHash permutations (SE of J-hat <= ~4.4%)
    "seed": 0,                    # deterministic permutation seed
    "tlsh_distance_threshold": 30,  # documented TLSH "very similar" band
    "jaccard_threshold": 0.85,    # symmetric content near-duplicate decision
    "overlap_threshold": 0.90,    # containment: appended/trimmed-row variants
    "overlap_min_tuples": 2,      # don't apply containment to trivial sets
    "review_threshold": 0.45,     # below VARIANT: flag for human review, never auto-link
    "require_shared_key": False,  # guardrail: near-dup must share key_field value
    "key_field": "account",       # which event field the guardrail applies to
    "tuple_fields": ["event_type", "timestamp", "amount", "reference"],
}

#: Normalizer applied per-field when building a canonical tuple. Callers may
#: override per field; normalization is what makes "1,23,456.50" equal "123456.50".
def _normalize_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # try numeric normalization (Indian-format commas, currency marks)
    cleaned = text.replace("₹", "").replace("Rs.", "").replace("INR", "").strip()
    try:
        return str(Decimal(cleaned.replace(",", "")))
    except (InvalidOperation, ValueError):
        pass
    return text.lower()


def _normalize_timestamp(val: Any) -> str:
    if not val:
        return ""
    from datetime import datetime
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        return val.strftime("%Y-%m-%dT%H:%M:%S")
    s = str(val).strip()
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return s.lower()


def canonical_tuple(event: dict[str, Any], fields: Sequence[str]) -> tuple[str, ...]:
    """Canonical, format-insensitive representation of one evidence row."""
    meta = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    def _val(f: str) -> Any:
        v = event.get(f)
        if v is not None and str(v).strip() != "":
            return v
        mv = meta.get(f)
        if mv is not None and str(mv).strip() != "":
            return mv
        if f == "amount":
            return meta.get("amount") or meta.get("debit") or meta.get("credit") or ""
        if f == "reference":
            ref = meta.get("reference") or meta.get("ref_no") or event.get("text") or meta.get("raw_line") or ""
            return str(ref)[:40]
        return ""

    out = []
    for f in fields:
        raw_val = _val(f)
        if f in ("timestamp", "time", "date"):
            out.append(_normalize_timestamp(raw_val))
        else:
            out.append(_normalize_value(raw_val))
    return tuple(out)


def _perm_hash(item: str, perm: int, seed: int) -> int:
    """Deterministic per-permutation 64-bit hash of one item."""
    h = hashlib.blake2b(
        item.encode("utf-8"), digest_size=8,
        person=f"{seed:08x}:{perm:04x}".encode(),
    )
    return int.from_bytes(h.digest(), "big")


@dataclass
class MinHash:
    num_perm: int
    signature: list[int]
    item_count: int

    @classmethod
    def from_items(cls, items: Iterable[str], num_perm: int = 128, seed: int = 0) -> "MinHash":
        items = list(items)
        signature = [min((_perm_hash(i, k, seed) for i in items), default=0) for k in range(num_perm)]
        return cls(num_perm=num_perm, signature=signature, item_count=len(items))

    def estimated_jaccard(self, other: "MinHash") -> float:
        if self.num_perm != other.num_perm:
            raise ValueError("num_perm mismatch")
        if self.item_count == 0 and other.item_count == 0:
            return 1.0
        matches = sum(1 for a, b in zip(self.signature, other.signature) if a == b)
        return matches / self.num_perm


@dataclass
class Fingerprint:
    sha256: str
    minhash: MinHash
    tlsh_hash: str | None
    tuples: set[tuple[str, ...]] = field(repr=False, default_factory=set)
    key_values: frozenset[str] = field(repr=False, default_factory=frozenset)

    @classmethod
    def compute(
        cls,
        raw_bytes: bytes,
        events: Sequence[dict[str, Any]],
        fields: Sequence[str],
        num_perm: int,
        seed: int,
        key_field: str | None = None,
    ) -> "Fingerprint":
        tuples = {canonical_tuple(e, fields) for e in events}
        tuples.discard(tuple("" for _ in fields))
        key_values: frozenset[str] = frozenset()
        if key_field:
            key_values = frozenset(
                v for v in (_normalize_value(e.get(key_field)) for e in events) if v
            )
        tlsh_hash = None
        if _tlsh is not None and len(raw_bytes) >= 256:
            try:
                digest = _tlsh.hash(raw_bytes)
                # TLSH returns the sentinel "TNULL..." for degenerate inputs
                # (too little entropy, e.g. highly repetitive bytes) instead of
                # raising — such digests must not be stored or diffed.
                if (isinstance(digest, str) and len(digest) >= 70
                        and "NULL" not in digest.upper()):
                    tlsh_hash = digest
            except Exception:  # TLSH refuses tiny/degenerate inputs
                tlsh_hash = None
        return cls(
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            minhash=MinHash.from_items(("│".join(t) for t in tuples), num_perm, seed),
            tlsh_hash=tlsh_hash,
            tuples=tuples,
            key_values=key_values,
        )


@dataclass
class DiffResult:
    added: list[tuple[str, ...]]
    removed: list[tuple[str, ...]]
    unchanged: list[tuple[str, ...]]

    @property
    def summary(self) -> dict[str, int]:
        return {
            "added_rows": len(self.added),
            "removed_rows": len(self.removed),
            "unchanged_rows": len(self.unchanged),
        }


class FingerprintEngine:
    """Stateless compare/classify logic. Callers own storage and IO."""

    def __init__(self, config: dict[str, Any] | None = None, **overrides: Any) -> None:
        merged = {**DEFAULT_CONFIG, **(config or {}), **overrides}
        self.config = merged
        self.tlsh_available = _tlsh is not None

    # -- fingerprinting ----------------------------------------------------
    def compute(self, raw_bytes: bytes, events: Sequence[dict[str, Any]]) -> Fingerprint:
        cfg = self.config
        return Fingerprint.compute(
            raw_bytes, events, cfg["tuple_fields"], cfg["num_perm"], cfg["seed"],
            key_field=cfg["key_field"] if cfg["require_shared_key"] else None,
        )

    def structural_diff(
        self,
        old_events: Sequence[dict[str, Any]],
        new_events: Sequence[dict[str, Any]],
    ) -> DiffResult:
        fields = self.config["tuple_fields"]
        old_set = {canonical_tuple(e, fields) for e in old_events}
        new_set = {canonical_tuple(e, fields) for e in new_events}
        old_set.discard(tuple("" for _ in fields))
        new_set.discard(tuple("" for _ in fields))
        return DiffResult(
            added=sorted(new_set - old_set),
            removed=sorted(old_set - new_set),
            unchanged=sorted(old_set & new_set),
        )

    # -- comparison --------------------------------------------------------
    def compare(self, a: Fingerprint, b: Fingerprint) -> dict[str, Any]:
        """Returns verdict + similarity evidence. No side effects."""
        if a.sha256 == b.sha256:
            return {"verdict": "EXACT_DUPLICATE", "jaccard_estimate": 1.0,
                    "tlsh_distance": 0 if a.tlsh_hash else None}
        j_hat = a.minhash.estimated_jaccard(b.minhash)
        tlsh_distance = None
        if a.tlsh_hash and b.tlsh_hash:
            tlsh_distance = _tlsh.diff(a.tlsh_hash, b.tlsh_hash)  # type: ignore[union-attr]
        # Containment (overlap coefficient): stays at 1.0 when rows are merely
        # APPENDED to an existing statement — the core "v2 re-upload" pattern.
        smaller = min(len(a.tuples), len(b.tuples))
        if smaller == 0:
            overlap = 1.0 if not a.tuples and not b.tuples else 0.0
        else:
            overlap = len(a.tuples & b.tuples) / smaller
        containment_hit = (
            smaller >= self.config["overlap_min_tuples"]
            and overlap >= self.config["overlap_threshold"]
        )
        similar_enough = j_hat >= self.config["jaccard_threshold"] or containment_hit
        if similar_enough:
            if self.config["require_shared_key"] and not self._shares_key(a, b):
                verdict = "REVIEW_SIMILAR" if not self.config.get("strict_guardrail") else "DISTINCT"
                return {"verdict": verdict, "jaccard_estimate": j_hat,
                        "containment": round(overlap, 4),
                        "tlsh_distance": tlsh_distance,
                        "reason": ("similar content but no shared key field value — "
                                   "possible same-template forgery; review, do not merge")}
            return {"verdict": "VARIANT", "jaccard_estimate": j_hat,
                    "containment": round(overlap, 4),
                    "tlsh_distance": tlsh_distance}
        best_sim = max(j_hat, overlap)
        if best_sim >= self.config["review_threshold"]:
            return {"verdict": "REVIEW_SIMILAR", "jaccard_estimate": j_hat,
                    "containment": round(overlap, 4),
                    "tlsh_distance": tlsh_distance,
                    "reason": ("partially similar to existing evidence (e.g. an edited "
                               "row) — compare the diff manually before deciding")}
        return {"verdict": "DISTINCT", "jaccard_estimate": j_hat,
                "containment": round(overlap, 4),
                "tlsh_distance": tlsh_distance}

    def _shares_key(self, a: Fingerprint, b: Fingerprint) -> bool:
        """Guardrail: true near-dups of one statement share its key identifiers."""
        if not self.config["key_field"]:
            return False
        return bool(a.key_values & b.key_values)

    def classify_upload(
        self,
        raw_bytes: bytes,
        events: Sequence[dict[str, Any]],
        prior_evidence: Sequence[tuple[str, Fingerprint, Sequence[dict[str, Any]]]],
    ) -> dict[str, Any]:
        """Match an upload against prior evidence within a case.

        prior_evidence: (evidence_id, fingerprint, events) triples.
        Returns the best match verdict; caller decides version linking and
        whether to ingest only diff.added rows.
        """
        fp = self.compute(raw_bytes, events)
        ranked: list[tuple[int, float, str, dict[str, Any], Sequence[dict[str, Any]]]] = []
        for evidence_id, prior_fp, prior_events in prior_evidence:
            result = self.compare(fp, prior_fp)
            result["matched_evidence_id"] = evidence_id
            rank = {"EXACT_DUPLICATE": 2, "VARIANT": 1}.get(result["verdict"], 0)
            ranked.append((rank, result["jaccard_estimate"], evidence_id, result, prior_events))
        if not ranked:
            return {"verdict": "NEW", "jaccard_estimate": None, "tlsh_distance": None,
                    "matched_evidence_id": None}
        ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
        _, _, _, best, best_prior_events = ranked[0]
        if best["verdict"] == "VARIANT":
            best["diff"] = self.structural_diff(best_prior_events, events).summary
        return best


def load_config(path: str) -> dict[str, Any]:
    """Load a config JSON that partially overrides DEFAULT_CONFIG."""
    with open(path, "r", encoding="utf-8") as fh:
        user = json.load(fh)
    unknown = set(user) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    return {**DEFAULT_CONFIG, **user}
