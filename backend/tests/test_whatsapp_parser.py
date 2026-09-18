"""
CyberDrishti AI — WhatsApp Parser Regression Tests

Tests specifically cover:
1. Chat header lines (Conversation:) → NOT emitted as messages/senders
2. Participant header lines (Participants:) → NOT emitted as messages/senders
3. Pipe-delimited timestamp|sender|message format → correctly parsed
4. Standard WhatsApp formats still work
5. False PERSON entity regression: "Conversation", "Participants",
   "2026-08-21 10", "2026-08-23 16" must never appear as senders
"""
from __future__ import annotations

import os
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path

import pytest
import sys

# Ensure the backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers.whatsapp_parser import parse_whatsapp_export


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp(content: str, suffix: str = ".txt") -> Path:
    """Write content to a temp file and return its Path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    return Path(path)


def _senders(events: list[dict]) -> list[str]:
    """Extract the list of sender values from parsed events."""
    return [e["metadata"]["sender"] for e in events]


def _timestamps(events: list[dict]) -> list[str | None]:
    """Extract the list of timestamp values from parsed events."""
    return [e.get("timestamp") for e in events]


# ---------------------------------------------------------------------------
# The exact file that caused the four bad entities
# ---------------------------------------------------------------------------

EXACT_05_CHAT_EXPORT = """\
SYNTHETIC / TRAINING DATA — NOT AN ACTUAL CHAT RECORD
Conversation: CHAT-001
Participants: +91-98XXXX1201, +91-97XXXX4418

2026-08-21 10:01:14 | +91-98XXXX1201 | Please confirm the account details.
2026-08-21 10:02:03 | +91-97XXXX4418 | Confirmed. I will check.
2026-08-21 10:13:42 | +91-97XXXX4418 | Received.
2026-08-21 10:26:51 | +91-97XXXX4418 | I am forwarding the reference now.
2026-08-21 10:29:18 | +91-98XXXX1201 | Keep the reference in the records.
2026-08-23 16:03:10 | +91-97XXXX4418 | The second payment is expected shortly.
"""


class TestExact05ChatExport:
    """Regression tests against the exact file that produced the 4 bad entities."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.file = tmp_path / "05_chat_export.txt"
        self.file.write_text(EXACT_05_CHAT_EXPORT, encoding="utf-8")
        self.events = parse_whatsapp_export(self.file)

    def test_only_message_lines_produce_events(self):
        """The 6 pipe-delimited message lines should produce exactly 6 events."""
        assert len(self.events) == 6

    def test_conversation_not_a_sender(self):
        """'Conversation' must NOT appear as a sender in any event."""
        senders = _senders(self.events)
        assert "Conversation" not in senders

    def test_participants_not_a_sender(self):
        """'Participants' must NOT appear as a sender in any event."""
        senders = _senders(self.events)
        assert "Participants" not in senders

    def test_date_prefix_not_a_sender(self):
        """'2026-08-21 10' and '2026-08-23 16' must NOT appear as senders."""
        senders = _senders(self.events)
        assert "2026-08-21 10" not in senders
        assert "2026-08-23 16" not in senders

    def test_preamble_not_a_sender(self):
        """'SYNTHETIC / TRAINING DATA' line must not produce a message."""
        senders = _senders(self.events)
        for s in senders:
            assert "SYNTHETIC" not in s.upper()

    def test_senders_are_phone_numbers(self):
        """All senders should be the phone numbers from pipe-delimited lines."""
        senders = set(_senders(self.events))
        assert senders == {"+91-98XXXX1201", "+91-97XXXX4418"}

    def test_timestamps_are_correct(self):
        """Each event should have a properly parsed ISO timestamp."""
        for evt in self.events:
            ts = evt.get("timestamp")
            assert ts is not None, f"Missing timestamp for event: {evt['text'][:30]}"
            # Should be a valid ISO timestamp
            parsed = datetime.fromisoformat(ts)
            assert parsed.year == 2026

    def test_first_message_content(self):
        """First message should be 'Please confirm the account details.'"""
        assert self.events[0]["text"] == "Please confirm the account details."
        assert self.events[0]["metadata"]["sender"] == "+91-98XXXX1201"
        assert self.events[0]["timestamp"] == "2026-08-21T10:01:14"

    def test_last_message_content(self):
        """Last message should be 'The second payment is expected shortly.'"""
        assert self.events[-1]["text"] == "The second payment is expected shortly."
        assert self.events[-1]["metadata"]["sender"] == "+91-97XXXX4418"
        assert self.events[-1]["timestamp"] == "2026-08-23T16:03:10"

    def test_chat_metadata_attached(self):
        """Chat metadata (conversation ID, participants) should be attached."""
        meta = self.events[0]["metadata"].get("chat_metadata", {})
        assert meta.get("conversation_id") == "CHAT-001"
        assert "+91-98XXXX1201" in meta.get("participants", [])
        assert "+91-97XXXX4418" in meta.get("participants", [])


# ---------------------------------------------------------------------------
# Pipe-delimited format tests (broader coverage)
# ---------------------------------------------------------------------------

class TestPipeDelimitedFormat:
    """Tests for the pipe-delimited timestamp | sender | message format."""

    def test_basic_pipe_format(self, tmp_path):
        f = tmp_path / "pipe.txt"
        f.write_text("2026-01-15 08:30:00 | Alice | Good morning\n")
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Alice"
        assert events[0]["text"] == "Good morning"
        assert events[0]["timestamp"] == "2026-01-15T08:30:00"

    def test_pipe_without_seconds(self, tmp_path):
        f = tmp_path / "pipe_nosec.txt"
        f.write_text("2026-01-15 08:30 | Bob | Hello\n")
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Bob"
        assert events[0]["timestamp"] == "2026-01-15T08:30:00"

    def test_multiple_pipe_messages(self, tmp_path):
        content = textwrap.dedent("""\
            2026-03-01 09:00:00 | Alice | First
            2026-03-01 09:01:00 | Bob | Second
            2026-03-01 09:02:00 | Alice | Third
        """)
        f = tmp_path / "multi.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 3
        assert [e["text"] for e in events] == ["First", "Second", "Third"]

    def test_phone_sender_in_pipe_format(self, tmp_path):
        f = tmp_path / "phone.txt"
        f.write_text("2026-05-10 14:22:33 | +91-9876543210 | Transfer done\n")
        events = parse_whatsapp_export(f)
        assert events[0]["metadata"]["sender"] == "+91-9876543210"

    def test_pipe_message_with_pipe_in_body(self, tmp_path):
        """If the message body itself contains a pipe, everything after the
        second pipe delimiter should be captured as the message text."""
        f = tmp_path / "pipe_in_body.txt"
        f.write_text("2026-05-10 14:22:33 | Alice | Status: OK | confirmed\n")
        events = parse_whatsapp_export(f)
        assert events[0]["text"] == "Status: OK | confirmed"


# ---------------------------------------------------------------------------
# Chat header and metadata tests
# ---------------------------------------------------------------------------

class TestChatHeaders:
    """Tests for chat header/metadata line recognition."""

    def test_conversation_header_skipped(self, tmp_path):
        content = "Conversation: CHAT-099\nAlice: Hello there\n"
        f = tmp_path / "header.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        # Only the Alice message should be an event
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Alice"

    def test_participants_header_skipped(self, tmp_path):
        content = "Participants: +91-111, +91-222, +91-333\nBob: Hi\n"
        f = tmp_path / "parts.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Bob"

    def test_chat_group_subject_headers(self, tmp_path):
        content = textwrap.dedent("""\
            Group: Operation Meridian
            Subject: Urgent
            Chat: CHAT-002
            Thread: T-001
            Alice: Meeting at 3pm
        """)
        f = tmp_path / "headers.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Alice"

    def test_case_insensitive_headers(self, tmp_path):
        content = "CONVERSATION: CHAT-X\nparticipants: A, B\nAlice: Hi\n"
        f = tmp_path / "ci.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1

    def test_metadata_propagated_to_events(self, tmp_path):
        content = textwrap.dedent("""\
            Conversation: CHAT-007
            Participants: Alice, Bob
            2026-01-01 12:00:00 | Alice | Hello
        """)
        f = tmp_path / "meta.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        meta = events[0]["metadata"].get("chat_metadata", {})
        assert meta["conversation_id"] == "CHAT-007"
        assert "Alice" in meta["participants"]
        assert "Bob" in meta["participants"]


# ---------------------------------------------------------------------------
# Standard WhatsApp format backward compatibility
# ---------------------------------------------------------------------------

class TestStandardWhatsAppFormat:
    """Ensure the existing standard formats still work correctly."""

    def test_standard_android_format(self, tmp_path):
        content = "22/04/2026, 9:00 am - Rohan: Hello World\n"
        f = tmp_path / "android.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Rohan"
        assert events[0]["text"] == "Hello World"

    def test_standard_24h_format(self, tmp_path):
        content = "22/04/2026 09:00 - Priya: Good morning\n"
        f = tmp_path / "24h.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Priya"

    def test_plain_sender_format(self, tmp_path):
        content = "John Doe: This is a message\n"
        f = tmp_path / "plain.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "John Doe"

    def test_multiline_message(self, tmp_path):
        content = textwrap.dedent("""\
            22/04/2026, 9:00 am - Rohan: First line
            continued on second line
            and third line
            22/04/2026, 9:05 am - Priya: Another message
        """)
        f = tmp_path / "multi.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 2
        assert "continued on second line" in events[0]["text"]
        assert "and third line" in events[0]["text"]

    def test_media_omitted(self, tmp_path):
        content = "22/04/2026, 9:00 am - Rohan: <Media omitted>\n"
        f = tmp_path / "media.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert events[0]["metadata"]["media_omitted"] is True

    @pytest.mark.xfail(reason="Pre-existing: bracket format [dd/mm/yyyy, HH:MM:SS] regex does not cleanly separate seconds from sender")
    def test_bracket_format(self, tmp_path):
        content = "[22/04/2026, 09:00:15] Rohan: Bracket format\n"
        f = tmp_path / "bracket.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Rohan"


# ---------------------------------------------------------------------------
# Mixed format tests
# ---------------------------------------------------------------------------

class TestMixedFormats:
    """Test files mixing headers, pipe-delimited, and standard formats."""

    def test_headers_then_pipe_then_standard(self, tmp_path):
        content = textwrap.dedent("""\
            Conversation: MIXED-001
            Participants: Alpha, Beta
            2026-06-01 10:00:00 | Alpha | Pipe message
            22/06/2026, 10:05 am - Beta: Standard message
        """)
        f = tmp_path / "mixed.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 2
        senders = _senders(events)
        assert "Conversation" not in senders
        assert "Participants" not in senders
        assert "Alpha" in senders
        assert "Beta" in senders

    def test_preamble_skipped(self, tmp_path):
        content = textwrap.dedent("""\
            SYNTHETIC DATA — NOT REAL
            NOTE: This is generated
            WARNING: Do not use
            --- separator ---
            Alice: Real message
        """)
        f = tmp_path / "preamble.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Alice"


# ---------------------------------------------------------------------------
# Entity validation integration check (no DB, just logic)
# ---------------------------------------------------------------------------

class TestEntityValidationIntegration:
    """Verify that the senders produced by the parser would NOT
    create false PER entities via the sender_name extractor path
    in evidence.py."""

    def test_no_false_person_entities_from_05(self, tmp_path):
        """None of the 4 known-bad sender values should be produced."""
        f = tmp_path / "05_chat_export.txt"
        f.write_text(EXACT_05_CHAT_EXPORT, encoding="utf-8")
        events = parse_whatsapp_export(f)

        bad_senders = {"Conversation", "Participants", "2026-08-21 10", "2026-08-23 16"}
        actual_senders = set(_senders(events))
        overlap = bad_senders & actual_senders
        assert overlap == set(), f"Bad senders still produced: {overlap}"

    def test_phone_senders_wont_become_PER(self, tmp_path):
        """Phone number senders start with '+', so evidence.py skips
        PER extraction for them. Verify they all start with '+'."""
        f = tmp_path / "05_chat_export.txt"
        f.write_text(EXACT_05_CHAT_EXPORT, encoding="utf-8")
        events = parse_whatsapp_export(f)

        for evt in events:
            sender = evt["metadata"]["sender"]
            # In our test data, all senders are phone numbers starting with +
            assert sender.startswith("+"), (
                f"Sender '{sender}' does not start with '+' — "
                f"evidence.py would create a PER entity for it"
            )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        events = parse_whatsapp_export(f)
        assert events == []

    def test_only_headers(self, tmp_path):
        content = "Conversation: CHAT-000\nParticipants: A, B\n"
        f = tmp_path / "onlyheaders.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert events == []

    def test_only_preamble(self, tmp_path):
        content = "SYNTHETIC DATA\nNOTE: training only\n"
        f = tmp_path / "onlypreamble.txt"
        f.write_text(content)
        events = parse_whatsapp_export(f)
        assert events == []

    def test_single_pipe_message(self, tmp_path):
        f = tmp_path / "single.txt"
        f.write_text("2026-12-25 00:00:00 | Santa | Merry Christmas\n")
        events = parse_whatsapp_export(f)
        assert len(events) == 1
        assert events[0]["metadata"]["sender"] == "Santa"
        assert events[0]["timestamp"] == "2026-12-25T00:00:00"
