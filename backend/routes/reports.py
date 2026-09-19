from __future__ import annotations
"""
CyberDrishti AI — Evidentiary Reports & Supervisor Export Approvals
Enforces dual-authorization (four-eyes principle) for Section 63 BSA
and Section 193 BNSS forensic court dossiers.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, CaseCollaborator, DossierExportApproval, EvidenceFile, User
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access
from utils.audit import append_audit

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
