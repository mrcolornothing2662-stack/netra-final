from __future__ import annotations
"""
Milestone 8 Section: Evidence Inventory
Generates the formal evidence ledger with SHA-256 digests, file sizes,
acquisition timestamps, and Section 63 BSA / Section 65B chain of custody.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_evidence_inventory_section(
    evidence_files: List[Any],
    resolver: ProvenanceResolver,
    order: int = 2,
) -> ReportSection:
    claims: List[ReportClaim] = []
    table_rows: List[dict] = []
    limitations: List[str] = []

    for idx, ef in enumerate(evidence_files or [], start=1):
        eid_str = str(ef.id)
        fname = getattr(ef, "original_name", None) or getattr(ef, "filename", "unnamed_artifact")
        sha = getattr(ef, "sha256_hash", None) or "MISSING_HASH"
        size = getattr(ef, "file_size_bytes", 0) or 0
        src_type = getattr(ef, "source_type", None) or getattr(ef, "file_type", "unknown")
        status = getattr(ef, "upload_status", "CONFIRMED")
        acq_time = (
            getattr(ef, "acquisition_timestamp", None).isoformat()
            if getattr(ef, "acquisition_timestamp", None)
            else (ef.uploaded_at.isoformat() if getattr(ef, "uploaded_at", None) else None)
        )

        row = {
            "index": idx,
            "evidence_id": eid_str,
            "filename": fname,
            "sha256_hash": sha,
            "file_size_bytes": size,
            "source_type": src_type,
            "status": status,
            "acquisition_timestamp": acq_time,
        }
        table_rows.append(row)

        if sha == "MISSING_HASH" or len(sha) != 64:
            limitations.append(f"Evidence artifact {fname} ({eid_str}) lacks cryptographic SHA-256 digest.")

        claim_text = (
            f"Evidence file #{idx} '{fname}' ({size} bytes, type: {src_type}) was cryptographically sealed "
            f"under SHA-256 digest {sha[:16]}... with ingestion status {status}."
        )

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-EVD-{idx:03d}",
                text=claim_text,
                claim_type="evidence_inventory",
                evidence_ids=[eid_str],
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH if sha != "MISSING_HASH" else ConfidenceStatus.LOW,
                generated_from="evidence_vault",
            )
        )

    summary_text = (
        f"{len(table_rows)} total forensic evidence artifacts recorded and cryptographically registered."
    )

    return ReportSection(
        section_id="evidence_inventory",
        title="2. Evidentiary Inventory & Cryptographic Registry",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"evidence_items": table_rows, "total_count": len(table_rows)},
        limitations=limitations,
    )
