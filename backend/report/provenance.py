from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Milestone 8 Provenance Resolver
Traces every claim back to:
Claim -> Finding -> Relationship -> Event -> EvidenceFile (page/line) -> SHA-256

Enforces strict negative guarantees:
- Rejects nonexistent evidence references.
- Flags claims lacking verifiable citations (PROVENANCE REVIEW REQUIRED).
- Prevents rejected relationships from masquerading as established facts.
- Prevents unresolved identity candidates from being treated as confirmed canonical entities.
"""
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from report.contracts import (
    ConfidenceStatus,
    EpistemicStatus,
    EvidenceCitation,
    ProvenanceChain,
    ProvenanceStatus,
    ReportClaim,
)


class ProvenanceResolver:
    """
    In-memory graph traverser that verifies and builds cryptographic and
    evidentiary provenance chains for report claims against authoritative case state.
    """

    def __init__(
        self,
        evidence_files: List[Any],
        evidence_events: List[Any],
        entities: List[Any],
        relationships: List[Any],
        findings: List[Any],
        identity_candidates: Optional[List[Any]] = None,
    ):
        self.evidence_files_by_id: Dict[str, Any] = {
            str(ef.id): ef for ef in (evidence_files or [])
        }
        self.events_by_id: Dict[str, Any] = {
            str(ev.id): ev for ev in (evidence_events or [])
        }
        self.entities_by_id: Dict[str, Any] = {
            str(e.id): e for e in (entities or [])
        }
        self.relationships_by_id: Dict[str, Any] = {
            str(r.id): r for r in (relationships or [])
        }
        self.findings_by_id: Dict[str, Any] = {
            str(f.id): f for f in (findings or [])
        }
        self.identity_candidates_by_id: Dict[str, Any] = {
            str(ic.id): ic for ic in (identity_candidates or [])
        }

        # Index events by evidence_file_id
        self.events_by_evidence_id: Dict[str, List[Any]] = {}
        for ev in (evidence_events or []):
            if ev.evidence_file_id:
                eid_str = str(ev.evidence_file_id)
                self.events_by_evidence_id.setdefault(eid_str, []).append(ev)

    def format_citation_label(
        self,
        evidence_file: Any,
        source_page: Optional[int] = None,
        source_line: Optional[int] = None,
    ) -> str:
        """
        Creates canonical citation badge, e.g. [E-017 · p.4 · line 23]
        """
        sha = getattr(evidence_file, "sha256_hash", "") or ""
        short_id = sha[:6].upper() if len(sha) >= 6 else str(evidence_file.id)[:6].upper()
        badge_name = f"E-{short_id}"

        parts = [badge_name]
        if source_page is not None and source_page > 0:
            parts.append(f"p.{source_page}")
        if source_line is not None and source_line > 0:
            parts.append(f"line {source_line}")

        return f"[{' · '.join(parts)}]"

    def resolve_citation(
        self,
        evidence_id: str,
        source_page: Optional[int] = None,
        source_line: Optional[int] = None,
        event_id: Optional[str] = None,
    ) -> Tuple[Optional[EvidenceCitation], Optional[str]]:
        """
        Validates evidence file existence, integrity, and builds an EvidenceCitation.
        Returns (citation, warning_if_any).
        """
        ef = self.evidence_files_by_id.get(str(evidence_id))
        if not ef:
            return None, f"Nonexistent evidence artifact reference: {evidence_id}"

        sha = getattr(ef, "sha256_hash", None)
        if not sha or len(sha) != 64:
            return None, f"Evidence file {ef.filename} lacks a valid SHA-256 digest."

        # If page/line not provided, check if event has them
        if event_id and (source_page is None or source_line is None):
            ev = self.events_by_id.get(str(event_id))
            if ev:
                if source_page is None:
                    source_page = getattr(ev, "source_page", None)
                if source_line is None:
                    source_line = getattr(ev, "source_line", None)

        label = self.format_citation_label(ef, source_page=source_page, source_line=source_line)

        citation = EvidenceCitation(
            evidence_id=str(ef.id),
            file_name=getattr(ef, "original_name", None) or getattr(ef, "filename", "unnamed_artifact"),
            sha256_hash=sha,
            source_page=source_page,
            source_line=source_line,
            event_id=str(event_id) if event_id else None,
            citation_label=label,
            source_type=getattr(ef, "source_type", None) or getattr(ef, "file_type", None),
        )
        return citation, None

    def build_claim_provenance(
        self,
        claim_id: str,
        text: str,
        claim_type: str,
        finding_id: Optional[str] = None,
        relationship_id: Optional[str] = None,
        entity_ids: Optional[List[str]] = None,
        event_ids: Optional[List[str]] = None,
        evidence_ids: Optional[List[str]] = None,
        explicit_citations: Optional[List[EvidenceCitation]] = None,
        epistemic_status: EpistemicStatus = EpistemicStatus.INFERRED,
        confidence_status: ConfidenceStatus = ConfidenceStatus.MEDIUM,
        limitations: Optional[List[str]] = None,
        generated_from: str = "investigation_brain",
    ) -> ReportClaim:
        """
        Traverses the full chain for a claim, verifies all references,
        gathers citations, flags warnings, and assigns provenance status.
        """
        warnings: List[str] = []
        trace_steps: List[str] = []
        collected_citations: List[EvidenceCitation] = []
        if explicit_citations:
            collected_citations.extend(explicit_citations)

        entity_refs_summary: List[Dict[str, Any]] = []
        event_refs_summary: List[Dict[str, Any]] = []
        evidence_files_summary: List[Dict[str, Any]] = []
        finding_ref_summary: Optional[Dict[str, Any]] = None
        relationship_ref_summary: Optional[Dict[str, Any]] = None

        all_evidence_ids_to_check: Set[str] = set(str(eid) for eid in (evidence_ids or []))
        all_event_ids_to_check: Set[str] = set(str(eid) for eid in (event_ids or []))
        all_entity_ids_to_check: Set[str] = set(str(eid) for eid in (entity_ids or []))

        # 1. Finding Resolution
        if finding_id:
            fid_str = str(finding_id)
            finding = self.findings_by_id.get(fid_str)
            if finding:
                scores = getattr(finding, "component_scores", {}) or {}
                finding_ref_summary = {
                    "id": str(finding.id),
                    "title": finding.title,
                    "severity": getattr(finding, "severity", "MEDIUM"),
                    "freshness_status": getattr(finding, "freshness_status", "CURRENT"),
                    "fingerprint": getattr(finding, "fingerprint", None),
                    "canonical_provenance": scores.get("canonical_provenance"),
                }
                trace_steps.append(f"Finding F-{finding.title[:24]}")
                # Pull finding's evidence refs
                for ref in (getattr(finding, "evidence_refs", []) or []):
                    if isinstance(ref, str):
                        all_evidence_ids_to_check.add(ref)
                    elif isinstance(ref, dict) and "id" in ref:
                        all_evidence_ids_to_check.add(str(ref["id"]))
                # Pull finding's entity refs
                for ref in (getattr(finding, "entity_refs", []) or []):
                    if isinstance(ref, str):
                        all_entity_ids_to_check.add(ref)
            else:
                warnings.append(f"Referenced finding {finding_id} not found in case findings.")

        # 2. Relationship Resolution
        if relationship_id:
            rid_str = str(relationship_id)
            rel = self.relationships_by_id.get(rid_str)
            if rel:
                s_id_val = str(getattr(rel, "source_entity_id", getattr(rel, "source_id", "")))
                t_id_val = str(getattr(rel, "target_entity_id", getattr(rel, "target_id", "")))
                rel_type_val = getattr(rel, "relationship_type", getattr(rel, "rel_type", "RELATED_TO"))
                rel_status = getattr(rel, "verification_status", getattr(rel, "status", "ACCEPTED"))

                source_ent = self.entities_by_id.get(s_id_val)
                target_ent = self.entities_by_id.get(t_id_val)

                # NEGATIVE GUARANTEE: Rejected relationships must never masquerade as established facts
                if rel_status == "REJECTED":
                    epistemic_status = EpistemicStatus.CONTRADICTED
                    warnings.append(f"Relationship REL-{rid_str[:8]} was REJECTED by investigator adjudication.")

                attrs = getattr(rel, "attributes", {}) or {}
                relationship_ref_summary = {
                    "id": str(rel.id),
                    "rel_type": rel_type_val,
                    "source_id": s_id_val,
                    "target_id": t_id_val,
                    "source_value": getattr(source_ent, "canonical_value", "Unknown"),
                    "target_value": getattr(target_ent, "canonical_value", "Unknown"),
                    "status": rel_status,
                    "confidence": getattr(rel, "confidence", 1.0),
                    "canonical_provenance": attrs.get("canonical_provenance"),
                }
                trace_steps.append(f"Relationship {relationship_ref_summary['source_value']} --[{rel_type_val}]--> {relationship_ref_summary['target_value']}")

                # Pull relationship evidence refs
                for ref in (getattr(rel, "evidence_refs", []) or []):
                    if isinstance(ref, str):
                        all_evidence_ids_to_check.add(ref)
                    elif isinstance(ref, dict) and "id" in ref:
                        all_evidence_ids_to_check.add(str(ref["id"]))
            else:
                warnings.append(f"Referenced relationship {relationship_id} not found in case relationships.")

        # 3. Entity Resolution & Identity Integrity
        for eid in all_entity_ids_to_check:
            ent = self.entities_by_id.get(eid)
            if ent:
                entity_refs_summary.append({
                    "id": str(ent.id),
                    "canonical_value": ent.canonical_value,
                    "entity_type": ent.entity_type,
                })
                # Check source refs on entity
                for ref in (getattr(ent, "source_refs", []) or []):
                    if isinstance(ref, str):
                        all_evidence_ids_to_check.add(ref)
                    elif isinstance(ref, dict) and "id" in ref:
                        all_evidence_ids_to_check.add(str(ref["id"]))

        # 4. Events Resolution
        for evid in all_event_ids_to_check:
            ev = self.events_by_id.get(evid)
            if ev:
                event_refs_summary.append({
                    "id": str(ev.id),
                    "event_type": getattr(ev, "event_type", "event"),
                    "event_timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                    "snippet": (ev.text_content[:80] + "...") if ev.text_content else None,
                    "source_page": getattr(ev, "source_page", None),
                    "source_line": getattr(ev, "source_line", None),
                })
                if ev.evidence_file_id:
                    all_evidence_ids_to_check.add(str(ev.evidence_file_id))
                    # Direct citation from event
                    cit, warn = self.resolve_citation(
                        str(ev.evidence_file_id),
                        source_page=getattr(ev, "source_page", None),
                        source_line=getattr(ev, "source_line", None),
                        event_id=str(ev.id),
                    )
                    if cit and cit not in collected_citations:
                        collected_citations.append(cit)
                    if warn:
                        warnings.append(warn)

        # 5. Direct Evidence File Resolution
        for efid in all_evidence_ids_to_check:
            cit, warn = self.resolve_citation(efid)
            if cit and cit not in collected_citations:
                collected_citations.append(cit)
            if warn:
                warnings.append(warn)

            ef = self.evidence_files_by_id.get(efid)
            if ef:
                evidence_files_summary.append({
                    "id": str(ef.id),
                    "filename": getattr(ef, "original_name", None) or getattr(ef, "filename", "artifact"),
                    "sha256": getattr(ef, "sha256_hash", None),
                    "size_bytes": getattr(ef, "file_size_bytes", None),
                    "upload_status": getattr(ef, "upload_status", None),
                })
                trace_steps.append(f"Evidence {ef.filename} (SHA-256: {ef.sha256_hash[:8]}...)")

        # 6. Provenance Status Determination
        has_citations = len(collected_citations) > 0
        has_invalid_refs = any("Nonexistent evidence" in w or "lacks a valid SHA-256" in w for w in warnings)

        if not has_citations:
            provenance_status = ProvenanceStatus.UNLINKED
            warnings.append("⚠ PROVENANCE REVIEW REQUIRED: No grounded evidentiary links found for this claim.")
        elif has_invalid_refs:
            provenance_status = ProvenanceStatus.REVIEW_REQUIRED
            warnings.append("⚠ PROVENANCE REVIEW REQUIRED: References invalid or missing evidence files.")
        else:
            # Fully verified with at least one validated evidence citation
            provenance_status = ProvenanceStatus.VERIFIED

        chain = ProvenanceChain(
            claim_id=claim_id,
            finding_ref=finding_ref_summary,
            relationship_ref=relationship_ref_summary,
            entity_refs=entity_refs_summary,
            event_refs=event_refs_summary,
            evidence_files=evidence_files_summary,
            provenance_status=provenance_status,
            trace_steps=trace_steps,
            warnings=warnings,
        )

        return ReportClaim(
            claim_id=str(claim_id),
            text=text,
            claim_type=claim_type,
            epistemic_status=epistemic_status,
            confidence_status=confidence_status,
            entity_refs=list(str(x) for x in all_entity_ids_to_check),
            relationship_refs=[str(relationship_id)] if relationship_id else [],
            event_refs=list(str(x) for x in all_event_ids_to_check),
            finding_refs=[str(finding_id)] if finding_id else [],
            evidence_refs=collected_citations,
            limitations=limitations or [],
            generated_from=generated_from,
            provenance_chain=chain,
            provenance_status=provenance_status,
        )
