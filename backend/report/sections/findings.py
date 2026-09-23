from __future__ import annotations
"""
Milestone 8 Section: Investigation Findings
Generates prioritized findings with freshness status, severity, confidence,
and multi-tier evidentiary provenance citations.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_findings_section(
    findings: List[Any],
    resolver: ProvenanceResolver,
    order: int = 6,
) -> ReportSection:
    claims: List[ReportClaim] = []
    finding_rows: List[dict] = []
    limitations: List[str] = []

    # Severity ordering
    sev_weight = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

    def _safe_conf(f_obj) -> float:
        val = getattr(f_obj, "confidence", None)
        return float(val) if val is not None else 0.8

    sorted_findings = sorted(
        (f for f in (findings or [])),
        key=lambda f: (
            sev_weight.get((getattr(f, "severity", "LOW") or "LOW").upper(), 0),
            _safe_conf(f),
        ),
        reverse=True,
    )

    for idx, f in enumerate(sorted_findings, start=1):
        fid_str = str(f.id)
        title = f.title
        desc = getattr(f, "description", "") or ""
        sev = (getattr(f, "severity", "MEDIUM") or "MEDIUM").upper()
        fresh = (getattr(f, "freshness_status", "CURRENT") or "CURRENT").upper()
        conf = _safe_conf(f)

        # Flag stale or invalidated findings
        if fresh in ("STALE", "INVALIDATED"):
            limitations.append(
                f"Finding '{title}' (ID: {fid_str[:8]}) has freshness status '{fresh}' due to subsequent case mutations."
            )

        row = {
            "index": idx,
            "finding_id": fid_str,
            "title": title,
            "description": desc,
            "severity": sev,
            "freshness_status": fresh,
            "confidence": conf,
            "fingerprint": getattr(f, "fingerprint", None),
        }
        finding_rows.append(row)

        claim_text = f"[{sev}] {title}: {desc} (Freshness: {fresh}, Confidence: {conf:.2f})"

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-FND-{idx:03d}",
                text=claim_text,
                claim_type="investigation_finding",
                finding_id=fid_str,
                epistemic_status=EpistemicStatus.CONFIRMED if fresh == "CURRENT" else EpistemicStatus.DISPUTED,
                confidence_status=ConfidenceStatus.HIGH if conf >= 0.8 else ConfidenceStatus.MEDIUM,
                generated_from="investigation_brain",
            )
        )

    summary_text = (
        f"{len(finding_rows)} investigative findings recorded: "
        f"{sum(1 for r in finding_rows if r['freshness_status'] == 'CURRENT')} CURRENT, "
        f"{sum(1 for r in finding_rows if r['freshness_status'] != 'CURRENT')} STALE/INVALIDATED."
    )

    return ReportSection(
        section_id="findings",
        title="6. Investigation Findings & Analytical Deductions",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"findings": finding_rows, "total_count": len(finding_rows)},
        limitations=limitations,
    )
