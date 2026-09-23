from __future__ import annotations
"""
Milestone 8 Section: Limitations & Uncertainty Disclosures
Collects and highlights technical, evidentiary, and epistemic boundaries.
Ensures uncertainty is NOT hidden to make the report look artificially certain.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_limitations_section(
    limitations_list: List[str],
    information_gaps: List[Any],
    resolver: ProvenanceResolver,
    order: int = 8,
) -> ReportSection:
    claims: List[ReportClaim] = []
    items: List[str] = list(limitations_list or [])

    # Include explicit standard forensic disclaimers
    standard_disclaimers = [
        "Cellular Tower / CDR triangulation denotes approximate sector coverage, not pinpoint GPS coordinates (technical limitation).",
        "Automated entity extractions and candidate merges require affirmative investigator adjudication prior to final judicial submission.",
        "Section 65B/63 analysis aid certificates do not substitute for original device custodian declarations.",
    ]
    for disc in standard_disclaimers:
        if disc not in items:
            items.append(disc)

    for gap in (information_gaps or []):
        gap_desc = getattr(gap, "description", None) or getattr(gap, "title", "Unspecified information gap")
        items.append(f"Investigative Gap: {gap_desc}")

    for idx, lim in enumerate(items, start=1):
        claim_text = f"Boundary/Limitation #{idx}: {lim}"

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-LIM-{idx:03d}",
                text=claim_text,
                claim_type="technical_limitation",
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH,
                generated_from="limitation_shield",
            )
        )

    summary_text = (
        f"{len(items)} explicit technical and evidentiary limitations recorded to preserve judicial integrity."
    )

    return ReportSection(
        section_id="limitations",
        title="8. Technical Limitations, Contradictions & Information Gaps",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"limitations": items, "total_count": len(items)},
        limitations=items,
    )
