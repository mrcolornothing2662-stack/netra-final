from __future__ import annotations
"""
Milestone 8 Section: Entities
Generates confirmed canonical entities, associated identifiers,
and highlights any unresolved identity candidates or identity conflicts.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_entities_section(
    entities: List[Any],
    identity_candidates: List[Any],
    resolver: ProvenanceResolver,
    order: int = 4,
) -> ReportSection:
    claims: List[ReportClaim] = []
    entity_rows: List[dict] = []
    limitations: List[str] = []

    # Map candidate status by canonical entity ID
    candidates_by_ent: dict = {}
    for ic in (identity_candidates or []):
        cid = str(ic.canonical_entity_id)
        candidates_by_ent.setdefault(cid, []).append(ic)

    for idx, ent in enumerate(entities or [], start=1):
        ent_id = str(ent.id)
        val = ent.canonical_value
        etype = ent.entity_type
        source_refs = getattr(ent, "source_refs", []) or []

        cands = candidates_by_ent.get(ent_id, [])
        confirmed_cands = [c.candidate_value for c in cands if getattr(c, "resolution_status", "") == "CONFIRMED_SAME"]
        pending_cands = [c.candidate_value for c in cands if getattr(c, "resolution_status", "") == "PENDING"]
        diff_cands = [c.candidate_value for c in cands if getattr(c, "resolution_status", "") in ("CONFIRMED_DIFFERENT", "REJECTED")]

        if pending_cands:
            limitations.append(
                f"Entity '{val}' has {len(pending_cands)} unadjudicated identity candidate(s): {', '.join(pending_cands)}. Merging is strictly blocked pending IO sign-off."
            )

        row = {
            "index": idx,
            "entity_id": ent_id,
            "canonical_value": val,
            "entity_type": etype,
            "source_refs_count": len(source_refs),
            "confirmed_aliases": confirmed_cands,
            "pending_candidates": pending_cands,
            "rejected_candidates": diff_cands,
        }
        entity_rows.append(row)

        alias_str = f" (confirmed aliases: {', '.join(confirmed_cands)})" if confirmed_cands else ""
        pending_str = f" [⚠ {len(pending_cands)} pending candidate(s)]" if pending_cands else ""
        claim_text = f"Canonical entity '{val}' of type '{etype}' identified in evidence{alias_str}{pending_str}."

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-ENT-{idx:03d}",
                text=claim_text,
                claim_type="canonical_entity",
                entity_ids=[ent_id],
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH if not pending_cands else ConfidenceStatus.MEDIUM,
                generated_from="entity_explorer",
            )
        )

    summary_text = (
        f"{len(entity_rows)} canonical entities identified. "
        f"{sum(len(r['confirmed_aliases']) for r in entity_rows)} confirmed aliases, "
        f"{sum(len(r['pending_candidates']) for r in entity_rows)} unadjudicated candidates requiring review."
    )

    return ReportSection(
        section_id="entities",
        title="4. Entities & Identity Resolution",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"entities": entity_rows, "total_count": len(entity_rows)},
        limitations=limitations,
    )
