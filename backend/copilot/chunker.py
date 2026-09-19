from __future__ import annotations

"""
NETRA 5.0 — Forensic Evidence Chunker

Provenance-preserving, format-aware document chunker for Indian cyber crime investigations:
1. Format-aware splitting:
   - CSV / Tabular (Bank statements, CDRs) preserves headers and row atomicity
   - Chat logs (WhatsApp, SMS, Telegram) preserves timestamps and message atomicity
   - PDF / Document pages preserves page numbering and paragraph flow
   - Standard forensic reports preserves section boundaries
2. Immutable provenance preservation:
   - Every chunk retains case_id, evidence_file_id, filename, and SHA-256 file_hash
   - Deterministic chunk ID generation based on content and provenance
   - Line and page numbering tracking
3. Never crosses evidence file boundaries
"""

import csv
import hashlib
import io
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .config import get_copilot_config
from .schemas import DocumentChunk


# Chat message regex (e.g. "[12:31] A: text", "12/08/2026, 14:30 - Suspect: message")
CHAT_TIMESTAMP_RE = re.compile(
    r"^(\[?\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}[,\s]+|\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?[,\s\-\]]+)",
    re.MULTILINE,
)


def _clean_filename(raw: str) -> str:
    """Strip UUID prefix from stored filenames for clean human-readable provenance."""
    cleaned = re.sub(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", "", raw)
    return cleaned or raw


class ForensicChunker:
    """Format-aware, provenance-preserving evidence chunker."""

    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        minimum_chunk_size: Optional[int] = None,
    ):
        config = get_copilot_config()
        self.chunk_size = chunk_size or config.chunk_size
        self.chunk_overlap = chunk_overlap or config.chunk_overlap
        self.minimum_chunk_size = minimum_chunk_size or config.minimum_chunk_size

    def _generate_chunk_id(
        self,
        case_id: str,
        evidence_file_id: Optional[str],
        chunk_index: int,
        file_hash: Optional[str],
        content_sample: str,
    ) -> str:
        """Deterministic chunk ID anchored to provenance and content."""
        token = f"{case_id}:{evidence_file_id or 'file'}:{chunk_index}:{file_hash or 'nohash'}:{content_sample[:40]}"
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Plain / Markdown Text Chunking (Paragraph-aware)
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_text(
        self,
        text: str,
        case_id: str,
        filename: str,
        evidence_file_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        source_page: Optional[str] = None,
        base_line_offset: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Chunk continuous text while preserving paragraphs and line ranges."""
        if not text or not text.strip():
            return []

        clean_file = _clean_filename(filename)
        base_meta = dict(metadata or {})
        lines = text.splitlines(keepends=True)
        if not lines:
            return []

        chunks: List[DocumentChunk] = []
        chunk_index = 0

        current_lines: List[str] = []
        current_len = 0
        start_line_num = base_line_offset

        for i, line in enumerate(lines):
            line_len = len(line)
            # If adding this line exceeds chunk_size and we have accumulated enough text
            if current_len + line_len > self.chunk_size and current_len >= self.minimum_chunk_size:
                chunk_text = "".join(current_lines).strip()
                if chunk_text:
                    end_line_num = start_line_num + len(current_lines) - 1
                    line_range = f"{start_line_num}" if start_line_num == end_line_num else f"{start_line_num}-{end_line_num}"

                    chunk_meta = dict(base_meta)
                    chunk_meta.update({
                        "line_start": start_line_num,
                        "line_end": end_line_num,
                        "format": "text",
                    })

                    c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
                    chunks.append(
                        DocumentChunk(
                            id=c_id,
                            case_id=case_id,
                            evidence_file_id=evidence_file_id,
                            filename=clean_file,
                            file_hash=file_hash,
                            chunk_index=chunk_index,
                            text=chunk_text,
                            source_line=line_range,
                            source_page=source_page or "1",
                            metadata=chunk_meta,
                        )
                    )
                    chunk_index += 1

                # Calculate overlap: retain the last N characters of lines
                overlap_lines: List[str] = []
                overlap_len = 0
                for rev_line in reversed(current_lines):
                    if overlap_len + len(rev_line) <= self.chunk_overlap:
                        overlap_lines.insert(0, rev_line)
                        overlap_len += len(rev_line)
                    else:
                        break

                current_lines = overlap_lines
                current_len = overlap_len
                start_line_num = (base_line_offset + i) - len(overlap_lines) + 1

            current_lines.append(line)
            current_len += line_len

        # Flush final chunk
        if current_lines:
            chunk_text = "".join(current_lines).strip()
            if chunk_text:
                end_line_num = start_line_num + len(current_lines) - 1
                line_range = f"{start_line_num}" if start_line_num == end_line_num else f"{start_line_num}-{end_line_num}"
                chunk_meta = dict(base_meta)
                chunk_meta.update({
                    "line_start": start_line_num,
                    "line_end": end_line_num,
                    "format": "text",
                })
                c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
                chunks.append(
                    DocumentChunk(
                        id=c_id,
                        case_id=case_id,
                        evidence_file_id=evidence_file_id,
                        filename=clean_file,
                        file_hash=file_hash,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        source_line=line_range,
                        source_page=source_page or "1",
                        metadata=chunk_meta,
                    )
                )

        return chunks

    # ─────────────────────────────────────────────────────────────────────────
    # 2. CSV / Tabular Chunking (Row-aware, Header-preserved)
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_csv(
        self,
        csv_content: str,
        case_id: str,
        filename: str,
        evidence_file_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Chunk CSV/TSV records while retaining headers in every chunk."""
        if not csv_content or not csv_content.strip():
            return []

        clean_file = _clean_filename(filename)
        base_meta = dict(metadata or {})
        base_meta["format"] = "csv"

        reader = csv.reader(io.StringIO(csv_content.strip()))
        rows = list(reader)
        if not rows:
            return []

        header = rows[0]
        header_text = ", ".join(header)
        data_rows = rows[1:]
        if not data_rows:
            # Only header present
            c_id = self._generate_chunk_id(case_id, evidence_file_id, 0, file_hash, header_text)
            return [
                DocumentChunk(
                    id=c_id,
                    case_id=case_id,
                    evidence_file_id=evidence_file_id,
                    filename=clean_file,
                    file_hash=file_hash,
                    chunk_index=0,
                    text=header_text,
                    source_line="1",
                    source_page="1",
                    metadata=base_meta,
                )
            ]

        chunks: List[DocumentChunk] = []
        chunk_index = 0
        current_rows: List[Tuple[int, List[str]]] = []  # (row_line_number, row)
        current_len = len(header_text)

        for row_idx, row in enumerate(data_rows, start=2):
            row_str = " | ".join(row)
            row_len = len(row_str) + 1  # newline

            if current_len + row_len > self.chunk_size and current_rows:
                # Format chunk with header and aligned records
                chunk_lines = [f"[Header: {header_text}]"]
                for l_num, r in current_rows:
                    chunk_lines.append(f"Row {l_num}: {' | '.join(r)}")
                chunk_text = "\n".join(chunk_lines)

                start_l = current_rows[0][0]
                end_l = current_rows[-1][0]
                line_range = f"{start_l}-{end_l}"

                chunk_meta = dict(base_meta)
                chunk_meta.update({
                    "row_count": len(current_rows),
                    "row_start": start_l,
                    "row_end": end_l,
                })

                c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
                chunks.append(
                    DocumentChunk(
                        id=c_id,
                        case_id=case_id,
                        evidence_file_id=evidence_file_id,
                        filename=clean_file,
                        file_hash=file_hash,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        source_line=line_range,
                        source_page="1",
                        metadata=chunk_meta,
                    )
                )
                chunk_index += 1
                current_rows = []
                current_len = len(header_text)

            current_rows.append((row_idx, row))
            current_len += row_len

        # Flush final rows
        if current_rows:
            chunk_lines = [f"[Header: {header_text}]"]
            for l_num, r in current_rows:
                chunk_lines.append(f"Row {l_num}: {' | '.join(r)}")
            chunk_text = "\n".join(chunk_lines)

            start_l = current_rows[0][0]
            end_l = current_rows[-1][0]
            line_range = f"{start_l}-{end_l}"

            chunk_meta = dict(base_meta)
            chunk_meta.update({
                "row_count": len(current_rows),
                "row_start": start_l,
                "row_end": end_l,
            })

            c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
            chunks.append(
                DocumentChunk(
                    id=c_id,
                    case_id=case_id,
                    evidence_file_id=evidence_file_id,
                    filename=clean_file,
                    file_hash=file_hash,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    source_line=line_range,
                    source_page="1",
                    metadata=chunk_meta,
                )
            )

        return chunks

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Chat / Communication Logs (Message-aware)
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_chat(
        self,
        chat_content: str,
        case_id: str,
        filename: str,
        evidence_file_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Chunk chat logs keeping complete messages atomic."""
        if not chat_content or not chat_content.strip():
            return []

        clean_file = _clean_filename(filename)
        base_meta = dict(metadata or {})
        base_meta["format"] = "chat"

        raw_lines = chat_content.splitlines()
        messages: List[Tuple[int, str]] = []  # (start_line, message_text)
        current_msg_lines: List[str] = []
        current_start_line = 1

        for idx, line in enumerate(raw_lines, start=1):
            # Check if this line begins a new message timestamp
            if CHAT_TIMESTAMP_RE.match(line) and current_msg_lines:
                messages.append((current_start_line, "\n".join(current_msg_lines)))
                current_msg_lines = [line]
                current_start_line = idx
            else:
                current_msg_lines.append(line)

        if current_msg_lines:
            messages.append((current_start_line, "\n".join(current_msg_lines)))

        # Group messages up to chunk_size
        chunks: List[DocumentChunk] = []
        chunk_index = 0
        current_batch: List[Tuple[int, str]] = []
        current_len = 0

        for start_l, msg in messages:
            msg_len = len(msg) + 1
            if current_len + msg_len > self.chunk_size and current_batch:
                chunk_text = "\n\n".join([m for _, m in current_batch])
                start_line = current_batch[0][0]
                end_line = current_batch[-1][0] + current_batch[-1][1].count("\n")
                line_range = f"{start_line}-{end_line}"

                chunk_meta = dict(base_meta)
                chunk_meta.update({
                    "message_count": len(current_batch),
                    "line_start": start_line,
                    "line_end": end_line,
                })

                c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
                chunks.append(
                    DocumentChunk(
                        id=c_id,
                        case_id=case_id,
                        evidence_file_id=evidence_file_id,
                        filename=clean_file,
                        file_hash=file_hash,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        source_line=line_range,
                        source_page="1",
                        metadata=chunk_meta,
                    )
                )
                chunk_index += 1
                current_batch = []
                current_len = 0

            current_batch.append((start_l, msg))
            current_len += msg_len

        # Flush final batch
        if current_batch:
            chunk_text = "\n\n".join([m for _, m in current_batch])
            start_line = current_batch[0][0]
            end_line = current_batch[-1][0] + current_batch[-1][1].count("\n")
            line_range = f"{start_line}-{end_line}"

            chunk_meta = dict(base_meta)
            chunk_meta.update({
                "message_count": len(current_batch),
                "line_start": start_line,
                "line_end": end_line,
            })

            c_id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, chunk_text)
            chunks.append(
                DocumentChunk(
                    id=c_id,
                    case_id=case_id,
                    evidence_file_id=evidence_file_id,
                    filename=clean_file,
                    file_hash=file_hash,
                    chunk_index=chunk_index,
                    text=chunk_text,
                    source_line=line_range,
                    source_page="1",
                    metadata=chunk_meta,
                )
            )

        return chunks

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Multi-Page Document Chunking (PDF / Doc Pages)
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_pages(
        self,
        pages: Sequence[Tuple[int, str]],  # [(page_num, text), ...]
        case_id: str,
        filename: str,
        evidence_file_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Chunk multi-page documents while maintaining strict page provenance."""
        chunks: List[DocumentChunk] = []
        chunk_index = 0

        for page_num, page_text in pages:
            if not page_text or not page_text.strip():
                continue

            page_meta = dict(metadata or {})
            page_meta["page_number"] = page_num
            page_meta["format"] = "pdf_page"

            # Use text chunking scoped strictly to this page
            page_chunks = self.chunk_text(
                text=page_text,
                case_id=case_id,
                filename=filename,
                evidence_file_id=evidence_file_id,
                file_hash=file_hash,
                source_page=str(page_num),
                metadata=page_meta,
            )

            # Re-index globally for the file
            for pc in page_chunks:
                pc.chunk_index = chunk_index
                pc.id = self._generate_chunk_id(case_id, evidence_file_id, chunk_index, file_hash, pc.text)
                chunks.append(pc)
                chunk_index += 1

        return chunks

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Database EvidenceEvents Chunking
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_evidence_events(
        self,
        events: Sequence[Any],  # Sequence of EvidenceEvent or dicts
        case_id: str,
    ) -> List[DocumentChunk]:
        """Directly map and bundle parsed EvidenceEvents into DocumentChunks."""
        chunks: List[DocumentChunk] = []
        for idx, ev in enumerate(events):
            # Support both SQLAlchemy model and dict
            if hasattr(ev, "id"):
                ev_id = str(ev.id)
                file_id = str(ev.evidence_file_id) if ev.evidence_file_id else None
                text = (ev.text_content or "").strip()
                s_line = str(ev.source_line or "1")
                s_page = str(ev.source_page or "1")
                ev_meta = ev.event_metadata or {}
                ev_type = ev.event_type or "event"
            else:
                ev_id = str(ev.get("id", idx))
                file_id = str(ev.get("evidence_file_id", "")) or None
                text = (ev.get("text_content") or ev.get("text") or "").strip()
                s_line = str(ev.get("source_line") or "1")
                s_page = str(ev.get("source_page") or "1")
                ev_meta = ev.get("event_metadata") or ev.get("metadata") or {}
                ev_type = ev.get("event_type", "event")

            if not text:
                continue

            src_file = _clean_filename(str(ev_meta.get("source_file") or f"{ev_type}.dat"))
            f_hash = ev_meta.get("file_hash") or ev_meta.get("sha256")

            c_id = self._generate_chunk_id(case_id, file_id, idx, f_hash, text)
            chunks.append(
                DocumentChunk(
                    id=c_id,
                    case_id=case_id,
                    evidence_file_id=file_id,
                    filename=src_file,
                    file_hash=f_hash,
                    chunk_index=idx,
                    text=text,
                    source_line=s_line,
                    source_page=s_page,
                    metadata={"event_id": ev_id, "event_type": ev_type, **ev_meta},
                )
            )

        return chunks

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Universal Evidence File Router
    # ─────────────────────────────────────────────────────────────────────────

    def chunk_evidence_content(
        self,
        content: str,
        case_id: str,
        filename: str,
        evidence_file_id: Optional[str] = None,
        file_hash: Optional[str] = None,
        file_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Inspect format and route to the optimal chunking strategy."""
        fn_lower = filename.lower()
        ft_lower = (file_type or "").lower()

        # CSV / Tabular
        if fn_lower.endswith(".csv") or fn_lower.endswith(".tsv") or "csv" in ft_lower:
            return self.chunk_csv(content, case_id, filename, evidence_file_id, file_hash, metadata)

        # Chat / WhatsApp
        if "chat" in fn_lower or "whatsapp" in fn_lower or CHAT_TIMESTAMP_RE.search(content[:500]):
            return self.chunk_chat(content, case_id, filename, evidence_file_id, file_hash, metadata)

        # Standard Text / Report
        return self.chunk_text(content, case_id, filename, evidence_file_id, file_hash, metadata=metadata)
