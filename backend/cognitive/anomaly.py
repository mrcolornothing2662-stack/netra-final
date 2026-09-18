"""CyberDrishti AI — Behavioral Anomaly Profiler (Feature 02)

Deterministic, grounded behavioral baseline profiling and anomaly detection.
Computes empirical per-entity baselines across multiple evidence modalities:
  1. Financial volume & velocity:
     - Mean, standard deviation, median, MAD (Median Absolute Deviation).
     - Transaction amount spikes via robust Z-score (standard or MAD).
     - Rapid pass-through turnover (inbound credit followed by outbound debit
       within a short time window with high retention drainage).
  2. Circadian / temporal distribution:
     - Off-hours activity surges (00:00 - 05:00) contrasting with daytime baseline.
  3. Multi-source spatial velocity:
     - Fuses telecom CDRs (File 04) and physical cell-site timeline observations
       (File 09) using conservative haversine physics and clock drift tolerance.

Epistemic Humility Standard:
  - Statements report observed deviations from the empirical baseline:
    "This behavior deviates from the established baseline (Z = 3.24, p < 0.01)."
  - The engine NEVER asserts criminal guilt or labels an entity as a "mule".
  - Reports sample size N and calculation method (standard_z vs mad_small_sample).
  - Explicitly abstains when N < 3 rather than hallucinating baselines.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from cognitive.contradiction import haversine_km, parse_ts

# ── City Centroid Database (for resolving tower-derived or city-level observations)
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    "chandigarh":  (30.7333, 76.7794),
    "mohali":      (30.7046, 76.7179),
    "panchkula":   (30.6942, 76.8606),
    "delhi":       (28.6139, 77.2090),
    "new delhi":   (28.6139, 77.2090),
    "noida":       (28.5355, 77.3910),
    "gurugram":    (28.4595, 77.0266),
    "gurgaon":     (28.4595, 77.0266),
    "mumbai":      (19.0760, 72.8777),
    "hyderabad":   (17.3850, 78.4867),
    "bengaluru":   (12.9716, 77.5946),
    "bangalore":   (12.9716, 77.5946),
    "kolkata":     (22.5726, 88.3639),
    "chennai":     (13.0827, 80.2707),
    "pune":        (18.5204, 73.8567),
    "jaipur":      (26.9124, 75.7873),
    "amritsar":    (31.6340, 74.8723),
    "ludhiana":    (30.9010, 75.8573),
}

# Prefix-to-city mapping for structured cell-site identifiers (e.g. CHD-CELL-17)
TOWER_PREFIX_MAP: dict[str, str] = {
    "CHD": "chandigarh",
    "MOH": "mohali",
    "PUN": "panchkula",
    "DEL": "delhi",
    "NOI": "noida",
    "GUR": "gurugram",
    "HYD": "hyderabad",
    "MUM": "mumbai",
    "BLR": "bengaluru",
}


def resolve_coordinates(event: dict[str, Any]) -> tuple[float, float] | None:
    """Extract or resolve lat/lon coordinates from event metadata."""
    lat = event.get("lat")
    lon = event.get("lon")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (ValueError, TypeError):
            pass

    # Try city name
    city = str(event.get("city") or "").strip().lower()
    if city in CITY_COORDINATES:
        return CITY_COORDINATES[city]

    # Try cell tower identifier
    tower = str(event.get("cell_tower") or event.get("cell_id") or event.get("source") or "").strip().upper()
    prefix = tower.split("-")[0] if "-" in tower else ""
    if prefix in TOWER_PREFIX_MAP:
        city_name = TOWER_PREFIX_MAP[prefix]
        return CITY_COORDINATES.get(city_name)

    return None


# ── Statistics Helpers ────────────────────────────────────────────────────────

def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float], mean_val: float | None = None) -> float:
    if len(values) < 2:
        return 0.0
    m = mean_val if mean_val is not None else _mean(values)
    variance = sum((x - m) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid] if n % 2 != 0 else (s[mid - 1] + s[mid]) / 2.0)


def _mad(values: Sequence[float], med_val: float | None = None) -> float:
    """Median Absolute Deviation (MAD)."""
    if not values:
        return 0.0
    m = med_val if med_val is not None else _median(values)
    deviations = [abs(x - m) for x in values]
    return _median(deviations)


# ── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class AnomalyFinding:
    """One grounded behavioral anomaly finding with strict epistemic status."""
    anomaly_type: str        # TRANSACTION_SPIKE | RAPID_PASS_THROUGH | CIRCADIAN_OFF_HOURS | IMPOSSIBLE_TRAVEL
    entity: str
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW
    title: str
    description: str
    confidence: float
    epistemic_status: str    # STATISTICAL_INFERENCE | OBSERVED
    component_scores: dict[str, Any] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    reasoning: str = ""
    event_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EntityProfile:
    """Empirical behavioral profile for a single entity."""
    entity: str
    entity_type: str = "UNKNOWN"
    total_events: int = 0
    # Financial metrics
    txn_count: int = 0
    total_volume: float = 0.0
    mean_amount: float = 0.0
    stdev_amount: float = 0.0
    median_amount: float = 0.0
    mad_amount: float = 0.0
    min_amount: float = 0.0
    max_amount: float = 0.0
    baseline_status: str = "insufficient_sample"  # insufficient_sample | established
    # Temporal metrics
    total_active_hours: int = 0
    off_hours_count: int = 0    # 00:00 - 05:00
    daytime_count: int = 0      # 08:00 - 20:00
    off_hours_ratio: float = 0.0
    # Velocity / Pass-through metrics
    pass_through_count: int = 0
    min_pass_through_min: float | None = None
    # Locations
    locations_seen: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Profile Building ──────────────────────────────────────────────────────────

def build_entity_profiles(
    bank_events: Sequence[dict[str, Any]],
    call_events: Sequence[dict[str, Any]],
    location_events: Sequence[dict[str, Any]],
) -> dict[str, EntityProfile]:
    """
    Construct empirical behavioral profiles for all entities observed in evidence.
    """
    by_entity: dict[str, dict[str, Any]] = {}

    def _ensure(ent: str, etype: str = "UNKNOWN") -> dict[str, Any]:
        if ent not in by_entity:
            by_entity[ent] = {
                "entity": ent,
                "entity_type": etype,
                "amounts": [],
                "event_timestamps": [],
                "locations": set(),
                "all_events": [],
                "credits": [],
                "debits": [],
            }
        return by_entity[ent]

    def _safe_float(val: Any) -> float:
        try:
            if val is None or val == "":
                return 0.0
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    # Process bank / UPI events
    for ev in bank_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        amount = _safe_float(meta.get("amount_val") or meta.get("amount"))
        credit = _safe_float(meta.get("credit"))
        debit = _safe_float(meta.get("debit"))
        ts_str = ev.get("timestamp") or ev.get("event_timestamp") or ""

        from_acc = meta.get("from_account") or meta.get("from") or ev.get("from_account") or ev.get("from")
        to_acc = meta.get("to_account") or meta.get("to") or ev.get("to_account") or ev.get("to")
        acc = meta.get("account") or ev.get("account")

        # 1. Source / sender account -> OUTFLOW (debit)
        if from_acc:
            rec = _ensure(str(from_acc), "UPI_ID" if "@" in str(from_acc) else "BANK_ACCOUNT")
            val = debit or amount
            if val > 0:
                rec["amounts"].append(val)
                rec["debits"].append((ts_str, val, ev))
            if ts_str:
                rec["event_timestamps"].append(ts_str)
            rec["all_events"].append(ev)

        # 2. Destination / receiver account -> INFLOW (credit)
        if to_acc:
            rec = _ensure(str(to_acc), "UPI_ID" if "@" in str(to_acc) else "BANK_ACCOUNT")
            val = credit or amount
            if val > 0:
                rec["amounts"].append(val)
                rec["credits"].append((ts_str, val, ev))
            if ts_str:
                rec["event_timestamps"].append(ts_str)
            rec["all_events"].append(ev)

        # 3. Single-party account ledger (where from_acc/to_acc are absent or distinct)
        if acc and acc != from_acc and acc != to_acc:
            rec = _ensure(str(acc), "UPI_ID" if "@" in str(acc) else "BANK_ACCOUNT")
            if credit > 0:
                rec["amounts"].append(credit)
                rec["credits"].append((ts_str, credit, ev))
            if debit > 0:
                rec["amounts"].append(debit)
                rec["debits"].append((ts_str, debit, ev))
            if credit <= 0 and debit <= 0 and amount > 0:
                rec["amounts"].append(amount)
            if ts_str:
                rec["event_timestamps"].append(ts_str)
            rec["all_events"].append(ev)

    # Process call events
    for ev in call_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        caller = meta.get("caller") or ev.get("entity")
        callee = meta.get("callee")
        ts_str = ev.get("timestamp") or ev.get("event_timestamp") or ""
        cell = meta.get("cell_id") or meta.get("source")

        for ent in [caller, callee]:
            if not ent or ent == "?":
                continue
            rec = _ensure(ent, "PHONE")
            if ts_str:
                rec["event_timestamps"].append(ts_str)
            if cell:
                rec["locations"].add(str(cell))
            rec["all_events"].append(ev)

    # Process location timeline events
    for ev in location_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        phone = meta.get("phone") or ev.get("entity")
        ts_str = ev.get("timestamp") or ev.get("event_timestamp") or ""
        loc = meta.get("cell_tower") or meta.get("city") or meta.get("location_reference")

        if phone:
            rec = _ensure(phone, "PHONE")
            if ts_str:
                rec["event_timestamps"].append(ts_str)
            if loc:
                rec["locations"].add(str(loc))
            rec["all_events"].append(ev)

    # Compute baseline metrics per entity
    profiles: dict[str, EntityProfile] = {}
    for ent, data in by_entity.items():
        amounts = data["amounts"]
        ts_list = data["event_timestamps"]
        n_amounts = len(amounts)

        mean_amt = _mean(amounts) if n_amounts > 0 else 0.0
        sd_amt = _stdev(amounts, mean_amt) if n_amounts >= 2 else 0.0
        med_amt = _median(amounts) if n_amounts > 0 else 0.0
        mad_amt = _mad(amounts, med_amt) if n_amounts > 0 else 0.0
        min_amt = min(amounts) if n_amounts > 0 else 0.0
        max_amt = max(amounts) if n_amounts > 0 else 0.0
        tot_vol = sum(amounts)

        # Circadian distribution
        off_hours = 0
        daytime = 0
        for ts in ts_list:
            try:
                dt = parse_ts(ts)
                hr = dt.hour
                if 0 <= hr < 5:
                    off_hours += 1
                elif 8 <= hr < 20:
                    daytime += 1
            except Exception:
                pass

        total_ts = len(ts_list)
        off_ratio = round(off_hours / total_ts, 3) if total_ts > 0 else 0.0

        # Pass-through turnaround time
        min_pass_min = None
        pass_count = 0
        credits = data["credits"]
        debits = data["debits"]
        for c_ts, c_amt, _ in credits:
            if not c_ts:
                continue
            try:
                dt_c = parse_ts(c_ts)
            except Exception:
                continue
            for d_ts, d_amt, _ in debits:
                if not d_ts:
                    continue
                try:
                    dt_d = parse_ts(d_ts)
                except Exception:
                    continue
                gap_sec = (dt_d - dt_c).total_seconds()
                if 0 < gap_sec <= 3600:  # Within 1 hour
                    retention = min(c_amt, d_amt) / max(c_amt, d_amt)
                    if retention >= 0.85:  # >=85% funds drained
                        gap_min = round(gap_sec / 60.0, 1)
                        pass_count += 1
                        if min_pass_min is None or gap_min < min_pass_min:
                            min_pass_min = gap_min

        profiles[ent] = EntityProfile(
            entity=ent,
            entity_type=data["entity_type"],
            total_events=len(data["all_events"]),
            txn_count=n_amounts,
            total_volume=round(tot_vol, 2),
            mean_amount=round(mean_amt, 2),
            stdev_amount=round(sd_amt, 2),
            median_amount=round(med_amt, 2),
            mad_amount=round(mad_amt, 2),
            min_amount=round(min_amt, 2),
            max_amount=round(max_amt, 2),
            baseline_status="established" if n_amounts >= 3 else "insufficient_sample",
            total_active_hours=len(set(parse_ts(ts).hour for ts in ts_list if ts)),
            off_hours_count=off_hours,
            daytime_count=daytime,
            off_hours_ratio=off_ratio,
            pass_through_count=pass_count,
            min_pass_through_min=min_pass_min,
            locations_seen=sorted(list(data["locations"])),
        )

    return profiles


# ── Anomaly Detectors ─────────────────────────────────────────────────────────

def detect_transaction_spikes(
    bank_events: Sequence[dict[str, Any]],
    profiles: dict[str, EntityProfile],
    z_critical: float = 3.0,
    z_high: float = 2.0,
) -> list[AnomalyFinding]:
    """
    Detect statistically anomalous transaction amounts using robust Z-score.
    - Uses standard Z-score when N >= 10.
    - Uses modified MAD Z-score when 3 <= N < 10 (small-sample outlier resistance).
    - Abstains when N < 3 (insufficient baseline).
    """
    findings: list[AnomalyFinding] = []

    for ev in bank_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        amount = float(meta.get("amount_val") or meta.get("amount") or meta.get("credit") or meta.get("debit") or 0.0)
        if amount <= 0:
            continue

        accounts = [
            meta.get("from_account") or meta.get("from") or ev.get("from_account") or ev.get("from"),
            meta.get("to_account") or meta.get("to") or ev.get("to_account") or ev.get("to"),
            meta.get("account") or ev.get("account"),
        ]
        for ent in accounts:
            if not ent or ent not in profiles:
                continue
            prof = profiles[ent]
            if prof.baseline_status != "established" or prof.txn_count < 3:
                continue

            z_val: float = 0.0
            calc_method = ""
            if prof.txn_count >= 10 and prof.stdev_amount > 0:
                z_val = (amount - prof.mean_amount) / prof.stdev_amount
                calc_method = "standard_z"
            elif prof.mad_amount > 0:
                # Boris Iglewicz and David Hoaglin (1993) modified Z-score
                z_val = 0.6745 * (amount - prof.median_amount) / prof.mad_amount
                calc_method = "mad_small_sample"
            else:
                continue

            if z_val >= z_high:
                severity = "CRITICAL" if z_val >= z_critical else "HIGH"
                confidence = min(0.98, round(0.70 + (z_val / 10.0), 2))
                ref = meta.get("ref_no") or ev.get("id") or "TXN"
                p_val_bound = "< 0.003" if z_val >= 3.0 else "< 0.05"

                findings.append(AnomalyFinding(
                    anomaly_type="TRANSACTION_SPIKE",
                    entity=ent,
                    severity=severity,
                    title=f"Transaction volume deviation: {ent} (Z = {z_val:.2f})",
                    description=(
                        f"Observed transaction amount ₹{amount:,.2f} ({ref}) deviates from "
                        f"{ent}'s baseline (mean ₹{prof.mean_amount:,.2f}, median ₹{prof.median_amount:,.2f}) "
                        f"with a statistical score of Z = {z_val:.2f} ({calc_method}, p {p_val_bound})."
                    ),
                    confidence=confidence,
                    epistemic_status="STATISTICAL_INFERENCE",
                    component_scores={
                        "observed_amount": amount,
                        "mean_amount": prof.mean_amount,
                        "median_amount": prof.median_amount,
                        "z_score": round(z_val, 2),
                        "sample_size_n": prof.txn_count,
                        "method": calc_method,
                    },
                    reason_codes=["TRANSACTION_SPIKE", calc_method],
                    reasoning=(
                        f"Statistical anomaly detected: observed amount exceeds established baseline "
                        f"by {z_val:.2f} standard units. Investigative review required to determine factual context."
                    ),
                    event_refs=[str(ev.get("id") or ev.get("event_id") or "")],
                    evidence_refs=[str(ev.get("evidence_file_id") or "")],
                    citations=[{
                        "entity": ent,
                        "ref_no": ref,
                        "amount": amount,
                        "z_score": round(z_val, 2),
                    }],
                ))

    return findings


def detect_pass_through_turnover(
    bank_events: Sequence[dict[str, Any]],
    max_gap_minutes: float = 30.0,
    min_turnover_ratio: float = 0.85,
) -> list[AnomalyFinding]:
    """
    Detect rapid pass-through velocity: inbound credit followed by an outbound
    debit within max_gap_minutes draining >= min_turnover_ratio of received funds.
    """
    findings: list[AnomalyFinding] = []
    acc_credits: dict[str, list[tuple[datetime, float, dict[str, Any]]]] = {}
    acc_debits: dict[str, list[tuple[datetime, float, dict[str, Any]]]] = {}

    for ev in bank_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        amount = float(meta.get("amount_val") or meta.get("amount") or 0.0)
        credit = float(meta.get("credit") or 0.0)
        debit = float(meta.get("debit") or 0.0)
        ts = ev.get("timestamp") or ev.get("event_timestamp")
        if not ts:
            continue
        try:
            dt = parse_ts(ts)
        except Exception:
            continue

        from_acc = meta.get("from_account") or meta.get("from") or ev.get("from_account") or ev.get("from")
        to_acc = meta.get("to_account") or meta.get("to") or ev.get("to_account") or ev.get("to")
        acc = meta.get("account") or ev.get("account")

        # Inflow / credit
        if to_acc:
            c_val = credit or amount
            if c_val > 0:
                acc_credits.setdefault(str(to_acc), []).append((dt, c_val, ev))
        # Outflow / debit
        if from_acc:
            d_val = debit or amount
            if d_val > 0:
                acc_debits.setdefault(str(from_acc), []).append((dt, d_val, ev))

        # Single ledger account
        if acc and acc != from_acc and acc != to_acc:
            if credit > 0:
                acc_credits.setdefault(str(acc), []).append((dt, credit, ev))
            if debit > 0:
                acc_debits.setdefault(str(acc), []).append((dt, debit, ev))

    all_accounts = set(acc_credits.keys()) | set(acc_debits.keys())
    for acc in sorted(all_accounts):
        credits = acc_credits.get(acc, [])
        debits = acc_debits.get(acc, [])

        # Check pairs
        for c_dt, c_val, c_ev in credits:
            for d_dt, d_val, d_ev in debits:
                gap_s = (d_dt - c_dt).total_seconds()
                if 0 <= gap_s <= (max_gap_minutes * 60.0):
                    turnover_ratio = min(c_val, d_val) / max(c_val, d_val)
                    if turnover_ratio >= min_turnover_ratio:
                        gap_min = round(gap_s / 60.0, 1)
                        pct = round(turnover_ratio * 100.0, 1)
                        c_ref = (c_ev.get("metadata") or {}).get("ref_no") or "credit"
                        d_ref = (d_ev.get("metadata") or {}).get("ref_no") or "debit"

                        findings.append(AnomalyFinding(
                            anomaly_type="RAPID_PASS_THROUGH",
                            entity=acc,
                            severity="CRITICAL",
                            title=f"Rapid pass-through velocity: {acc} ({gap_min}m turnaround)",
                            description=(
                                f"Account {acc} received credit of ₹{c_val:,.2f} ({c_ref}) and disbursed "
                                f"₹{d_val:,.2f} ({d_ref}) within {gap_min} minutes, retaining only "
                                f"{100.0 - pct:.1f}% of received funds ({pct}% turnover ratio)."
                            ),
                            confidence=0.96,
                            epistemic_status="OBSERVED",
                            component_scores={
                                "credit_amount": c_val,
                                "debit_amount": d_val,
                                "time_gap_minutes": gap_min,
                                "turnover_ratio": turnover_ratio,
                            },
                            reason_codes=["RAPID_PASS_THROUGH", "high_velocity_drainage"],
                            reasoning=(
                                f"Observed temporal sequence exhibits rapid fund turnover: credit followed "
                                f"by debit in {gap_min} minutes with {pct}% turnover. High velocity "
                                f"interposition pattern requiring investigative verification."
                            ),
                            event_refs=[
                                str(c_ev.get("id") or c_ev.get("event_id") or ""),
                                str(d_ev.get("id") or d_ev.get("event_id") or ""),
                            ],
                            evidence_refs=[
                                str(c_ev.get("evidence_file_id") or ""),
                                str(d_ev.get("evidence_file_id") or ""),
                            ],
                            citations=[{
                                "account": acc,
                                "credit_ref": c_ref,
                                "debit_ref": d_ref,
                                "time_gap_minutes": gap_min,
                                "turnover_percent": pct,
                            }],
                        ))

    return findings


def detect_circadian_anomalies(
    events: Sequence[dict[str, Any]],
    profiles: dict[str, EntityProfile],
    min_off_hours_events: int = 2,
) -> list[AnomalyFinding]:
    """
    Detect circadian oddity: an entity with an established daytime baseline
    suddenly generating concentrated activity during off-hours (00:00 - 05:00).
    """
    findings: list[AnomalyFinding] = []

    for ent, prof in profiles.items():
        if prof.total_events < 5:
            continue
        # Daytime baseline: >=70% daytime activity historically
        daytime_ratio = prof.daytime_count / prof.total_events if prof.total_events else 0.0
        if daytime_ratio >= 0.70 and prof.off_hours_count >= min_off_hours_events:
            findings.append(AnomalyFinding(
                anomaly_type="CIRCADIAN_OFF_HOURS",
                entity=ent,
                severity="MEDIUM",
                title=f"Circadian activity deviation: {ent}",
                description=(
                    f"Entity {ent} has an established daytime pattern ({daytime_ratio*100:.0f}% daytime events), "
                    f"but exhibited {prof.off_hours_count} event(s) during off-hours (00:00 - 05:00)."
                ),
                confidence=0.82,
                epistemic_status="STATISTICAL_INFERENCE",
                component_scores={
                    "off_hours_count": prof.off_hours_count,
                    "daytime_ratio": round(daytime_ratio, 2),
                    "off_hours_ratio": prof.off_hours_ratio,
                },
                reason_codes=["CIRCADIAN_OFF_HOURS", "nocturnal_surge"],
                reasoning=(
                    f"Temporal activity profile deviates from regular daytime baseline. "
                    f"Off-hours activity clusters warrant chronological review."
                ),
            ))

    return findings


def detect_fused_travel(
    call_events: Sequence[dict[str, Any]],
    location_events: Sequence[dict[str, Any]],
    impossible_kmh: float = 900.0,
    suspicious_kmh: float = 200.0,
    clock_tolerance_s: int = 600,
) -> list[AnomalyFinding]:
    """
    Multi-source spatial velocity detection fusing telecom CDRs and cell-site timeline observations.
    """
    all_events: list[dict[str, Any]] = []

    for ev in call_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        coords = resolve_coordinates(meta)
        ent = meta.get("caller") or ev.get("entity")
        ts = ev.get("timestamp") or ev.get("event_timestamp")
        if coords and ent and ts:
            all_events.append({
                "entity": str(ent),
                "timestamp": ts,
                "lat": coords[0],
                "lon": coords[1],
                "source": meta.get("cell_id") or "CDR",
                "event_id": ev.get("id") or ev.get("event_id"),
                "evidence_file_id": ev.get("evidence_file_id"),
            })

    for ev in location_events:
        meta = ev.get("metadata") or ev.get("event_metadata") or ev
        coords = resolve_coordinates(meta)
        ent = meta.get("phone") or ev.get("entity")
        ts = ev.get("timestamp") or ev.get("event_timestamp")
        if coords and ent and ts:
            all_events.append({
                "entity": str(ent),
                "timestamp": ts,
                "lat": coords[0],
                "lon": coords[1],
                "source": meta.get("cell_tower") or meta.get("city") or "LocationTimeline",
                "event_id": ev.get("id") or ev.get("event_id"),
                "evidence_file_id": ev.get("evidence_file_id"),
            })

    # Group by entity
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for ev in all_events:
        by_entity.setdefault(ev["entity"], []).append(ev)

    findings: list[AnomalyFinding] = []
    for ent, ev_list in by_entity.items():
        ev_list.sort(key=lambda e: parse_ts(e["timestamp"]))
        for i in range(len(ev_list) - 1):
            a, b = ev_list[i], ev_list[i + 1]
            gap_s = (parse_ts(b["timestamp"]) - parse_ts(a["timestamp"])).total_seconds()
            if gap_s < 60:
                continue

            dist_km = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            v_lower = dist_km / ((gap_s + clock_tolerance_s) / 3600.0)
            v_naive = (dist_km / gap_s) * 3600.0

            kind = None
            if v_lower > impossible_kmh:
                kind = "IMPOSSIBLE_TRAVEL"
                severity = "CRITICAL"
            elif v_naive > suspicious_kmh:
                kind = "SUSPICIOUS_VELOCITY"
                severity = "HIGH"

            if kind:
                findings.append(AnomalyFinding(
                    anomaly_type=kind,
                    entity=ent,
                    severity=severity,
                    title=f"{kind.replace('_', ' ').title()}: {ent} ({v_lower:.0f} km/h)",
                    description=(
                        f"Entity {ent} recorded movement of {dist_km:.1f} km between {a['source']} "
                        f"and {b['source']} in {gap_s/60:.0f} minutes (lower bound speed {v_lower:.0f} km/h "
                        f"even with ±{clock_tolerance_s//60} min clock tolerance). Exceeds plausible speed."
                    ),
                    confidence=0.92 if kind == "IMPOSSIBLE_TRAVEL" else 0.80,
                    epistemic_status="STATISTICAL_INFERENCE",
                    component_scores={
                        "distance_km": round(dist_km, 1),
                        "time_gap_seconds": gap_s,
                        "velocity_kmh": round(v_lower, 1),
                        "source_a": a["source"],
                        "source_b": b["source"],
                    },
                    reason_codes=[kind, "cell_site_displacement"],
                    reasoning=(
                        f"Tower/cell-site association delta yields physically implausible velocity ({v_lower:.0f} km/h). "
                        f"Potential indicators include simultaneous device usage, cloned identifier, or multi-party handover."
                    ),
                    event_refs=[str(x) for x in (a.get("event_id"), b.get("event_id")) if x],
                    evidence_refs=[str(x) for x in (a.get("evidence_file_id"), b.get("evidence_file_id")) if x],
                    citations=[{
                        "entity": ent,
                        "distance_km": round(dist_km, 1),
                        "velocity_kmh": round(v_lower, 1),
                        "from_loc": a["source"],
                        "to_loc": b["source"],
                    }],
                ))

    return findings


# ── Full Profile & Scan Entrypoint ───────────────────────────────────────────

def scan_behavioral_anomalies(
    bank_events: Sequence[dict[str, Any]],
    call_events: Sequence[dict[str, Any]],
    location_events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """
    Execute full behavioral profiling and multi-modality anomaly detection.
    """
    profiles = build_entity_profiles(bank_events, call_events, location_events)

    spike_findings = detect_transaction_spikes(bank_events, profiles)
    pass_through_findings = detect_pass_through_turnover(bank_events)
    circadian_findings = detect_circadian_anomalies([], profiles)
    travel_findings = detect_fused_travel(call_events, location_events)

    all_findings = spike_findings + pass_through_findings + circadian_findings + travel_findings

    return {
        "profiles": {k: v.to_dict() for k, v in profiles.items()},
        "findings": [f.to_dict() for f in all_findings],
        "summary": {
            "total_entities_profiled": len(profiles),
            "established_baselines": sum(1 for p in profiles.values() if p.baseline_status == "established"),
            "total_anomalies": len(all_findings),
            "by_severity": {
                "CRITICAL": sum(1 for f in all_findings if f.severity == "CRITICAL"),
                "HIGH": sum(1 for f in all_findings if f.severity == "HIGH"),
                "MEDIUM": sum(1 for f in all_findings if f.severity == "MEDIUM"),
                "LOW": sum(1 for f in all_findings if f.severity == "LOW"),
            },
        },
    }
