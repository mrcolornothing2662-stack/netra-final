from __future__ import annotations
"""
CyberDrishti AI — Evidence Seizure / Custody Memo Parser (Phase 5)

Parses tabular evidence seizure memos (e.g. 10_evidence_seizure_memo.pdf)
into EvidenceEvent-compatible dicts with event_type="seizure_memo".

Schema expected:
  Evidence ID | Item | Source | Condition

Custody fields expected in footer:
  Collector: Synthetic Test Operator
  Collection date: 2026-08-23
  Integrity hash: TEST-HASH-DO-NOT-TREAT-AS-REAL
  Purpose: NETRA parser and provenance testing.
"""
import re
from pathlib import Path
from typing import Any

import pdfplumber


def is_seizure_memo_header(first_row: list[str]) -> bool:
    """Check if table headers match the evidence seizure memo schema."""
    if not first_row or len(first_row) < 4:
        return False
    row_lower = [str(c or "").strip().lower() for c in first_row]
    has_evd = any("evidence" in c or "id" in c for c in row_lower)
    has_item = any("item" in c or "description" in c for c in row_lower)
    has_source = any("source" in c for c in row_lower)
    has_cond = any("condition" in c for c in row_lower)
    return has_evd and has_item and has_source and has_cond


def parse_seizure_memo(
    file_path: str | Path,
    source_doc: str | None = None,
) -> list[dict[str, Any]]:
    """
    Parse an Evidence Seizure / Custody Memo PDF.

    Extracts exactly the inventory records from the tabular data and
    attaches custody metadata (collector, collection_date, integrity_hash,
    purpose) to each record's metadata. Skips preambles, titles, and
    footer text from generating noisy events.
    """
    path = Path(file_path)
    source_doc = source_doc or path.name
    events: list[dict[str, Any]] = []

    with pdfplumber.open(str(path)) as pdf:
        # 1. Collect document-level custody metadata across all pages
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        collector_m = re.search(r"Collector:\s*([^\n\r]+)", full_text, re.IGNORECASE)
        date_m = re.search(r"Collection date:\s*(\d{4}-\d{2}-\d{2})", full_text, re.IGNORECASE)
        hash_m = re.search(r"Integrity hash:\s*([^\n\r]+)", full_text, re.IGNORECASE)
        purpose_m = re.search(r"Purpose:\s*([^\n\r]+)", full_text, re.IGNORECASE)

        collector = collector_m.group(1).strip() if collector_m else None
        collection_date = date_m.group(1).strip() if date_m else None
        integrity_hash = hash_m.group(1).strip() if hash_m else None
        purpose = purpose_m.group(1).strip() if purpose_m else None

        # 2. Extract inventory records from the inventory table
        for page_idx, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                header = tbl[0]
                if not is_seizure_memo_header(header):
                    continue

                for row_idx, row in enumerate(tbl[1:], start=2):
                    if not row or len(row) < 4:
                        continue
                    ev_id = str(row[0] or "").strip()
                    item = str(row[1] or "").strip()
                    source = str(row[2] or "").strip()
                    condition = str(row[3] or "").strip()

                    if not ev_id or not item:
                        continue

                    text = (
                        f"Seized evidence: {ev_id} — {item} "
                        f"(Source: {source}, Condition: {condition})"
                    )

                    events.append({
                        "source_doc": source_doc,
                        "timestamp": collection_date,
                        "text": text,
                        "event_type": "seizure_memo",
                        "source_line": row_idx,
                        "source_page": page_idx,
                        "metadata": {
                            "evidence_id": ev_id,
                            "item": item,
                            "source": source,
                            "condition": condition,
                            "collector": collector,
                            "collection_date": collection_date,
                            "integrity_hash": integrity_hash,
                            "purpose": purpose,
                            "source_doc": source_doc,
                            "source_page": page_idx,
                            "source_row": row_idx,
                        },
                    })

    return events
