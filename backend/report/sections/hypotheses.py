from __future__ import annotations
"""
Milestone 8 Section: Hypotheses & Working Theories
Generates active investigative hypotheses with supporting/contradicting corroborations.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_hypotheses_section(
    hypotheses: List[Any],
    resolver: ProvenanceResolver,
    order: int = 7,
) -> ReportSection:
    claims: List[ReportClaim] = []
    hypothesis_rows: List[dict] = []

    for idx, h in enumerate(hypotheses or [], start=1):
        hid_str = str(h.id)
        title = h.title
        desc = getattr(h, "description", "") or ""
        status = getattr(h, "status", "ACTIVE")
        conf = getattr(h, "confidence", 0.5)

        row = {
            "index": idx,
            "hypothesis_id": hid_str,
            "title": title,
            "description": desc,
            "status": status,
            "confidence": conf,
        }
        hypothesis_rows.append(row)

        claim_text = f"Working Hypothesis #{idx}: '{title}' — {desc} (Status: {status}, Confidence: {conf:.2f})"

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-HYP-{idx:03d}",
                text=claim_text,
                claim_type="investigative_hypothesis",
                epistemic_status=EpistemicStatus.ALLEGED,
                confidence_status=ConfidenceStatus.MEDIUM if conf >= 0.5 else ConfidenceStatus.LOW,
                generated_from="hypothesis_board",
            )
        )

    summary_text = f"{len(hypothesis_rows)} working theories undergoing forensic evaluation."

    return ReportSection(
        section_id="hypotheses",
        title="7. Investigative Hypotheses & Working Theories",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"hypotheses": hypothesis_rows, "total_count": len(hypothesis_rows)},
        limitations=[],
    )
