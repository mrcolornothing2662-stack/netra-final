from __future__ import annotations
"""
Milestone 8 Section: Established Relationships
Generates established (active/confirmed) graph relationships with full evidence provenance.
Enforces the negative guarantee that rejected relationships are NEVER presented as facts.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_relationships_section(
    relationships: List[Any],
    resolver: ProvenanceResolver,
    order: int = 5,
) -> ReportSection:
    claims: List[ReportClaim] = []
    established_rows: List[dict] = []
    rejected_rows: List[dict] = []
    pending_rows: List[dict] = []
    limitations: List[str] = []

    for idx, r in enumerate(relationships or [], start=1):
        rid_str = str(r.id)
        s_id_val = str(getattr(r, "source_entity_id", getattr(r, "source_id", "")))
        t_id_val = str(getattr(r, "target_entity_id", getattr(r, "target_id", "")))
        source_ent = resolver.entities_by_id.get(s_id_val)
        target_ent = resolver.entities_by_id.get(t_id_val)
        src_val = getattr(source_ent, "canonical_value", "Unknown Entity")
        tgt_val = getattr(target_ent, "canonical_value", "Unknown Entity")
        rel_type = getattr(r, "relationship_type", getattr(r, "rel_type", "RELATED_TO"))
        rel_status = getattr(r, "verification_status", getattr(r, "status", "ACCEPTED"))
        conf = getattr(r, "confidence", 1.0)
        adjudication_notes = getattr(r, "adjudication_notes", getattr(r, "reason_codes", None))

        row = {
            "index": idx,
            "relationship_id": rid_str,
            "source": src_val,
            "target": tgt_val,
            "rel_type": rel_type,
            "status": rel_status,
            "confidence": conf,
            "adjudication_notes": adjudication_notes,
        }

        if rel_status == "REJECTED":
            # NEGATIVE GUARANTEE: Never present rejected relationship as established fact
            rejected_rows.append(row)
            limitations.append(
                f"Relationship {src_val} -[{rel_type}]-> {tgt_val} was REJECTED during review: {adjudication_notes or 'Investigator rejected'}. Excluded from established facts."
            )
            continue
        elif rel_status == "PENDING_REVIEW":
            pending_rows.append(row)
            limitations.append(
                f"Relationship {src_val} -[{rel_type}]-> {tgt_val} remains PENDING_REVIEW (confidence: {conf})."
            )
            continue

        established_rows.append(row)

        claim_text = (
            f"Established relationship: '{src_val}' is connected to '{tgt_val}' via [{rel_type}] "
            f"(confidence: {conf:.2f}, status: {rel_status})."
        )

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-REL-{idx:03d}",
                text=claim_text,
                claim_type="established_relationship",
                relationship_id=rid_str,
                entity_ids=[s_id_val, t_id_val],
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH if conf >= 0.8 else ConfidenceStatus.MEDIUM,
                generated_from="relationship_adjudicator",
            )
        )

    summary_text = (
        f"{len(established_rows)} established evidentiary relationships confirmed. "
        f"{len(pending_rows)} pending investigator review, {len(rejected_rows)} formally rejected."
    )

    return ReportSection(
        section_id="relationships",
        title="5. Established Evidentiary Relationships",
        order=order,
        summary=summary_text,
        claims=claims,
        data={
            "established": established_rows,
            "pending": pending_rows,
            "rejected": rejected_rows,
            "total_established": len(established_rows),
        },
        limitations=limitations,
    )
