from __future__ import annotations
"""
Milestone 8 Section: Investigator Decisions & Adjudication Log
Records human-in-the-loop investigator decisions: identity confirmations/differentiations,
relationship reviews, command authorizations, and supervisor export sign-offs.
"""
from typing import Any, List
from report.contracts import ConfidenceStatus, EpistemicStatus, ReportClaim, ReportSection
from report.provenance import ProvenanceResolver


def build_investigator_actions_section(
    identity_candidates: List[Any],
    relationships: List[Any],
    activities: List[Any],
    resolver: ProvenanceResolver,
    order: int = 9,
) -> ReportSection:
    claims: List[ReportClaim] = []
    action_rows: List[dict] = []

    # 1. Identity Resolutions
    for ic in (identity_candidates or []):
        res_status = getattr(ic, "resolution_status", "PENDING")
        if res_status != "PENDING":
            val = getattr(ic, "candidate_value", "Unknown")
            can_ent = resolver.entities_by_id.get(str(ic.canonical_entity_id))
            can_val = getattr(can_ent, "canonical_value", "Canonical Entity")
            res_by = str(ic.resolved_by) if getattr(ic, "resolved_by", None) else "System/IO"
            res_at = ic.resolved_at.isoformat() if getattr(ic, "resolved_at", None) else "Recorded"

            row = {
                "action_type": "IDENTITY_RESOLUTION",
                "target": f"Candidate '{val}' -> '{can_val}'",
                "decision": res_status,
                "actor": res_by,
                "timestamp": res_at,
            }
            action_rows.append(row)

    # 2. Relationship Adjudications
    for r in (relationships or []):
        r_status = getattr(r, "verification_status", getattr(r, "status", "ACTIVE"))
        notes = getattr(r, "adjudication_notes", getattr(r, "reason_codes", None))
        if r_status in ("REJECTED", "ACCEPTED", "ACTIVE") and notes:
            s_id = str(getattr(r, "source_entity_id", getattr(r, "source_id", "")))
            t_id = str(getattr(r, "target_entity_id", getattr(r, "target_id", "")))
            s_ent = resolver.entities_by_id.get(s_id)
            t_ent = resolver.entities_by_id.get(t_id)
            s_val = getattr(s_ent, "canonical_value", "Source")
            t_val = getattr(t_ent, "canonical_value", "Target")
            r_type = getattr(r, "relationship_type", getattr(r, "rel_type", "RELATED_TO"))

            row = {
                "action_type": "RELATIONSHIP_ADJUDICATION",
                "target": f"{s_val} -[{r_type}]-> {t_val}",
                "decision": r_status,
                "actor": str(getattr(r, "verified_by", getattr(r, "adjudicated_by", "IO"))),
                "timestamp": getattr(r, "updated_at", getattr(r, "created_at", None)),
                "notes": str(notes),
            }
            action_rows.append(row)

    # 3. Key Investigation Activities
    for act in (activities or [])[:20]:
        act_type = getattr(act, "activity_type", "ACTION")
        row = {
            "action_type": act_type,
            "target": str(getattr(act, "entity_id", None) or getattr(act, "finding_id", "Case State")),
            "decision": "RECORDED",
            "actor": str(getattr(act, "actor_id", "IO")),
            "timestamp": act.created_at.isoformat() if getattr(act, "created_at", None) else None,
        }
        action_rows.append(row)

    for idx, act in enumerate(action_rows[:30], start=1):
        claim_text = (
            f"Investigator Decision #{idx} [{act['action_type']}]: {act['target']} "
            f"adjudicated as '{act['decision']}' by officer {str(act['actor'])[:8]}."
        )

        claims.append(
            resolver.build_claim_provenance(
                claim_id=f"CLAIM-ACT-{idx:03d}",
                text=claim_text,
                claim_type="investigator_action",
                epistemic_status=EpistemicStatus.CONFIRMED,
                confidence_status=ConfidenceStatus.HIGH,
                generated_from="investigation_command_gateway",
            )
        )

    summary_text = (
        f"{len(action_rows)} explicit human-in-the-loop investigator adjudications recorded."
    )

    return ReportSection(
        section_id="investigator_actions",
        title="9. Investigator Adjudications & Command Decisions",
        order=order,
        summary=summary_text,
        claims=claims,
        data={"actions": action_rows, "total_count": len(action_rows)},
        limitations=[],
    )
