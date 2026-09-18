from __future__ import annotations
"""
CyberDrishti AI — Location / Cell-Site Timeline Parser (Phase 5)

Parses tabular cell-site observation reports (e.g. 09_location_timeline.pdf)
into EvidenceEvent-compatible dicts with event_type="location_timeline".

Schema expected:
  Time | Phone | Location reference | Observation

Extracts:
  - phone: literal value preserved, including synthetic masking (e.g. +91-98XXXX1201)
  - city: city extracted from 'City / Cell-Tower' location reference
  - cell_tower: tower identifier (e.g. CHD-CELL-17)
  - observation: observation note (e.g. Cell-site association)
  - limitation: technical disclaimer preserved as non-inferred metadata
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

LOCATION_DISCLAIMER = (
    "Cell-site association is not precise GPS and should not be "
    "treated as exact physical location without corroboration."
)


def is_location_timeline_header(first_row: list[str]) -> bool:
    """Check if table headers match the location timeline schema."""
    if not first_row or len(first_row) < 4:
        return False
    row_lower = [str(c or "").strip().lower() for c in first_row]
    has_time = any("time" in c or "date" in c for c in row_lower)
    has_phone = any("phone" in c or "mobile" in c for c in row_lower)
    has_loc = any("location" in c for c in row_lower)
    has_obs = any("observation" in c or "cell" in c for c in row_lower)
    return has_time and has_phone and has_loc and has_obs


def parse_location_timeline(
    file_path: str | Path,
    source_doc: str | None = None,
) -> list[dict[str, Any]]:
    """
    Parse a PDF containing cell-site location timeline observations.

    Skips preamble, header, and footer text, parsing strictly the tabular
    evidence rows. Preserves timestamps, source page, line provenance, and
    the non-GPS limitation disclaimer in event metadata.
    """
    path = Path(file_path)
    source_doc = source_doc or path.name
    events: list[dict[str, Any]] = []

    with pdfplumber.open(str(path)) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                header = tbl[0]
                if not is_location_timeline_header(header):
                    continue

                for row_idx, row in enumerate(tbl[1:], start=2):
                    if not row or len(row) < 4:
                        continue
                    time_raw = str(row[0] or "").strip()
                    phone_raw = str(row[1] or "").strip()
                    loc_raw = str(row[2] or "").strip()
                    obs_raw = str(row[3] or "").strip()

                    if not time_raw or not phone_raw:
                        continue

                    # Split location reference: "City / Cell-Tower"
                    city: str | None = None
                    cell_tower: str | None = None
                    if "/" in loc_raw:
                        parts = [p.strip() for p in loc_raw.split("/", 1)]
                        city = parts[0] if parts[0] else None
                        cell_tower = parts[1] if len(parts) > 1 and parts[1] else None
                    else:
                        if "-CELL-" in loc_raw.upper():
                            cell_tower = loc_raw
                        else:
                            city = loc_raw

                    # Parse timestamp (e.g. "2026-08-21 10:02")
                    ts_iso: str | None = None
                    try:
                        dt = datetime.strptime(time_raw, "%Y-%m-%d %H:%M")
                        ts_iso = dt.isoformat()
                    except ValueError:
                        try:
                            dt = datetime.fromisoformat(time_raw)
                            ts_iso = dt.isoformat()
                        except ValueError:
                            ts_iso = time_raw

                    loc_desc = f"{city} / {cell_tower}" if (city and cell_tower) else (cell_tower or city or loc_raw)
                    text = f"Cell-site observation: {phone_raw} at {loc_desc} [{obs_raw}]"

                    events.append({
                        "source_doc": source_doc,
                        "timestamp": ts_iso,
                        "text": text,
                        "event_type": "location_timeline",
                        "source_line": row_idx,
                        "source_page": page_idx,
                        "metadata": {
                            "phone": phone_raw,
                            "city": city,
                            "cell_tower": cell_tower,
                            "location_reference": loc_raw,
                            "observation": obs_raw,
                            "limitation": LOCATION_DISCLAIMER,
                            "source_doc": source_doc,
                            "source_page": page_idx,
                            "source_row": row_idx,
                        },
                    })

    return events
