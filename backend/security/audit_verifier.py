from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Cryptographic Audit Ledger Verifier
Verifies the tamper-evident SHA-256 hash chain from genesis anchor.
Detects:
- Broken prev_hash links between consecutive entries (BROKEN HASH CHAIN)
- Altered payload details or state hashes
- Altered timestamps or actor IDs
- Missing or injected entries
Strictly read-only; never mutates audit records.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


def _canonical_timestamp(dt: datetime | None) -> str:
    """Normalize datetime to UTC ISO-8601 string matching append_audit format."""
    if dt is None:
        return ""
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.isoformat()


def serialize_audit_payload(
    action: str,
    user_id: Optional[str],
    resource_id: Optional[str],
    details: dict[str, Any],
    timestamp: str,
) -> str:
    """Canonical deterministic JSON representation of an audit entry for hashing."""
    return json.dumps(
        {
            "action": action,
            "user_id": user_id,
            "resource_id": resource_id,
            "details": details or {},
            "timestamp": timestamp,
        },
        sort_keys=True,
    )


class AuditVerifier:
    """High-assurance cryptographic verification service for NETRA audit ledgers."""

    @staticmethod
    def verify_records(rows: list[AuditLog]) -> dict[str, Any]:
        """
        Verify an in-memory or queried sequence of AuditLog records.
        Returns a rich status dictionary. If tampering is detected, status is
        'BROKEN_HASH_CHAIN' and identifies the exact entry.
        """
        if not rows:
            return {
                "intact": True,
                "status": "EMPTY",
                "global_entry_count": 0,
                "message": "Audit ledger is empty.",
            }

        prev_hash = rows[0].prev_hash
        genesis_hash = rows[0].entry_hash

        for idx, entry in enumerate(rows):
            if entry.action == "GENESIS":
                prev_hash = entry.entry_hash
                continue

            # Link verification: this entry's prev_hash must match prior entry's entry_hash
            if entry.prev_hash != prev_hash and idx != 0:
                try:
                    from observability.metrics import telemetry
                    telemetry.record_audit_verification_failure()
                except Exception:
                    pass
                return {
                    "intact": False,
                    "status": "BROKEN_HASH_CHAIN",
                    "first_broken_entry_id": entry.id,
                    "sequence_index": idx,
                    "message": f"BROKEN HASH CHAIN: prev_hash mismatch at entry #{entry.id} ({entry.prev_hash} != {prev_hash})",
                    "expected_prev_hash": prev_hash,
                    "found_prev_hash": entry.prev_hash,
                }

            # Cryptographic hash verification: entry_hash must equal SHA256(prev_hash + entry_data)
            entry_data = serialize_audit_payload(
                action=entry.action,
                user_id=str(entry.user_id) if entry.user_id else None,
                resource_id=str(entry.resource_id) if entry.resource_id else None,
                details=entry.details_json or {},
                timestamp=_canonical_timestamp(entry.event_timestamp),
            )
            expected_hash = hashlib.sha256((prev_hash + entry_data).encode("utf-8")).hexdigest()

            if expected_hash != entry.entry_hash:
                try:
                    from observability.metrics import telemetry
                    telemetry.record_audit_verification_failure()
                except Exception:
                    pass
                return {
                    "intact": False,
                    "status": "BROKEN_HASH_CHAIN",
                    "first_broken_entry_id": entry.id,
                    "sequence_index": idx,
                    "message": f"BROKEN HASH CHAIN: Hash mismatch at entry #{entry.id}. Data or timestamp was modified.",
                    "expected_hash": expected_hash,
                    "found_hash": entry.entry_hash,
                }

            prev_hash = entry.entry_hash

        return {
            "intact": True,
            "status": "VERIFIED",
            "global_entry_count": len(rows),
            "genesis_hash": genesis_hash,
            "last_hash": prev_hash,
            "message": f"Audit ledger verified successfully. {len(rows)} entries cryptographically intact.",
        }

    @classmethod
    async def verify_ledger(
        cls,
        db: AsyncSession,
        case_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Recompute and verify the global audit chain directly from the database.
        Optionally filters case-specific entries count while verifying the unbroken chain.
        """
        stmt = select(AuditLog).order_by(AuditLog.id.asc())
        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        verification = cls.verify_records(rows)
        if case_id:
            case_entries = [r for r in rows if str(r.resource_id) == str(case_id) or (isinstance(r.details_json, dict) and r.details_json.get("case_id") == str(case_id))]
            verification["case_id"] = str(case_id)
            verification["case_entry_count"] = len(case_entries)

        return verification
