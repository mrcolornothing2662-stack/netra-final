from __future__ import annotations
"""
CyberDrishti AI — Evidentiary Reports & Supervisor Export Approvals
Enforces dual-authorization (four-eyes principle) for Section 63 BSA
and Section 193 BNSS forensic court dossiers.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    CaseCollaborator,
    DossierExportApproval,
    Entity,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
    ReportSnapshot,
    User,
)
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access
from utils.audit import append_audit
from report.contracts import (
    EvidenceUsageClaim,
    EvidenceUsageFinding,
    EvidenceUsageRelationship,
    EvidenceUsageResponse,
    ReportGenerateRequest,
    ReportPayload,
    ReportReviewBody,
    ReportType,
)
from report.builder import ReportBuilder
from report.renderer import ReportRenderer

router = APIRouter(prefix="/cases/{case_id}/reports", tags=["Reports & Export Approvals"])


class ApprovalRequestCreate(BaseModel):
    report_type: str = Field(..., description="E.g. 'section_63_bsa', 'section_193_bnss', 'chargesheet_dossier'")
    notes: Optional[str] = Field(None, description="Reason / purpose of court dossier export")


class ApprovalReviewBody(BaseModel):
    action: str = Field(..., description="'APPROVE' or 'REJECT'")
    rejection_reason: Optional[str] = Field(None, description="Required if action is REJECT")


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    report_type: str
    requested_by: uuid.UUID
    approved_by: Optional[uuid.UUID]
    status: str
    rejection_reason: Optional[str]
    created_at: datetime
    reviewed_at: Optional[datetime]

    class Config:
        from_attributes = True


@router.post("/approval-request", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def request_dossier_export_approval(
    case_id: str,
    body: ApprovalRequestCreate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """
    Investigating Officer requests supervisor approval to export a statutory court dossier.
    """
    case = await require_case_access(db, current, case_id, write=True)

    norm_type = body.report_type.strip().lower()
    valid_types = {"section_63_bsa", "section_193_bnss", "chargesheet_dossier", "forensic_summary"}
    if norm_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid report type. Allowed types: {sorted(list(valid_types))}",
        )

    # Check if there is already an active pending request
    pending = await db.execute(
        select(DossierExportApproval).where(
            DossierExportApproval.case_id == case.id,
            DossierExportApproval.report_type == norm_type,
            DossierExportApproval.status == "PENDING",
        )
    )
    if pending.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A pending export approval request for '{norm_type}' already exists for this case.",
        )

    approval = DossierExportApproval(
        case_id=case.id,
        report_type=norm_type,
        requested_by=current.id,
        status="PENDING",
    )
    db.add(approval)
    await db.flush()

    await append_audit(
        db,
        action="DOSSIER_EXPORT_REQUESTED",
        resource_type="dossier_export_approval",
        resource_id=str(approval.id),
        details={
            "case_id": str(case.id),
            "case_number": case.case_number,
            "report_type": norm_type,
            "notes": body.notes,
        },
        user_id=str(current.id),
    )

    return approval


@router.get("/approvals", response_model=List[ApprovalResponse])
async def list_export_approvals(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    List all dossier export approval records for a case.
    """
    case = await require_case_access(db, current, case_id)
    res = await db.execute(
        select(DossierExportApproval)
        .where(DossierExportApproval.case_id == case.id)
        .order_by(desc(DossierExportApproval.created_at))
    )
    return res.scalars().all()


@router.post("/approvals/{approval_id}/review", response_model=ApprovalResponse)
async def review_dossier_export_approval(
    case_id: str,
    approval_id: str,
    body: ApprovalReviewBody,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "admin")),
):
    """
    Review (Approve/Reject) an export request.
    Strictly enforces the Four-Eyes Principle: The reviewer CANNOT be the officer who requested it.
    Reviewer must be a supervisor collaborator, another IO, or an admin with case access.
    """
    case = await require_case_access(db, current, case_id, write=True)

    try:
        appr_uuid = uuid.UUID(str(approval_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid approval UUID format")

    res = await db.execute(
        select(DossierExportApproval).where(
            DossierExportApproval.id == appr_uuid,
            DossierExportApproval.case_id == case.id,
        )
    )
    approval = res.scalars().first()
    if not approval:
        raise HTTPException(status_code=404, detail="Dossier export approval request not found")

    if approval.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request is already resolved with status '{approval.status}'",
        )

    # Four-Eyes Check: An officer cannot approve their own export request
    if approval.requested_by == current.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Four-Eyes Policy Violation: You cannot approve your own dossier export request. A second officer or supervisor must review it.",
        )

    action_norm = body.action.strip().upper()
    if action_norm not in {"APPROVE", "REJECT"}:
        raise HTTPException(status_code=400, detail="Action must be 'APPROVE' or 'REJECT'")

    if action_norm == "REJECT" and not body.rejection_reason:
        raise HTTPException(status_code=400, detail="A rejection reason must be provided when rejecting an export request")

    approval.status = "APPROVED" if action_norm == "APPROVE" else "REJECTED"
    approval.approved_by = current.id
    approval.reviewed_at = datetime.now(timezone.utc)
    approval.rejection_reason = body.rejection_reason if action_norm == "REJECT" else None

    await append_audit(
        db,
        action=f"DOSSIER_EXPORT_{approval.status}",
        resource_type="dossier_export_approval",
        resource_id=str(approval.id),
        details={
            "case_id": str(case.id),
            "case_number": case.case_number,
            "report_type": approval.report_type,
            "action": approval.status,
            "reviewer_rank": current.rank,
            "rejection_reason": approval.rejection_reason,
        },
        user_id=str(current.id),
    )

    return approval


@router.get("/export")
async def export_certified_dossier(
    case_id: str,
    report_type: str = Query(..., description="E.g. 'section_63_bsa', 'section_193_bnss'"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Generate and export a certified Section 63 BSA / Section 193 BNSS court dossier.
    Requires an existing APPROVED supervisor authorization under dual-control policy.
    """
    case = await require_case_access(db, current, case_id)

    norm_type = report_type.strip().lower()

    # Check for approved export authorization
    approval_res = await db.execute(
        select(DossierExportApproval).where(
            DossierExportApproval.case_id == case.id,
            DossierExportApproval.report_type == norm_type,
            DossierExportApproval.status == "APPROVED",
        ).order_by(desc(DossierExportApproval.reviewed_at))
    )
    active_approval = approval_res.scalars().first()

    if not active_approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Dual-authorization required: Exporting '{norm_type}' dossier requires supervisor approval. "
                f"No APPROVED request found for case {case.case_number}. Please request supervisor sign-off."
            ),
        )

    # Fetch evidence files for the Section 63 BSA certificate table
    ev_res = await db.execute(
        select(EvidenceFile).where(EvidenceFile.case_id == case.id).order_by(EvidenceFile.created_at)
    )
    evidence_items = ev_res.scalars().all()

    evidence_table = []
    for ev in evidence_items:
        evidence_table.append({
            "filename": ev.filename,
            "sha256_hash": ev.sha256_hash,
            "file_size_bytes": ev.file_size_bytes,
            "source_type": ev.source_type,
            "acquisition_tool": getattr(ev, "acquisition_tool", None) or "CyberDrishti Forensic Ingestion v5.0",
            "acquisition_timestamp": (
                getattr(ev, "acquisition_timestamp", None).isoformat()
                if getattr(ev, "acquisition_timestamp", None)
                else ev.created_at.isoformat()
            ),
            "is_encrypted_at_rest": getattr(ev, "is_encrypted", False),
        })

    # Log export in audit ledger
    await append_audit(
        db,
        action="DOSSIER_EXPORTED",
        resource_type="case",
        resource_id=str(case.id),
        details={
            "case_number": case.case_number,
            "report_type": norm_type,
            "approval_id": str(active_approval.id),
            "approved_by": str(active_approval.approved_by),
            "evidence_item_count": len(evidence_table),
        },
        user_id=str(current.id),
    )

    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "status": "success",
        "dossier_type": norm_type,
        "case_id": str(case.id),
        "case_number": case.case_number,
        "fir_number": case.fir_number,
        "police_station": case.police_station,
        "export_timestamp": now_iso,
        "authorization": {
            "approval_id": str(active_approval.id),
            "requested_by": str(active_approval.requested_by),
            "approved_by": str(active_approval.approved_by),
            "approved_at": active_approval.reviewed_at.isoformat() if active_approval.reviewed_at else None,
        },
        "statutory_provisions": {
            "admissibility_mandate": "Section 63, Bharatiya Sakshya Adhiniyam (BSA), 2023",
            "police_report_mandate": "Section 193, Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023",
            "search_seizure_mandate": "Section 105, Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023",
        },
        "evidence_manifest": evidence_table,
    }


# ── Milestone 8: Evidence-Linked Report Snapshots & Workflow ─────────────────

@router.post("/generate", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def generate_case_report(
    case_id: str,
    body: ReportGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Generate an immutable, reproducible report snapshot (Brief or Formal Dossier).
    Computes deterministic content hash, verifies claim provenance, and preserves
    exact case state version without mutating case domain tables.
    """
    from investigation.policies import user_has_capability, CAP_REPORT_GENERATE
    if not user_has_capability(current.role, CAP_REPORT_GENERATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: REPORT_GENERATE capability required",
        )

    case = await require_case_access(db, current, case_id)

    payload = await ReportBuilder.build_report(
        case_id=str(case.id),
        db=db,
        report_type=body.report_type,
        user_id=str(current.id),
        title=body.title,
        section_keys=body.section_keys,
    )

    meta = payload.metadata
    snapshot = ReportSnapshot(
        id=uuid.UUID(meta.report_id),
        case_id=case.id,
        report_type=meta.report_type.value,
        status=meta.status.value,
        case_state_version=meta.case_state_version,
        template_version=meta.template_version,
        content_hash=meta.content_hash,
        title=meta.title,
        summary=meta.summary,
        claims_count=meta.claims_count,
        linked_claims_count=meta.linked_claims_count,
        review_required_claims_count=meta.review_required_claims_count,
        payload=payload.model_dump(),
        generated_by=current.id,
    )
    db.add(snapshot)
    await db.flush()

    await append_audit(
        db,
        action="REPORT_SNAPSHOT_GENERATED",
        resource_type="report_snapshot",
        resource_id=str(snapshot.id),
        details={
            "case_id": str(case.id),
            "report_type": meta.report_type.value,
            "case_state_version": meta.case_state_version,
            "content_hash": meta.content_hash,
            "claims_count": meta.claims_count,
            "linked_claims_count": meta.linked_claims_count,
            "review_required_claims_count": meta.review_required_claims_count,
        },
        user_id=str(current.id),
    )

    return payload.model_dump()


@router.get("/snapshots")
async def list_report_snapshots(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    List all immutable report snapshots created for this case.
    """
    case = await require_case_access(db, current, case_id)
    res = await db.execute(
        select(ReportSnapshot)
        .where(ReportSnapshot.case_id == case.id)
        .order_by(desc(ReportSnapshot.generated_at))
    )
    snapshots = res.scalars().all()
    return [
        {
            "id": str(s.id),
            "case_id": str(s.case_id),
            "report_type": s.report_type,
            "status": s.status,
            "case_state_version": s.case_state_version,
            "template_version": s.template_version,
            "content_hash": s.content_hash,
            "title": s.title,
            "summary": s.summary,
            "claims_count": s.claims_count,
            "linked_claims_count": s.linked_claims_count,
            "review_required_claims_count": s.review_required_claims_count,
            "generated_by": str(s.generated_by) if s.generated_by else None,
            "generated_at": s.generated_at.isoformat() if s.generated_at else None,
            "approved_by": str(s.approved_by) if s.approved_by else None,
            "approved_at": s.approved_at.isoformat() if s.approved_at else None,
            "rejection_reason": s.rejection_reason,
        }
        for s in snapshots
    ]


@router.get("/snapshots/{snapshot_id}")
async def get_report_snapshot(
    case_id: str,
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Retrieve an exact, frozen report snapshot.
    Historical Guarantee: Returns the immutable snapshot as generated at case_state_version,
    never silently recomputing against newer mutations.
    """
    case = await require_case_access(db, current, case_id)
    try:
        snap_uuid = uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid snapshot UUID format")

    res = await db.execute(
        select(ReportSnapshot).where(
            ReportSnapshot.id == snap_uuid,
            ReportSnapshot.case_id == case.id,
        )
    )
    snapshot = res.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Report snapshot not found")

    return snapshot.payload


@router.post("/snapshots/{snapshot_id}/submit-review")
async def submit_snapshot_for_review(
    case_id: str,
    snapshot_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Submit a DRAFT report snapshot for supervisor / four-eyes review.
    """
    from investigation.policies import user_has_capability, CAP_REPORT_GENERATE
    if not user_has_capability(current.role, CAP_REPORT_GENERATE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: REPORT_GENERATE capability required",
        )

    case = await require_case_access(db, current, case_id, write=True)
    try:
        snap_uuid = uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid snapshot UUID format")

    res = await db.execute(
        select(ReportSnapshot).where(
            ReportSnapshot.id == snap_uuid,
            ReportSnapshot.case_id == case.id,
        )
    )
    snapshot = res.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Report snapshot not found")

    if snapshot.status not in ("DRAFT", "REJECTED"):
        raise HTTPException(status_code=400, detail=f"Cannot submit snapshot with status '{snapshot.status}' for review")

    snapshot.status = "REVIEW"
    if isinstance(snapshot.payload, dict) and "metadata" in snapshot.payload:
        snapshot.payload["metadata"]["status"] = "REVIEW"

    await append_audit(
        db,
        action="REPORT_SNAPSHOT_SUBMITTED_FOR_REVIEW",
        resource_type="report_snapshot",
        resource_id=str(snapshot.id),
        details={"case_id": str(case.id), "report_type": snapshot.report_type},
        user_id=str(current.id),
    )
    return {"status": "success", "snapshot_id": str(snapshot.id), "new_status": "REVIEW"}


@router.post("/snapshots/{snapshot_id}/review")
async def review_report_snapshot(
    case_id: str,
    snapshot_id: str,
    body: ReportReviewBody,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Four-Eyes review of a report snapshot.
    Strict Policy: An officer cannot approve their own report snapshot.
    """
    case = await require_case_access(db, current, case_id, write=True)
    try:
        snap_uuid = uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid snapshot UUID format")

    res = await db.execute(
        select(ReportSnapshot).where(
            ReportSnapshot.id == snap_uuid,
            ReportSnapshot.case_id == case.id,
        )
    )
    snapshot = res.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Report snapshot not found")

    if snapshot.status != "REVIEW":
        raise HTTPException(status_code=400, detail=f"Cannot review snapshot with status '{snapshot.status}'. Must be in 'REVIEW' status.")

    # FOUR-EYES PRINCIPLE: An officer cannot approve their own report
    if snapshot.generated_by == current.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Four-Eyes Policy Violation: You cannot approve your own report. A second officer or supervisor must review it.",
        )

    from investigation.policies import user_has_capability, CAP_REPORT_APPROVE
    if not user_has_capability(current.role, CAP_REPORT_APPROVE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: REPORT_APPROVE capability required",
        )

    action_norm = body.action.strip().upper()
    if action_norm not in ("APPROVE", "REJECT"):
        raise HTTPException(status_code=400, detail="Action must be 'APPROVE' or 'REJECT'")

    if action_norm == "REJECT" and not body.rejection_reason:
        raise HTTPException(status_code=400, detail="A rejection reason must be provided when rejecting a report snapshot")

    now = datetime.now(timezone.utc)
    if action_norm == "APPROVE":
        snapshot.status = "APPROVED"
        snapshot.approved_by = current.id
        snapshot.approved_at = now
        snapshot.rejection_reason = None
    else:
        snapshot.status = "REJECTED"
        snapshot.rejection_reason = body.rejection_reason

    if isinstance(snapshot.payload, dict) and "metadata" in snapshot.payload:
        snapshot.payload["metadata"]["status"] = snapshot.status
        snapshot.payload["metadata"]["approved_by"] = str(current.id) if action_norm == "APPROVE" else None
        snapshot.payload["metadata"]["approved_at"] = now.isoformat() if action_norm == "APPROVE" else None
        snapshot.payload["metadata"]["rejection_reason"] = snapshot.rejection_reason

    await append_audit(
        db,
        action=f"REPORT_SNAPSHOT_{snapshot.status}",
        resource_type="report_snapshot",
        resource_id=str(snapshot.id),
        details={
            "case_id": str(case.id),
            "report_type": snapshot.report_type,
            "status": snapshot.status,
            "reviewer_rank": current.rank,
            "rejection_reason": snapshot.rejection_reason,
        },
        user_id=str(current.id),
    )

    return {
        "status": "success",
        "snapshot_id": str(snapshot.id),
        "new_status": snapshot.status,
        "approved_by": str(snapshot.approved_by) if snapshot.approved_by else None,
        "approved_at": snapshot.approved_at.isoformat() if snapshot.approved_at else None,
    }


@router.post("/snapshots/{snapshot_id}/export")
async def export_report_snapshot(
    case_id: str,
    snapshot_id: str,
    export_format: str = Query("json", description="'json', 'markdown', 'html', or 'pdf'"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Controlled export of a report snapshot.
    Formal Dossier strictly requires 'APPROVED' status.
    """
    case = await require_case_access(db, current, case_id)
    try:
        snap_uuid = uuid.UUID(str(snapshot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid snapshot UUID format")

    res = await db.execute(
        select(ReportSnapshot).where(
            ReportSnapshot.id == snap_uuid,
            ReportSnapshot.case_id == case.id,
        )
    )
    snapshot = res.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Report snapshot not found")

    # Authorize export: Formal dossier requires APPROVED status
    if snapshot.report_type == "formal_dossier" and snapshot.status not in ("APPROVED", "EXPORTED"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Dual-authorization required: Exporting a formal dossier requires 'APPROVED' status. Current status is '{snapshot.status}'.",
        )

    from investigation.policies import user_has_capability, CAP_REPORT_EXPORT
    if not user_has_capability(current.role, CAP_REPORT_EXPORT):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions: REPORT_EXPORT capability required",
        )

    payload = ReportPayload.model_validate(snapshot.payload)
    snapshot.status = "EXPORTED"

    await append_audit(
        db,
        action="REPORT_SNAPSHOT_EXPORTED",
        resource_type="report_snapshot",
        resource_id=str(snapshot.id),
        details={
            "case_id": str(case.id),
            "report_type": snapshot.report_type,
            "export_format": export_format,
            "content_hash": snapshot.content_hash,
        },
        user_id=str(current.id),
    )

    fmt = export_format.strip().lower()
    if fmt == "markdown":
        from fastapi.responses import PlainTextResponse
        md_text = ReportRenderer.to_markdown(payload)
        return PlainTextResponse(md_text, media_type="text/markdown")
    elif fmt == "html":
        from fastapi.responses import HTMLResponse
        html_text = ReportRenderer.to_html(payload)
        return HTMLResponse(html_text)
    elif fmt == "pdf":
        from fastapi.responses import FileResponse
        pdf_path = await ReportRenderer.render_pdf(payload)
        media_type = "application/pdf" if str(pdf_path).endswith(".pdf") else "text/html"
        return FileResponse(pdf_path, media_type=media_type, filename=f"Dossier_{case.case_number}.pdf")
    else:
        payload_dict = snapshot.payload if isinstance(snapshot.payload, dict) else {}
        meta = dict(payload_dict.get("metadata") or {})
        meta["status"] = snapshot.status
        meta["exported_by"] = str(current.id)
        meta["exported_at"] = datetime.now(timezone.utc).isoformat()
        return {**payload_dict, "status": snapshot.status, "metadata": meta}


@router.get("/evidence/{evidence_id}/usage", response_model=EvidenceUsageResponse)
async def get_evidence_usage(
    case_id: str,
    evidence_id: str,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Bidirectional Evidence / Report Link:
    Given an evidence item, returns every finding, relationship, and report claim
    grounded in this evidence bitstream.
    """
    case = await require_case_access(db, current, case_id)
    try:
        ev_uuid = uuid.UUID(str(evidence_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid evidence UUID format")

    ef_res = await db.execute(
        select(EvidenceFile).where(EvidenceFile.id == ev_uuid, EvidenceFile.case_id == case.id)
    )
    ef = ef_res.scalar_one_or_none()
    if not ef:
        raise HTTPException(status_code=404, detail="Evidence file not found in case.")

    # 1. Findings using this evidence
    findings_res = await db.execute(
        select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
    )
    findings = findings_res.scalars().all()
    ev_str = str(ev_uuid)
    matched_findings = []
    for f in findings:
        refs = getattr(f, "evidence_refs", []) or []
        ref_ids = [r if isinstance(r, str) else str(r.get("id")) for r in refs if r]
        if ev_str in ref_ids:
            matched_findings.append(
                EvidenceUsageFinding(
                    id=str(f.id),
                    title=f.title,
                    severity=getattr(f, "severity", "MEDIUM"),
                    freshness_status=getattr(f, "freshness_status", "CURRENT"),
                )
            )

    # 2. Relationships using this evidence
    rel_res = await db.execute(
        select(Relationship).where(Relationship.case_id == case.id)
    )
    relationships = rel_res.scalars().all()
    ent_res = await db.execute(select(Entity).where(Entity.case_id == case.id))
    ents = {str(e.id): e.canonical_value for e in ent_res.scalars().all()}

    matched_relationships = []
    for r in relationships:
        refs = getattr(r, "evidence_refs", []) or []
        ref_ids = [ref if isinstance(ref, str) else str(ref.get("id")) for ref in refs if ref]
        if ev_str in ref_ids:
            s_id = str(getattr(r, "source_entity_id", getattr(r, "source_id", "")))
            t_id = str(getattr(r, "target_entity_id", getattr(r, "target_id", "")))
            r_type = getattr(r, "relationship_type", getattr(r, "rel_type", "RELATED_TO"))
            r_stat = getattr(r, "verification_status", getattr(r, "status", "ACTIVE"))
            matched_relationships.append(
                EvidenceUsageRelationship(
                    id=str(r.id),
                    rel_type=r_type,
                    source_name=ents.get(s_id, "Unknown"),
                    target_name=ents.get(t_id, "Unknown"),
                    status=r_stat,
                )
            )

    # 3. Claims using this evidence across report snapshots
    snaps_res = await db.execute(
        select(ReportSnapshot).where(ReportSnapshot.case_id == case.id)
    )
    snapshots = snaps_res.scalars().all()
    matched_claims = []
    for s in snapshots:
        payload = s.payload or {}
        for sec in payload.get("sections", []):
            for c in sec.get("claims", []):
                for e_ref in c.get("evidence_refs", []):
                    if e_ref.get("evidence_id") == ev_str:
                        matched_claims.append(
                            EvidenceUsageClaim(
                                claim_id=c.get("claim_id", "CLAIM"),
                                text=c.get("text", "")[:120],
                                report_type=s.report_type,
                                report_id=str(s.id),
                            )
                        )
                        break

    return EvidenceUsageResponse(
        evidence_id=ev_str,
        case_id=str(case.id),
        filename=getattr(ef, "original_name", None) or getattr(ef, "filename", "artifact"),
        sha256_hash=getattr(ef, "sha256_hash", "") or "",
        file_size_bytes=getattr(ef, "file_size_bytes", None),
        upload_status=getattr(ef, "upload_status", "CONFIRMED"),
        findings=matched_findings,
        claims=matched_claims,
        relationships=matched_relationships,
        total_usages=len(matched_findings) + len(matched_claims) + len(matched_relationships),
    )
