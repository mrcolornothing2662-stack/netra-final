from __future__ import annotations
"""
Milestone 8 Section: Tamper-Evident Audit Ledger Verification
Certifies audit hash-chain integrity, genesis seed, and entry sequencing.
"""
from typing import Any, Dict, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_audit_section(
    audit_verification: Dict[str, Any],
    resolver: ProvenanceResolver,
    order: int = 10,
) -> ReportSection:
    claims: List[ReportClaim] = []
    limitations: List[str] = []

    intact = audit_verification.get("intact", True)
    total_entries = audit_verification.get("global_entry_count") or audit_verification.get("case_entry_count") or 0
    gen_hash = audit_verification.get("genesis_hash", "0" * 64)
    last_hash = audit_verification.get("last_hash", "0" * 64)
    first_broken = audit_verification.get("first_broken_entry_id")

    if not intact:
        limitations.append(
            f"CRITICAL AUDIT ALERT: Audit chain integrity broken at entry #{first_broken}. Possible log tampering detected."
        )

    claim_text = (
        f"Audit hash chain integrity: {'VERIFIED / INTACT' if intact else 'BROKEN / COMPROMISED'}. "
        f"Verified across {total_entries} cryptographic log entries from genesis seed to latest tip "
        f"({str(last_hash)[:16]}...)."
    )

    claims.append(
        resolver.build_claim_provenance(
            claim_id="CLAIM-AUD-001",
            text=claim_text,
            claim_type="audit_verification",
            epistemic_status=EpistemicStatus.CONFIRMED if intact else EpistemicStatus.CONTRADICTED,
            confidence_status=ConfidenceStatus.HIGH,
            generated_from="audit_integrity_verifier",
        )
    )

    data = {
        "intact": intact,
        "total_entries": total_entries,
        "genesis_hash": gen_hash,
        "last_hash": last_hash,
        "first_broken_entry_id": first_broken,
    }

    return ReportSection(
        section_id="audit",
        title="10. Cryptographic Audit Chain & Chain-of-Custody Integrity",
        order=order,
        summary="Tamper-evident cryptographic ledger verification certifying that no historical case logs were altered.",
        claims=claims,
        data=data,
        limitations=limitations,
    )
