from __future__ import annotations
"""
CyberDrishti AI — Bank Statement PDF Parser
Extracts {date, narration, credit, debit, balance} rows from Indian bank
statement PDFs using pdfplumber (digital) with Camelot as fallback (scanned).

Outputs EvidenceEvent-compatible dicts with event_type='bank_txn'.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Lazy imports to avoid loading heavy libs until needed
_pdfplumber = None
_camelot = None


def _get_pdfplumber():
    global _pdfplumber
    if _pdfplumber is None:
        import pdfplumber
        _pdfplumber = pdfplumber
    return _pdfplumber


def _get_camelot():
    global _camelot
    if _camelot is None:
        import camelot
        _camelot = camelot
    return _camelot


# ── Date normalisation ────────────────────────────────────────────────────────

_DATE_FMTS = [
    "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
    "%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y",
    "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M",
]


def _parse_date(raw: str) -> str | None:
    """Try multiple date formats; return ISO string or None."""
    raw = raw.strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw, fmt).isoformat()
        except ValueError:
            continue
    return None


# ── Amount normalisation ──────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"[\d,]+\.?\d*")


def _parse_amount(raw: str) -> float | None:
    """Extract numeric float from currency-formatted string like '1,23,456.78'."""
    if not raw or str(raw).strip() in ("", "-", "nan"):
        return None
    m = _AMOUNT_RE.search(str(raw).replace(",", ""))
    return float(m.group()) if m else None


# ── Column header fuzzy mapper ────────────────────────────────────────────────

_HEADER_PATTERNS: dict[str, list[str]] = {
    "date":       ["date", "txn date", "transaction date", "value date", "posting date", "date/time"],
    "narration":  ["narration", "description", "particulars", "details", "remarks", "transaction details"],
    "debit":      ["debit", "dr", "withdrawal", "amount (dr)", "debit amount", "withdrawals"],
    "credit":     ["credit", "cr", "deposit", "amount (cr)", "credit amount", "deposits"],
    "amount":     ["amount", "txn amount", "transaction amount", "total amount"],
    "balance":    ["balance", "running balance", "closing balance", "available balance"],
    "ref_no":     ["ref no", "reference", "chq no", "cheque no", "txn id", "utr", "ref number"],
    "direction":  ["direction", "type", "txn type", "cr/dr", "d/c"],
}

# Transfer/UPI table patterns — account/party columns are mapped BEFORE
# financial columns so "payer" is never mistaken for a generic field.
_ACCOUNT_PATTERNS: dict[str, list[str]] = {
    "from_account": ["debit_account", "debit account", "from account", "from_account",
                     "source account", "payer", "remitter", "sender account", "a/c debited"],
    "to_account":   ["credit_account", "credit account", "to account", "to_account",
                     "destination account", "payee", "beneficiary", "receiver account",
                     "a/c credited"],
}

_TRANSFER_FIELD_PATTERNS: dict[str, list[str]] = {
    "date":      ["timestamp_ist", "timestamp", "date time", "datetime", "txn date",
                  "transaction date", "value date", "posting date", "event_time",
                  "event time", "date", "time"],
    "amount":    ["amount_inr", "amount inr", "transaction amount", "txn amount",
                  "amount", "value"],
    "ref_no":    ["reference", "ref no", "ref number", "utr", "cheque no", "chq no",
                  "txn id", "transaction_id", "transaction id"],
    "upi_id":    ["upi_id", "upi id", "upi", "vpa"],
    "channel":   ["channel", "payment mode", "mode", "method"],
    "status":    ["txn status", "transaction status", "status"],
    "narration": ["narration", "description", "particulars", "details", "remarks",
                  "transaction details", "purpose"],
}


def _match_col(columns: list[str], lc_cols: list[str], patterns: list[str],
               claimed: set[str]) -> str | None:
    """First raw column (not already claimed) whose lowercased name contains a pattern."""
    for pat in patterns:
        for raw_col, lc_col in zip(columns, lc_cols):
            if raw_col in claimed:
                continue
            if pat in lc_col:
                return raw_col
    return None


def _map_columns(columns: list[str]) -> dict[str, str | None]:
    """
    Map raw column headers to canonical names using lowercased substring matching.
    Returns {canonical -> raw_column_name | None}.
    """
    lc_cols = [str(c).lower().strip() for c in columns if c is not None]
    result = {k: None for k in _HEADER_PATTERNS}

    for canonical, patterns in _HEADER_PATTERNS.items():
        for raw_col, lc_col in zip(columns, lc_cols):
            if any(p in lc_col for p in patterns):
                result[canonical] = raw_col
                break

    return result


def _map_transfer_columns(columns: list[str]) -> dict[str, str | None]:
    """Map raw column headers for transfer/UPI-style tables.

    Account/party columns are claimed first so 'payer' is never eaten by a
    generic field pattern — mirroring the logic in bank_csv_parser."""
    lc_cols = [str(c).lower().strip() for c in columns]
    result: dict[str, str | None] = {}
    claimed: set[str] = set()

    for canonical, patterns in _ACCOUNT_PATTERNS.items():
        col = _match_col(columns, lc_cols, patterns, claimed)
        result[canonical] = col
        if col:
            claimed.add(col)

    for canonical, patterns in _TRANSFER_FIELD_PATTERNS.items():
        col = _match_col(columns, lc_cols, patterns, claimed)
        result[canonical] = col
        if col:
            claimed.add(col)

    return result


def _is_bank_statement_table(col_map: dict[str, str | None]) -> bool:
    """
    Verify that an extracted table actually resembles a bank statement transaction ledger.
    Must possess at least one financial amount/balance column and a date or narration column.
    """
    has_financial = any(col_map.get(k) is not None for k in ("debit", "credit", "balance", "amount"))
    has_date_or_narration = (col_map.get("date") is not None or col_map.get("narration") is not None)
    return bool(has_financial and has_date_or_narration)


def _is_transfer_table(col_map: dict[str, str | None]) -> bool:
    """Does the table have Payer/Payee transfer semantics?"""
    has_parties = (col_map.get("from_account") is not None or
                   col_map.get("to_account") is not None)
    has_amount_or_date = (col_map.get("amount") is not None or
                          col_map.get("date") is not None)
    return bool(has_parties and has_amount_or_date)


def _is_identifier_table(headers: list[str]) -> bool:
    """Does the table look like a 2-column identifier alias table?
    e.g. headers = ['Field', 'Value'] with rows like ['UPI-001', 'arjun@upi']."""
    if len(headers) != 2:
        return False
    lc = [str(h).lower().strip() for h in headers]
    return lc == ["field", "value"]


# ── Amount normalisation for PDF (handles ZapfDingbats glyph artifact) ────────

_GLYPH_AMOUNT_RE = re.compile(r'^n([\d,]+\.?\d*)$')


def _parse_transfer_amount(raw: str) -> float | None:
    """Parse amount from PDF table cell, handling the ZapfDingbats 'n' glyph
    that replaces the ₹ currency symbol in some synthetic PDFs."""
    if not raw or str(raw).strip() in ("", "-", "nan"):
        return None
    s = str(raw).strip()
    # First try the standard amount parser
    std = _parse_amount(s)
    if std is not None:
        return std
    # Handle ZapfDingbats glyph: 'n48,500' → 48500.0
    gm = _GLYPH_AMOUNT_RE.match(s)
    if gm:
        try:
            return float(gm.group(1).replace(",", ""))
        except ValueError:
            pass
    # Last resort: strip any leading non-digit and try
    stripped = re.sub(r'^[^\d]+', '', s)
    if stripped:
        try:
            return float(stripped.replace(",", ""))
        except ValueError:
            pass
    return None


def _build_alias_map(table: list[list[str]]) -> dict[str, str]:
    """Build an identifier alias map from a 2-column [Field, Value] table.
    Returns {alias_code: resolved_value}, e.g. {'UPI-001': 'arjun@upi'}."""
    aliases: dict[str, str] = {}
    if len(table) < 2:
        return aliases
    for row in table[1:]:
        if len(row) >= 2 and row[0] and row[1]:
            key = str(row[0]).strip()
            val = str(row[1]).strip()
            if key and val and key.lower() not in ("field", "nan", ""):
                aliases[key] = val
    return aliases


# ── Core extraction ──────────────────────────────────────────────────────────

def _dataframe_to_events(df: pd.DataFrame, source_doc: str, page_num: int) -> list[dict]:
    """Convert a parsed DataFrame into EvidenceEvent dicts."""
    col_map = _map_columns(list(df.columns))
    if not _is_bank_statement_table(col_map):
        return []

    events = []

    for idx, row in df.iterrows():
        date_raw   = str(row[col_map["date"]]) if col_map["date"] else ""
        narration  = str(row[col_map["narration"]]) if col_map["narration"] else str(row.iloc[1] if len(row) > 1 else "")
        debit_val  = _parse_amount(row[col_map["debit"]]) if col_map["debit"] else None
        credit_val = _parse_amount(row[col_map["credit"]]) if col_map["credit"] else None
        balance    = _parse_amount(row[col_map["balance"]]) if col_map["balance"] else None
        ref_no     = str(row[col_map["ref_no"]]) if col_map["ref_no"] else None

        # Resolve generic amount column using direction if available
        if col_map.get("amount") and debit_val is None and credit_val is None:
            amt = _parse_amount(row[col_map["amount"]])
            dir_str = str(row[col_map["direction"]]).lower().strip() if col_map.get("direction") else ""
            if "debit" in dir_str or dir_str == "dr":
                debit_val = amt
            elif "credit" in dir_str or dir_str == "cr":
                credit_val = amt
            else:
                credit_val = amt

        parsed_date = _parse_date(date_raw)

        # Skip header repeat rows and empty rows
        if not narration or narration.lower() in ("nan", "description", "narration", "particulars"):
            continue
        if debit_val is None and credit_val is None and balance is None and parsed_date is None:
            continue

        amount = credit_val or debit_val  # primary amount for text
        txn_direction = "credit" if credit_val else ("debit" if debit_val else "unknown")
        amount_str = f"₹{amount:,.2f}" if amount else ""

        if amount:
            text = f"{narration.strip()} | {txn_direction.upper()} {amount_str}".strip(" |")
        else:
            text = narration.strip()

        events.append({
            "source_doc":   source_doc,
            "timestamp":    parsed_date,
            "text":         text,
            "event_type":   "bank_txn",
            "source_line":  None,
            "source_page":  page_num,
            "metadata": {
                "narration":  narration.strip(),
                "debit":      debit_val,
                "credit":     credit_val,
                "balance":    balance,
                "ref_no":     ref_no,
                "date_raw":   date_raw,
            },
        })

    return events


def _dataframe_to_transfer_events(
    df: pd.DataFrame,
    source_doc: str,
    page_num: int,
    alias_map: dict[str, str] | None = None,
) -> list[dict]:
    """Convert a transfer/UPI-style DataFrame into EvidenceEvent dicts.

    Mirrors the transfer-model path of bank_csv_parser._dataframe_to_events
    so the downstream relationship engine (``_typed_bank``) receives identical
    metadata keys: ``from_account``, ``to_account``, ``amount``, ``ref_no``,
    ``status``, ``upi_id``, ``channel``.
    """
    col_map = _map_transfer_columns(list(df.columns))
    if not _is_transfer_table(col_map):
        return []

    alias = alias_map or {}
    events = []

    for idx, row in df.iterrows():
        def _g(key: str) -> str | None:
            c = col_map.get(key)
            if not c or c not in row:
                return None
            v = str(row[c]).strip()
            return v if v.lower() not in ("nan", "none", "") else None

        from_raw = _g("from_account") or ""
        to_raw = _g("to_account") or ""
        ref_no = _g("ref_no")
        status = _g("status")
        upi_id = _g("upi_id")
        channel = _g("channel")
        narration = _g("narration") or ""
        date_raw = _g("date") or ""
        amount_raw = _g("amount") or ""

        # Resolve aliases (e.g. UPI-001 → arjun@upi)
        from_resolved = alias.get(from_raw, from_raw)
        to_resolved = alias.get(to_raw, to_raw)

        parsed_date = _parse_date(date_raw)
        amount = _parse_transfer_amount(amount_raw)

        # Skip header-repeat and empty rows
        if not from_resolved and not to_resolved:
            continue

        amount_str = f"Rs.{amount:,.2f}" if amount else ""
        desc = f" ({narration})" if narration else ""
        text = f"{from_resolved} -> {to_resolved} | {amount_str}{desc}".strip(" |")
        if ref_no:
            text = f"{text} [{ref_no}]"

        events.append({
            "source_doc":   source_doc,
            "timestamp":    parsed_date,
            "text":         text,
            "event_type":   "bank_txn",
            "source_line":  None,
            "source_page":  page_num,
            "metadata": {
                "model":        "transfer",
                "narration":    narration or None,
                "from_account": from_resolved,
                "to_account":   to_resolved,
                "amount":       amount,
                "ref_no":       ref_no,
                "status":       status,
                "upi_id":       upi_id,
                "channel":      channel,
                "date_raw":     date_raw,
                "account":      to_resolved or from_resolved,
                # Preserve original alias codes for provenance
                "from_alias":   from_raw if from_raw != from_resolved else None,
                "to_alias":     to_raw if to_raw != to_resolved else None,
            },
        })

    return events


def parse_bank_pdf(
    file_path: str | Path,
    source_doc: str | None = None,
    use_camelot_fallback: bool = True,
) -> list[dict]:
    """
    Parse an Indian bank statement or transfer/UPI PDF.

    Supports two table schemas:
      (A) Ledger: date, narration, credit, debit, balance
      (B) Transfer: time, reference, payer, payee, amount, status

    Also handles 2-column identifier/alias tables (e.g. UPI-001 → arjun@upi)
    and resolves aliases within transfer events.

    Tries pdfplumber first (works for digital PDFs with embedded text).
    Falls back to camelot lattice/stream extraction for scanned tables.
    """
    path = Path(file_path)
    source_doc = source_doc or path.name
    all_events: list[dict] = []

    # ── Attempt 1: pdfplumber ──────────────────────────────────────────────
    pdfplumber = _get_pdfplumber()
    with pdfplumber.open(str(path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables(
                table_settings={
                    "vertical_strategy":   "lines_strict",
                    "horizontal_strategy": "lines_strict",
                }
            )
            
            if not tables:
                # Fallback to text strategy for borderless Indian bank statements
                tables = page.extract_tables(
                    table_settings={
                        "vertical_strategy":   "text",
                        "horizontal_strategy": "text",
                    }
                )

            if not tables:
                tables = page.extract_tables()

            # ── First pass: collect identifier/alias tables ────────────────
            alias_map: dict[str, str] = {}
            remaining_tables: list[list] = []
            for table in (tables or []):
                if not table or len(table) < 2:
                    continue
                headers = [str(h).strip() for h in table[0] if h is not None]
                if _is_identifier_table(headers):
                    alias_map.update(_build_alias_map(table))
                else:
                    remaining_tables.append(table)

            # ── Second pass: parse ledger or transfer tables ──────────────
            for table in remaining_tables:
                try:
                    df = pd.DataFrame(table[1:], columns=table[0])

                    # Try ledger schema first
                    ledger_col_map = _map_columns(list(df.columns))
                    if _is_bank_statement_table(ledger_col_map):
                        events = _dataframe_to_events(df, source_doc, page_num)
                        all_events.extend(events)
                        continue

                    # Try transfer/UPI schema
                    events = _dataframe_to_transfer_events(
                        df, source_doc, page_num, alias_map=alias_map,
                    )
                    all_events.extend(events)
                except Exception as e:
                    print(f"pdfplumber table parse error on page {page_num}: {e}")

    # ── Attempt 2: camelot fallback ────────────────────────────────────────
    if not all_events and use_camelot_fallback:
        try:
            camelot = _get_camelot()
        except ImportError:
            camelot = None
            print("Camelot is not installed or missing dependencies, skipping fallback.")
        
        if camelot:
            for flavor in ("lattice", "stream"):
                try:
                    tables = camelot.read_pdf(str(path), pages="all", flavor=flavor)
                    for tbl in tables:
                        df = tbl.df
                        if df.empty or len(df) < 2:
                            continue
                        df.columns = df.iloc[0]
                        df = df.iloc[1:].reset_index(drop=True)
                        events = _dataframe_to_events(df, source_doc, tbl.page)
                        all_events.extend(events)
                    if all_events:
                        break
                except Exception as e:
                    print(f"camelot fallback error with flavor {flavor}: {e}")
                    continue

    return all_events
