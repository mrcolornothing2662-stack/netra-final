from __future__ import annotations
"""
CyberDrishti AI — Network Log Parser
Parses structured network log CSV exports (e.g. proxy, firewall, flow logs)
and outputs EvidenceEvent-compatible dicts with event_type='network_log'.
"""
import csv
from datetime import datetime
from pathlib import Path
from typing import Any


_EXPECTED_COLUMNS = {"timestamp", "device", "ip", "destination", "port", "action"}

_DT_FMTS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
]


def _parse_dt(raw: str) -> str | None:
    raw = str(raw).strip()
    if not raw or raw.lower() in ("nan", "none", ""):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in _DT_FMTS:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return None


def is_network_log_header(headers: list[str]) -> bool:
    """Check if the provided header row matches the network log schema."""
    cleaned = {str(h).lower().strip().replace('"', '').replace("'", "") for h in headers if h}
    # Must have ip and at least 3 other key network log fields
    key_fields = {"device", "destination", "port", "action"}
    return "ip" in cleaned and len(key_fields.intersection(cleaned)) >= 2


def parse_network_log_csv(file_path: str | Path, source_doc: str | None = None) -> list[dict[str, Any]]:
    """
    Parse a network log CSV file into structured EvidenceEvent dictionaries.
    
    Expected columns:
      timestamp, device, ip, destination, port, action
    """
    path = Path(file_path)
    source_name = source_doc or path.name

    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return []

    reader = csv.reader(lines)
    header = None
    for row in reader:
        if row and any(c.strip() for c in row):
            header = [c.strip().lower() for c in row]
            break

    if not header or not is_network_log_header(header):
        return []

    col_idx = {h: i for i, h in enumerate(header)}
    events: list[dict[str, Any]] = []

    # Reset reader from line 1
    reader = csv.reader(lines)
    header_seen = False

    for line_idx, row in enumerate(reader, start=1):
        if not row or not any(c.strip() for c in row):
            continue

        if not header_seen:
            header_seen = True
            continue  # Skip header row

        def _get(field: str) -> str | None:
            idx = col_idx.get(field)
            if idx is not None and idx < len(row):
                val = row[idx].strip()
                return val if val.lower() not in ("nan", "none", "") else None
            return None

        ts_raw = _get("timestamp") or _get("time") or _get("date")
        device = _get("device") or _get("device_id")
        ip = _get("ip") or _get("source_ip") or _get("src_ip")
        destination = _get("destination") or _get("dest") or _get("host") or _get("domain")
        port_raw = _get("port") or _get("dest_port") or _get("dst_port")
        action = _get("action") or _get("protocol") or _get("event") or "CONNECTION"

        # Require at least an IP or device to be a valid network event
        if not ip and not device:
            continue

        port: int | None = None
        if port_raw:
            try:
                port = int(port_raw)
            except ValueError:
                pass

        dt_iso = _parse_dt(ts_raw) if ts_raw else None

        # Build clean structured text representation for display and hybrid entity extraction
        dev_str = device or "UNKNOWN_DEVICE"
        ip_str = ip or "UNKNOWN_IP"
        dest_str = destination or "UNKNOWN_DESTINATION"
        port_str = f":{port}" if port is not None else ""
        act_str = f" ({action})" if action else ""
        text = f"{dev_str} [{ip_str}] -> {dest_str}{port_str}{act_str}"

        metadata = {
            "device": device,
            "ip": ip,
            "destination": destination,
            "port": port,
            "action": action,
            "source_doc": source_name,
        }

        events.append({
            "source_doc": source_name,
            "timestamp": dt_iso,
            "text": text,
            "event_type": "network_log",
            "source_line": line_idx,
            "source_page": 1,
            "metadata": metadata,
        })

    return events
