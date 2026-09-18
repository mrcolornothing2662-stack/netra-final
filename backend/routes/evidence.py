from __future__ import annotations
"""
CyberDrishti AI — Evidence Upload & Processing Routes (Phase 7)
POST /upload — multipart zip, routes to parsers, SHA-256 hash at ingestion.
"""
import hashlib
import io
import os
import pathlib
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Any

from config import settings
from db.models import Entity, EntityMention, EvidenceEvent, EvidenceFile, User
from db.session import AsyncSessionLocal, get_db
from nlp.entity_validation import validate_entity_candidate
from routes.auth import get_current_user
from routes.case_access import require_case_access
from routes.cases import _audit

router = APIRouter()

UPLOAD_DIR = pathlib.Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_ARCHIVE_MEMBERS = 100
MAX_ARCHIVE_RATIO = 100


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
    temp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=case_upload_dir, delete=False) as staged:
            staged.write(raw)
            staged.flush()
            os.fsync(staged.fileno())
            temp_path = pathlib.Path(staged.name)
        if _sha256_file(temp_path) != sha256:
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

            path = pathlib.Path(file_path)
            resolved_path = path.resolve()
            if UPLOAD_DIR.resolve() not in resolved_path.parents:
                raise ValueError("Evidence storage path is outside the protected upload directory")
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
                    prev_p = pathlib.Path(prev_f.storage_path)
                    if prev_p.exists():
                        try:
                            prev_raw = prev_p.read_bytes()
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

        except Exception as exc:
            ev_file.upload_status = "failed"
            ev_file.parse_error   = str(exc)

        await db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

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
