from __future__ import annotations
"""
CyberDrishti AI — Evidence Upload & Processing Routes (Phase 7)
POST /upload — multipart zip, routes to parsers, SHA-256 hash at ingestion.
"""
import base64
import csv
import hashlib
import io
import json
import os
import pathlib
import tempfile
import time
import uuid
import zipfile
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import contextlib
from typing import Any, Generator, Optional, Dict, List

from config import settings
from db.models import Entity, EntityMention, EvidenceEvent, EvidenceFile, IdentityCandidate, User
from db.session import AsyncSessionLocal, get_db
from graph.graph_builder import _similarity
from nlp.entity_validation import validate_entity_candidate
from routes.auth import get_current_user
from routes.case_access import require_case_access
from routes.cases import _audit
from utils.encryption import EnvelopeEncryption

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = pathlib.Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STAGING_DIR = UPLOAD_DIR / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)
MAX_ARCHIVE_MEMBERS = 100
MAX_ARCHIVE_RATIO = 100

# ── Server-Side Idempotency Cache for Preview Confirmations ──────────────────
# Retained for 1 hour to absorb network retries, browser reloads, and double-clicks
_SEALED_PREVIEW_CACHE: dict[str, dict[str, Any]] = {}
_SEALED_PREVIEW_LOCK = asyncio.Lock()


def _cache_sealed_preview(preview_id: str, record: dict[str, Any]) -> None:
    now = time.time()
    for k in list(_SEALED_PREVIEW_CACHE.keys()):
        if now - _SEALED_PREVIEW_CACHE[k].get("timestamp", 0) > 3600:
            _SEALED_PREVIEW_CACHE.pop(k, None)
    _SEALED_PREVIEW_CACHE[preview_id] = {
        "timestamp": now,
        "record": record,
    }


def _get_sealed_preview(preview_id: str) -> dict[str, Any] | None:
    entry = _SEALED_PREVIEW_CACHE.get(preview_id)
    if entry and (time.time() - entry.get("timestamp", 0) <= 3600):
        return entry.get("record")
    return None


def _cleanup_stale_staging(max_age_seconds: int = 1800) -> None:
    """Prune any abandoned unconfirmed preview staging files older than 30 minutes."""
    try:
        if not STAGING_DIR.exists():
            return
        now = time.time()
        for p in STAGING_DIR.rglob("*"):
            if p.is_file():
                try:
                    if now - p.stat().st_mtime > max_age_seconds:
                        p.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass


def sanitize_db_val(val):
    if isinstance(val, str):
        # Replace common non-WIN1252 characters like Rupee symbol with Windows-1252 compatible characters
        val = val.replace('₹', 'Rs.')
        try:
            return val.encode('windows-1252', errors='replace').decode('windows-1252')
        except Exception:
            return val.encode('ascii', errors='ignore').decode('ascii')
    elif isinstance(val, dict):
        return {k: sanitize_db_val(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_db_val(v) for v in val]
    return val


# ── SHA-256 hash helper ───────────────────────────────────────────────────────

def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_display_name(filename: str | None) -> str:
    name = pathlib.PurePath((filename or "evidence").replace("\\", "/")).name
    name = "".join(ch for ch in name if ch >= " " and ch not in '<>:"/\\|?*').strip(" .")
    return (name or "evidence")[:240]


async def _read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"File exceeds the {settings.max_upload_size_mb} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _lock_evidence_hash(db: AsyncSession, case_id: uuid.UUID, sha256: str) -> None:
    """Serialize same-case hash ingestion on PostgreSQL; DB uniqueness is the final guard."""
    if db.bind and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"{case_id}:{sha256}"},
        )


async def _existing_evidence(db: AsyncSession, case_id: uuid.UUID, sha256: str) -> EvidenceFile | None:
    await _lock_evidence_hash(db, case_id, sha256)
    return (await db.execute(
        select(EvidenceFile).where(
            EvidenceFile.case_id == case_id,
            EvidenceFile.sha256_hash == sha256,
        )
    )).scalar_one_or_none()


def read_decrypted_bytes(ev_file: EvidenceFile) -> bytes:
    """Read plaintext bytes of an evidence file, decrypting on the fly if encrypted."""
    storage_path = pathlib.Path(ev_file.storage_path)
    if not storage_path.exists():
        raise FileNotFoundError(f"Stored evidence file not found at {storage_path}")
    raw_data = storage_path.read_bytes()
    if not getattr(ev_file, "is_encrypted", False):
        return raw_data
    return EnvelopeEncryption.decrypt_bytes(
        ciphertext=raw_data,
        encrypted_dek_b64=ev_file.encrypted_dek,
        iv_b64=ev_file.encryption_iv,
    )


@contextlib.contextmanager
def open_decrypted_evidence(ev_file: EvidenceFile) -> Generator[pathlib.Path, None, None]:
    """
    Yields a temporary path containing the decrypted plaintext for parsing or analysis.
    Safely removes the temporary plaintext file upon exit.
    """
    storage_path = pathlib.Path(ev_file.storage_path)
    if not getattr(ev_file, "is_encrypted", False):
        yield storage_path
        return

    plaintext = read_decrypted_bytes(ev_file)
    suffix = pathlib.Path(ev_file.original_name or ev_file.filename).suffix
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(plaintext)
        tmp.flush()
        tmp_path = pathlib.Path(tmp.name)

    try:
        yield tmp_path
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


async def _register_evidence(
    db: AsyncSession,
    *,
    case_id: uuid.UUID,
    current: User,
    original_name: str,
    source_type: str,
    raw: bytes,
) -> tuple[EvidenceFile, pathlib.Path, bool]:
    sha256 = hashlib.sha256(raw).hexdigest()
    duplicate = await _existing_evidence(db, case_id, sha256)
    if duplicate:
        return duplicate, pathlib.Path(duplicate.storage_path), True

    display_name = _safe_display_name(original_name)
    suffix = pathlib.Path(display_name).suffix.lower()[:12]
    case_upload_dir = UPLOAD_DIR / str(case_id)
    case_upload_dir.mkdir(parents=True, exist_ok=True)
    destination = case_upload_dir / f"{uuid.uuid4().hex}{suffix}"

    # Envelope encryption at rest: AES-256-GCM with per-file random DEK
    ciphertext, encrypted_dek_b64, payload_iv_b64 = EnvelopeEncryption.encrypt_bytes(raw)
    cipher_hash = hashlib.sha256(ciphertext).hexdigest()

    temp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=case_upload_dir, delete=False) as staged:
            staged.write(ciphertext)
            staged.flush()
            os.fsync(staged.fileno())
            temp_path = pathlib.Path(staged.name)
        if _sha256_file(temp_path) != cipher_hash:
            raise HTTPException(500, "Evidence integrity verification failed during ingestion")
        temp_path.replace(destination)
        ev_file = EvidenceFile(
            case_id=case_id,
            filename=destination.name,
            original_name=display_name,
            file_type=_detect_file_type(display_name),
            source_type=source_type,
            file_size_bytes=len(raw),
            sha256_hash=sha256,
            storage_path=str(destination),
            uploaded_by=current.id,
            is_encrypted=True,
            encrypted_dek=encrypted_dek_b64,
            encryption_iv=payload_iv_b64,
            acquisition_tool="CyberDrishti Ingestion v5.0",
            acquisition_timestamp=datetime.now(timezone.utc),
        )
        db.add(ev_file)
        await db.flush()
        return ev_file, destination, False
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise


def _detect_file_type(filename: str) -> str:
    ext = pathlib.Path(filename).suffix.lower()
    return {
        ".pdf": "pdf", ".csv": "csv",
        ".png": "image", ".jpg": "image", ".jpeg": "image",
        ".webp": "image", ".tiff": "image", ".bmp": "image",
        ".zip": "zip", ".txt": "txt", ".json": "json",
    }.get(ext, "other")


def _detect_mime_and_validate(raw: bytes, filename: str) -> tuple[str, str]:
    """
    Validates file headers and detects MIME type and normalized category.
    Protects against file extension spoofing and executable binaries disguised as documents.
    """
    ext = pathlib.Path(filename).suffix.lower()

    # Check Magic Bytes
    if raw.startswith(b"%PDF-"):
        return "application/pdf", "pdf"
    elif raw.startswith(b"PK\x03\x04") or raw.startswith(b"PK\x05\x06") or raw.startswith(b"PK\x07\x08"):
        return "application/zip", "zip"
    elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "image"
    elif raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "image"
    elif raw.startswith(b"RIFF") and len(raw) > 12 and raw[8:12] == b"WEBP":
        return "image/webp", "image"
    elif raw.startswith(b"II*\x00") or raw.startswith(b"MM\x00*"):
        return "image/tiff", "image"
    elif raw.startswith(b"BM"):
        return "image/bmp", "image"

    # Reject dangerous executable formats regardless of extension
    if raw.startswith(b"MZ") or raw.startswith(b"\x7fELF") or raw.startswith(b"\xca\xfe\xba\xbe") or raw.startswith(b"\xfe\xed\xfa\xce") or raw.startswith(b"\xfe\xed\xfa\xcf"):
        raise HTTPException(400, "Executable binary files are strictly prohibited in evidence intake")

    # Check for text formats (JSON, CSV, TXT, LOG)
    is_text = False
    decoded_head = ""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "windows-1252"):
        try:
            decoded_head = raw[:4096].decode(enc)
            is_text = True
            break
        except UnicodeDecodeError:
            continue

    if is_text:
        stripped = decoded_head.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
            return "application/json", "json"
        if ext in (".csv", ".tsv"):
            return "text/csv", "csv"
        if ext in (".txt", ".log"):
            return "text/plain", "txt"
        if ext in (".json",):
            return "application/json", "json"
        return "text/plain", "txt"

    mapped = _detect_file_type(filename)
    if mapped != "other":
        mime_map = {
            "pdf": "application/pdf",
            "csv": "text/csv",
            "image": "image/jpeg",
            "zip": "application/zip",
            "txt": "text/plain",
            "json": "application/json",
        }
        return mime_map.get(mapped, "application/octet-stream"), mapped

    return "application/octet-stream", "other"


def _extract_preview_metadata(raw: bytes, filename: str, ftype: str, mime_type: str) -> dict[str, Any]:
    """
    Extract read-only inspection metadata from original bytes.
    NEVER modifies original bytes. Purely for forensic review prior to cryptographic hashing.
    """
    metadata: dict[str, Any] = {
        "filename": filename,
        "file_type": ftype,
        "mime_type": mime_type,
        "file_size_bytes": len(raw),
        "page_count": None,
        "row_count": None,
        "line_count": None,
        "preview_text": None,
        "preview_rows": None,
        "preview_image": None,
        "archive_manifest": None,
        "detected_subtype": None,
        "metadata_fields": {},
    }

    if ftype == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                metadata["page_count"] = len(pdf.pages)
                metadata["metadata_fields"] = {k: str(v) for k, v in (pdf.metadata or {}).items() if v}
                if pdf.pages:
                    first_text = pdf.pages[0].extract_text() or ""
                    metadata["preview_text"] = first_text[:2000]
                    lower_text = first_text.lower()
                    if any(k in lower_text for k in ("evidence seizure", "custody memo", "seizure / custody memo")):
                        metadata["detected_subtype"] = "Seizure / Panchnama Memo"
                    elif any(k in lower_text for k in ("location / cell-site timeline", "cell-site association", "location reference")):
                        metadata["detected_subtype"] = "Location & Cell Tower Timeline"
                    elif any(k in lower_text for k in ("device extraction", "forensic extraction", "device id")):
                        metadata["detected_subtype"] = "Device Extraction Report"
                    elif any(k in lower_text for k in ("upi transaction", "upi report", "payer", "payee")):
                        metadata["detected_subtype"] = "UPI / Banking Transaction Statement"
                    elif any(k in lower_text for k in ("bank", "account", "balance", "debit", "credit")):
                        metadata["detected_subtype"] = "Bank Statement"
                    else:
                        metadata["detected_subtype"] = "Forensic PDF Document"
        except Exception as e:
            metadata["metadata_fields"]["pdf_error"] = f"Partial read: {str(e)[:100]}"
            metadata["detected_subtype"] = "PDF Document"

    elif ftype == "csv":
        try:
            text_content = raw.decode("utf-8", errors="replace")
            lines = [line for line in text_content.splitlines() if line.strip()]
            metadata["line_count"] = len(lines)
            metadata["row_count"] = max(0, len(lines) - 1)
            reader = list(csv.reader(lines[:12]))
            if reader:
                headers = reader[0]
                rows = reader[1:11]
                metadata["preview_rows"] = {
                    "headers": headers,
                    "sample_rows": rows,
                    "total_rows": metadata["row_count"],
                }
                head_str = " ".join(headers).lower()
                if any(k in head_str for k in ("call", "duration", "imei", "imsi", "tower", "cdr")):
                    metadata["detected_subtype"] = "Call Detail Record (CDR)"
                elif any(k in head_str for k in ("narration", "credit", "debit", "balance", "upi")):
                    metadata["detected_subtype"] = "Banking / Financial Ledger"
                elif any(k in head_str for k in ("src_ip", "dst_ip", "bytes", "port", "protocol")):
                    metadata["detected_subtype"] = "Network Traffic / Firewall Log"
                elif any(k in head_str for k in ("sender", "message", "chat", "text")):
                    metadata["detected_subtype"] = "Chat / Communication Export"
                else:
                    metadata["detected_subtype"] = "Structured CSV Dataset"
        except Exception:
            metadata["detected_subtype"] = "CSV Document"

    elif ftype in ("txt", "json"):
        try:
            text_content = raw.decode("utf-8", errors="replace")
            lines = text_content.splitlines()
            metadata["line_count"] = len(lines)
            metadata["preview_text"] = "\n".join(lines[:40])[:2500]
            if ftype == "json":
                metadata["detected_subtype"] = "Device Extraction JSON Payload"
            else:
                if any(":" in l and ("am" in l.lower() or "pm" in l.lower() or "-" in l) for l in lines[:5]):
                    metadata["detected_subtype"] = "Chat / Messaging Transcript"
                else:
                    metadata["detected_subtype"] = "Text Forensic Artifact"
        except Exception:
            metadata["detected_subtype"] = "Text Document"

    elif ftype == "image":
        try:
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as img:
                metadata["metadata_fields"] = {
                    "dimensions": f"{img.width} × {img.height}",
                    "format": img.format,
                    "mode": img.mode,
                }
                metadata["detected_subtype"] = f"{img.format or 'Image'} Evidence Capture"
                if len(raw) < 1_500_000:
                    b64 = base64.b64encode(raw).decode("ascii")
                    metadata["preview_image"] = f"data:{mime_type};base64,{b64}"
                else:
                    thumb = img.copy()
                    thumb.thumbnail((800, 800))
                    buf = io.BytesIO()
                    thumb.save(buf, format="JPEG", quality=80)
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    metadata["preview_image"] = f"data:image/jpeg;base64,{b64}"
        except Exception:
            metadata["detected_subtype"] = "Image Evidence"

    elif ftype == "zip":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                total_uncompressed = sum(m.file_size for m in members)
                metadata["metadata_fields"] = {
                    "member_count": len(members),
                    "uncompressed_size_bytes": total_uncompressed,
                }
                metadata["archive_manifest"] = [
                    {
                        "filename": _safe_display_name(m.filename),
                        "file_size": m.file_size,
                        "compress_size": m.compress_size,
                    }
                    for m in members[:50]
                ]
        except Exception:
            metadata["detected_subtype"] = "ZIP Archive"

    if metadata.get("preview_rows"):
        p_rows = metadata["preview_rows"]
        headers = p_rows.get("headers", [])
        metadata["column_names"] = headers
        metadata["sample_rows"] = [dict(zip(headers, r)) for r in p_rows.get("sample_rows", [])]
    if metadata.get("preview_text"):
        metadata["text_snippet"] = metadata["preview_text"]
    if metadata.get("preview_image"):
        metadata["thumbnail_data_url"] = metadata["preview_image"]
    if metadata.get("archive_manifest"):
        metadata["member_count"] = len(metadata["archive_manifest"])
        metadata["members"] = [m["filename"] for m in metadata["archive_manifest"]]

    return metadata


def _classify_and_route_file(path: pathlib.Path) -> tuple[str, str]:
    """
    Auto-classify individual files based on extension AND file header/content inspection.
    Segregates batch uploads so every file is routed to its optimal parser model:
    WhatsApp chat -> parse_whatsapp_export
    Bank CSV/PDF  -> parse_bank_pdf / Bank Txn Parser
    CDR Call Log  -> parse_call_log_csv
    ID/Image OCR  -> parse_image_ocr
    """
    ext = path.suffix.lower()
    head_sample = ""
    try:
        if ext in (".txt", ".csv", ".log"):
            head_sample = path.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
    except Exception:
        pass

    if ext == ".txt":
        return "txt", "whatsapp"
    elif ext == ".json":
        return "json", "device_extraction"
    elif ext == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                if pdf.pages:
                    pdf_text = (pdf.pages[0].extract_text() or "").lower()
                    if any(k in pdf_text for k in ("evidence seizure", "custody memo", "seizure / custody memo")):
                        return "pdf", "seizure_memo"
                    if any(k in pdf_text for k in ("location / cell-site timeline", "cell-site association", "location reference", "cell-site timeline")):
                        return "pdf", "location_timeline"
                    if any(k in pdf_text for k in ("device extraction", "forensic extraction", "device id", "extraction reference")):
                        return "pdf", "device_extraction"
                    if any(k in pdf_text for k in ("upi transaction", "upi report", "payer", "payee")):
                        return "pdf", "bank_statement"
        except Exception:
            pass
        return "pdf", "bank_statement"
    elif ext in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"):
        return "image", "ocr_document"
    elif ext in (".csv", ".xlsx"):
        first_line = head_sample.splitlines()[0] if head_sample.splitlines() else ""
        first_cols = [c.strip().lower().replace('"', '').replace("'", "") for c in first_line.split(",")]
        try:
            from parsers.network_log_parser import is_network_log_header
            if is_network_log_header(first_cols):
                return "csv", "network_log"
        except Exception:
            pass

        if any(k in head_sample for k in ("narration", "credit", "debit", "balance", "upi", "bank", "account", "txn")):
            return "csv", "bank_statement"
        elif any(k in head_sample for k in ("call", "duration", "caller", "receiver", "imei", "imsi", "tower", "cdr")):
            return "csv", "cdr_call_log"
        elif any(k in head_sample for k in ("message", "chat", "sender", "text")):
            return "csv", "whatsapp"
        else:
            return "csv", "cdr_call_log"
    elif ext == ".zip":
        return "zip", "archive"
    else:
        return "other", "unknown"


def _safe_parse_iso(val: Any) -> datetime | None:
    """Robust parser for varying timestamp formats across evidence exports."""
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        clean_val = val.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(clean_val)
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d-%m-%Y %H:%M",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d/%m/%y %H:%M:%S",
            "%d/%m/%Y %I:%M:%S %p",
            "%d/%m/%Y %I:%M %p",
            "%Y/%m/%d %H:%M:%S",
        ):
            try:
                return datetime.strptime(clean_val, fmt)
            except Exception:
                pass
    return None


async def _process_evidence_file(evidence_file_id: str | uuid.UUID, file_path: str):
    """Parse evidence file in the background and store events."""
    if isinstance(evidence_file_id, str):
        try:
            evidence_file_id = uuid.UUID(evidence_file_id)
        except Exception:
            pass

    async with AsyncSessionLocal() as db:
        ev_file = await db.get(EvidenceFile, evidence_file_id)
        if not ev_file:
            return

        ev_file.upload_status = "processing"
        await db.commit()

        ev_file_cm = open_decrypted_evidence(ev_file)
        path = ev_file_cm.__enter__()
        try:
            # Lazy imports safely inside the try block
            from parsers.whatsapp_parser import parse_whatsapp_export
            from parsers.bank_pdf_parser import parse_bank_pdf
            from parsers.bank_csv_parser import parse_bank_csv
            from parsers.call_log_parser import parse_call_log_csv
            from parsers.ocr_parser import parse_image_ocr
            from parsers.network_log_parser import parse_network_log_csv
            from parsers.location_timeline_parser import parse_location_timeline
            from parsers.seizure_memo_parser import parse_seizure_memo

            storage_p = pathlib.Path(file_path)
            resolved_storage = storage_p.resolve()
            if UPLOAD_DIR.resolve() not in resolved_storage.parents:
                raise ValueError("Evidence storage path is outside the protected upload directory")
            resolved_path = path.resolve()
            if _sha256_file(resolved_path) != ev_file.sha256_hash:
                raise ValueError("Stored evidence hash does not match the ingestion record")
            events: list[dict] = []

            # Dynamic classification and model routing per file
            file_type, detected_source_type = _classify_and_route_file(path)
            ev_file.file_type = file_type
            if not ev_file.source_type or ev_file.source_type in ("unknown", "zip", "archive"):
                ev_file.source_type = detected_source_type

            if file_type == "txt" or detected_source_type == "whatsapp":
                try:
                    events = parse_whatsapp_export(path)
                except Exception:
                    events = []
            elif detected_source_type == "seizure_memo":
                try:
                    events = parse_seizure_memo(path)
                except Exception:
                    events = []
            elif detected_source_type == "network_log":
                try:
                    events = parse_network_log_csv(path)
                except Exception:
                    events = []
            elif detected_source_type == "location_timeline":
                try:
                    events = parse_location_timeline(path)
                except Exception:
                    events = []
            elif detected_source_type == "bank_statement":
                if file_type == "pdf":
                    try:
                        events = parse_bank_pdf(path)
                    except Exception:
                        events = []
                else:
                    # Structured CSV parse (ledger + transfer schemas). Falls
                    # back to raw-line capture below if it yields nothing.
                    try:
                        events = parse_bank_csv(path)
                    except Exception:
                        events = []
            elif detected_source_type == "cdr_call_log":
                try:
                    events = parse_call_log_csv(path)
                except Exception:
                    events = []
            elif file_type == "image":
                try:
                    events = parse_image_ocr(path)
                except Exception:
                    events = []
            elif file_type == "pdf":
                try:
                    events = parse_bank_pdf(path)
                except Exception:
                    events = []
            elif file_type == "json" or detected_source_type == "device_extraction":
                try:
                    import json
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    data = json.loads(content)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                events.append({
                                    "source_doc": path.name,
                                    "timestamp": item.get("timestamp"),
                                    "text": f"{item.get('artifact_type', 'EVENT')}: {item.get('artifact', '')} phone={item.get('phone', '')} device={item.get('device_id', '')}",
                                    "event_type": "device_extraction",
                                    "source_line": 1,
                                    "source_page": 1,
                                    "metadata": item,
                                })
                    elif isinstance(data, dict):
                        events.append({
                            "source_doc": path.name,
                            "timestamp": data.get("timestamp") or data.get("created"),
                            "text": data.get("title") or data.get("purpose") or str(data),
                            "event_type": "document_text",
                            "source_line": 1,
                            "source_page": 1,
                            "metadata": data,
                        })
                except Exception:
                    events = []

            # Fallback for PDF documents without tabular transactions (FIRs, charge sheets, reports, device extraction)
            if not events and file_type == "pdf":
                try:
                    import re
                    import pdfplumber
                    with pdfplumber.open(str(path)) as pdf:
                        for page_idx, page in enumerate(pdf.pages, start=1):
                            text = page.extract_text() or ""
                            for line_idx, line in enumerate(text.splitlines(), start=1):
                                line_clean = line.strip()
                                if line_clean:
                                    line_ts = None
                                    ts_m = re.match(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)", line_clean)
                                    if ts_m:
                                        line_ts = ts_m.group(1)
                                    events.append({
                                        "source_doc": path.name,
                                        "timestamp": line_ts,
                                        "text": line_clean,
                                        "event_type": "document_text",
                                        "source_line": line_idx,
                                        "source_page": page_idx,
                                        "metadata": {"page": page_idx}
                                    })
                except Exception:
                    pass

            # Fallback for text/csv files without parsed events
            if not events and file_type in ("txt", "csv", "log", "other"):
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for idx, line in enumerate(lines, start=1):
                        line_clean = line.strip()
                        if line_clean:
                            events.append({
                                "source_doc": path.name,
                                "timestamp": None,
                                "text": line_clean,
                                "event_type": "text_record",
                                "source_line": idx,
                                "source_page": 1,
                                "metadata": {"raw_line": line_clean}
                            })
                except Exception:
                    pass

            diff_obj = None
            # ── Feature 01: Resilient Fingerprinting & Variant Detection ─────
            try:
                from cognitive.fingerprint import FingerprintEngine
                fp_engine = FingerprintEngine()
                raw_bytes = resolved_path.read_bytes()
                fp = fp_engine.compute(raw_bytes, events)
                ev_file.fingerprint_hash = f"MH-{fp.sha256[:8].upper()}"

                # Cross-check existing files in the same case for appended/variant statements
                other_files = (await db.execute(
                    select(EvidenceFile).where(
                        EvidenceFile.case_id == ev_file.case_id,
                        EvidenceFile.id != ev_file.id,
                        EvidenceFile.file_type == ev_file.file_type,
                        EvidenceFile.upload_status == "processed",
                    )
                )).scalars().all()

                for prev_f in other_files:
                    if prev_f.storage_path and pathlib.Path(prev_f.storage_path).exists():
                        try:
                            prev_raw = read_decrypted_bytes(prev_f)
                            prev_evts = (await db.execute(
                                select(EvidenceEvent).where(EvidenceEvent.evidence_file_id == prev_f.id)
                            )).scalars().all()
                            prev_dicts = [
                                {
                                    "event_type": e.event_type or "event",
                                    "timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
                                    "amount": (e.event_metadata or {}).get("amount", ""),
                                    "reference": (e.event_metadata or {}).get("reference", "") or (e.text_content or "")[:40],
                                }
                                for e in prev_evts
                            ]
                            prev_fp = fp_engine.compute(prev_raw, prev_dicts)
                            comp = fp_engine.compare(prev_fp, fp)
                            if comp.get("verdict") == "VARIANT":
                                diff = fp_engine.structural_diff(prev_dicts, events)
                                diff_obj = diff
                                containment = float(comp.get("containment") or comp.get("overlap_ratio", 0.9))
                                jaccard = float(comp.get("jaccard_estimate", 0.0))
                                ev_file.parent_evidence_id = prev_f.id
                                ev_file.version_number = (prev_f.version_number or 1) + 1
                                ev_file.version_status = "variant"
                                ev_file.parse_error = f"[VARIANT] Appended document (+{len(diff.added)} new rows, {round(containment*100)}% containment with {prev_f.original_name})"
                                ev_file.variant_details = {
                                    "parent_id": str(prev_f.id),
                                    "parent_name": prev_f.original_name,
                                    "containment": containment,
                                    "jaccard": jaccard,
                                    "verdict": "VARIANT",
                                    "diff": diff.summary,
                                    "added_row_count": len(diff.added),
                                    "removed_row_count": len(diff.removed),
                                    "unchanged_row_count": len(diff.unchanged),
                                }
                                uploader = await db.get(User, ev_file.uploaded_by)
                                if uploader is not None:
                                    await _audit(
                                        db,
                                        uploader,
                                        "VARIANT_EVIDENCE_DETECTED",
                                        str(ev_file.case_id),
                                        {
                                            "evidence_id": str(ev_file.id),
                                            "parent_id": str(prev_f.id),
                                            "parent_file": prev_f.original_name,
                                            "version_number": ev_file.version_number,
                                            "containment": containment,
                                            "diff": diff.summary,
                                        },
                                    )
                                break
                        except Exception as comp_exc:
                            import traceback as _tb
                            print(f"[WARN] Fingerprint compare failed against {prev_f.id}: {comp_exc}")
                            print(_tb.format_exc())
            except Exception as fp_exc:
                import traceback as _tb
                print(f"[WARN] Fingerprint engine top-level failed: {fp_exc}")
                print(_tb.format_exc())

            # Insert events and materialise deterministic entity mentions for
            # the timeline, graph and retrieval layers.
            from correlation.regex_extractors import extract, Extraction
            
            existing_entities = (await db.execute(
                select(Entity).where(Entity.case_id == ev_file.case_id)
            )).scalars().all()
            entity_cache: dict[tuple[str, str], Entity] = {
                (e.entity_type, e.canonical_value.lower()): e
                for e in existing_entities
            }
            detected_candidates: set[tuple[str, str]] = set()

            for idx, evt in enumerate(events):
                event_id = uuid.uuid4()
                event = EvidenceEvent(
                    id=event_id,
                    case_id=ev_file.case_id,
                    evidence_file_id=ev_file.id,
                    event_timestamp=_safe_parse_iso(evt.get("timestamp")),
                    event_type=evt.get("event_type"),
                    text_content=sanitize_db_val(evt.get("text")),
                    source_line=evt.get("source_line"),
                    source_page=evt.get("source_page"),
                    event_metadata=sanitize_db_val(evt.get("metadata", {})),
                )
                db.add(event)

                # High-throughput classification:
                # Tabular / machine log events bypass natural language ML NER for speed
                is_machine_log = evt.get("event_type") in (
                    "network_log", "cctv_frame", "device_extraction", "cdr_call", "location_timeline", "bank_txn", "upi_txn"
                )
                extracted_items = []
                if not is_machine_log:
                    try:
                        from ml.inference import run_hybrid_extraction
                        hybrid_res = run_hybrid_extraction(evt.get("text") or "")
                        for m in hybrid_res.mentions:
                            etype = "PER" if m.entity_type in ("PERSON", "PER") else m.entity_type
                            extracted_items.append(Extraction(
                                entity_type=etype,
                                raw_value=m.raw_value,
                                norm_value=m.canonical_value,
                                span_start=m.span_start,
                                span_end=m.span_end,
                                confidence=m.confidence,
                                extractor=m.extractor,
                            ))
                    except Exception:
                        extracted_items = list(extract(evt.get("text") or ""))
                else:
                    extracted_items = list(extract(evt.get("text") or ""))

                sender_name = (evt.get("metadata") or {}).get("sender")
                if isinstance(sender_name, str):
                    sender_name = sender_name.strip()
                    if (
                        sender_name
                        and sender_name.upper() not in {
                            "UNKNOWN",
                            "UNK",
                            "N/A",
                            "NA",
                            "NULL",
                            "NONE",
                            "SYSTEM",
                            "UNKNOWN SENDER",
                            "UNKNOWN PARTICIPANT",
                        }
                        and not sender_name.startswith("+")
                    ):
                        extracted_items.append(Extraction(
                            entity_type="PER",
                            raw_value=sender_name,
                            norm_value=sender_name,
                            span_start=0,
                            span_end=len(sender_name),
                            extractor="sender_name",
                        ))

                # Named transfer accounts (e.g. ACCT-MULE-11) are alphanumeric and
                # are NOT matched by the digit-based ACCOUNT regex. Surface them as
                # graph entities directly from the parsed structured metadata so
                # money-flow edges form between the debit and credit parties.
                _meta = evt.get("metadata") or {}
                if evt.get("event_type") == "network_log":
                    _dev = _meta.get("device")
                    if _dev and isinstance(_dev, str) and not any(e.raw_value == _dev for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="DEVICE",
                            raw_value=_dev,
                            norm_value=_dev.upper(),
                            span_start=0,
                            span_end=len(_dev),
                            extractor="network_log_field",
                        ))
                    _ip = _meta.get("ip")
                    if _ip and isinstance(_ip, str) and not any(e.raw_value == _ip for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="IP",
                            raw_value=_ip,
                            norm_value=_ip,
                            span_start=0,
                            span_end=len(_ip),
                            extractor="network_log_field",
                        ))
                if evt.get("event_type") == "location_timeline":
                    _phone = _meta.get("phone")
                    if _phone and isinstance(_phone, str) and not any(e.raw_value == _phone for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="PHONE",
                            raw_value=_phone,
                            norm_value=_phone.strip(),
                            span_start=0,
                            span_end=len(_phone),
                            extractor="location_timeline_field",
                        ))
                    _tower = _meta.get("cell_tower")
                    if _tower and isinstance(_tower, str) and not any(e.raw_value == _tower for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="CELL_TOWER",
                            raw_value=_tower,
                            norm_value=_tower.strip().upper(),
                            span_start=0,
                            span_end=len(_tower),
                            extractor="location_timeline_field",
                        ))
                    _city = _meta.get("city")
                    if _city and isinstance(_city, str) and not any(e.raw_value == _city for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="LOCATION",
                            raw_value=_city,
                            norm_value=_city.strip(),
                            span_start=0,
                            span_end=len(_city),
                            extractor="location_timeline_field",
                        ))
                if evt.get("event_type") == "seizure_memo":
                    _collector = _meta.get("collector")
                    if _collector and isinstance(_collector, str) and not any(e.raw_value == _collector for e in extracted_items):
                        extracted_items.append(Extraction(
                            entity_type="PER",
                            raw_value=_collector.strip(),
                            norm_value=_collector.strip(),
                            span_start=0,
                            span_end=len(_collector.strip()),
                            extractor="seizure_memo_field",
                        ))
                for _acct_key in ("from_account", "to_account", "account"):
                    _acct = _meta.get(_acct_key)
                    if _acct and isinstance(_acct, str):
                        _acct = _acct.strip()
                        if len(_acct) >= 3 and not _acct.isdigit():
                            extracted_items.append(Extraction(
                                entity_type="ACCOUNT",
                                raw_value=_acct,
                                norm_value=_acct.upper(),
                                span_start=0,
                                span_end=len(_acct),
                                extractor="bank_csv_field",
                            ))

                for found in extracted_items:
                    if not validate_entity_candidate(found.entity_type, found.raw_value):
                        continue

                    canonical_value = str(found.norm_value if found.norm_value is not None else found.raw_value).strip()
                    if not canonical_value:
                        continue
                    key = (found.entity_type, canonical_value.lower())
                    entity = entity_cache.get(key)
                    if entity is None:
                        # Check for identity ambiguity against existing entities before creation
                        if found.entity_type in ("PER", "LOCATION", "ORG"):
                            for (other_etype, other_norm), other_ent in list(entity_cache.items()):
                                if other_etype == found.entity_type and other_norm != canonical_value.lower():
                                    sim = _similarity(canonical_value, other_ent.canonical_value, found.entity_type)
                                    if 0.80 <= sim < 1.0:
                                        pair_key = (min(canonical_value.lower(), other_norm), max(canonical_value.lower(), other_norm))
                                        if pair_key not in detected_candidates:
                                            detected_candidates.add(pair_key)
                                            db.add(IdentityCandidate(
                                                id=uuid.uuid4(),
                                                case_id=ev_file.case_id,
                                                canonical_entity_id=other_ent.id,
                                                candidate_value=sanitize_db_val(canonical_value),
                                                candidate_type=found.entity_type,
                                                source_refs=[{
                                                    "evidence_file_id": str(ev_file.id),
                                                    "event_id": str(event.id),
                                                    "similarity": round(sim, 3),
                                                    "matched_canonical": other_ent.canonical_value,
                                                }],
                                                resolution_status="UNRESOLVED",
                                            ))

                        entity = Entity(
                            id=uuid.uuid4(),
                            case_id=ev_file.case_id,
                            canonical_value=sanitize_db_val(canonical_value),
                            entity_type=found.entity_type,
                            first_seen=event.event_timestamp,
                            last_seen=event.event_timestamp,
                        )
                        db.add(entity)
                        entity_cache[key] = entity
                    else:
                        entity.last_seen = event.event_timestamp or entity.last_seen

                    db.add(EntityMention(
                        entity_id=entity.id,
                        evidence_event_id=event.id,
                        raw_value=sanitize_db_val(found.raw_value),
                        entity_type=found.entity_type,
                        confidence=found.confidence,
                        extractor=found.extractor,
                        span_start=found.span_start,
                        span_end=found.span_end,
                    ))

                if (idx + 1) % 500 == 0:
                    await db.flush()

            await db.flush()

            # Materialise the observed Case Graph edges for this evidence file.
            # Every edge carries evidence_refs/event_refs provenance so the graph
            # is traceable back to the exact source rows, and repeat uploads
            # aggregate onto the same edge rather than duplicating it.
            try:
                await db.flush()
                from graph.relationships import materialize_observed_relationships
                rel_summary = await materialize_observed_relationships(
                    db, ev_file.case_id, evidence_file_id=ev_file.id
                )
            except Exception as rel_exc:
                import traceback as _tb
                print(f"[WARN] Relationship materialisation failed for {ev_file.id}: {rel_exc}")
                print(_tb.format_exc())

            # Document Version Timeline (F01): semantic impact analysis
            if ev_file.parent_evidence_id and diff_obj is not None:
                try:
                    await db.flush()
                    from cognitive.version_impact import compute_version_impact
                    impact = await compute_version_impact(
                        db,
                        case_id=ev_file.case_id,
                        parent_file_id=ev_file.parent_evidence_id,
                        variant_file_id=ev_file.id,
                        diff=diff_obj,
                    )
                    v_details = dict(ev_file.variant_details or {})
                    v_details["impact"] = impact
                    ev_file.variant_details = v_details
                except Exception as impact_exc:
                    print(f"[WARN] Version impact computation failed for {ev_file.id}: {impact_exc}")

            ev_file.upload_status = "processed"
            ev_file.processed_at  = datetime.now(timezone.utc)

            # Vector search improves the copilot but must never invalidate
            # successfully preserved evidence, parsed events or graph data.
            try:
                from rag.copilot import get_vector_store
                vs = get_vector_store()
                vs.index_events(str(ev_file.case_id), [
                    {"id": None, "text_content": e.get("text"), "source_doc": path.name,
                     "source_line": e.get("source_line"), "source_page": e.get("source_page"),
                     "event_type": e.get("event_type")}
                    for e in events if e.get("text")
                ])
            except Exception as exc:
                # Keep parsing successful; retrieval can fall back to direct
                # database search when the optional embedding runtime is absent.
                if not ev_file.parse_error:
                    ev_file.parse_error = f"Vector indexing deferred: {exc}"

            await db.commit()
        except Exception as exc:
            logger.error("Background evidence processing failed for %s: %s", evidence_file_id, exc)
            try:
                await db.rollback()
            except Exception:
                pass
            try:
                ev_f_fail = await db.get(EvidenceFile, evidence_file_id)
                if ev_f_fail:
                    ev_f_fail.upload_status = "failed"
                    ev_f_fail.parse_error = str(exc)[:1000]
                    await db.commit()
            except Exception as inner_exc:
                logger.error("Failed to commit failed status for %s: %s", evidence_file_id, inner_exc)
        finally:
            ev_file_cm.__exit__(None, None, None)


# ── Pre-Hash Forensic Preview & Sealing Endpoints ──────────────────────────────

@router.post("/preview")
async def preview_evidence(
    case_id:     str = Form(...),
    source_type: str = Form(default="unknown"),
    file:        UploadFile = File(...),
    db:          AsyncSession = Depends(get_db),
    current:     User = Depends(get_current_user),
):
    """
    Stage an unhashed evidence file for read-only forensic preview.
    Does NOT calculate canonical SHA-256 or insert database records.
    Staged file is strictly isolated in quarantine pending officer review.
    """
    case = await require_case_access(db, current, case_id, write=True)
    case_uuid = case.id

    _cleanup_stale_staging()

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    raw = await _read_upload_limited(file, max_bytes)
    display_name = _safe_display_name(file.filename)
    mime_type, ftype = _detect_mime_and_validate(raw, display_name)

    # Archive safety validations if zip
    if ftype == "zip":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = [member for member in zf.infolist() if not member.is_dir()]
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    raise HTTPException(413, f"Archive contains more than {MAX_ARCHIVE_MEMBERS} files")
                total_size = sum(member.file_size for member in members)
                if total_size > max_bytes:
                    raise HTTPException(413, "Archive uncompressed contents exceed upload limit")
                for member in members:
                    norm_p = pathlib.PurePosixPath(member.filename)
                    if ".." in norm_p.parts or norm_p.is_absolute() or member.filename.startswith(("/", "\\")):
                        raise HTTPException(400, f"Evidence archive rejected: member '{member.filename}' contains unsafe path traversal")
                    if member.flag_bits & 0x1:
                        raise HTTPException(400, "Encrypted archives are not supported")
                    ratio = member.file_size / max(member.compress_size, 1)
                    if ratio > MAX_ARCHIVE_RATIO:
                        raise HTTPException(400, "Archive compression ratio exceeds safety limit")
        except zipfile.BadZipFile:
            raise HTTPException(400, "Invalid ZIP archive")

    preview_id = uuid.uuid4().hex
    case_staging_dir = STAGING_DIR / str(case_uuid)
    case_staging_dir.mkdir(parents=True, exist_ok=True)
    staged_path = case_staging_dir / f"{preview_id}___{display_name}"

    with open(staged_path, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())

    preview_meta = _extract_preview_metadata(raw, display_name, ftype, mime_type)

    return {
        "preview_id": preview_id,
        "case_id": str(case_uuid),
        "source_type": source_type,
        "filename": display_name,
        "mime_type": mime_type,
        "file_size": len(raw),
        "file_size_bytes": len(raw),
        "status": "unhashed_preview",
        "warning": "STATUS: PRE-HASH PREVIEW — Evidence has not yet been fingerprinted. No cryptographic hash has been computed or recorded.",
        "preview": preview_meta,
        "metadata": preview_meta,
    }


@router.post("/preview/cancel")
async def cancel_preview(
    case_id:    str = Form(...),
    preview_id: str = Form(...),
    db:         AsyncSession = Depends(get_db),
    current:    User = Depends(get_current_user),
):
    """
    Cancel an unsealed evidence preview.
    Safely purges staged raw bytes from quarantine.
    """
    case = await require_case_access(db, current, case_id, write=True)
    clean_preview_id = "".join(ch for ch in preview_id if ch.isalnum())
    case_staging_dir = STAGING_DIR / str(case.id)

    removed = False
    if case_staging_dir.exists():
        for staged_file in case_staging_dir.glob(f"{clean_preview_id}*"):
            staged_file.unlink(missing_ok=True)
            removed = True

    return {"status": "discarded", "preview_id": preview_id, "purged": removed}


@router.post("/preview/batch")
async def preview_evidence_batch(
    case_id:     str = Form(...),
    source_type: str = Form(default="unknown"),
    files:       list[UploadFile] = File(...),
    db:          AsyncSession = Depends(get_db),
    current:     User = Depends(get_current_user),
):
    """
    Stage multiple unhashed evidence files for read-only forensic batch preview.
    Does NOT calculate canonical SHA-256 or insert database records.
    Staged files are strictly isolated in quarantine pending officer review.
    """
    case = await require_case_access(db, current, case_id, write=True)
    case_uuid = case.id

    _cleanup_stale_staging()

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    case_staging_dir = STAGING_DIR / str(case_uuid)
    case_staging_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []

    for file in files:
        display_name = _safe_display_name(file.filename)
        try:
            raw = await _read_upload_limited(file, max_bytes)
            mime_type, ftype = _detect_mime_and_validate(raw, display_name)

            if ftype == "zip":
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        members = [member for member in zf.infolist() if not member.is_dir()]
                        if len(members) > MAX_ARCHIVE_MEMBERS:
                            raise HTTPException(413, f"Archive contains more than {MAX_ARCHIVE_MEMBERS} files")
                        total_size = sum(member.file_size for member in members)
                        if total_size > max_bytes:
                            raise HTTPException(413, "Archive uncompressed contents exceed upload limit")
                        for member in members:
                            norm_p = pathlib.PurePosixPath(member.filename)
                            if ".." in norm_p.parts or norm_p.is_absolute() or member.filename.startswith(("/", "\\")):
                                raise HTTPException(400, f"Evidence archive rejected: member '{member.filename}' contains unsafe path traversal")
                            if member.flag_bits & 0x1:
                                raise HTTPException(400, "Encrypted archives are not supported")
                            ratio = member.file_size / max(member.compress_size, 1)
                            if ratio > MAX_ARCHIVE_RATIO:
                                raise HTTPException(400, "Archive compression ratio exceeds safety limit")
                except zipfile.BadZipFile:
                    raise HTTPException(400, "Invalid ZIP archive")

            preview_id = uuid.uuid4().hex
            staged_path = case_staging_dir / f"{preview_id}___{display_name}"

            with open(staged_path, "wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())

            preview_meta = _extract_preview_metadata(raw, display_name, ftype, mime_type)

            items.append({
                "preview_id": preview_id,
                "case_id": str(case_uuid),
                "source_type": source_type,
                "filename": display_name,
                "mime_type": mime_type,
                "file_size": len(raw),
                "file_size_bytes": len(raw),
                "status": "unhashed_preview",
                "warning": "STATUS: PRE-HASH PREVIEW — Evidence has not yet been fingerprinted. No cryptographic hash has been computed or recorded.",
                "preview": preview_meta,
                "metadata": preview_meta,
            })
        except HTTPException as he:
            items.append({
                "preview_id": None,
                "case_id": str(case_uuid),
                "source_type": source_type,
                "filename": display_name,
                "mime_type": "unknown",
                "file_size": 0,
                "file_size_bytes": 0,
                "status": "error",
                "error": str(he.detail),
                "warning": "Pre-flight inspection rejected file",
                "preview": {"file_type": "other", "error": str(he.detail)},
                "metadata": {"file_type": "other", "error": str(he.detail)},
            })
        except Exception as e:
            items.append({
                "preview_id": None,
                "case_id": str(case_uuid),
                "source_type": source_type,
                "filename": display_name,
                "mime_type": "unknown",
                "file_size": 0,
                "file_size_bytes": 0,
                "status": "error",
                "error": str(e),
                "warning": "Pre-flight inspection rejected file",
                "preview": {"file_type": "other", "error": str(e)},
                "metadata": {"file_type": "other", "error": str(e)},
            })

    return {
        "case_id": str(case_uuid),
        "total": len(items),
        "items": items,
    }


@router.post("/preview/cancel/batch")
async def cancel_preview_batch(
    case_id:          str = Form(...),
    preview_ids:      list[str] = Form(default=[]),
    preview_ids_json: str | None = Form(default=None),
    db:               AsyncSession = Depends(get_db),
    current:          User = Depends(get_current_user),
):
    """
    Cancel multiple unsealed evidence previews.
    Safely purges staged raw bytes from quarantine.
    """
    case = await require_case_access(db, current, case_id, write=True)
    all_ids: list[str] = list(preview_ids)
    if preview_ids_json:
        try:
            parsed = json.loads(preview_ids_json)
            if isinstance(parsed, list):
                all_ids.extend(str(x) for x in parsed)
        except Exception:
            pass

    case_staging_dir = STAGING_DIR / str(case.id)
    purged_count = 0
    purged_ids = []

    if case_staging_dir.exists():
        for pid in all_ids:
            clean_pid = "".join(ch for ch in pid if ch.isalnum())
            if not clean_pid:
                continue
            for staged_file in case_staging_dir.glob(f"{clean_pid}*"):
                staged_file.unlink(missing_ok=True)
                purged_count += 1
                purged_ids.append(pid)

    return {
        "status": "discarded",
        "purged_count": purged_count,
        "purged_ids": purged_ids,
    }


@router.post("/confirm")
async def confirm_and_seal_evidence(
    background_tasks: BackgroundTasks,
    case_id:       str = Form(...),
    preview_id:    str = Form(...),
    source_type:   str = Form(default="unknown"),
    original_name: str | None = Form(default=None),
    db:            AsyncSession = Depends(get_db),
    current:       User = Depends(get_current_user),
):
    """
    Confirm and seal staged evidence into Section 63 BSA chain of custody.
    Computes canonical SHA-256 from exact original staged bytes on the server.
    Creates permanent encrypted EvidenceFile record and triggers analysis pipeline.
    """
    case = await require_case_access(db, current, case_id, write=True)
    case_uuid = case.id
    clean_preview_id = "".join(ch for ch in preview_id if ch.isalnum())
    case_staging_dir = STAGING_DIR / str(case_uuid)

    cached = _get_sealed_preview(clean_preview_id)
    if cached:
        return cached

    staged_matches = list(case_staging_dir.glob(f"{clean_preview_id}*")) if case_staging_dir.exists() else []
    if not staged_matches:
        raise HTTPException(404, "Staged preview file not found or expired")

    staged_file = staged_matches[0]
    raw = staged_file.read_bytes()

    # Determine original filename from staged file naming convention
    if "___" in staged_file.name:
        inferred_name = staged_file.name.split("___", 1)[1]
    else:
        inferred_name = original_name or f"evidence_{clean_preview_id[:8]}{staged_file.suffix}"
    final_display_name = _safe_display_name(inferred_name)
    ftype = _detect_file_type(final_display_name)

    created: list[dict] = []
    duplicates: list[dict] = []
    created_paths: list[pathlib.Path] = []
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    try:
        if ftype == "zip":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = [member for member in zf.infolist() if not member.is_dir()]
                for member in members:
                    norm_p = pathlib.PurePosixPath(member.filename)
                    if ".." in norm_p.parts or norm_p.is_absolute() or member.filename.startswith(("/", "\\")):
                        raise HTTPException(400, f"Evidence archive rejected: member '{member.filename}' contains unsafe path traversal")

                parent_zip_ev, parent_zip_path, parent_is_dup = await _register_evidence(
                    db,
                    case_id=case_uuid,
                    current=current,
                    original_name=final_display_name,
                    source_type="archive_container",
                    raw=raw,
                )
                parent_record = {
                    "id": str(parent_zip_ev.id),
                    "filename": parent_zip_ev.original_name,
                    "sha256_hash": parent_zip_ev.sha256_hash,
                }
                if parent_is_dup:
                    duplicates.append(parent_record)
                else:
                    created.append(parent_record)
                    created_paths.append(parent_zip_path)
                    parent_zip_ev.upload_status = "processed"

                for member in members:
                    member_bytes = zf.read(member)
                    member_name = pathlib.PurePath(member.filename.replace("\\", "/")).name or "member"
                    ev_f, member_path, is_dup = await _register_evidence(
                        db,
                        case_id=case_uuid,
                        current=current,
                        original_name=member_name,
                        source_type=source_type,
                        raw=member_bytes,
                    )
                    ev_f.parent_evidence_id = parent_zip_ev.id
                    item = {"id": str(ev_f.id), "filename": ev_f.original_name, "sha256_hash": ev_f.sha256_hash, "parent_evidence_id": str(parent_zip_ev.id)}
                    if is_dup:
                        duplicates.append(item)
                        await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                            "evidence_id": str(ev_f.id),
                            "submitted_name": member_name,
                            "sha256": ev_f.sha256_hash,
                        })
                    else:
                        created.append(item)
                        created_paths.append(member_path)
                        await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                            "evidence_id": str(ev_f.id),
                            "original_name": ev_f.original_name,
                            "sha256": ev_f.sha256_hash,
                            "size_bytes": ev_f.file_size_bytes,
                        })
                        background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(member_path))
        else:
            ev_f, destination, is_dup = await _register_evidence(
                db,
                case_id=case_uuid,
                current=current,
                original_name=final_display_name,
                source_type=source_type,
                raw=raw,
            )
            item = {"id": str(ev_f.id), "filename": ev_f.original_name, "sha256_hash": ev_f.sha256_hash}
            if is_dup:
                duplicates.append(item)
                await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                    "evidence_id": str(ev_f.id),
                    "submitted_name": final_display_name,
                    "sha256": ev_f.sha256_hash,
                })
            else:
                created.append(item)
                created_paths.append(destination)
                await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                    "evidence_id": str(ev_f.id),
                    "original_name": ev_f.original_name,
                    "sha256": ev_f.sha256_hash,
                    "size_bytes": ev_f.file_size_bytes,
                })
                background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(destination))

        await db.commit()
        staged_file.unlink(missing_ok=True)
    except Exception:
        await db.rollback()
        for created_path in created_paths:
            created_path.unlink(missing_ok=True)
        raise

    if settings.enable_cognitive_orchestration and created:
        background_tasks.add_task(_run_orchestration_after_upload, str(case_uuid))

    primary = created[0] if created else (duplicates[0] if duplicates else None)
    res = {
        "status": "sealed",
        "message": "Evidence successfully sealed into chain of custody",
        "id": primary["id"] if primary else None,
        "filename": primary["filename"] if primary else final_display_name,
        "sha256_hash": primary["sha256_hash"] if primary else None,
        "uploaded_count": len(created),
        "duplicate_count": len(duplicates),
        "files": created,
        "duplicates": duplicates,
    }
    _cache_sealed_preview(clean_preview_id, res)
    return res


@router.post("/confirm/batch")
async def confirm_and_seal_evidence_batch(
    background_tasks: BackgroundTasks,
    case_id:          str = Form(...),
    preview_ids:      list[str] = Form(default=[]),
    items:            str | None = Form(default=None),
    source_type:      str = Form(default="unknown"),
    db:               AsyncSession = Depends(get_db),
    current:          User = Depends(get_current_user),
):
    """
    Confirm and seal a batch of staged evidence files into Section 63 BSA chain of custody.
    Computes canonical SHA-256 from exact original staged bytes on the server.
    Independent processing per file: partial failures do not roll back valid records.
    Provides deterministic server-side idempotency against double-clicks and retries.
    """
    case = await require_case_access(db, current, case_id, write=True)
    case_uuid = case.id
    case_staging_dir = STAGING_DIR / str(case_uuid)

    batch_requests: list[dict[str, Any]] = []
    if items:
        try:
            parsed_items = json.loads(items)
            if isinstance(parsed_items, list):
                batch_requests = parsed_items
        except Exception:
            pass

    if not batch_requests and preview_ids:
        batch_requests = [{"preview_id": pid, "source_type": source_type} for pid in preview_ids]

    if not batch_requests:
        raise HTTPException(400, "No evidence items supplied for batch confirmation")

    sealed: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for req in batch_requests:
        pid = req.get("preview_id")
        item_source_type = req.get("source_type") or source_type or "unknown"
        original_name = req.get("original_name")

        if not pid:
            failed.append({"preview_id": None, "filename": original_name or "unknown", "error": "Missing preview ID"})
            continue

        clean_preview_id = "".join(ch for ch in str(pid) if ch.isalnum())
        cached = _get_sealed_preview(clean_preview_id)
        if cached:
            if isinstance(cached, list):
                sealed.extend(cached)
            else:
                sealed.append(cached)
            continue

        staged_matches = list(case_staging_dir.glob(f"{clean_preview_id}*")) if case_staging_dir.exists() else []
        if not staged_matches:
            failed.append({"preview_id": pid, "filename": original_name or f"evidence_{clean_preview_id[:8]}", "error": "Staged preview file not found or expired"})
            continue

        staged_file = staged_matches[0]
        file_created_paths: list[pathlib.Path] = []
        try:
            raw = staged_file.read_bytes()
            if "___" in staged_file.name:
                inferred_name = staged_file.name.split("___", 1)[1]
            else:
                inferred_name = original_name or f"evidence_{clean_preview_id[:8]}{staged_file.suffix}"
            final_display_name = _safe_display_name(inferred_name)
            ftype = _detect_file_type(final_display_name)

            item_sealed: list[dict] = []
            item_duplicates: list[dict] = []

            if ftype == "zip":
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    members = [member for member in zf.infolist() if not member.is_dir()]
                    for member in members:
                        norm_p = pathlib.PurePosixPath(member.filename)
                        if ".." in norm_p.parts or norm_p.is_absolute() or member.filename.startswith(("/", "\\")):
                            raise HTTPException(400, f"Evidence archive rejected: member '{member.filename}' contains unsafe path traversal")

                    parent_zip_ev, parent_zip_path, parent_is_dup = await _register_evidence(
                        db,
                        case_id=case_uuid,
                        current=current,
                        original_name=final_display_name,
                        source_type="archive_container",
                        raw=raw,
                    )
                    parent_record = {
                        "id": str(parent_zip_ev.id),
                        "filename": parent_zip_ev.original_name,
                        "sha256_hash": parent_zip_ev.sha256_hash,
                        "file_size_bytes": parent_zip_ev.file_size_bytes,
                        "preview_id": pid,
                    }
                    if parent_is_dup:
                        item_duplicates.append(parent_record)
                    else:
                        item_sealed.append(parent_record)
                        file_created_paths.append(parent_zip_path)
                        parent_zip_ev.upload_status = "processed"

                    for member in members:
                        member_bytes = zf.read(member)
                        member_name = pathlib.PurePath(member.filename.replace("\\", "/")).name or "member"
                        ev_f, member_path, is_dup = await _register_evidence(
                            db,
                            case_id=case_uuid,
                            current=current,
                            original_name=member_name,
                            source_type=item_source_type,
                            raw=member_bytes,
                        )
                        ev_f.parent_evidence_id = parent_zip_ev.id
                        record_item = {
                            "id": str(ev_f.id),
                            "filename": ev_f.original_name,
                            "sha256_hash": ev_f.sha256_hash,
                            "file_size_bytes": ev_f.file_size_bytes,
                            "preview_id": pid,
                            "parent_evidence_id": str(parent_zip_ev.id),
                        }
                        if is_dup:
                            item_duplicates.append(record_item)
                            await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                                "evidence_id": str(ev_f.id),
                                "submitted_name": member_name,
                                "sha256": ev_f.sha256_hash,
                            })
                        else:
                            item_sealed.append(record_item)
                            file_created_paths.append(member_path)
                            await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                                "evidence_id": str(ev_f.id),
                                "original_name": ev_f.original_name,
                                "sha256": ev_f.sha256_hash,
                                "size_bytes": ev_f.file_size_bytes,
                            })
                            background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(member_path))
            else:
                ev_f, destination, is_dup = await _register_evidence(
                    db,
                    case_id=case_uuid,
                    current=current,
                    original_name=final_display_name,
                    source_type=item_source_type,
                    raw=raw,
                )
                record_item = {
                    "id": str(ev_f.id),
                    "filename": ev_f.original_name,
                    "sha256_hash": ev_f.sha256_hash,
                    "file_size_bytes": ev_f.file_size_bytes,
                    "preview_id": pid,
                }
                if is_dup:
                    item_duplicates.append(record_item)
                    await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                        "evidence_id": str(ev_f.id),
                        "submitted_name": final_display_name,
                        "sha256": ev_f.sha256_hash,
                    })
                else:
                    item_sealed.append(record_item)
                    file_created_paths.append(destination)
                    await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                        "evidence_id": str(ev_f.id),
                        "original_name": ev_f.original_name,
                        "sha256": ev_f.sha256_hash,
                        "size_bytes": ev_f.file_size_bytes,
                    })
                    background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(destination))

            # Commit individual file transaction so partial failures do not roll back valid records
            await db.commit()
            staged_file.unlink(missing_ok=True)
            if item_sealed:
                _cache_sealed_preview(clean_preview_id, item_sealed[0] if len(item_sealed) == 1 else item_sealed)
            elif item_duplicates:
                _cache_sealed_preview(clean_preview_id, item_duplicates[0])
            sealed.extend(item_sealed)
            duplicates.extend(item_duplicates)

        except Exception as e:
            await db.rollback()
            for cp in file_created_paths:
                cp.unlink(missing_ok=True)
            failed.append({
                "preview_id": pid,
                "filename": final_display_name if 'final_display_name' in locals() else (original_name or staged_file.name),
                "error": str(e),
            })

    if settings.enable_cognitive_orchestration and sealed:
        background_tasks.add_task(_run_orchestration_after_upload, str(case_uuid))

    return {
        "status": "batch_completed",
        "message": f"{len(sealed)} evidence file(s) sealed into Section 63 BSA chain of custody",
        "sealed_count": len(sealed),
        "duplicate_count": len(duplicates),
        "failed_count": len(failed),
        "sealed": sealed,
        "duplicates": duplicates,
        "failed": failed,
    }


# ── Direct Upload Endpoint (Backward-Compatible) ──────────────────────────────

@router.post("/upload")
async def upload_evidence(
    background_tasks: BackgroundTasks,
    case_id:     str = Form(...),
    source_type: str = Form(default="unknown"),
    files:       list[UploadFile] = File(...),
    db:          AsyncSession = Depends(get_db),
    current:     User = Depends(get_current_user),
):
    """
    Upload one or more evidence files for a case.
    Accepts individual files or a zip archive (auto-extracted).
    SHA-256 is computed before any processing.
    """
    case = await require_case_access(db, current, case_id, write=True)
    case_uuid = case.id

    created: list[dict] = []
    duplicates: list[dict] = []
    created_paths: list[pathlib.Path] = []
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    for upload in files:
        raw = await _read_upload_limited(upload, max_bytes)
        original_name = _safe_display_name(upload.filename)
        ftype = _detect_file_type(original_name)

        # Auto-extract zip
        if ftype == "zip":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    members = [member for member in zf.infolist() if not member.is_dir()]
                    if len(members) > MAX_ARCHIVE_MEMBERS:
                        raise HTTPException(413, f"Archive contains more than {MAX_ARCHIVE_MEMBERS} files")
                    total_size = sum(member.file_size for member in members)
                    if total_size > max_bytes:
                        raise HTTPException(413, "Archive uncompressed contents exceed the upload limit")
                    for member in members:
                        if member.flag_bits & 0x1:
                            raise HTTPException(400, "Encrypted archives are not supported")
                        ratio = member.file_size / max(member.compress_size, 1)
                        if ratio > MAX_ARCHIVE_RATIO:
                            raise HTTPException(400, "Archive compression ratio exceeds the safety limit")
                        member_bytes = zf.read(member)
                        ev_f, member_path, is_duplicate = await _register_evidence(
                            db,
                            case_id=case_uuid,
                            current=current,
                            original_name=member.filename,
                            source_type=source_type,
                            raw=member_bytes,
                        )
                        item = {"id": str(ev_f.id), "filename": ev_f.original_name, "sha256_hash": ev_f.sha256_hash}
                        if is_duplicate:
                            duplicates.append(item)
                            await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                                "evidence_id": str(ev_f.id),
                                "submitted_name": _safe_display_name(member.filename),
                                "sha256": ev_f.sha256_hash,
                            })
                        else:
                            created.append(item)
                            created_paths.append(member_path)
                            await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                                "evidence_id": str(ev_f.id),
                                "original_name": ev_f.original_name,
                                "sha256": ev_f.sha256_hash,
                                "size_bytes": ev_f.file_size_bytes,
                            })
                            background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(member_path))
                continue
            except zipfile.BadZipFile:
                raise HTTPException(400, "Invalid ZIP archive")

        ev_f, destination, is_duplicate = await _register_evidence(
            db,
            case_id=case_uuid,
            current=current,
            original_name=original_name,
            source_type=source_type,
            raw=raw,
        )
        item = {"id": str(ev_f.id), "filename": ev_f.original_name, "sha256_hash": ev_f.sha256_hash}
        if is_duplicate:
            duplicates.append(item)
            await _audit(db, current, "EVIDENCE_DUPLICATE_DETECTED", str(case_uuid), {
                "evidence_id": str(ev_f.id),
                "submitted_name": original_name,
                "sha256": ev_f.sha256_hash,
            })
        else:
            created.append(item)
            created_paths.append(destination)
            await _audit(db, current, "EVIDENCE_UPLOADED", str(case_uuid), {
                "evidence_id": str(ev_f.id),
                "original_name": ev_f.original_name,
                "sha256": ev_f.sha256_hash,
                "size_bytes": ev_f.file_size_bytes,
            })
            background_tasks.add_task(_process_evidence_file, str(ev_f.id), str(destination))

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        for created_path in created_paths:
            created_path.unlink(missing_ok=True)
        raise

    # Once every parsing task for this batch has run, trigger one cognitive
    # analysis pass so the investigator immediately sees findings for the new
    # evidence (evidence → understand → connect → reason loop).
    if settings.enable_cognitive_orchestration and created:
        background_tasks.add_task(_run_orchestration_after_upload, str(case_uuid))

    return {
        "uploaded": len(created),
        "duplicate_count": len(duplicates),
        "files": created,
        "duplicates": duplicates,
    }


async def _run_orchestration_after_upload(case_id: str):
    """Best-effort post-upload cognitive run; never affects evidence ingestion."""
    try:
        from orchestration.investigation_orchestrator import run_case_orchestration
        case_uuid = uuid.UUID(str(case_id))
        async with AsyncSessionLocal() as db:
            await run_case_orchestration(db, case_uuid, trigger="upload")
            await db.commit()
    except Exception as exc:
        print(f"[WARN] Post-upload cognitive orchestration failed for case {case_id}: {exc}")


@router.get("/{case_id}")
async def list_evidence(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    case = await require_case_access(db, current, case_id)
    files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
        .order_by(EvidenceFile.uploaded_at.desc())
    )).scalars().all()

    return {
        "case_id": case_id,
        "count":   len(files),
        "files":   [
            {
                "id":                 str(f.id),
                "filename":           f.original_name,
                "file_type":          f.file_type,
                "source_type":        f.source_type,
                "file_size_bytes":    f.file_size_bytes,
                "sha256_hash":        f.sha256_hash,
                "upload_status":      f.upload_status,
                "uploaded_at":        f.uploaded_at.isoformat() if f.uploaded_at else None,
                "processed_at":       f.processed_at.isoformat() if f.processed_at else None,
                "parse_error":        f.parse_error,
                "parent_evidence_id": str(f.parent_evidence_id) if f.parent_evidence_id else None,
                "version_number":     f.version_number or 1,
                "version_status":     f.version_status or "original",
                "variant_details":    f.variant_details or {},
                "is_variant":         bool(f.version_status == "variant" or (f.parse_error and f.parse_error.startswith("[VARIANT]"))),
                "variant_note":       f.parse_error if (f.parse_error and f.parse_error.startswith("[VARIANT]")) else None,
                "fingerprint":        f.fingerprint_hash or f"MH-{f.sha256_hash[:8].upper()}",
            }
            for f in files
        ],
    }


@router.get("/{case_id}/version-timeline")
async def get_version_timeline(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Document Version Timeline (F01).
    Groups evidence files into version lineages with structural diffs and semantic impact.
    """
    case = await require_case_access(db, current, case_id)
    files = (await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id)
        .order_by(EvidenceFile.uploaded_at.asc())
    )).scalars().all()

    def _serialize_v(f: EvidenceFile) -> dict[str, Any]:
        return {
            "id":                 str(f.id),
            "filename":           f.original_name,
            "file_type":          f.file_type,
            "source_type":        f.source_type,
            "file_size_bytes":    f.file_size_bytes,
            "sha256_hash":        f.sha256_hash,
            "version_number":     f.version_number or 1,
            "version_status":     f.version_status or "original",
            "parent_evidence_id": str(f.parent_evidence_id) if f.parent_evidence_id else None,
            "uploaded_at":        f.uploaded_at.isoformat() if f.uploaded_at else None,
            "processed_at":       f.processed_at.isoformat() if f.processed_at else None,
            "fingerprint_hash":   f.fingerprint_hash or f"MH-{f.sha256_hash[:8].upper()}",
            "variant_details":    f.variant_details or {},
        }

    lineages: list[dict[str, Any]] = []
    roots = [f for f in files if not f.parent_evidence_id]

    for root in roots:
        chain = [_serialize_v(root)]
        direct_variants = [f for f in files if str(f.parent_evidence_id) == str(root.id)]
        for v in direct_variants:
            chain.append(_serialize_v(v))

        lineages.append({
            "root_id":        str(root.id),
            "root_filename":  root.original_name,
            "source_type":    root.source_type,
            "has_variants":   len(chain) > 1,
            "total_versions": len(chain),
            "versions":       chain,
        })

    # Capture any variant whose parent wasn't found in roots (orphaned variant guard)
    handled_ids = {v["id"] for lin in lineages for v in lin["versions"]}
    unhandled = [f for f in files if str(f.id) not in handled_ids]
    for u in unhandled:
        lineages.append({
            "root_id":        str(u.id),
            "root_filename":  u.original_name,
            "source_type":    u.source_type,
            "has_variants":   False,
            "total_versions": 1,
            "versions":       [_serialize_v(u)],
        })

    variant_count = sum(1 for f in files if f.parent_evidence_id or f.version_status == "variant")

    return {
        "case_id":       case_id,
        "total_files":   len(files),
        "variant_count": variant_count,
        "lineage_count": len(lineages),
        "lineages":      lineages,
    }


@router.get("/{case_id}/files/{evidence_id}/download")
async def download_evidence(
    case_id: str,
    evidence_id: str,
    request: Request,
    reason: Optional[str] = Query(None, description="Operational justification for accessing original evidence"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Download seized evidence file.
    Enforces case access control, strict evidence access justification, device trust,
    decrypts on-the-fly, verifies Section 63 BSA SHA-256 integrity,
    and logs the access event in the tamper-evident audit ledger.
    """
    from investigation.policies import user_has_capability, CAP_EVIDENCE_READ
    if not user_has_capability(current.role, CAP_EVIDENCE_READ):
        raise HTTPException(status_code=403, detail="Insufficient permission to access evidence")

    case = await require_case_access(db, current, case_id)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid evidence UUID")

    ev_file = await db.get(EvidenceFile, ev_uuid)
    if not ev_file or ev_file.case_id != case.id:
        raise HTTPException(404, "Evidence file not found")

    dev_id = request.headers.get("X-Device-ID") or getattr(request.state, "device_id", None) or "device-primary"
    session_id = getattr(request.state, "session_id", None)

    # Stricter than case access: Operational reason check
    reason_str = (reason or request.headers.get("X-Access-Reason") or "").strip()
    from utils.audit import append_audit
    if not reason_str or len(reason_str) < 5:
        await append_audit(
            db,
            action="EVIDENCE_ACCESS_DENIED",
            resource_type="evidence_file",
            resource_id=str(ev_file.id),
            details={
                "actor": str(current.username),
                "case_id": str(case.id),
                "evidence_id": str(ev_file.id),
                "device_id": dev_id,
                "session_id": session_id,
                "reason": "Missing or insufficient operational justification",
                "operation": "EVIDENCE_DOWNLOAD",
                "result": "DENIED",
            },
            user_id=str(current.id),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evidence access requires explicit operational justification and verified device context under Section 63 BSA",
        )

    plaintext = read_decrypted_bytes(ev_file)
    if hashlib.sha256(plaintext).hexdigest() != ev_file.sha256_hash:
        raise HTTPException(500, "Integrity check failed: Decrypted evidence hash mismatch")

    await append_audit(
        db,
        action="EVIDENCE_ACCESS_GRANTED",
        resource_type="evidence_file",
        resource_id=str(ev_file.id),
        details={
            "actor": str(current.username),
            "case_id": str(case.id),
            "evidence_id": str(ev_file.id),
            "case_number": case.case_number,
            "filename": ev_file.original_name,
            "sha256_hash": ev_file.sha256_hash,
            "device_id": dev_id,
            "session_id": session_id,
            "reason": reason_str,
            "operation": "EVIDENCE_DOWNLOAD",
            "result": "AUTHORIZED",
        },
        user_id=str(current.id),
    )
    await db.commit()

    from fastapi.responses import Response
    return Response(
        content=plaintext,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{ev_file.original_name}"',
            "X-Evidence-SHA256": ev_file.sha256_hash,
            "X-BSA-Section": "63",
        },
    )


@router.delete("/{case_id}/files/{evidence_id}")
async def delete_evidence(
    case_id: str,
    evidence_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Delete evidence endpoint with immutability guarantees.
    Original seized evidence cannot be deleted under Section 63 BSA.
    """
    case = await require_case_access(db, current, case_id, write=True)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid evidence UUID")

    ev_file = await db.get(EvidenceFile, ev_uuid)
    if not ev_file or ev_file.case_id != case.id:
        raise HTTPException(404, "Evidence file not found")

    from utils.audit import append_audit
    dev_id = request.headers.get("X-Device-ID") or getattr(request.state, "device_id", None) or "device-primary"

    # Immutability negative guarantee: Original evidence can never be deleted
    if ev_file.original_immutable or ev_file.version_status == "original":
        await append_audit(
            db,
            action="EVIDENCE_MUTATION_BLOCKED",
            resource_type="evidence_file",
            resource_id=str(ev_file.id),
            details={
                "actor": str(current.username),
                "case_id": str(case.id),
                "operation": "DELETE_ORIGINAL",
                "result": "BLOCKED",
                "device_id": dev_id,
                "reason": "Original evidence is immutable under Section 63 BSA",
            },
            user_id=str(current.id),
        )
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail="Original seized evidence is immutable under Section 63 BSA and cannot be deleted. Allowed operations create derivatives or analysis artifacts instead.",
        )

    # If it is a derivative/variant, allow deletion
    await db.delete(ev_file)
    await append_audit(
        db,
        action="EVIDENCE_VARIANT_DELETED",
        resource_type="evidence_file",
        resource_id=str(ev_file.id),
        details={"case_id": str(case.id), "filename": ev_file.original_name, "device_id": dev_id},
        user_id=str(current.id),
    )
    await db.commit()
    return {"status": "ok", "message": "Evidence variant deleted."}


@router.patch("/{case_id}/files/{evidence_id}")
@router.put("/{case_id}/files/{evidence_id}")
async def update_evidence_metadata(
    case_id: str,
    evidence_id: str,
    body: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Update evidence metadata.
    Protects original evidence from byte replacement, hash change, or acquisition tampering.
    """
    case = await require_case_access(db, current, case_id, write=True)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid evidence UUID")

    ev_file = await db.get(EvidenceFile, ev_uuid)
    if not ev_file or ev_file.case_id != case.id:
        raise HTTPException(404, "Evidence file not found")

    # Protected forensic columns that can never be modified on original evidence
    immutable_fields = {"sha256_hash", "filename", "original_name", "storage_path", "file_size_bytes", "source_device_hash", "acquisition_tool", "acquisition_timestamp"}
    attempted_immutable = immutable_fields.intersection(body.keys())
    if attempted_immutable and (ev_file.original_immutable or ev_file.version_status == "original"):
        raise HTTPException(
            status_code=403,
            detail=f"Original evidence is immutable. Cannot modify protected forensic fields: {', '.join(sorted(attempted_immutable))}. Create an analysis variant instead.",
        )

    # Allowed mutable fields (e.g. officer_notes, retention_class)
    if "officer_notes" in body:
        ev_file.officer_notes = str(body["officer_notes"])
    if "retention_class" in body:
        ev_file.retention_class = str(body["retention_class"])

    from utils.audit import append_audit
    await append_audit(
        db,
        action="EVIDENCE_METADATA_UPDATED",
        resource_type="evidence_file",
        resource_id=str(ev_file.id),
        details={"case_id": str(case.id), "updated_fields": list(body.keys())},
        user_id=str(current.id),
    )
    await db.commit()
    return {"status": "ok", "evidence_id": str(ev_file.id), "message": "Metadata updated."}


@router.post("/{case_id}/files/{evidence_id}/derivatives")
async def create_evidence_derivative(
    case_id: str,
    evidence_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Create a modifiable/recomputable analysis derivative from an immutable parent.
    """
    case = await require_case_access(db, current, case_id, write=True)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid evidence UUID")

    parent = await db.get(EvidenceFile, ev_uuid)
    if not parent or parent.case_id != case.id:
        raise HTTPException(404, "Parent evidence not found")

    derivative_name = body.get("name") or f"{parent.original_name}_derivative"
    deriv_hash = hashlib.sha256(f"derivative:{parent.sha256_hash}:{uuid.uuid4().hex}".encode()).hexdigest()
    deriv_file = EvidenceFile(
        case_id=case.id,
        parent_evidence_id=parent.id,
        filename=derivative_name,
        original_name=derivative_name,
        file_type=parent.file_type,
        source_type="ANALYSIS_DERIVATIVE",
        sha256_hash=deriv_hash,
        storage_path=f"derivatives/{case.id}/{deriv_hash}.bin",
        upload_status="processed",
        integrity_status="verified",
        original_immutable=False,
        version_status="variant",
        version_number=parent.version_number + 1,
        variant_details=body.get("details", {}),
        uploaded_by=current.id,
    )
    db.add(deriv_file)
    from utils.audit import append_audit
    await append_audit(
        db,
        action="EVIDENCE_DERIVATIVE_CREATED",
        resource_type="evidence_file",
        resource_id=str(deriv_file.id),
        details={"parent_id": str(parent.id), "derivative_name": derivative_name},
        user_id=str(current.id),
    )
    await db.commit()
    await db.refresh(deriv_file)
    return {
        "status": "ok",
        "derivative_id": str(deriv_file.id),
        "parent_evidence_id": str(parent.id),
        "version_status": deriv_file.version_status,
    }



@router.post("/{case_id}/{evidence_id}/retry")
@router.post("/{case_id}/files/{evidence_id}/retry")
async def retry_evidence_processing(
    case_id: str,
    evidence_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Retry parsing and background processing on an already-sealed EvidenceFile.
    Atomically clears previous partial events and mentions for this evidence file to prevent duplicates.
    Preserves the original SHA-256 hash and Section 63 BSA cryptographic chain of custody.
    """
    case = await require_case_access(db, current, case_id, write=True)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid evidence UUID")

    ev_file = await db.get(EvidenceFile, ev_uuid)
    if not ev_file or ev_file.case_id != case.id:
        raise HTTPException(404, "Evidence file not found in this case")

    # Clean up prior partial events and mentions from this evidence file
    # to maintain strict 0-duplicate invariant
    existing_event_ids = (await db.execute(
        select(EvidenceEvent.id).where(EvidenceEvent.evidence_file_id == ev_uuid)
    )).scalars().all()
    if existing_event_ids:
        await db.execute(
            delete(EntityMention).where(EntityMention.evidence_event_id.in_(existing_event_ids))
        )
        await db.execute(
            delete(EvidenceEvent).where(EvidenceEvent.evidence_file_id == ev_uuid)
        )

    ev_file.upload_status = "pending"
    ev_file.parse_error = None
    await db.commit()

    background_tasks.add_task(_process_evidence_file, str(ev_file.id), str(ev_file.storage_path))
    await _audit(db, current, "EVIDENCE_PROCESSING_RETRIED", str(case.id), {
        "evidence_id": str(ev_file.id),
        "filename": ev_file.original_name,
    })

    return {
        "status": "processing",
        "message": f"Processing restarted for {ev_file.original_name}",
        "evidence_id": str(ev_file.id),
    }


