"""Regression guards for the two cognitive-route serialization contracts fixed
during the pipeline-repair campaign:

  (f) TravelFinding serialization — impossible_travel() returns TravelFinding
      dataclasses carrying `event_a` / `event_b` dicts (NOT location_a/_b). The
      contradictions route must adapt them via _loc_label(); this guards the
      real object schema and asserts the location fields the route emits are
      JSON-serializable and MEANINGFUL (source label + coordinates), not just
      that an HTTP call returned 200.
      [cognitive/contradiction.py::TravelFinding, routes/cognitive.py::_loc_label]

  (g) Counterfactual result contract — simulate_freeze() returns
      `completed_transfers` as an int (len of the completed list), and exposes
      NO `completed` key. The route passes completed_transfers straight through
      and only applies len() to the *event lists*. Guards against the
      "len(result['completed'])" / "len(completed_transfers)" regression.
      [cognitive/counterfactual.py::simulate_freeze]

Pure/synchronous — the engines under test take no DB and no event loop.
Dual-mode: `python3 tests/test_regression_cognitive.py` AND pytest-discoverable.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# _loc_label lives in routes.cognitive, whose import constructs the app engine
# from DATABASE_URL. Point it at a throwaway path and silence echo — no DB is
# actually used by these tests.
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.gettempdir()}/_cog_import_guard.db")
os.environ.setdefault("DEBUG", "false")

from cognitive.contradiction import TravelFinding, impossible_travel  # noqa: E402
from cognitive.counterfactual import simulate_freeze  # noqa: E402
from routes.cognitive import _loc_label  # noqa: E402  (the real route serializer)


# ── (f) TravelFinding schema + route serialization ────────────────────────────

def test_travelfinding_schema_has_event_dicts_not_locations():
    """The dataclass exposes event_a/event_b dicts, never location_a/location_b.
    (Emitting location_a/_b directly off the finding was the original bug.)"""
    fields = set(TravelFinding.__dataclass_fields__.keys())
    assert "event_a" in fields and "event_b" in fields, fields
    assert "location_a" not in fields and "location_b" not in fields, fields


def test_impossible_travel_findings_serialize_with_meaningful_locations():
    """Build a genuinely impossible hop (Hyderabad→Delhi in <3 min), then
    reproduce the contradictions-route serialization and assert the location
    fields are real, JSON-serializable strings — not 'None'/empty."""
    events = [
        {"entity": "+91-9000000101", "timestamp": "2026-08-18T04:25:21Z",
         "lat": 17.3850, "lon": 78.4867, "source": "CYB-HYD-03"},
        {"entity": "+91-9000000101", "timestamp": "2026-08-18T04:28:11Z",
         "lat": 28.5355, "lon": 77.3910, "source": "DEL-NOI-02"},
    ]
    findings = impossible_travel(events)
    assert findings, "expected at least one impossible-travel finding"
    f = findings[0]
    assert isinstance(f, TravelFinding)
    assert f.kind == "IMPOSSIBLE_TRAVEL", f.kind
    assert isinstance(f.event_a, dict) and isinstance(f.event_b, dict)

    # Reproduce EXACTLY what routes/cognitive.py::get_contradictions emits.
    serialized = {
        "kind": f.kind, "entity": f.entity,
        "location_a": _loc_label(f.event_a), "location_b": _loc_label(f.event_b),
        "distance_km": f.distance_km, "time_gap_s": f.time_gap_s,
        "velocity_kmh": f.velocity_kmh, "explanation": f.explanation,
        "epistemic_status": f.epistemic_status,
    }
    # Must be JSON-serializable (goes out over HTTP).
    json.dumps(serialized)

    for key in ("location_a", "location_b"):
        loc = serialized[key]
        assert isinstance(loc, str) and loc, f"{key} not a non-empty string: {loc!r}"
        assert loc.lower() not in ("none", "unknown"), f"{key} not meaningful: {loc!r}"
    # The endpoint mapping preserves the two distinct tower sources + coords.
    assert "CYB-HYD-03" in serialized["location_a"] and "17.3850" in serialized["location_a"]
    assert "DEL-NOI-02" in serialized["location_b"] and "28.5355" in serialized["location_b"]
    assert serialized["velocity_kmh"] > 900, serialized["velocity_kmh"]


def test_loc_label_degrades_without_coordinates():
    """No fabrication: missing coords → the source label; nothing → 'unknown'."""
    assert _loc_label({"source": "DEL-IGI-04", "lat": None, "lon": None}) == "DEL-IGI-04"
    assert _loc_label({}) == "unknown"
    assert _loc_label({"source": "T1", "lat": 12.9, "lon": 77.6}) == "T1 (12.9000, 77.6000)"


# ── (g) Counterfactual completed_transfers is a scalar int ────────────────────

def test_simulate_freeze_completed_transfers_is_int_contract():
    transfers = [
        {"from": "VICTIM", "to": "MULE", "amount": 100000, "timestamp": "2026-08-18T09:50:03"},
        {"from": "MULE",   "to": "X",    "amount": 60000,  "timestamp": "2026-08-18T09:50:41"},
        {"from": "MULE",   "to": "Y",    "amount": 30000,  "timestamp": "2026-08-18T09:51:00"},
    ]
    result = simulate_freeze(transfers, "MULE", "2026-08-18T09:50:30")

    # THE contract: completed_transfers is a scalar int, and there is no
    # `completed` list key that a caller might len() by mistake.
    assert isinstance(result["completed_transfers"], int), type(result["completed_transfers"])
    assert "completed" not in result, "resurrected the len()-able 'completed' list key"

    # The route may only len() the event *lists*; guard that they ARE lists and
    # that completed_transfers is NOT a collection (len() must raise).
    assert isinstance(result["blocked_out_events"], list)
    assert isinstance(result["stopped_in_events"], list)
    try:
        len(result["completed_transfers"])  # noqa: F821 — must raise
        raise AssertionError("completed_transfers is len()-able — route would double-count")
    except TypeError:
        pass

    # Deterministic values for this scenario: TX1 completes pre-freeze; the two
    # post-freeze MULE debits are blocked, preserving 60k + 30k.
    assert result["completed_transfers"] == 1, result["completed_transfers"]
    assert len(result["blocked_out_events"]) == 2
    assert result["preserved_total"] == 90000.0, result["preserved_total"]


# ── (h) Timezone-invariant freeze: naive IST == aware IST (+05:30) ────────────

def test_freeze_identical_naive_vs_aware_ist():
    """§1.1 regression: the same Shadow Mule scenario must produce identical
    preserved capital whether event timestamps are naive IST (SQLite path)
    or explicit +05:30 offset-aware (PostgreSQL ``timestamptz`` path).

    Root cause of the original 18/19 on PG: _ts() treated naive timestamps
    as UTC, so when PG returned +05:30 events and the freeze_time was naive,
    the freeze landed 5.5h "after" all transfers → preserved ₹0."""
    transfers_naive = [
        {"from": "VICTIM", "to": "MULE", "amount": 285000, "timestamp": "2026-08-18T09:50:03"},
        {"from": "MULE",   "to": "X",    "amount": 180000, "timestamp": "2026-08-18T09:50:41"},
        {"from": "MULE",   "to": "Y",    "amount": 95000,  "timestamp": "2026-08-18T09:51:02"},
    ]
    transfers_aware = [
        {"from": "VICTIM", "to": "MULE", "amount": 285000, "timestamp": "2026-08-18T09:50:03+05:30"},
        {"from": "MULE",   "to": "X",    "amount": 180000, "timestamp": "2026-08-18T09:50:41+05:30"},
        {"from": "MULE",   "to": "Y",    "amount": 95000,  "timestamp": "2026-08-18T09:51:02+05:30"},
    ]
    freeze_time_naive = "2026-08-18T09:50:30"
    freeze_time_aware = "2026-08-18T09:50:30+05:30"

    r_naive = simulate_freeze(transfers_naive, "MULE", freeze_time_naive)
    r_aware = simulate_freeze(transfers_aware, "MULE", freeze_time_aware)
    r_mixed = simulate_freeze(transfers_aware, "MULE", freeze_time_naive)

    # All three must produce the identical preserved_total: VICTIM→MULE (₹285k)
    # arrives pre-freeze; the two MULE→X/Y debits (₹275k) are blocked post-freeze.
    for label, result in [("naive", r_naive), ("aware", r_aware), ("mixed", r_mixed)]:
        assert result["preserved_total"] == 275000.0, \
            f"{label} preserved {result['preserved_total']}, expected 275000"
        assert result["completed_transfers"] == 1, \
            f"{label} completed {result['completed_transfers']}, expected 1"
        assert len(result["blocked_out_events"]) == 2, \
            f"{label} blocked {len(result['blocked_out_events'])}, expected 2"


# ── Dual-mode runner ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    _tests = [(n, f) for n, f in sorted(globals().items())
              if n.startswith("test_") and callable(f)]
    _failed = 0
    for _name, _fn in _tests:
        try:
            _fn()
            print(f"[PASS] {_name}")
        except Exception as _e:  # noqa: BLE001
            _failed += 1
            import traceback
            print(f"[FAIL] {_name}: {_e!r}")
            traceback.print_exc()
    print(f"\n{len(_tests) - _failed}/{len(_tests)} cognitive-regression checks passed")
    sys.exit(1 if _failed else 0)
