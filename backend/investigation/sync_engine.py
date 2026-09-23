from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Offline Synchronization Engine
Enforces "Offline commands, not offline truth":
- Reconciles queued mutations through Command Gateway
- Resolves conflicts deterministically (APPLY, REBASE, CONFLICT)
- Maintains server-authoritative case versioning
- Guarantees mutation idempotency and complete audit trails
"""
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    SyncConflictRecord,
    SyncProcessedMutation,
    User,
)
from investigation.brain import InvestigationBrain
from investigation.commands import CommandRequest, dispatch_command
from investigation.policies import (
    CAP_CASE_WRITE,
    CAP_ENTITY_WRITE,
    CAP_FINDING_REVIEW,
    CAP_HYPOTHESIS_WRITE,
    CAP_RELATIONSHIP_CONFIRM,
    CAP_RELATIONSHIP_REJECT,
    CAP_RELATIONSHIP_WRITE,
    user_has_capability,
)
from investigation.sync_contracts import (
    ConflictResolutionRequest,
    ConflictResolutionResponse,
    OfflineBundleResponse,
    OfflineMutationEnvelope,
    SyncBatchRequest,
    SyncBatchResponse,
    SyncConflict,
    SyncProjectionDelta,
    SyncRejection,
)
import graph.relationship_types as RT


class OfflineSyncEngine:
    """Core synchronization and conflict reconciliation engine."""

    @staticmethod
    async def build_offline_bundle(
        db: AsyncSession,
        case_id: str | uuid.UUID,
        user: User,
    ) -> OfflineBundleResponse:
        """
        Produce a comprehensive, read-only case snapshot for offline SQLite caching.
        Strictly read-only; no database rows are mutated and version is not bumped.
        """
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        case = await db.get(Case, case_uuid)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # 1. Case details
        case_dict = {
            "id": str(case.id),
            "case_number": case.case_number,
            "title": case.title,
            "description": case.description,
            "crime_type": case.crime_type,
            "fir_number": case.fir_number,
            "police_station": case.police_station,
            "priority": case.priority,
            "status": case.status,
            "state_version": case.state_version or 1,
            "created_at": case.created_at.isoformat() if case.created_at else None,
            "updated_at": case.updated_at.isoformat() if case.updated_at else None,
        }

        # 2. Entities
        ents = list((await db.execute(select(Entity).where(Entity.case_id == case.id))).scalars().all())
        entities_data = [
            {
                "id": str(e.id),
                "canonical_value": e.canonical_value,
                "entity_type": e.entity_type,
                "degree_centrality": e.degree_centrality or 0.0,
                "bridge_score": e.bridge_score or 0.0,
                "node_metadata": e.node_metadata or {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in ents
        ]

        # 3. Evidence files metadata
        files = list((await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case.id))).scalars().all())
        files_data = [
            {
                "id": str(f.id),
                "filename": f.filename,
                "file_type": f.file_type,
                "file_size_bytes": f.file_size_bytes,
                "sha256_hash": f.sha256_hash,
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
            }
            for f in files
        ]

        # 4. Events
        evs = list((await db.execute(select(EvidenceEvent).where(EvidenceEvent.case_id == case.id))).scalars().all())
        events_data = [
            {
                "id": str(ev.id),
                "event_type": ev.event_type,
                "event_timestamp": ev.event_timestamp.isoformat() if ev.event_timestamp else None,
                "summary": ev.text_content or "",
                "source_line": ev.source_line,
                "source_page": ev.source_page,
                "metadata": ev.event_metadata or {},
                "evidence_file_id": str(ev.evidence_file_id) if ev.evidence_file_id else None,
            }
            for ev in evs
        ]

        # 5. Relationships
        rels = list((await db.execute(select(Relationship).where(Relationship.case_id == case.id))).scalars().all())
        rels_data = [
            {
                "id": str(r.id),
                "source_entity_id": str(r.source_entity_id),
                "target_entity_id": str(r.target_entity_id),
                "relationship_type": r.relationship_type,
                "direction": r.direction,
                "epistemic_status": r.epistemic_status,
                "verification_status": r.verification_status,
                "confidence": r.confidence,
                "evidence_refs": [str(x) for x in (r.evidence_refs or [])],
                "event_refs": [str(x) for x in (r.event_refs or [])],
            }
            for r in rels
        ]

        # 6. Findings
        fnds = list((await db.execute(select(InvestigationFinding).where(InvestigationFinding.case_id == case.id))).scalars().all())
        findings_data = [
            {
                "id": str(f.id),
                "finding_type": f.finding_type,
                "title": f.title,
                "severity": f.severity,
                "confidence": f.confidence,
                "status": f.status,
                "freshness_status": f.freshness_status,
                "generated_at_case_version": f.generated_at_case_version,
            }
            for f in fnds
        ]

        # 7. Timeline activity
        acts = list((await db.execute(select(InvestigationActivity).where(InvestigationActivity.case_id == case.id).order_by(InvestigationActivity.created_at.asc()))).scalars().all())
        activity_data = [
            {
                "id": str(a.id),
                "activity_type": a.activity_type,
                "target_type": a.target_type,
                "target_id": str(a.target_id) if a.target_id else None,
                "reason": a.reason,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in acts
        ]

        # 8. Identity candidates
        cands = list((await db.execute(select(IdentityCandidate).where(IdentityCandidate.case_id == case.id))).scalars().all())
        cands_data = [
            {
                "id": str(c.id),
                "canonical_entity_id": str(c.canonical_entity_id) if c.canonical_entity_id else None,
                "candidate_value": c.candidate_value,
                "candidate_type": c.candidate_type,
                "resolution_status": c.resolution_status,
                "source_refs": c.source_refs or [],
                "supporting_refs": c.supporting_refs or [],
                "contradicting_refs": c.contradicting_refs or [],
            }
            for c in cands
        ]

        # 9. Replay index
        ckpts = list((await db.execute(select(InvestigationState).where(InvestigationState.case_id == case.id).order_by(InvestigationState.version.asc()))).scalars().all())
        replay_data = [
            {
                "version": ck.version,
                "state_hash": ck.state_hash,
                "created_at": ck.created_at.isoformat() if ck.created_at else None,
            }
            for ck in ckpts
        ]

        return OfflineBundleResponse(
            case=case_dict,
            server_state_version=case.state_version or 1,
            entities=entities_data,
            evidence_metadata=files_data,
            events=events_data,
            relationships=rels_data,
            findings=findings_data,
            timeline_activity=activity_data,
            identity_candidates=cands_data,
            replay_index=replay_data,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    async def process_sync_batch(
        db: AsyncSession,
        case_id: str | uuid.UUID,
        request: SyncBatchRequest,
        actor: User,
    ) -> SyncBatchResponse:
        """
        Process a batch of queued mutations from an offline client.
        Categorizes mutations as ACCEPTED, REBASED, CONFLICT, or REJECTED.
        Guarantees idempotency via SyncProcessedMutation.
        """
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        case = (
            await db.execute(select(Case).where(Case.id == case_uuid).with_for_update())
        ).scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        accepted: list[str] = []
        rebased: list[str] = []
        conflicts: list[SyncConflict] = []
        rejected: list[SyncRejection] = []

        # Sort mutations by local sequence
        sorted_mutations = sorted(request.mutations, key=lambda m: m.local_sequence)

        for mut in sorted_mutations:
            # 1. Idempotency check (Invariant 1)
            existing_proc = await db.get(SyncProcessedMutation, mut.mutation_id)
            if existing_proc:
                if existing_proc.outcome == "APPLIED":
                    accepted.append(mut.mutation_id)
                elif existing_proc.outcome == "REBASED":
                    rebased.append(mut.mutation_id)
                continue

            # 2. Permission check (Invariant 4)
            req_cap = OfflineSyncEngine._get_required_capability(mut.command_type)
            if req_cap and not user_has_capability(actor.role, req_cap):
                rejected.append(
                    SyncRejection(
                        mutation_id=mut.mutation_id,
                        error_code="UNAUTHORIZED",
                        detail=f"Role '{actor.role}' lacks required capability '{req_cap}' for command '{mut.command_type}'.",
                    )
                )
                continue

            # 3. Tri-state evaluation (APPLY vs REBASE vs CONFLICT)
            current_ver = case.state_version or 1
            is_stale = mut.base_state_version < current_ver

            if not is_stale:
                # Direct apply against current version
                try:
                    cmd_res = await dispatch_command(
                        db=db,
                        case_id=case.id,
                        request=CommandRequest(
                            command=mut.command_type,
                            payload=mut.payload,
                            reason=mut.payload.get("rationale") or "Offline sync mutation",
                            client_mutation_id=mut.mutation_id,
                            base_case_version=mut.base_state_version,
                        ),
                        current_user=actor,
                    )
                    db.add(
                        SyncProcessedMutation(
                            mutation_id=mut.mutation_id,
                            device_id=request.device_id,
                            actor_id=actor.id,
                            case_id=case.id,
                            command_type=mut.command_type,
                            base_state_version=mut.base_state_version,
                            server_state_version=cmd_res.new_state_version,
                            outcome="APPLIED",
                            activity_id=uuid.UUID(cmd_res.activity_id) if cmd_res.activity_id else None,
                        )
                    )
                    accepted.append(mut.mutation_id)
                except HTTPException as he:
                    rejected.append(
                        SyncRejection(
                            mutation_id=mut.mutation_id,
                            error_code="COMMAND_DISPATCH_FAILED",
                            detail=str(he.detail),
                        )
                    )
            else:
                # Stale base version -> Check semantic compatibility (Rebase or Conflict)
                outcome, conflict_or_msg = await OfflineSyncEngine._evaluate_stale_mutation(
                    db=db, case=case, mutation=mut, actor=actor
                )
                if outcome == "REBASE":
                    # Can safely apply against newer server state
                    try:
                        cmd_res = await dispatch_command(
                            db=db,
                            case_id=case.id,
                            request=CommandRequest(
                                command=mut.command_type,
                                payload=mut.payload,
                                reason=mut.payload.get("rationale") or "Rebased offline sync mutation",
                                client_mutation_id=mut.mutation_id,
                                base_case_version=case.state_version,
                            ),
                            current_user=actor,
                        )
                        db.add(
                            SyncProcessedMutation(
                                mutation_id=mut.mutation_id,
                                device_id=request.device_id,
                                actor_id=actor.id,
                                case_id=case.id,
                                command_type=mut.command_type,
                                base_state_version=mut.base_state_version,
                                server_state_version=cmd_res.new_state_version,
                                outcome="REBASED",
                                activity_id=uuid.UUID(cmd_res.activity_id) if cmd_res.activity_id else None,
                            )
                        )
                        rebased.append(mut.mutation_id)
                    except HTTPException as he:
                        rejected.append(
                            SyncRejection(
                                mutation_id=mut.mutation_id,
                                error_code="REBASE_EXECUTION_FAILED",
                                detail=str(he.detail),
                            )
                        )
                elif outcome == "ALREADY_CONVERGED":
                    # Already in desired state; record as rebased without double-mutating
                    rebased.append(mut.mutation_id)
                    db.add(
                        SyncProcessedMutation(
                            mutation_id=mut.mutation_id,
                            device_id=request.device_id,
                            actor_id=actor.id,
                            case_id=case.id,
                            command_type=mut.command_type,
                            base_state_version=mut.base_state_version,
                            server_state_version=case.state_version or 1,
                            outcome="REBASED",
                        )
                    )
                elif outcome == "CONFLICT":
                    # Explicit conflict record created (Invariant 7)
                    conflict_record = conflict_or_msg
                    conflicts.append(
                        SyncConflict(
                            conflict_id=str(conflict_record.id),
                            mutation_id=conflict_record.mutation_id,
                            command_type=conflict_record.command_type,
                            conflict_type=conflict_record.conflict_type,
                            client_payload=conflict_record.client_payload or {},
                            server_current_state=conflict_record.server_current_state or {},
                            message=(
                                f"Conflict on {conflict_record.command_type}: Server state at v{case.state_version} "
                                f"conflicts with offline mutation created at v{mut.base_state_version}."
                            ),
                            status=conflict_record.status,
                            created_at=conflict_record.created_at.isoformat() if conflict_record.created_at else None,
                        )
                    )
                else:
                    # Target not found or unrecoverable error
                    rejected.append(
                        SyncRejection(
                            mutation_id=mut.mutation_id,
                            error_code="TARGET_STATE_INVALID",
                            detail=str(conflict_or_msg),
                        )
                    )

        await db.commit()

        # 4. Generate projection delta from client_state_version to current case.state_version
        delta = await OfflineSyncEngine._build_projection_delta(
            db=db, case=case, client_state_version=request.client_state_version
        )

        return SyncBatchResponse(
            case_id=str(case.id),
            server_state_version=case.state_version or 1,
            accepted=accepted,
            rebased=rebased,
            conflicts=conflicts,
            rejected=rejected,
            projection_delta=delta,
        )

    @staticmethod
    async def _evaluate_stale_mutation(
        db: AsyncSession,
        case: Case,
        mutation: OfflineMutationEnvelope,
        actor: User,
    ) -> tuple[str, Any]:
        """
        Evaluate whether a stale mutation can be REBASED or represents a CONFLICT.
        """
        cmd = mutation.command_type.strip().upper()
        p = mutation.payload

        if cmd == "RESOLVE_IDENTITY_CANDIDATE":
            cand_id = p.get("candidate_id")
            if not cand_id:
                return "REJECTED", "Missing candidate_id in payload"
            try:
                c_uuid = uuid.UUID(str(cand_id))
            except ValueError:
                return "REJECTED", "Invalid candidate_id UUID"

            cand = await db.get(IdentityCandidate, c_uuid)
            if not cand or cand.case_id != case.id:
                return "REJECTED", "Target IdentityCandidate not found"

            desired_decision = p.get("resolution_status") or p.get("decision")  # CONFIRMED_SAME | CONFIRMED_DIFFERENT
            if desired_decision == "KEEP_SEPARATE":
                desired_decision = "CONFIRMED_DIFFERENT"

            if cand.resolution_status == "UNRESOLVED":
                # Candidate is still unresolved on server: safe to rebase!
                return "REBASE", None
            elif cand.resolution_status == desired_decision:
                # Already resolved in identical way by another investigator
                return "ALREADY_CONVERGED", None
            else:
                # True conflict! Another investigator resolved differently
                conflict = SyncConflictRecord(
                    id=uuid.uuid4(),
                    mutation_id=mutation.mutation_id,
                    device_id=mutation.device_id,
                    actor_id=actor.id,
                    case_id=case.id,
                    command_type=cmd,
                    client_payload=p,
                    base_state_version=mutation.base_state_version,
                    server_state_version=case.state_version or 1,
                    conflict_type="IDENTITY_DECISION_CONFLICT",
                    server_current_state={
                        "candidate_id": str(cand.id),
                        "server_status": cand.resolution_status,
                        "created_by": str(cand.created_by) if cand.created_by else None,
                    },
                    status="PENDING_REVIEW",
                )
                db.add(conflict)
                await db.flush()
                from observability.metrics import telemetry
                telemetry.record_sync_conflict()
                return "CONFLICT", conflict

        elif cmd in ["CONFIRM_RELATIONSHIP", "REJECT_RELATIONSHIP"]:
            rel_id = p.get("relationship_id")
            if not rel_id:
                return "REJECTED", "Missing relationship_id in payload"
            try:
                r_uuid = uuid.UUID(str(rel_id))
            except ValueError:
                return "REJECTED", "Invalid relationship_id UUID"

            rel = await db.get(Relationship, r_uuid)
            if not rel or rel.case_id != case.id:
                return "REJECTED", "Target Relationship not found"

            desired_verif = RT.REVIEW_ACCEPTED if cmd == "CONFIRM_RELATIONSHIP" else RT.REVIEW_REJECTED
            if rel.verification_status == RT.REVIEW_UNREVIEWED:
                return "REBASE", None
            elif rel.verification_status == desired_verif:
                return "ALREADY_CONVERGED", None
            else:
                conflict = SyncConflictRecord(
                    id=uuid.uuid4(),
                    mutation_id=mutation.mutation_id,
                    device_id=mutation.device_id,
                    actor_id=actor.id,
                    case_id=case.id,
                    command_type=cmd,
                    client_payload=p,
                    base_state_version=mutation.base_state_version,
                    server_state_version=case.state_version or 1,
                    conflict_type="RELATIONSHIP_REVIEW_CONFLICT",
                    server_current_state={
                        "relationship_id": str(rel.id),
                        "server_status": rel.verification_status,
                        "verified_by": str(rel.verified_by) if rel.verified_by else None,
                    },
                    status="PENDING_REVIEW",
                )
                db.add(conflict)
                await db.flush()
                from observability.metrics import telemetry
                telemetry.record_sync_conflict()
                return "CONFLICT", conflict

        elif cmd == "ADD_INVESTIGATOR_RELATIONSHIP":
            # Check if matching relationship already exists between source and target
            src = p.get("source_entity_id")
            tgt = p.get("target_entity_id")
            rtype = p.get("relationship_type", "ASSOCIATED_WITH")
            if src and tgt:
                q = select(Relationship).where(
                    Relationship.case_id == case.id,
                    Relationship.source_entity_id == uuid.UUID(str(src)),
                    Relationship.target_entity_id == uuid.UUID(str(tgt)),
                    Relationship.relationship_type == rtype,
                )
                existing = (await db.execute(q)).scalars().first()
                if existing:
                    # Invariant 13: Retrying mutation cannot duplicate relationship
                    return "ALREADY_CONVERGED", None
            return "REBASE", None

        elif cmd == "REVIEW_FINDING":
            f_id = p.get("finding_id")
            if not f_id:
                return "REJECTED", "Missing finding_id in payload"
            fnd = await db.get(InvestigationFinding, uuid.UUID(str(f_id)))
            if not fnd or fnd.case_id != case.id:
                return "REJECTED", "Target finding not found"
            desired_st = p.get("status")
            if fnd.status == "NEW" or fnd.status == desired_st:
                return "REBASE", None
            else:
                conflict = SyncConflictRecord(
                    id=uuid.uuid4(),
                    mutation_id=mutation.mutation_id,
                    device_id=mutation.device_id,
                    actor_id=actor.id,
                    case_id=case.id,
                    command_type=cmd,
                    client_payload=p,
                    base_state_version=mutation.base_state_version,
                    server_state_version=case.state_version or 1,
                    conflict_type="FINDING_REVIEW_CONFLICT",
                    server_current_state={"finding_id": str(fnd.id), "status": fnd.status},
                    status="PENDING_REVIEW",
                )
                db.add(conflict)
                await db.flush()
                from observability.metrics import telemetry
                telemetry.record_sync_conflict()
                return "CONFLICT", conflict

        elif cmd in ["CREATE_HYPOTHESIS", "ADD_INVESTIGATOR_NOTE"]:
            return "REBASE", None

        return "REJECTED", f"Unsupported offline command: {cmd}"

    @staticmethod
    async def resolve_sync_conflict(
        db: AsyncSession,
        case_id: str | uuid.UUID,
        conflict_id: str | uuid.UUID,
        request: ConflictResolutionRequest,
        actor: User,
    ) -> ConflictResolutionResponse:
        """
        Adjudicate an explicit sync conflict.
        Supports KEEP_SERVER, APPLY_OFFLINE, CREATE_NEW_REVIEW.
        Audits resolution and increments case version (Invariant 8).
        """
        c_uuid = conflict_id if isinstance(conflict_id, uuid.UUID) else uuid.UUID(str(conflict_id))
        conflict = await db.get(SyncConflictRecord, c_uuid)
        if not conflict or str(conflict.case_id) != str(case_id):
            raise HTTPException(status_code=404, detail="Conflict record not found")

        if conflict.status != "PENDING_REVIEW":
            raise HTTPException(status_code=400, detail=f"Conflict already resolved with status '{conflict.status}'")

        case = (
            await db.execute(select(Case).where(Case.id == conflict.case_id).with_for_update())
        ).scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        res_type = request.resolution.strip().upper()

        if res_type == "KEEP_SERVER":
            conflict.status = "RESOLVED_KEEP_SERVER"
            conflict.resolution_rationale = request.rationale
            conflict.resolved_by = actor.id
            conflict.resolved_at = datetime.now(timezone.utc)

            await InvestigationBrain.record_activity(
                db=db,
                case_id=case.id,
                activity_type="SYNC_CONFLICT_RESOLVED",
                actor=actor,
                target_type="sync_conflict",
                target_id=str(conflict.id),
                before_state={"status": "PENDING_REVIEW"},
                after_state={"status": conflict.status, "resolution": "KEEP_SERVER"},
                reason=request.rationale,
            )
            new_ver = await InvestigationBrain.bump_case_version(
                db=db, case=case, actor=actor, reason="Sync conflict resolved: kept server state"
            )
            await db.commit()

            return ConflictResolutionResponse(
                success=True,
                conflict_id=str(conflict.id),
                status=conflict.status,
                server_state_version=new_ver,
                message="Conflict resolved: Server state retained.",
            )

        elif res_type == "APPLY_OFFLINE":
            # Apply original offline command through gateway
            cmd_res = await dispatch_command(
                db=db,
                case_id=case.id,
                request=CommandRequest(
                    command=conflict.command_type,
                    payload=conflict.client_payload or {},
                    reason=f"Conflict resolution: applied offline decision ({request.rationale})",
                    client_mutation_id=conflict.mutation_id,
                    base_case_version=case.state_version,
                ),
                current_user=actor,
            )

            conflict.status = "RESOLVED_APPLY_OFFLINE"
            conflict.resolution_rationale = request.rationale
            conflict.resolved_by = actor.id
            conflict.resolved_at = datetime.now(timezone.utc)

            db.add(
                SyncProcessedMutation(
                    mutation_id=conflict.mutation_id,
                    device_id=conflict.device_id,
                    actor_id=actor.id,
                    case_id=case.id,
                    command_type=conflict.command_type,
                    base_state_version=conflict.base_state_version,
                    server_state_version=cmd_res.new_state_version,
                    outcome="APPLIED",
                    activity_id=uuid.UUID(cmd_res.activity_id) if cmd_res.activity_id else None,
                )
            )
            await db.commit()

            return ConflictResolutionResponse(
                success=True,
                conflict_id=str(conflict.id),
                status=conflict.status,
                server_state_version=cmd_res.new_state_version,
                message="Conflict resolved: Offline decision applied through gateway.",
            )

        elif res_type == "CREATE_NEW_REVIEW":
            # Discard conflict and reset target candidate/relationship to unreviewed
            if conflict.conflict_type == "IDENTITY_DECISION_CONFLICT":
                cand_id = (conflict.client_payload or {}).get("candidate_id")
                if cand_id:
                    cand = await db.get(IdentityCandidate, uuid.UUID(str(cand_id)))
                    if cand:
                        cand.resolution_status = "UNRESOLVED"
                        cand.resolved_at = None

            conflict.status = "DISCARDED"
            conflict.resolution_rationale = request.rationale
            conflict.resolved_by = actor.id
            conflict.resolved_at = datetime.now(timezone.utc)

            new_ver = await InvestigationBrain.bump_case_version(
                db=db, case=case, actor=actor, reason="Sync conflict reset for new review"
            )
            await db.commit()

            return ConflictResolutionResponse(
                success=True,
                conflict_id=str(conflict.id),
                status=conflict.status,
                server_state_version=new_ver,
                message="Conflict resolved: Item re-opened for new review.",
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown resolution '{request.resolution}'. Supported: KEEP_SERVER, APPLY_OFFLINE, CREATE_NEW_REVIEW",
            )

    @staticmethod
    async def _build_projection_delta(
        db: AsyncSession,
        case: Case,
        client_state_version: int,
    ) -> SyncProjectionDelta:
        """
        Build delta of items modified or created since client_state_version.
        """
        target_version = case.state_version or 1
        if client_state_version >= target_version:
            return SyncProjectionDelta(from_version=client_state_version, to_version=target_version)

        # Recent activities
        act_q = select(InvestigationActivity).where(
            InvestigationActivity.case_id == case.id,
        ).order_by(InvestigationActivity.created_at.desc()).limit(50)
        recent_acts = list((await db.execute(act_q)).scalars().all())

        # Relationships
        rel_q = select(Relationship).where(Relationship.case_id == case.id)
        rels = list((await db.execute(rel_q)).scalars().all())

        # Identity Candidates
        cand_q = select(IdentityCandidate).where(IdentityCandidate.case_id == case.id)
        cands = list((await db.execute(cand_q)).scalars().all())

        # Findings
        fnd_q = select(InvestigationFinding).where(InvestigationFinding.case_id == case.id)
        findings = list((await db.execute(fnd_q)).scalars().all())

        return SyncProjectionDelta(
            from_version=client_state_version,
            to_version=target_version,
            relationships=[
                {
                    "id": str(r.id),
                    "source_entity_id": str(r.source_entity_id),
                    "target_entity_id": str(r.target_entity_id),
                    "relationship_type": r.relationship_type,
                    "verification_status": r.verification_status,
                    "epistemic_status": r.epistemic_status,
                }
                for r in rels
            ],
            identity_candidates=[
                {
                    "id": str(c.id),
                    "canonical_entity_id": str(c.canonical_entity_id) if c.canonical_entity_id else None,
                    "candidate_value": c.candidate_value,
                    "candidate_type": c.candidate_type,
                    "resolution_status": c.resolution_status,
                }
                for c in cands
            ],
            findings=[
                {
                    "id": str(f.id),
                    "finding_type": f.finding_type,
                    "title": f.title,
                    "status": f.status,
                    "freshness_status": f.freshness_status,
                }
                for f in findings
            ],
            activities=[
                {
                    "id": str(a.id),
                    "activity_type": a.activity_type,
                    "target_id": str(a.target_id) if a.target_id else None,
                    "reason": a.reason,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in recent_acts
            ],
        )

    @staticmethod
    def _get_required_capability(command_type: str) -> Optional[str]:
        """Map command to required policy capability."""
        cmd = command_type.strip().upper()
        mapping = {
            "CONFIRM_RELATIONSHIP": CAP_RELATIONSHIP_CONFIRM,
            "REJECT_RELATIONSHIP": CAP_RELATIONSHIP_REJECT,
            "ADD_INVESTIGATOR_RELATIONSHIP": CAP_RELATIONSHIP_WRITE,
            "RESOLVE_IDENTITY_CANDIDATE": CAP_ENTITY_WRITE,
            "REVIEW_FINDING": CAP_FINDING_REVIEW,
            "CREATE_HYPOTHESIS": CAP_HYPOTHESIS_WRITE,
            "ADD_INVESTIGATOR_NOTE": CAP_CASE_WRITE,
        }
        return mapping.get(cmd)
