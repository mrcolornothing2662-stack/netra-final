from __future__ import annotations
"""
Milestone 8 Section: Case Summary & Scope
Renders case identification, police station, FIR, crime type, and situation summary.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_case_summary_section(
    case: Any,
    resolver: ProvenanceResolver,
    order: int = 1,
) -> ReportSection:
    claims: List[ReportClaim] = []

    case_num = getattr(case, "case_number", "CASE-UNKNOWN")
    fir_num = getattr(case, "fir_number", None) or "Not Registered"
    ps = getattr(case, "police_station", None) or "Cyber Crime Police Station"
    crime = getattr(case, "crime_type", None) or "Cybercrime Investigation"
    priority = (getattr(case, "priority", "medium") or "medium").upper()
    status = (getattr(case, "status", "open") or "open").upper()
    version = getattr(case, "state_version", 1)

    text_id = (
        f"Case {case_num} ({case.title}) is registered under {ps}, FIR: {fir_num}. "
        f"Investigation scope encompasses {crime} with {priority} operational priority at case state v{version}."
    )

    claims.append(
        resolver.build_claim_provenance(
            claim_id="CLAIM-SUM-001",
            text=text_id,
            claim_type="case_identification",
            epistemic_status=EpistemicStatus.CONFIRMED,
            confidence_status=ConfidenceStatus.HIGH,
            generated_from="case_registry",
        )
    )

    data = {
        "case_id": str(case.id),
        "case_number": case_num,
        "title": case.title,
        "fir_number": fir_num,
        "police_station": ps,
        "crime_type": crime,
        "priority": priority,
        "status": status,
        "case_state_version": version,
        "created_at": case.created_at.isoformat() if getattr(case, "created_at", None) else None,
        "last_activity_at": case.last_activity_at.isoformat() if getattr(case, "last_activity_at", None) else None,
    }

    return ReportSection(
        section_id="case_summary",
        title="1. Case Identification & Investigation Scope",
        order=order,
        summary=f"Formal case registry profile and operational parameters for {case_num}.",
        claims=claims,
        data=data,
        limitations=[],
    )
