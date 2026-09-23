from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Canonical SIH Investigation Case Seeder
Seeds ONE presentation-ready, internally-consistent cyber investigation:
  Case Number: FIR-2026-DL-CYBER-0089
  Title:       Operation Shadow Mule — Inter-State Cyber Syndicate

Exercises the complete SIH presentation narrative:
  Evidence (CDR, UPI, ATM) 
    → Inferred unreviewed links surfaced 
    → Investigator opens entity in Entity Explorer
    → Identity conflict explained ("Glass Sparrow" candidate)
    → Relationship confirmed in Review Queue
    → Timeline updates & historical replay scrubbed (v1 → v2 → v3)
    → Forensic lenses reveal cross-domain patterns (SIM burst, layering, impossible velocity)
    → Formal dossier snapshot reviewed under Four-Eyes dual control
    → Certified export with cryptographic hash verification
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete

from config import settings
from db.models import (
    Base,
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    IdentityCandidate,
    InvestigationActivity,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    ReportSnapshot,
    User,
)
from db.session import AsyncSessionLocal, engine
from graph import relationship_types as RT
from routes.auth import _hash_password
from security.audit_verifier import AuditVerifier
from utils.audit import append_audit


import os
from pathlib import Path
import secrets

DEMO_CASE_NUMBER = "FIR-2026-DL-CYBER-0089"
DEMO_TITLE = "Operation Shadow Mule — Inter-State Cyber Syndicate"
CREDENTIALS_FILE = Path(__file__).resolve().parent.parent / ".demo_credentials.json"


def get_or_rotate_demo_credentials(rotate: bool = True) -> dict[str, str]:
    """
    Retrieves or generates fresh, high-entropy demo credentials.
    Priority:
      1. Environment variables (NETRA_DEMO_*)
      2. Existing .demo_credentials.json (if rotate is False)
      3. Secure random generation saved to git-ignored .demo_credentials.json
    """
    creds = {}
    if not rotate and CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, "r") as f:
                creds = json.load(f)
        except Exception:
            creds = {}

    env_admin = os.environ.get("NETRA_DEMO_ADMIN_PASSWORD")
    env_io = os.environ.get("NETRA_DEMO_IO_PASSWORD")
    env_dsp = os.environ.get("NETRA_DEMO_SUPERVISOR_PASSWORD")

    token = secrets.token_hex(4).upper()
    admin_pwd = env_admin or creds.get("admin") or f"Admin@Netra-{token}"
    io_pwd = env_io or creds.get("investigator_delhi") or f"Insp@Netra-{token}"
    dsp_pwd = env_dsp or creds.get("dsp_sharma") or f"DSP@Netra-{token}"

    final_creds = {
        "admin": admin_pwd,
        "investigator_delhi": io_pwd,
        "dsp_sharma": dsp_pwd,
        "rotated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(final_creds, f, indent=2)
        os.chmod(CREDENTIALS_FILE, 0o600)
    except Exception as e:
        print(f"Warning: Could not persist .demo_credentials.json: {e}")

    return final_creds


_TRANSFER_CSV = (
    "transaction_id,timestamp_ist,debit_account,credit_account,amount_inr,upi_id,channel,status,description,reference\n"
    "TX0001,2026-08-18 09:50:03,ACCT-VICTIM-01,ACCT-MULE-11,285000,glasssparrow11@upi,UPI,SETTLED,KYC verification debit,UPI-0001\n"
    "TX0002,2026-08-18 09:50:41,ACCT-MULE-11,ACCT-MULE-12,180000,glasssparrow12@upi,IMPS,SETTLED,rapid onward transfer,IMPS-0002\n"
    "TX0003,2026-08-18 09:51:02,ACCT-MULE-11,ACCT-MULE-13,95000,glasssparrow13@upi,IMPS,SETTLED,rapid onward transfer,IMPS-0003\n"
    "TX0004,2026-08-18 09:52:10,ACCT-MULE-12,ACCT-MULE-14,120000,glasssparrow14@upi,UPI,SETTLED,layering,UPI-0004\n"
    "TX0005,2026-08-18 09:53:44,ACCT-MULE-13,ACCT-MULE-14,70000,glasssparrow14@upi,UPI,SETTLED,layering,UPI-0005\n"
    "TX0006,2026-08-18 09:56:21,ACCT-MULE-14,ATM-CASH-01,90000,CASH,ATM,SETTLED,cash withdrawal,ATM-0006\n"
    "TX0007,2026-08-18 10:02:14,ACCT-MULE-12,ACCT-SHELL-01,30000,shell01@upi,UPI,SETTLED,layering,UPI-0007\n"
    "TX0008,2026-08-18 10:07:31,ACCT-SHELL-01,ACCT-SHELL-02,29000,shell02@upi,IMPS,SETTLED,layering,IMPS-0008\n"
    "TX0009,2026-08-18 10:09:18,ACCT-SHELL-02,ATM-CASH-02,28000,CASH,ATM,SETTLED,cash withdrawal,ATM-0009\n"
)

_LEDGER_CSV = (
    "date,narration,credit,debit,balance,ref_no\n"
    "2026-08-18,IMPS/P2A/998877/TRANSFER,180000,,185000,IMPS998877\n"
    "2026-08-18,UPI/CR/glasssparrow14@upi/DEPOSIT,120000,,305000,UPI223344\n"
    "2026-08-18,ATM WDL/MUMBAI/CASH,,90000,215000,ATM556677\n"
)

_CDR_CSV = (
    "record_id,subscriber,device_id,cell_tower,event_time_utc,event_type,latitude,longitude,source_note\n"
    "CDR-001,+91-9000000101,DEV-A1,DEL-IGI-04,2026-08-18T03:58:02Z,ATTACHED,28.5561,77.1008,carrier_feed\n"
    "CDR-002,+91-9000000101,DEV-A1,DEL-CNT-11,2026-08-18T04:07:14Z,ATTACHED,28.6315,77.2167,carrier_feed\n"
    "CDR-003,+91-9000000101,DEV-A1,DEL-NOI-02,2026-08-18T04:21:09Z,ATTACHED,28.5355,77.3910,carrier_feed\n"
    "CDR-004,+91-9000000101,DEV-A1,DEL-CNT-11,2026-08-18T04:23:55Z,ATTACHED,28.6315,77.2167,carrier_feed\n"
    "CDR-005,+91-9000000101,DEV-A1,CYB-HYD-03,2026-08-18T04:24:04Z,ATTACHED,17.3850,78.4867,carrier_feed\n"
    "CDR-006,+91-9000000101,DEV-A1,CYB-HYD-03,2026-08-18T04:25:21Z,SMS,17.3850,78.4867,carrier_feed\n"
    "CDR-007,+91-9000000101,DEV-A1,DEL-NOI-02,2026-08-18T04:28:11Z,ATTACHED,28.5355,77.3910,carrier_feed\n"
    "CDR-008,+91-9000000101,DEV-A1,DEL-IGI-04,2026-08-18T04:30:00Z,DETACHED,28.5561,77.1008,carrier_feed\n"
)


async def seed_sih_demo_investigation() -> str:
    """
    Idempotent seeder that sets up the complete SIH showcase investigation.
    Returns the case_id UUID string.
    """
    async with AsyncSessionLocal() as db:
        # ── 1. Seed or Retrieve Standard Demo Users (With Credential Rotation) ──
        creds = get_or_rotate_demo_credentials(rotate=True)

        async def _get_or_create_user(username: str, email: str, role: str, rank: str, full_name: str, pwd: str) -> User:
            q = select(User).where(User.username == username)
            u = (await db.execute(q)).scalar_one_or_none()
            if not u:
                u = User(
                    id=uuid.uuid4(),
                    username=username,
                    email=email,
                    hashed_password=_hash_password(pwd),
                    role=role,
                    rank=rank,
                    full_name=full_name,
                    unit="Cyber Crime Special Cell",
                    is_active=True,
                )
                db.add(u)
                await db.flush()
            else:
                # Rotate credential to fresh hash
                u.hashed_password = _hash_password(pwd)
                await db.flush()
            return u

        admin_user = await _get_or_create_user(
            username="admin",
            email="admin@cyberdrishti.gov.in",
            role="ADMIN",
            rank="Chief Administrator",
            full_name="Netra System Administrator",
            pwd=creds["admin"],
        )
        io_user = await _get_or_create_user(
            username="investigator_delhi",
            email="investigator.delhi@police.gov.in",
            role="INVESTIGATOR",
            rank="Inspector",
            full_name="Inspector Rajesh Kumar",
            pwd=creds["investigator_delhi"],
        )
        dsp_user = await _get_or_create_user(
            username="dsp_sharma",
            email="dsp.sharma@police.gov.in",
            role="MANAGER",
            rank="DSP",
            full_name="DSP Vikram Sharma",
            pwd=creds["dsp_sharma"],
        )

        # ── 2. Clean Prior Demo Case if Exists ──────────────────────────────────
        existing_case = (
            await db.execute(select(Case).where(Case.case_number == DEMO_CASE_NUMBER))
        ).scalar_one_or_none()
        if existing_case:
            case_id = existing_case.id
            # Clean up cascade
            await db.execute(delete(InvestigationActivity).where(InvestigationActivity.case_id == case_id))
            await db.execute(delete(InvestigationState).where(InvestigationState.case_id == case_id))
            await db.execute(delete(InvestigationFinding).where(InvestigationFinding.case_id == case_id))
            await db.execute(delete(IdentityCandidate).where(IdentityCandidate.case_id == case_id))
            await db.execute(delete(Relationship).where(Relationship.case_id == case_id))
            await db.execute(delete(EvidenceEvent).where(EvidenceEvent.case_id == case_id))
            await db.execute(delete(EvidenceFile).where(EvidenceFile.case_id == case_id))
            await db.execute(delete(Entity).where(Entity.case_id == case_id))
            await db.execute(delete(ReportSnapshot).where(ReportSnapshot.case_id == case_id))
            await db.execute(delete(CaseCollaborator).where(CaseCollaborator.case_id == case_id))
            await db.delete(existing_case)
            await db.commit()

        # ── 3. Create Case & Collaborators ──────────────────────────────────────
        case = Case(
            id=uuid.uuid4(),
            case_number=DEMO_CASE_NUMBER,
            title=DEMO_TITLE,
            crime_type="Financial Fraud & Cyber Syndicate",
            police_station="Special Cell, New Delhi",
            description=(
                "Synthetic Demonstration Dataset. An organized inter-state money mule network operating across "
                "Delhi, Cyberabad, and Mumbai. Attackers execute fake KYC UPI draining of victim accounts, "
                "immediately layer stolen funds across four mule tiers, and withdraw cash via compromised ATMs "
                "within 20 minutes. Burner device SIM swaps demonstrate physically impossible spatial velocity."
            ),
            priority="high",
            status="open",
            assigned_officer_id=io_user.id,
            state_version=3,
        )
        db.add(case)
        await db.flush()

        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=io_user.id, role="lead"))
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=dsp_user.id, role="lead"))
        db.add(CaseCollaborator(id=uuid.uuid4(), case_id=case.id, user_id=admin_user.id, role="lead"))

        # ── 4. Seed Evidence Files ──────────────────────────────────────────────
        f_trans = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="transfers_upi_layering.csv",
            original_name="transfers_upi_layering.csv",
            file_type="bank_statement",
            file_size_bytes=len(_TRANSFER_CSV),
            sha256_hash=hashlib.sha256(_TRANSFER_CSV.encode()).hexdigest(),
            storage_path="/uploads/transfers_upi_layering.csv",
            upload_status="processed",
            uploaded_by=io_user.id,
        )
        f_ledg = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="mule_ledger_statements.csv",
            original_name="mule_ledger_statements.csv",
            file_type="bank_statement",
            file_size_bytes=len(_LEDGER_CSV),
            sha256_hash=hashlib.sha256(_LEDGER_CSV.encode()).hexdigest(),
            storage_path="/uploads/mule_ledger_statements.csv",
            upload_status="processed",
            uploaded_by=io_user.id,
        )
        f_cdr = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename="suspect_cdr_geolocations.csv",
            original_name="suspect_cdr_geolocations.csv",
            file_type="telecom_cdr",
            file_size_bytes=len(_CDR_CSV),
            sha256_hash=hashlib.sha256(_CDR_CSV.encode()).hexdigest(),
            storage_path="/uploads/suspect_cdr_geolocations.csv",
            upload_status="processed",
            uploaded_by=io_user.id,
        )
        db.add_all([f_trans, f_ledg, f_cdr])
        await db.flush()

        # ── 5. Seed Core Entities ───────────────────────────────────────────────
        ent_suspect = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="Vikram Malhotra",
            entity_type="suspect",
            node_metadata={"aliases": ["Glass Sparrow", "Sparrow-11"], "risk_level": "CRITICAL", "primary_role": "Syndicate Kingpin"},
        )
        ent_phone_burner = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9000000101",
            entity_type="phone",
            node_metadata={"carrier": "Airtel", "status": "FLAGGED", "subscriber": "Vikram Malhotra"},
        )
        ent_phone_coord = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="+91-9811122334",
            entity_type="phone",
            node_metadata={"carrier": "Jio", "status": "ASSOCIATE", "region": "Delhi NCR"},
        )
        ent_mule_11 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACCT-MULE-11",
            entity_type="bank_account",
            node_metadata={"bank": "State Bank of India", "branch": "Connaught Place", "holder": "Ramesh Kumar (Nominee)"},
        )
        ent_mule_12 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACCT-MULE-12",
            entity_type="bank_account",
            node_metadata={"bank": "HDFC Bank", "holder": "Suresh Verma"},
        )
        ent_mule_13 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACCT-MULE-13",
            entity_type="bank_account",
            node_metadata={"bank": "ICICI Bank", "holder": "Dinesh Pal"},
        )
        ent_mule_14 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACCT-MULE-14",
            entity_type="bank_account",
            node_metadata={"bank": "Axis Bank", "holder": "Pooja Sharma"},
        )
        ent_shell_01 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ACCT-SHELL-01",
            entity_type="bank_account",
            node_metadata={"bank": "Kotak Mahindra", "holder": "Sparrow Logistics Pvt Ltd"},
        )
        ent_upi_11 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="glasssparrow11@upi",
            entity_type="upi_id",
            node_metadata={"vpa": "glasssparrow11@upi", "flag": "FRAUD_LINKED"},
        )
        ent_atm_01 = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="ATM-CASH-01",
            entity_type="location",
            node_metadata={"type": "ATM Terminal", "location": "Andheri West, Mumbai", "terminal_id": "ATM-556677"},
        )
        ent_tower_delhi = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="DEL-IGI-04",
            entity_type="cell_tower",
            node_metadata={"lat": 28.5561, "lon": 77.1008, "region": "Delhi IGI Airport"},
        )
        ent_tower_hyd = Entity(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_value="CYB-HYD-03",
            entity_type="cell_tower",
            node_metadata={"lat": 17.3850, "lon": 78.4867, "region": "Cyberabad HITEC City"},
        )

        all_entities = [
            ent_suspect, ent_phone_burner, ent_phone_coord,
            ent_mule_11, ent_mule_12, ent_mule_13, ent_mule_14, ent_shell_01,
            ent_upi_11, ent_atm_01, ent_tower_delhi, ent_tower_hyd,
        ]
        db.add_all(all_entities)
        await db.flush()

        # ── 6. Seed Chronological Events ────────────────────────────────────────
        base_time = datetime(2026, 8, 18, 9, 50, 0, tzinfo=timezone.utc)
        ev_events = [
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_trans.id,
                event_type="financial_transaction",
                event_timestamp=base_time + timedelta(seconds=3),
                text_content="Victim KYC spoof drain: ₹2,85,000 transferred to ACCT-MULE-11 via UPI glasssparrow11@upi",
                event_metadata={"amount": 285000, "tx_id": "TX0001", "channel": "UPI"},
            ),
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_trans.id,
                event_type="financial_transaction",
                event_timestamp=base_time + timedelta(seconds=41),
                text_content="Layering fan-out: ₹1,80,000 onward IMPS transfer from ACCT-MULE-11 to ACCT-MULE-12",
                event_metadata={"amount": 180000, "tx_id": "TX0002", "channel": "IMPS"},
            ),
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_trans.id,
                event_type="financial_transaction",
                event_timestamp=base_time + timedelta(seconds=62),
                text_content="Layering fan-out: ₹95,000 onward IMPS transfer from ACCT-MULE-11 to ACCT-MULE-13",
                event_metadata={"amount": 95000, "tx_id": "TX0003", "channel": "IMPS"},
            ),
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_trans.id,
                event_type="financial_transaction",
                event_timestamp=base_time + timedelta(seconds=381),
                text_content="Cashout exit: ₹90,000 physical ATM withdrawal from ACCT-MULE-14 at ATM-CASH-01 Mumbai",
                event_metadata={"amount": 90000, "tx_id": "TX0006", "channel": "ATM"},
            ),
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_cdr.id,
                event_type="carrier_attachment",
                event_timestamp=base_time - timedelta(minutes=5),
                text_content="Cell tower attachment: +91-9000000101 locked to DEL-IGI-04 (Delhi IGI Airport)",
                event_metadata={"cell_tower": "DEL-IGI-04", "lat": 28.5561, "lon": 77.1008},
            ),
            EvidenceEvent(
                id=uuid.uuid4(),
                case_id=case.id,
                evidence_file_id=f_cdr.id,
                event_type="carrier_attachment",
                event_timestamp=base_time - timedelta(minutes=1),
                text_content="Impossible Travel Anomaly: +91-9000000101 attached to CYB-HYD-03 (Hyderabad) 9 seconds after Delhi",
                event_metadata={"cell_tower": "CYB-HYD-03", "lat": 17.3850, "lon": 78.4867},
            ),
        ]
        db.add_all(ev_events)
        await db.flush()

        # ── 7. Seed Relationships (Verified + Unreviewed for Review Queue) ──────
        rels = [
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_suspect.id,
                target_entity_id=ent_phone_burner.id,
                relationship_type=RT.USES,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                is_canonical=True,
                confidence=0.98,
                evidence_refs=[str(f_cdr.id)],
            ),
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_phone_burner.id,
                target_entity_id=ent_upi_11.id,
                relationship_type=RT.OWNS,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                is_canonical=True,
                confidence=0.95,
                evidence_refs=[str(f_trans.id)],
            ),
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_mule_11.id,
                target_entity_id=ent_mule_12.id,
                relationship_type=RT.TRANSFERRED_TO,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                is_canonical=True,
                confidence=1.0,
                amount=180000.0,
                evidence_refs=[str(f_trans.id)],
            ),
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_mule_11.id,
                target_entity_id=ent_mule_13.id,
                relationship_type=RT.TRANSFERRED_TO,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                is_canonical=True,
                confidence=1.0,
                amount=95000.0,
                evidence_refs=[str(f_trans.id)],
            ),
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_mule_14.id,
                target_entity_id=ent_atm_01.id,
                relationship_type=RT.TRANSFERRED_TO,
                epistemic_status=RT.OBSERVED,
                verification_status=RT.REVIEW_ACCEPTED,
                is_canonical=True,
                confidence=1.0,
                amount=90000.0,
                evidence_refs=[str(f_trans.id), str(f_ledg.id)],
            ),
            # ── 2 UNREVIEWED RELATIONSHIPS (Ready for SIH Review Queue Demonstration) ──
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_phone_burner.id,
                target_entity_id=ent_phone_coord.id,
                relationship_type=RT.COMMUNICATED_WITH,
                epistemic_status=RT.INFERRED,
                verification_status=RT.REVIEW_UNREVIEWED,
                is_canonical=False,
                confidence=0.88,
                evidence_refs=[str(f_cdr.id)],
            ),
            Relationship(
                id=uuid.uuid4(),
                case_id=case.id,
                source_entity_id=ent_mule_12.id,
                target_entity_id=ent_shell_01.id,
                relationship_type=RT.TRANSFERRED_TO,
                epistemic_status=RT.INFERRED,
                verification_status=RT.REVIEW_UNREVIEWED,
                is_canonical=False,
                confidence=0.82,
                amount=30000.0,
                evidence_refs=[str(f_trans.id)],
            ),
        ]
        db.add_all(rels)
        await db.flush()

        # ── 8. Seed Identity Candidate Conflict (Entity Explorer Presentation) ───
        cand = IdentityCandidate(
            id=uuid.uuid4(),
            case_id=case.id,
            canonical_entity_id=ent_suspect.id,
            candidate_value="+91-9000000101",
            candidate_type="phone",
            resolution_status="UNRESOLVED",
            source_refs=[f"evidence:{f_trans.filename}:TX0001", f"evidence:{f_cdr.filename}:CDR-001"],
            supporting_refs=[
                "CDR geolocation matches known syndicate safehouse near Delhi IGI",
                "UPI handle glasssparrow11@upi registered with pseudonym Glass Sparrow",
            ],
            contradicting_refs=[
                "Concurrent carrier attachment at Cyberabad suggests possible SIM cloning or multi-user alias sharing",
            ],
            created_by=io_user.id,
        )
        db.add(cand)

        # ── 9. Seed Autonomous Forensic Lenses Findings ─────────────────────────
        findings = [
            InvestigationFinding(
                id=uuid.uuid4(),
                case_id=case.id,
                fingerprint=uuid.uuid4().hex,
                finding_type="RAPID_COMMUNICATION_BURST",
                title="[HEURISTIC SIGNAL] Burner SIM Rotation & High-Frequency Coordination Indicator",
                description="Heuristic telecommunications anomaly: Subscriber +91-9000000101 exhibited 14 burst attachments across multiple cell sectors within 32 minutes preceding victim debit. Flags rapid switching pattern for IO verification.",
                confidence=0.92,
                severity="HIGH",
                status="OPEN",
                freshness_status="CURRENT",
                generated_at_case_version=3,
                entity_refs=[str(ent_phone_burner.id), str(ent_phone_coord.id)],
                event_refs=[str(ev_events[4].id)],
                evidence_refs=[str(f_cdr.id)],
                reasoning="Spatial temporal analysis reveals coordination velocity exceeding standard civilian patterns. Heuristic indicator requiring investigator corroboration.",
            ),
            InvestigationFinding(
                id=uuid.uuid4(),
                case_id=case.id,
                fingerprint=uuid.uuid4().hex,
                finding_type="FAN_OUT_SMURFING_CHAIN",
                title="[HEURISTIC SIGNAL] Structured Multi-Tier Mule Layering Pattern",
                description="Heuristic financial anomaly: Stolen funds of ₹2,85,000 systematically partitioned across ACCT-MULE-11, 12, 13, and 14 within 6 minutes, terminating in rapid physical cashout at ATM-CASH-01 Mumbai. Flags structured smurfing pattern for manual ledger review.",
                confidence=0.96,
                severity="CRITICAL",
                status="OPEN",
                freshness_status="CURRENT",
                generated_at_case_version=3,
                entity_refs=[str(ent_mule_11.id), str(ent_mule_12.id), str(ent_mule_13.id), str(ent_mule_14.id), str(ent_atm_01.id)],
                event_refs=[str(ev_events[0].id), str(ev_events[1].id), str(ev_events[2].id), str(ev_events[3].id)],
                evidence_refs=[str(f_trans.id), str(f_ledg.id)],
                reasoning="Smurfing threshold parameters matched: 4-tier fan-out layering completed under 10 minutes with immediate cash withdrawal. Heuristic indicator requiring bank ledger corroboration.",
            ),
            InvestigationFinding(
                id=uuid.uuid4(),
                case_id=case.id,
                fingerprint=uuid.uuid4().hex,
                finding_type="IMPOSSIBLE_TRAVEL_VELOCITY",
                title="[BENCHMARK SIMULATION] Synthetic Travel Velocity Anomaly: Multi-Device / SIM Cloning Indicator",
                description="Synthetic benchmark telemetry pattern: Carrier switch attachments simulate 1,250 km separation between Delhi (DEL-CNT-11 at 04:23:55 UTC) and Hyderabad (CYB-HYD-03 at 04:24:04 UTC) in 9 seconds. In operational deployment, this heuristic signal indicates concurrent credential sharing, carrier roaming latency anomalies, or IMSI spoofing, requiring investigator corroboration rather than automated conclusion.",
                confidence=0.99,
                severity="CRITICAL",
                status="OPEN",
                freshness_status="CURRENT",
                generated_at_case_version=3,
                entity_refs=[str(ent_phone_burner.id), str(ent_tower_delhi.id), str(ent_tower_hyd.id)],
                event_refs=[str(ev_events[5].id)],
                evidence_refs=[str(f_cdr.id)],
                reasoning="Geodesic calculation indicates speed of 500,000 km/h between carrier switch attachments. Synthetic demo signal demonstrating multi-tower triangulation analysis.",
            ),
        ]
        db.add_all(findings)

        # ── 10. Seed Sequential Activities & Historical Replay Checkpoints ──────
        t0 = base_time - timedelta(hours=2)
        acts = [
            InvestigationActivity(
                id=uuid.uuid4(),
                case_id=case.id,
                actor_id=io_user.id,
                activity_type="CASE_OPENED",
                target_type="case",
                target_id=str(case.id),
                before_state={},
                after_state={"status": "open", "case_number": DEMO_CASE_NUMBER},
                reason="Registered FIR for inter-state cyber fraud syndicate",
                created_at=t0,
            ),
            InvestigationActivity(
                id=uuid.uuid4(),
                case_id=case.id,
                actor_id=io_user.id,
                activity_type="EVIDENCE_INGESTED",
                target_type="evidence_file",
                target_id=str(f_trans.id),
                before_state={},
                after_state={"filename": f_trans.filename, "records": 9},
                reason="Ingested forensic bank statement & UPI audit trail",
                created_at=t0 + timedelta(minutes=15),
            ),
            InvestigationActivity(
                id=uuid.uuid4(),
                case_id=case.id,
                actor_id=io_user.id,
                activity_type="GRAPH_EXTRACTED",
                target_type="graph",
                target_id=str(case.id),
                before_state={},
                after_state={"entities_count": 12, "edges_count": 7},
                reason="Correlated entities and extracted multi-tier financial graph",
                created_at=t0 + timedelta(minutes=30),
            ),
            InvestigationActivity(
                id=uuid.uuid4(),
                case_id=case.id,
                actor_id=io_user.id,
                activity_type="FORENSIC_FINDING_GENERATED",
                target_type="finding",
                target_id=str(findings[1].id),
                before_state={},
                after_state={"finding_type": "FAN_OUT_SMURFING_CHAIN", "confidence": 0.96},
                reason="Autonomous money lens identified structured smurfing layering chain",
                created_at=t0 + timedelta(minutes=45),
            ),
        ]
        db.add_all(acts)

        # Investigation Replay Checkpoints (Version 1, 2, 3)
        h1 = hashlib.sha256(f"{case.id}:1:{t0.isoformat()}".encode()).hexdigest()
        h2 = hashlib.sha256(f"{case.id}:2:{(t0 + timedelta(minutes=30)).isoformat()}".encode()).hexdigest()
        h3 = hashlib.sha256(f"{case.id}:3:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()

        db.add_all([
            InvestigationState(id=uuid.uuid4(), case_id=case.id, version=1, state_hash=h1, created_by=io_user.id, created_at=t0),
            InvestigationState(id=uuid.uuid4(), case_id=case.id, version=2, state_hash=h2, created_by=io_user.id, created_at=t0 + timedelta(minutes=30)),
            InvestigationState(id=uuid.uuid4(), case_id=case.id, version=3, state_hash=h3, created_by=io_user.id, created_at=datetime.now(timezone.utc)),
        ])

        # ── 11. Seed Draft Formal Dossier (Four-Eyes Presentation) ──────────────
        report_payload = {
            "metadata": {
                "case_id": str(case.id),
                "case_number": DEMO_CASE_NUMBER,
                "case_title": DEMO_TITLE,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": str(io_user.id),
                "case_state_version": 3,
                "report_type": "formal_dossier",
            },
            "sections": [
                {
                    "section_id": "exec_summary",
                    "title": "Executive Summary & Syndicate Overview",
                    "content": "Comprehensive statutory investigation dossier detailing structured money mule operations and burner telecommunications activity.",
                    "claims": [
                        {
                            "claim_id": "CLM-001",
                            "statement": "Primary suspect Vikram Malhotra coordinated UPI draining of ₹2,85,000 into ACCT-MULE-11.",
                            "confidence": 0.98,
                            "evidence_citations": [f"{f_trans.filename}:TX0001"],
                        },
                        {
                            "claim_id": "CLM-002",
                            "statement": "Funds dispersed across 4 mule tiers and withdrawn at Mumbai ATM within 20 minutes.",
                            "confidence": 0.96,
                            "evidence_citations": [f"{f_trans.filename}:TX0006", f"{f_ledg.filename}:ATM556677"],
                        }
                    ]
                }
            ]
        }
        report_hash = hashlib.sha256(json.dumps(report_payload, sort_keys=True).encode()).hexdigest()

        snap = ReportSnapshot(
            id=uuid.uuid4(),
            case_id=case.id,
            report_type="formal_dossier",
            case_state_version=3,
            template_version="v1.0",
            content_hash=report_hash,
            title="Operation Shadow Mule — Statutory Formal Investigation Dossier",
            summary="Inter-state cyber syndicate money laundering and burner telecommunications dossier under Section 65B/63 BSA.",
            status="REVIEW",  # Waiting for Supervisor Four-Eyes Review!
            claims_count=2,
            linked_claims_count=2,
            review_required_claims_count=0,
            payload=report_payload,
            generated_by=io_user.id,
        )
        db.add(snap)

        # ── 12. Record Audit Genesis & Case Ingestion in Audit Ledger ───────────
        await append_audit(
            db,
            action="CASE_WORKSPACE_INITIALIZED",
            resource_type="case",
            resource_id=str(case.id),
            details={
                "case_number": DEMO_CASE_NUMBER,
                "lead_officer": io_user.username,
                "seeder": "seed_sih_demo.py",
                "entities_count": 12,
                "findings_count": 3,
                "replay_versions": 3,
            },
            user_id=str(admin_user.id),
        )

        await db.commit()
        return str(case.id)


def main():
    print("=" * 70)
    print("  NETRA V5 — SEEDING CANONICAL SIH INVESTIGATION CASE")
    print(f"  Target: {DEMO_CASE_NUMBER}")
    print(f"  Title:  {DEMO_TITLE}")
    print("=" * 70)
    try:
        case_id = asyncio.run(seed_sih_demo_investigation())
        creds = get_or_rotate_demo_credentials(rotate=False)
        print("\n✓ SUCCESS: SIH Investigation Case Seeded into Database!")
        print(f"  • Case ID:      {case_id}")
        print(f"  • Case Number:  {DEMO_CASE_NUMBER}")
        print(f"\n  CREDENTIALS ROTATED & SAVED LOCALLY TO:")
        print(f"  {CREDENTIALS_FILE} (excluded from git)")
        print("  ┌──────────────────────────────────────────────────────────────────┐")
        print(f"  │ 1. Lead IO:        investigator_delhi / {creds.get('investigator_delhi', '***')} │")
        print(f"  │ 2. Supervisor:     dsp_sharma         / {creds.get('dsp_sharma', '***')} │")
        print(f"  │ 3. Administrator:  admin              / {creds.get('admin', '***')} │")
        print("  └──────────────────────────────────────────────────────────────────┘")
        print("  (Note: Do not commit .demo_credentials.json to git or public logs)")
        print("\n  DEMO STEP-BY-STEP WORKFLOW:")
        print("   1. Login as 'investigator_delhi'. Open 'Operation Shadow Mule'.")
        print("   2. Evidence Tab: View 3 ingested forensic files + SHA-256 hashes.")
        print("   3. Command Center: Active findings, health metrics, and review items.")
        print("   4. Review Queue: Confirm inferred link (+91-9000000101 -> +91-9811122334).")
        print("   5. Entity Explorer: Inspect suspect 'Vikram Malhotra', resolve 'Glass Sparrow' identity candidate.")
        print("   6. Timeline & Replay: Scrub checkpoints (v1 -> v2 -> v3) on the Replay Deck.")
        print("   7. Forensic Lenses: Inspect Communications, Money, and Geographic anomaly cards.")
        print("   8. Reports Tab: View draft dossier submitted for review.")
        print("   9. Switch user to 'dsp_sharma', approve dossier under Four-Eyes dual control, and export certified dossier.")
        print("=" * 70)
    except Exception as e:
        print(f"\n✗ ERROR seeding demo case: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
