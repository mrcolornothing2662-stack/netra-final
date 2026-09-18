from __future__ import annotations
"""
CyberDrishti AI — WhatsApp Export Parser
Parses multiple WhatsApp chat export formats:
  1. Standard export:  dd/mm/yyyy, h:mm am/pm - Sender: message body
  2. 24-hour export:   dd/mm/yyyy 09:00 - Sender: message
  3. Pipe-delimited:   YYYY-MM-DD HH:MM:SS | sender | message
  4. Plain fallback:   Sender: message
Outputs a list of EvidenceEvent-compatible dicts.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Pre-parse filters: lines that are chat metadata, NOT messages
# ---------------------------------------------------------------------------

# Chat header lines: "Conversation: CHAT-001", "Chat: ...", "Group: ..."
_CHAT_HEADER_RE = re.compile(
    r"^\s*(?:Conversation|Chat|Group|Thread|Subject)\s*:\s*(.*)$",
    re.IGNORECASE,
)

# Participant header lines: "Participants: +91-xxx, +91-yyy"
_PARTICIPANTS_RE = re.compile(
    r"^\s*(?:Participants?|Members?)\s*:\s*(.+)$",
    re.IGNORECASE,
)

# Preamble/disclaimer lines (e.g. "SYNTHETIC / TRAINING DATA — ...")
_PREAMBLE_RE = re.compile(
    r"^\s*(?:SYNTHETIC|DISCLAIMER|NOTE|WARNING|CONFIDENTIAL|---)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Message patterns (ordered by specificity, most specific first)
# ---------------------------------------------------------------------------
_MSG_PATTERNS = [
    # 1. Standard Android/iOS export: 22/04/2026, 9:00 am - Sender: message or [22/04/2026, 09:00:15] Sender: message
    re.compile(r"^\s*\[?(\d{1,4}[/\.\-]\d{1,2}[/\.\-]\d{1,4})[,\s]+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]m)?)[\]\s]*[\-:]\s*([^:]+?):\s*(.*?)$", re.IGNORECASE),
    # 2. 24-hour time export: 22/04/2026 09:00 - Sender: message
    re.compile(r"^\s*(\d{1,4}[/\.\-]\d{1,2}[/\.\-]\d{1,4})[,\s]+(\d{1,2}:\d{2}(?::\d{2})?)\s*[\-:]\s*([^:]+?):\s*(.*?)$", re.IGNORECASE),
    # 3. Plain Chat format fallback: Sender: Message
    #    (only matches if pre-parse filters above did NOT match)
    re.compile(r"^\s*([A-Za-z0-9_\+\-\s\.\(\)]{2,30}):\s*(.+)$"),
]

# 3b. Pipe-delimited chat format (checked before the generic colon fallback):
#     YYYY-MM-DD HH:MM:SS | sender | message
_PIPE_DELIMITED_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s*\|\s*(.+?)\s*\|\s*(.+)$"
)

# System messages (no sender colon)
_SYS_RE = re.compile(
    r"^\s*\[?(\d{1,4}[/\.\-]\d{1,2}[/\.\-]\d{1,4})[,\s]+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[ap]m)?)[\]\s]*[\-:]\s*(.+)$",
    re.IGNORECASE,
)


@dataclass
class WhatsAppMessage:
    timestamp: datetime | None
    sender: str
    text: str
    source_line: int
    is_system: bool = False
    media_omitted: bool = False
    metadata: dict = field(default_factory=dict)


def _parse_ts(date_str: str, time_str: str) -> datetime | None:
    """
    Parse WhatsApp date/time. Handles both 2-digit and 4-digit years,
    and 12-hour AM/PM & 24-hour format.
    """
    time_str = time_str.strip().lower().replace(" ", " ")
    combined = f"{date_str} {time_str}"
    for fmt in ("%d/%m/%y %I:%M %p", "%d/%m/%Y %I:%M %p",
                "%m/%d/%y %I:%M %p", "%m/%d/%Y %I:%M %p",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(combined, fmt)
        except ValueError:
            continue
    return None


def _parse_pipe_ts(ts_str: str) -> datetime | None:
    """Parse a timestamp from a pipe-delimited line (YYYY-MM-DD HH:MM:SS)."""
    ts_str = ts_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            continue
    return None


def parse_whatsapp_export(
    file_path: str | Path,
    source_doc: str | None = None,
    encoding: str = "utf-8",
) -> list[dict]:
    path = Path(file_path)
    source_doc = source_doc or path.name

    messages: list[WhatsAppMessage] = []
    current: WhatsAppMessage | None = None
    chat_metadata: dict = {}

    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        content = path.read_text(encoding="latin-1", errors="ignore")

    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        # ----- Pre-parse: skip preamble/disclaimer lines -----
        if _PREAMBLE_RE.match(line):
            continue

        # ----- Pre-parse: chat header → metadata, NOT a message -----
        header_m = _CHAT_HEADER_RE.match(line)
        if header_m:
            chat_metadata["conversation_id"] = header_m.group(1).strip()
            continue

        # ----- Pre-parse: participant header → metadata, NOT a message -----
        part_m = _PARTICIPANTS_RE.match(line)
        if part_m:
            raw_participants = part_m.group(1).strip()
            chat_metadata["participants"] = [
                p.strip() for p in raw_participants.split(",") if p.strip()
            ]
            continue

        # ----- Pipe-delimited format: timestamp | sender | message -----
        pipe_m = _PIPE_DELIMITED_RE.match(line)
        if pipe_m:
            if current is not None:
                messages.append(current)

            ts_str, sender, body = pipe_m.group(1), pipe_m.group(2), pipe_m.group(3)
            ts = _parse_pipe_ts(ts_str)
            media = "<Media omitted>" in body or "image omitted" in body.lower()
            current = WhatsAppMessage(
                timestamp=ts,
                sender=sender.strip(),
                text=body.strip(),
                source_line=lineno,
                media_omitted=media,
            )
            continue

        # ----- Standard WhatsApp message patterns -----
        matched = False
        for pat in _MSG_PATTERNS:
            m = pat.match(line)
            if m:
                if current is not None:
                    messages.append(current)

                groups = m.groups()
                if len(groups) == 4:
                    date_s, time_s, sender, body = groups
                    ts = _parse_ts(date_s, time_s)
                else:
                    sender, body = groups
                    ts = None

                media = "<Media omitted>" in body or "image omitted" in body.lower()
                current = WhatsAppMessage(
                    timestamp=ts,
                    sender=sender.strip(),
                    text=body.strip(),
                    source_line=lineno,
                    media_omitted=media,
                )
                matched = True
                break

        if not matched:
            sys_m = _SYS_RE.match(line)
            if sys_m and current is None:
                date_s, time_s, body = sys_m.groups()
                ts = _parse_ts(date_s, time_s)
                messages.append(WhatsAppMessage(
                    timestamp=ts,
                    sender="__system__",
                    text=body.strip(),
                    source_line=lineno,
                    is_system=True,
                ))
            elif current is not None:
                current.text += "\n" + line

    # Flush last message
    if current is not None:
        messages.append(current)

    # Attach chat-level metadata to every event so downstream consumers
    # (e.g. entity extractors) have access to conversation context.
    # Convert to EvidenceEvent dicts
    return [
        {
            "source_doc": source_doc,
            "timestamp": msg.timestamp.isoformat() if msg.timestamp and msg.timestamp.year != 1970 else None,
            "text": msg.text,
            "event_type": "whatsapp_msg",
            "source_line": msg.source_line,
            "source_page": None,
            "metadata": {
                "sender": msg.sender,
                "is_system": msg.is_system,
                "media_omitted": msg.media_omitted,
                **({"chat_metadata": chat_metadata} if chat_metadata else {}),
            },
        }
        for msg in messages
    ]
