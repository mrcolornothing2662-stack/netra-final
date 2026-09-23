from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 10
Definitive End-to-End Investigation Acceptance Test
Executes the full canonical investigation lifecycle in ONE unified integration flow:

LOGIN
  ↓
SESSION + DEVICE TRUST
  ↓
OPEN CASE
  ↓
INGEST EVIDENCE
  ↓
PARSE / EXTRACT
  ↓
ENTITIES
  ↓
EVENTS
  ↓
RELATIONSHIPS
  ↓
IDENTITY CANDIDATE
  ↓
FINDING
  ↓
RELATIONSHIP REVIEW
  ↓
ENTITY RESOLUTION
  ↓
TIMELINE
  ↓
REPLAY
  ↓
FORENSIC LENSES
  ↓
COMMAND CENTER
  ↓
OFFLINE MUTATION
  ↓
SYNC
  ↓
CONFLICT
  ↓
CONFLICT RESOLUTION
  ↓
REPORT
  ↓
FOUR-EYES APPROVAL
  ↓
EXPORT
  ↓
AUDIT VERIFICATION
"""

import hashlib
import io
import pathlib
import uuid
from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationFinding,
    Relationship,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
import graph.relationship_types as RT
from main import app
from routes.auth import _create_access_token, _hash_password
from security.audit_verifier import AuditVerifier


@pytest.mark.asyncio
async def test_netra_canonical_investigation_e2e():
    run_id = uuid.uuid4().hex[:8]
    dev_io = f"DEV-FIELD-IO-{run_id[:4]}"
    dev_dsp = f"DEV-HQ-DSP-{run_id[:4]}"

    async with AsyncSessionLocal() as db:
        # ── 1. Setup Users ────────────────────────────────────────────────────
        io_user = User(
            id=uuid.uuid4(),
            username=f"io_full_{run_id}",
            email=f"io_full_{run_id}@police.gov.in",
            hashed_password=_hash_password("Secr3tP@ssword123!"),
            full_name="Inspector Vikramaditya",
            rank="Inspector",
            unit="Special Cyber Taskforce",
            role="INVESTIGATOR",
            is_active=True,
        )
        dsp_user = User(
            id=uuid.uuid4(),
            username=f"dsp_full_{run_id}",
            email=f"dsp_full_{run_id}@police.gov.in",
            hashed_password=_hash_password("Secr3tP@ssword123!"),
            full_name="DSP Meenakshi Sundaram",
            rank="DSP",
            unit="Supervisory Command",
            role="MANAGER",
            is_active=True,
        )
        db.add_all([io_user, dsp_user])
        await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # ── Step 1: LOGIN ─────────────────────────────────────────────────
            login_resp = await client.post(
                "/api/v1/auth/login",
                data={"username": io_user.username, "password": "Secr3tP@ssword123!"},
                headers={"X-Device-ID": dev_io},
            )
            assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
            token_data = login_resp.json()
            io_jwt = token_data["access_token"]
            headers_io = {
                "Authorization": f"Bearer {io_jwt}",
                "X-Device-ID": dev_io,
            }

            # Also authenticate DSP supervisor
            login_dsp = await client.post(
                "/api/v1/auth/login",
                data={"username": dsp_user.username, "password": "Secr3tP@ssword123!"},
                headers={"X-Device-ID": dev_dsp},
            )
            assert login_dsp.status_code == 200
            dsp_jwt = login_dsp.json()["access_token"]
            headers_dsp = {
                "Authorization": f"Bearer {dsp_jwt}",
                "X-Device-ID": dev_dsp,
            }

            # ── Step 2: SESSION + DEVICE TRUST ────────────────────────────────
            sess_resp = await client.get("/api/v1/auth/sessions", headers=headers_io)
            assert sess_resp.status_code == 200
            sessions = sess_resp.json()
            assert any(s["device_id"] == dev_io and not s["revoked"] for s in sessions)

            # ── Step 3: OPEN CASE ─────────────────────────────────────────────
            case_resp = await client.post(
                "/api/v1/cases",
                json={
                    "case_number": f"FIR-E2E-{run_id.upper()}",
                    "title": "Operation Thunder Shield — Canonical E2E Investigation",
                    "crime_type": "Syndicate Narcotics",
                    "priority": "high",
                    "police_station": "Cyber Crime PS Cyberabad",
                },
                headers=headers_io,
            )
            assert case_resp.status_code == 201, case_resp.text
            case_data = case_resp.json()
            case_id = case_data["id"]
            assert case_data["state_version"] == 1

            # Add supervisor as collaborator so they have dual-auth review access
            collab = CaseCollaborator(
                case_id=uuid.UUID(case_id),
                user_id=dsp_user.id,
                role="supervisor",
            )
            db.add(collab)
            await db.commit()

            # ── Step 4 & 5: INGEST EVIDENCE & PARSE/EXTRACT ────────────────────
            evidence_bytes = b"2026-09-22 14:30:00,+919876543210,+918765432109,CALL,420,TOWER_DELHI_04\n"
            evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()

            ev_upload = await client.post(
                "/api/v1/evidence/upload",
                files=[("files", ("cdr_dump_day1.csv", io.BytesIO(evidence_bytes), "text/csv"))],
                data={"case_id": case_id, "source_type": "cdr"},
                headers=headers_io,
            )
            assert ev_upload.status_code == 200, ev_upload.text
            ev_data = ev_upload.json()
            assert ev_data["uploaded"] >= 1
            ev_id = ev_data["files"][0]["id"]

            # Seed authoritative extracted entities, events, relationships into case
            e_phone1 = Entity(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                canonical_value="+919876543210",
                entity_type="phone",
            )
            e_phone2 = Entity(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                canonical_value="+918765432109",
                entity_type="phone",
            )
            e_person1 = Entity(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                canonical_value="Vikramaditya Rao",
                entity_type="person",
            )
            e_person2 = Entity(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                canonical_value="Aman Deep Mule",
                entity_type="person",
            )
            db.add_all([e_phone1, e_phone2, e_person1, e_person2])
            await db.flush()

            # ── Step 6: EVENTS & RELATIONSHIPS ────────────────────────────────
            event_call = EvidenceEvent(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                evidence_file_id=uuid.UUID(ev_id),
                event_type="call",
                event_timestamp=datetime.now(timezone.utc),
                text_content="Cell tower call from +919876543210 to +918765432109 duration 420s",
                source_page=1,
                source_line=1,
            )
            db.add(event_call)

            rel_observed = Relationship(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                source_entity_id=e_phone1.id,
                target_entity_id=e_phone2.id,
                relationship_type=RT.COMMUNICATED_WITH,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                confidence=0.98,
                verified_by=io_user.id,
                evidence_refs=[str(ev_id)],
            )
            rel_candidate = Relationship(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                source_entity_id=e_person1.id,
                target_entity_id=e_phone1.id,
                relationship_type=RT.USES,
                epistemic_status=RT.INFERRED,
                verification_status=RT.REVIEW_UNREVIEWED,
                confidence=0.82,
                evidence_refs=[str(ev_id)],
            )
            db.add_all([rel_observed, rel_candidate])

            # ── Step 7: IDENTITY CANDIDATE ────────────────────────────────────
            ident_cand = IdentityCandidate(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                canonical_entity_id=e_person1.id,
                candidate_value="V. Rao",
                candidate_type="person",
                resolution_status="UNRESOLVED",
                source_refs=[str(ev_id)],
                supporting_refs=["CDR registered name"],
            )
            db.add(ident_cand)

            # ── Step 8: FINDING ───────────────────────────────────────────────
            finding = InvestigationFinding(
                id=uuid.uuid4(),
                case_id=uuid.UUID(case_id),
                fingerprint=f"fp_e2e_{run_id}",
                finding_type="communication_frequency",
                title="Sustained Cryptic Coordination",
                description="Long duration nocturnal calls between suspect phones.",
                severity="HIGH",
                status="OPEN",
                confidence=0.91,
                source_engine="neural_correlation",
                entity_refs=[str(e_person1.id), str(e_person2.id)],
                evidence_refs=[str(ev_id)],
            )
            db.add(finding)
            await db.commit()

            # Verify entities endpoint returns all entities (both auto-extracted and seeded)
            ent_resp = await client.get(f"/api/v1/cases/{case_id}/entities", headers=headers_io)
            assert ent_resp.status_code == 200
            assert len(ent_resp.json()["entities"]) >= 4

            # ── Step 9: RELATIONSHIP REVIEW ───────────────────────────────────
            rel_review_resp = await client.post(
                f"/api/v1/cases/{case_id}/commands",
                json={
                    "command": "CONFIRM_RELATIONSHIP",
                    "payload": {"relationship_id": str(rel_candidate.id)},
                    "reason": "Subscriber form verified suspect's signature",
                },
                headers=headers_io,
            )
            assert rel_review_resp.status_code == 200, rel_review_resp.text
            assert rel_review_resp.json()["new_state_version"] == 2

            # ── Step 10: ENTITY RESOLUTION ────────────────────────────────────
            ident_resolve_resp = await client.post(
                f"/api/v1/cases/{case_id}/commands",
                json={
                    "command": "RESOLVE_IDENTITY_CANDIDATE",
                    "payload": {
                        "candidate_id": str(ident_cand.id),
                        "resolution_status": "CONFIRMED_SAME",
                    },
                    "reason": "Fingerprint match on seized device confirmed V. Rao is Vikramaditya Rao",
                },
                headers=headers_io,
            )
            assert ident_resolve_resp.status_code == 200, ident_resolve_resp.text
            assert ident_resolve_resp.json()["new_state_version"] == 3

            # ── Step 11: TIMELINE ─────────────────────────────────────────────
            timeline_resp = await client.get(f"/api/v1/cases/{case_id}/timeline", headers=headers_io)
            assert timeline_resp.status_code == 200
            tl_data = timeline_resp.json()
            assert tl_data["total"] >= 1
            assert len(tl_data["items"]) >= 1

            # ── Step 12: REPLAY (TIME-TRAVEL) ─────────────────────────────────
            replay_v1 = await client.get(f"/api/v1/cases/{case_id}/replay/1", headers=headers_io)
            assert replay_v1.status_code == 200
            replay_v3 = await client.get(f"/api/v1/cases/{case_id}/replay/3", headers=headers_io)
            assert replay_v3.status_code == 200
            assert replay_v1.json()["state_version"] == 1
            assert replay_v3.json()["state_version"] == 3

            # ── Step 13: FORENSIC LENSES ──────────────────────────────────────
            comms_lens = await client.get(f"/api/v1/cases/{case_id}/lenses/communications", headers=headers_io)
            assert comms_lens.status_code == 200
            money_lens = await client.get(f"/api/v1/cases/{case_id}/lenses/money", headers=headers_io)
            assert money_lens.status_code == 200
            geo_lens = await client.get(f"/api/v1/cases/{case_id}/lenses/geographic", headers=headers_io)
            assert geo_lens.status_code == 200

            # ── Step 14: COMMAND CENTER ───────────────────────────────────────
            cmd_center = await client.get(f"/api/v1/cases/{case_id}/command-center", headers=headers_io)
            assert cmd_center.status_code == 200
            cc_data = cmd_center.json()
            assert cc_data["state_version"] == 3
            assert cc_data["investigation_health"]["entities_count"] >= 4

            # ── Step 15: OFFLINE BUNDLE ───────────────────────────────────────
            bundle_resp = await client.get(f"/api/v1/cases/{case_id}/offline-bundle", headers=headers_io)
            assert bundle_resp.status_code == 200
            bundle_data = bundle_resp.json()
            assert bundle_data["server_state_version"] == 3

            # ── Step 16: OFFLINE MUTATION & SYNC ──────────────────────────────
            mutation_id_1 = str(uuid.uuid4())
            sync_resp = await client.post(
                f"/api/v1/cases/{case_id}/sync",
                json={
                    "device_id": dev_io,
                    "client_state_version": 3,
                    "mutations": [
                        {
                            "mutation_id": mutation_id_1,
                            "device_id": dev_io,
                            "actor_id": str(io_user.id),
                            "case_id": case_id,
                            "client_created_at": datetime.now(timezone.utc).isoformat(),
                            "command_type": "CREATE_HYPOTHESIS",
                            "payload": {
                                "title": "Suspect Relocation Hypothesis",
                                "description": "Target is planning to move operations out of state.",
                            },
                            "base_state_version": 3,
                        }
                    ],
                },
                headers=headers_io,
            )
            assert sync_resp.status_code == 200, sync_resp.text
            sync_res_data = sync_resp.json()
            assert len(sync_res_data["accepted"]) == 1
            assert sync_res_data["server_state_version"] == 4

            # ── Step 17: CONFLICT GENERATION ──────────────────────────────────
            # Second mutation submits a conflicting review on a relationship with a stale version
            mutation_id_2 = str(uuid.uuid4())
            conflict_sync_resp = await client.post(
                f"/api/v1/cases/{case_id}/sync",
                json={
                    "device_id": dev_io,
                    "client_state_version": 1,
                    "mutations": [
                        {
                            "mutation_id": mutation_id_2,
                            "device_id": dev_io,
                            "actor_id": str(io_user.id),
                            "case_id": case_id,
                            "client_created_at": datetime.now(timezone.utc).isoformat(),
                            "command_type": "REJECT_RELATIONSHIP",
                            "payload": {"relationship_id": str(rel_candidate.id)},
                            "base_state_version": 1,
                        }
                    ],
                },
                headers=headers_io,
            )
            assert conflict_sync_resp.status_code == 200
            conf_sync_data = conflict_sync_resp.json()
            assert len(conf_sync_data["conflicts"]) == 1

            # ── Step 18: CONFLICT RESOLUTION ──────────────────────────────────
            conflicts_list = await client.get(f"/api/v1/cases/{case_id}/conflicts", headers=headers_io)
            assert conflicts_list.status_code == 200
            pending_confs = conflicts_list.json()
            assert len(pending_confs) >= 1
            target_conflict = pending_confs[0]

            resolve_conf_resp = await client.post(
                f"/api/v1/cases/{case_id}/conflicts/{target_conflict['conflict_id']}/resolve",
                json={
                    "resolution": "APPLY_OFFLINE",
                    "rationale": "Field intel supercedes prior record",
                },
                headers=headers_io,
            )
            assert resolve_conf_resp.status_code == 200
            assert "RESOLVED" in resolve_conf_resp.json()["status"]
            assert resolve_conf_resp.json()["success"] is True

            # ── Step 19: REPORT GENERATION ────────────────────────────────────
            gen_rep_resp = await client.post(
                f"/api/v1/cases/{case_id}/reports/generate",
                json={
                    "report_type": "formal_dossier",
                    "title": "Comprehensive E2E Court Dossier",
                },
                headers=headers_io,
            )
            assert gen_rep_resp.status_code == 201, gen_rep_resp.text
            snapshot_id = gen_rep_resp.json()["metadata"]["report_id"]

            submit_rep = await client.post(
                f"/api/v1/cases/{case_id}/reports/snapshots/{snapshot_id}/submit-review",
                headers=headers_io,
            )
            assert submit_rep.status_code == 200
            assert submit_rep.json()["new_status"] == "REVIEW"

            # ── Step 20: FOUR-EYES APPROVAL ───────────────────────────────────
            # Investigator cannot approve their own report
            self_appr = await client.post(
                f"/api/v1/cases/{case_id}/reports/snapshots/{snapshot_id}/review",
                json={"action": "APPROVE"},
                headers=headers_io,
            )
            assert self_appr.status_code == 403
            assert "Four-Eyes" in self_appr.json()["detail"]

            # DSP Supervisor reviews and approves
            dsp_appr = await client.post(
                f"/api/v1/cases/{case_id}/reports/snapshots/{snapshot_id}/review",
                json={"action": "APPROVE"},
                headers=headers_dsp,
            )
            assert dsp_appr.status_code == 200
            assert dsp_appr.json()["new_status"] == "APPROVED"

            # ── Step 21: EXPORT ───────────────────────────────────────────────
            export_resp = await client.post(
                f"/api/v1/cases/{case_id}/reports/snapshots/{snapshot_id}/export?export_format=markdown",
                headers=headers_dsp,
            )
            assert export_resp.status_code == 200
            assert "# Comprehensive E2E Court Dossier" in export_resp.text or "Formal Investigation Dossier" in export_resp.text

            # ── Step 22: AUDIT VERIFICATION ───────────────────────────────────
            audit_report = await AuditVerifier.verify_ledger(db, case_id=case_id)
            assert audit_report["intact"] is True, f"Audit chain broken: {audit_report}"
            assert audit_report["status"] == "VERIFIED"
            assert audit_report["global_entry_count"] > 0
            assert audit_report["case_entry_count"] > 0
