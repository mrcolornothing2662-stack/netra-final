from __future__ import annotations
"""
Milestone 8 Section: Chronology
Generates the strictly ordered chronological sequence of forensic events,
grounded with exact evidence file, page, and line number citations.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_chronology_section(
    events: List[Any],
    resolver: ProvenanceResolver,
    order: int = 3,
) -> ReportSection:
    claims: List[ReportClaim] = []
    chronology_rows: List[dict] = []

    sorted_events = sorted(
        (ev for ev in (events or []) if ev.event_timestamp is not None),
        key=lambda ev: ev.event_timestamp,
    )

    for idx, ev in enumerate(sorted_events, start=1):
        ev_id = str(ev.id)
        ev_type = getattr(ev, "event_type", "event")
        ts_iso = ev.event_timestamp.isoformat()
        txt = getattr(ev, "text_content", "") or ""
        p = getattr(ev, "source_page", None)
        ln = getattr(ev, "source_line", None)
        ef_id = str(ev.evidence_file_id) if ev.evidence_file_id else None

        ef = resolver.evidence_files_by_id.get(ef_id) if ef_id else None
        fname = getattr(ef, "original_name", None) or getattr(ef, "filename", "unlinked_artifact")
        citation_label = resolver.format_citation_label(ef, source_page=p, source_line=ln) if ef else "[Unlinked]"

        row = {
            "index": idx,
            "event_id": ev_id,
            "timestamp": ts_iso,
            "event_type": ev_type,
            "snippet": txt[:160],
            "evidence_id": ef_id,
            "filename": fname,
            "source_page": p,
            "source_line": ln,
            "citation": citation_label,
        }
        chronology_rows.append(row)

        claim_text = f"At {ts_iso}, event [{ev_type}] observed: '{txt[:100]}...' {citation_label}"

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-CHR-{idx:03d}",
                text=claim_text,
                claim_type="chronology_event",
                event_ids=[ev_id],
                evidence_ids=[ef_id] if ef_id else [],
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH,
                generated_from="timeline_engine",
            )
        )

    summary_text = (
        f"{len(chronology_rows)} chronological evidentiary events reconstructed across all seized files."
    )

    return ReportSection(
        section_id="chronology",
        title="3. Evidentiary Chronology & Incident Timeline",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"events": chronology_rows, "total_count": len(chronology_rows)},
        limitations=[],
    )
