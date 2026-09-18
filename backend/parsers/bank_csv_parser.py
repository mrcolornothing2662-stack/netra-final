from __future__ import annotations
"""
CyberDrishti AI — Bank / Transaction CSV Parser

Replaces the naïve "dump the whole line into raw_line" ingestion path for
tabular financial CSVs. Fuzzy-maps varying column headers and emits
EvidenceEvent-compatible dicts (event_type='bank_txn') with *structured*
metadata and a parsed ISO timestamp, so the downstream cognitive engines
(ledger audit, counterfactual freeze, hypotheses) receive the exact shape
they expect instead of re-splitting a raw string positionally.

Handles the two schemas that occur in real Indian cyber-fraud evidence:

  (A) Ledger statement:   date, narration, credit, debit, balance, ref_no
        → per-row running balance; feeds contradiction.ledger_audit.

  (B) Transfer / UPI log:  transaction_id, timestamp_ist, debit_account,
        credit_account, amount_inr, upi_id, channel, status, description,
        reference
        → party-to-party money flow; feeds counterfactual.simulate_freeze
          and the money-flow graph.

Every emitted event also keeps the original `raw_line` for backward
compatibility with any legacy consumer.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ── Amount / date normalisation ───────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"-?[\d,]+\.?\d*")

_DT_FMTS = [
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y %H:%M:%S",
    "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%Y/%m/%d %H:%M:%S",
]

# A narration fragment that is really a clock/index artifact (e.g. "509:53:44")
# signals a mis-mapped column, not real transaction text. It must never be shown.
_TIMELIKE_RE = re.compile(r"^\d{1,3}:\d{2}(:\d{2})?$")


def _looks_like_corrupt_narration(value: str | None) -> bool:
    if not value:
        return False
    t = value.strip()
    if not t:
        return False
    if _TIMELIKE_RE.match(t):
        return True
    # Numeric-only fragments containing ':' are corruption; a plain reference
    # number (no colon) is a legitimate identifier and is left alone.
    return ":" in t and not re.search(r"[A-Za-z]", t)


def _parse_amount(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "nan", "None", "NaN"):
        return None
    m = _AMOUNT_RE.search(s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _parse_dt(raw: Any) -> str | None:
    """Return an ISO-8601 string (naïve or aware) or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "nan", "None"):
        return None
    # ISO first (handles trailing 'Z' and offsets)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    for fmt in _DT_FMTS:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


# ── Header fuzzy mapping ──────────────────────────────────────────────────────
# Order matters: account/party columns are matched BEFORE the plain
# credit/debit amount columns so "debit_account" is never mistaken for a
# debit *amount*.

_ACCOUNT_PATTERNS: dict[str, list[str]] = {
    "from_account": ["debit_account", "debit account", "from account", "from_account",
                     "source account", "payer", "remitter", "sender account", "a/c debited"],
    "to_account":   ["credit_account", "credit account", "to account", "to_account",
                     "destination account", "payee", "beneficiary", "receiver account",
                     "a/c credited"],
}

_FIELD_PATTERNS: dict[str, list[str]] = {
    "date":      ["timestamp_ist", "timestamp", "date time", "datetime", "txn date",
                  "transaction date", "value date", "posting date", "event_time",
                  "event time", "date", "time"],
    "narration": ["narration", "description", "particulars", "details", "remarks",
                  "transaction details", "purpose"],
    "credit":    ["credit amount", "cr amount", "amount (cr)", "deposit", "deposits",
                  "credit", "cr"],
    "debit":     ["debit amount", "dr amount", "amount (dr)", "withdrawal", "withdrawals",
                  "debit", "dr"],
    "balance":   ["running balance", "closing balance", "available balance", "balance"],
    "amount":    ["amount_inr", "amount inr", "transaction amount", "txn amount",
                  "amount", "value"],
    "upi_id":    ["upi_id", "upi id", "upi", "vpa"],
    "channel":   ["channel", "payment mode", "mode", "method"],
    "status":    ["txn status", "transaction status", "status"],
    "ref_no":    ["reference", "ref no", "ref number", "utr", "cheque no", "chq no",
                  "txn id", "transaction_id", "transaction id"],
}


def _match_col(columns: list[str], lc_cols: list[str], patterns: list[str],
               claimed: set[str]) -> str | None:
    """First raw column (not already claimed) whose lowercased name contains a pattern.
    Patterns are tried most-specific first."""
    for pat in patterns:
        for raw_col, lc_col in zip(columns, lc_cols):
            if raw_col in claimed:
                continue
            if pat in lc_col:
                return raw_col
    return None


def _map_columns(columns: list[str]) -> dict[str, str | None]:
    lc_cols = [str(c).lower().strip() for c in columns]
    result: dict[str, str | None] = {}
    claimed: set[str] = set()

    # 1. Account / party columns first (so they don't get eaten by credit/debit).
    for canonical, patterns in _ACCOUNT_PATTERNS.items():
        col = _match_col(columns, lc_cols, patterns, claimed)
        result[canonical] = col
        if col:
            claimed.add(col)

    # 2. Remaining fields. Plain credit/debit amount columns must not be an
    #    already-claimed *_account column.
    for canonical, patterns in _FIELD_PATTERNS.items():
        col = _match_col(columns, lc_cols, patterns, claimed)
        result[canonical] = col
        if col:
            claimed.add(col)

    return result


# ── Core extraction ───────────────────────────────────────────────────────────

_HEADER_TOKENS = {"nan", "", "description", "narration", "particulars", "date",
                  "transaction_id", "timestamp_ist"}


def _dataframe_to_events(df: pd.DataFrame, source_doc: str) -> list[dict]:
    col = _map_columns([str(c) for c in df.columns])
    has_balance_col = col["balance"] is not None
    has_transfer_cols = bool(col["from_account"] or col["to_account"] or col["amount"])
    model = "ledger" if has_balance_col else ("transfer" if has_transfer_cols else "ledger")

    events: list[dict] = []
    for lineno, (_, row) in enumerate(df.iterrows(), start=2):  # +2: header is line 1
        def g(key: str) -> str | None:
            c = col.get(key)
            if not c or c not in row:
                return None
            v = str(row[c]).strip()
            return v if v.lower() not in ("nan", "none", "") else None

        narration = g("narration") or ""
        # Skip obvious header-repeat rows.
        if narration.lower() in _HEADER_TOKENS and not (g("amount") or g("credit") or g("debit")):
            continue

        credit_val = _parse_amount(g("credit"))
        debit_val = _parse_amount(g("debit"))
        balance_val = _parse_amount(g("balance"))
        amount_val = _parse_amount(g("amount"))
        from_acct = g("from_account")
        to_acct = g("to_account")
        upi_id = g("upi_id")
        channel = g("channel")
        status = g("status")
        ref_no = g("ref_no")
        ts = _parse_dt(g("date"))

        # Primary amount for display / graph weighting.
        primary_amount = amount_val or credit_val or debit_val

        # Nothing usable on this row → skip.
        if primary_amount is None and not (from_acct or to_acct or narration):
            continue

        # ── Validation ────────────────────────────────────────────────────────
        # A transaction is only reliable when its core fields are structured and
        # sane. Corruption is reported (PARSE_ERROR), never rendered.
        parse_errors: list[str] = []
        corrupt_narration = _looks_like_corrupt_narration(narration)
        if model == "transfer" or (from_acct or to_acct):
            if not from_acct:
                parse_errors.append("missing_source_account")
            if not to_acct:
                parse_errors.append("missing_destination_account")
            if primary_amount is None:
                parse_errors.append("missing_amount")
            if not ts:
                parse_errors.append("missing_or_invalid_timestamp")
        else:  # ledger
            if primary_amount is None:
                parse_errors.append("missing_amount")
            if corrupt_narration:
                parse_errors.append("corrupt_narration")

        parser_status = "PARSE_ERROR" if parse_errors else "OK"

        # Build investigator-facing text from structured fields only. Parser
        # corruption is never concatenated into the display string.
        if parser_status == "PARSE_ERROR":
            amount_str = ""
            direction = ""
            text = f"Unparsed transaction (line {lineno}) — {', '.join(parse_errors)}"
        elif model == "transfer" or (from_acct or to_acct):
            amount_str = f"Rs.{primary_amount:,.2f}"
            chan = f" {channel}" if channel else ""
            desc = f" ({narration})" if narration and not corrupt_narration else ""
            text = f"{from_acct} -> {to_acct} | {amount_str}{chan}{desc}".strip()
        else:
            amount_str = f"Rs.{primary_amount:,.2f}"
            direction = "CREDIT" if (credit_val and credit_val > 0) else (
                "DEBIT" if (debit_val and debit_val > 0) else "TXN")
            narration_part = narration if (narration and not corrupt_narration) else ""
            text = f"{narration_part} | {direction} {amount_str}".strip(" |")

        raw_line = ",".join("" if pd.isna(v) else str(v) for v in row.values)

        events.append({
            "source_doc":  source_doc,
            "timestamp":   ts,
            "text":        text,
            "event_type":  "bank_txn",
            "source_line": lineno,
            "source_page": None,
            "parser_status": parser_status,
            "parse_errors": parse_errors,
            "metadata": {
                "model":         model,
                "narration":     narration or None,
                "narration_valid": not corrupt_narration,
                "credit":        credit_val,
                "debit":         debit_val,
                "balance":       balance_val,
                "amount":        None if parser_status == "PARSE_ERROR" else primary_amount,
                "from_account":  from_acct,
                "to_account":    to_acct,
                "upi_id":        upi_id,
                "channel":       channel,
                "status":        status,
                "ref_no":        ref_no,
                "account":       to_acct or from_acct,
                "parser_status": parser_status,
                "parse_errors":  parse_errors,
                "raw_line":      raw_line,
            },
        })

    return events


def parse_bank_csv(
    file_path: str | Path,
    source_doc: str | None = None,
    encoding: str = "utf-8",
) -> list[dict]:
    """Parse a bank statement / transaction CSV into EvidenceEvent dicts.

    Returns [] (never raises for a malformed row) so the ingestion pipeline can
    fall back to raw-line capture without losing the evidence file.
    """
    path = Path(file_path)
    source_doc = source_doc or path.name

    df: pd.DataFrame | None = None
    for enc in (encoding, "utf-8-sig", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(str(path), encoding=enc, dtype=str, skip_blank_lines=True)
            break
        except Exception:
            continue

    if df is None or df.empty:
        return []

    df.dropna(axis=1, how="all", inplace=True)
    df.columns = [str(c).strip() for c in df.columns]
    return _dataframe_to_events(df, source_doc)
