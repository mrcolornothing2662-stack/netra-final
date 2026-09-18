from __future__ import annotations

"""
Fingerprint Engine Adapter

Detects near-duplicate / appended (variant) evidence across the files of a
case, using the same FingerprintEngine the ingestion pipeline uses. Also
surfaces any [VARIANT] marker the ingestion step already recorded. Each finding
links both evidence files so the investigator can compare the diff.
"""
from typing import Any

from cognitive.fingerprint import FingerprintEngine
from orchestration.contracts import (
    FINGERPRINT_VARIANT,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "FingerprintEngine"
ENGINE_VERSION = "1.0"


def _events_by_file(context: CaseContext) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in context.events:
        file_id = event.get("evidence_file_id")
        if not file_id:
            continue
        meta = event.get("event_metadata") or {}
        grouped.setdefault(file_id, []).append({
            "event_type": event.get("event_type"),
            "timestamp": event.get("event_timestamp"),
            "amount": meta.get("amount") or meta.get("credit") or meta.get("debit"),
            "reference": meta.get("ref_no") or meta.get("narration") or (event.get("text_content") or "")[:40],
        })
    return grouped


def applies(context: CaseContext) -> bool:
    if any((f.get("parse_error") or "").startswith("[VARIANT]") or f.get("version_status") == "variant" for f in context.evidence_files):
        return True
    return len(_events_by_file(context)) >= 2


def run(context: CaseContext) -> list[CognitiveResult]:
    engine = FingerprintEngine()
    grouped = _events_by_file(context)
    file_ids = list(grouped.keys())

    fingerprints = {}
    for file_id in file_ids:
        # Distinct raw bytes per file so the engine's sha shortcut never treats
        # separate files as byte-identical; content similarity drives the verdict.
        fingerprints[file_id] = engine.compute(file_id.encode("utf-8"), grouped[file_id])

    results: list[CognitiveResult] = []
    covered: set[str] = set()

    # 1. Surface first-class Document Version Timeline lineages (F01) with impact analysis
    for evidence in context.evidence_files:
        marker = evidence.get("parse_error") or ""
        v_details = evidence.get("variant_details") or {}
        parent_id = str(evidence.get("parent_evidence_id") or v_details.get("parent_id") or "")
        file_id = str(evidence.get("id") or "")
        is_var = bool(evidence.get("version_status") == "variant" or marker.startswith("[VARIANT]"))
        if not file_id or not is_var:
            continue

        covered.update({file_id, parent_id} if parent_id else {file_id})

        impact = v_details.get("impact") or {}
        new_ents = impact.get("new_entities") or []
        ent_refs = [e["id"] for e in new_ents if "id" in e]
        ev_refs = [file_id]
        if parent_id and parent_id not in ev_refs:
            ev_refs.insert(0, parent_id)

        v_num = evidence.get("version_number") or 2
        fname = evidence.get("original_name") or file_id[:8]
        pname = v_details.get("parent_name") or (parent_id[:8] if parent_id else "original")

        desc = marker.replace("[VARIANT]", "").strip()
        if not desc:
            added_cnt = v_details.get("added_row_count", 0)
            desc = f"Appended document {fname} (v{v_num}) adds {added_cnt} new rows over {pname}."
        if new_ents:
            ent_names = ", ".join(e.get("canonical_value", "") for e in new_ents[:3])
            desc += f" Introduced {len(new_ents)} new entities: {ent_names}."

        results.append(CognitiveResult(
            finding_type=FINGERPRINT_VARIANT,
            title=f"Document Version Lineage: {fname} (v{v_num})",
            description=desc,
            confidence=0.95,
            severity=SEVERITY_HIGH if new_ents else SEVERITY_MEDIUM,
            source_engine=ENGINE_NAME,
            engine_version=ENGINE_VERSION,
            evidence_refs=ev_refs,
            entity_refs=ent_refs,
            reason_codes=["VARIANT", "VERSION_LINEAGE", "IMPACT_ANALYZED"],
            reasoning="Derived from Document Version Timeline (F01) structural diff and semantic impact analysis.",
            dedup_key=f"fingerprint:version:{file_id}",
        ))

    # 2. Pairwise content comparison for files not already grouped into a version lineage
    for i in range(len(file_ids)):
        for j in range(i + 1, len(file_ids)):
            a_id, b_id = file_ids[i], file_ids[j]
            if a_id in covered and b_id in covered:
                continue
            comparison = engine.compare(fingerprints[a_id], fingerprints[b_id])
            verdict = comparison.get("verdict")
            if verdict not in ("VARIANT", "EXACT_DUPLICATE", "REVIEW_SIMILAR"):
                continue
            jaccard = float(comparison.get("jaccard_estimate") or 0.0)
            containment = float(comparison.get("containment") or 0.0)
            confidence = round(max(jaccard, containment), 4)
            covered.update({a_id, b_id})
            results.append(CognitiveResult(
                finding_type=FINGERPRINT_VARIANT,
                title=f"Evidence variant cluster ({verdict})",
                description=(
                    f"Evidence {a_id[:8]} and {b_id[:8]} share "
                    f"{round(confidence * 100)}% content overlap ({verdict})."
                ),
                confidence=confidence,
                severity=SEVERITY_HIGH if verdict in ("VARIANT", "EXACT_DUPLICATE") else SEVERITY_LOW,
                source_engine=ENGINE_NAME,
                engine_version=ENGINE_VERSION,
                evidence_refs=[a_id, b_id],
                component_scores={
                    "jaccard_estimate": jaccard,
                    "containment": containment,
                    "verdict": verdict,
                },
                reason_codes=[verdict, "CONTENT_OVERLAP"],
                reasoning="MinHash/containment comparison of structured evidence rows.",
                dedup_key=f"fingerprint:{verdict}:{a_id}:{b_id}",
            ))

    return results


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Near-duplicate / appended evidence detection.",
    applicability=applies,
    skip_reason="insufficient_evidence_files",
)
