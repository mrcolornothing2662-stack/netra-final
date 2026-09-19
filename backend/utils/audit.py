from __future__ import annotations
"""
CyberDrishti AI — Shared Audit Utility
Provides a single append_audit() function used by all routes
instead of duplicating the audit chain logic in each module.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


async def append_audit(
    db: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: str,
    details: Dict[str, Any],
    user_id: Optional[str] = None,
) -> AuditLog:
    """
    Append a tamper-evident audit log entry.

    Computes SHA-256(prev_entry_hash + JSON(this_entry)) and stores
    as the new chain link. The genesis entry must already exist.

    Args:
        db:            Active async DB session.
        action:        Uppercase action code e.g. EVIDENCE_UPLOADED.
        resource_type: DB entity type e.g. "evidence_file", "case".
        resource_id:   UUID string of the affected resource.
        details:       Extra context dict (stored as JSONB).
        user_id:       UUID string of the acting user, or None for system events.

    Returns:
        The created AuditLog instance (not yet committed — caller commits).
    """
    # Serialize chain appends. Without this, concurrent transactions can commit
    # hash-links out of id order and the recomputed chain verify diverges (the
    # failure mode behind historical entry #754). PostgreSQL only; released at
    # transaction end. SQLite has a single writer and needs no lock.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('cyberdrishti:audit-chain'))"))

    # Fetch the most recent hash in the chain
    prev = await db.execute(
        select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1).with_for_update()
    )
    prev_hash = prev.scalar_one_or_none() or "0" * 64

    event_timestamp = datetime.now(timezone.utc)

    user_id_str = str(user_id) if user_id is not None else None
    resource_id_str = str(resource_id) if resource_id is not None else None

    # Canonical JSON for hashing — must match verification logic in audit.py
    entry_data = json.dumps(
        {
            "action":      action,
            "user_id":     user_id_str,
            "resource_id": resource_id_str,
            "details":     details,
            "timestamp":   event_timestamp.isoformat(),
        },
        sort_keys=True,
    )

    entry_hash = hashlib.sha256((prev_hash + entry_data).encode()).hexdigest()

    # Bind the FK column as the PK's Python type. The cross-dialect UUID column
    # (PG_UUID on Postgres, Uuid(as_uuid=True) on SQLite) binds via value.hex on
    # SQLite and raises "'str' object has no attribute 'hex'" when handed a raw
    # string. Callers pass str(current.id), which is exactly what the hash
    # payload above must contain (the verifier in routes/audit.py recomputes with
    # str(row.user_id)), so we keep the string in the hash but coerce a typed
    # value for the column. Matches routes/cases._audit, which hashes str(user.id)
    # yet binds user_id=user.id.
    user_id_col: Optional[uuid.UUID] = None
    if user_id is not None:
        try:
            user_id_col = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            user_id_col = None

    log = AuditLog(
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        user_id=user_id_col,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details_json=details,
        event_timestamp=event_timestamp,
    )
    db.add(log)
    return log


def verify_chain(logs: list[AuditLog]) -> tuple[bool, str]:
    """
    Verify the integrity of a list of AuditLog records.
    Returns (True, "OK") if all hashes match, or (False, reason) if tampered.
    """
    if not logs:
        return True, "Chain is empty"

    def _canonical_ts(dt: datetime | None) -> str:
        if dt is None:
            return ""
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        return dt.isoformat()

    prev_hash = "0" * 64
    for idx, entry in enumerate(logs):
        if entry.action == "GENESIS":
            prev_hash = entry.entry_hash
            continue
        if entry.prev_hash != prev_hash and idx != 0:
            return False, f"Broken link at sequence #{idx}: prev_hash mismatch ({entry.prev_hash} != {prev_hash})"

        # Re-compute hash over the exact canonical payload that append_audit
        # signed, and actually compare it. (Previously the computed value was
        # discarded, so tampering was never detected.)
        entry_data = json.dumps(
            {
                "action":      entry.action,
                "user_id":     str(entry.user_id) if entry.user_id else None,
                "resource_id": str(entry.resource_id) if entry.resource_id else None,
                "details":     entry.details_json or {},
                "timestamp":   _canonical_ts(entry.event_timestamp),
            },
            sort_keys=True,
        )
        expected_hash = hashlib.sha256((prev_hash + entry_data).encode()).hexdigest()
        if expected_hash != entry.entry_hash:
            return False, f"Hash mismatch at entry #{entry.id}"

        prev_hash = entry.entry_hash

    return True, f"Verified {len(logs)} audit entries successfully"

