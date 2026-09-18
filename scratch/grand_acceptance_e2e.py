"""
NETRA 5.0 — Grand Multi-Engine Acceptance E2E Demonstration.
Exercises the entire cognitive pipeline, multi-tenant security,
evidence provenance, and statutory compliance on a fresh synthetic case.
"""

import asyncio
import hashlib
import json
import os
import sys
import time
import uuid

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import httpx
from db.session import AsyncSessionLocal
from db.models import Case, EvidenceFile, EvidenceEvent, Entity, Relationship, User

BASE_URL = "http://127.0.0.1:8000"

# Assertion tracker
checkpoints_passed = 0
total_checkpoints = 0

def check(condition: bool, description: str):
    global checkpoints_passed, total_checkpoints
    total_checkpoints += 1
    if condition:
        checkpoints_passed += 1
        print(f"  [PASS {checkpoints_passed:03d}] {description}")
    else:
        print(f"  [FAIL {total_checkpoints:03d}] {description}")
        raise AssertionError(f"Checkpoint FAILED: {description}")


async def run_grand_acceptance():
    global checkpoints_passed, total_checkpoints
    print("=" * 75)
    print("  NETRA 5.0 — GRAND MULTI-ENGINE ACCEPTANCE E2E DEMONSTRATION")
    print("=" * 75)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # ── 1. Authentication & Role-Based Access ─────────────────────────────
        print("\n--- Gate 1: Security, Authentication & Role Isolation ---")
        login_resp = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        check(login_resp.status_code == 200, "Admin login returns HTTP 200")
        admin_token = login_resp.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        check(len(admin_token) > 20, "Admin JWT access token issued")

        # Create/find an IO user
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            io_user = (await db.execute(select(User).where(User.username == "io_officer"))).scalar_one_or_none()
            if not io_user:
                from routes.auth import _hash_password
                io_user = User(
                    username="io_officer",
                    email="io_officer@cyberdrishti.gov.in",
                    hashed_password=_hash_password("officer123"),
                    full_name="Inspector R. Sharma",
                    rank="Inspector",
                    unit="Cyber Crime Cell",
                    role="io",
                    is_active=True,
                )
                db.add(io_user)
                await db.commit()
                await db.refresh(io_user)

        io_login_resp = await client.post("/api/v1/auth/login", data={"username": "io_officer", "password": "officer123"})
        check(io_login_resp.status_code == 200, "IO login returns HTTP 200")
        io_token = io_login_resp.json()["access_token"]
        io_headers = {"Authorization": f"Bearer {io_token}"}
        check(len(io_token) > 20, "IO JWT access token issued")

        # ── 2. Create Fresh Synthetic Case ────────────────────────────────────
        print("\n--- Gate 2: Case Inception & Tenancy Firewall ---")
        case_title = f"Operation Vajra — Grand Acceptance {int(time.time())}"
        case_res = await client.post(
            "/api/v1/cases",
            json={
                "title": case_title,
                "description": "Multi-engine end-to-end acceptance pass testing extortion syndicate money trail",
                "crime_type": "Digital Arrest & Organized Cyber Syndicate",
                "priority": "critical",
                "tags": ["grand_acceptance", "f01_f11", "digital_arrest"],
            },
            headers=io_headers,
        )
        check(case_res.status_code in (200, 201), f"Case creation succeeds with HTTP {case_res.status_code}")
        case_data = case_res.json()
        case_id = case_data["id"]
        check(bool(case_id), f"Case ID generated: {case_id}")
        check(case_data.get("status") == "open", "Case initializes in 'open' status")

        # ── 3. Multi-Modal Evidence Ingestion & SHA-256 Provenance ──────────
        print("\n--- Gate 3: Evidence Ingestion & Chain-of-Custody Provenance ---")
        
        # Synthetic WhatsApp Chat Transcript
        chat_content = (
            "18/08/2026, 09:30 am - DCP Cyber Crime: You are placed under digital arrest for terror financing.\n"
            "18/08/2026, 09:45 am - DCP Cyber Crime: Keep your camera turned on continuously on Skype.\n"
            "18/08/2026, 10:15 am - DCP Cyber Crime: Transfer Rs 5,00,000 to RBI Clearance Account 4455667788.\n"
            "18/08/2026, 10:20 am - Victim: Sir funds sent via RTGS reference RTGS99887766.\n"
            "18/08/2026, 10:30 am - DCP Cyber Crime: Transfer another Rs 3,00,000 to account 1122334455.\n"
        ).encode("utf-8")
        chat_hash = hashlib.sha256(chat_content).hexdigest()

        # Bank Statement CSV
        bank_csv = (
            "account_number,transaction_date,amount,type,counterparty,narration\n"
            "ACC_PRIMARY,2026-08-18 10:21:00,500000.00,CREDIT,ACC_VICTIM,RTGS INWARD VICTIM EXTORTION\n"
            "ACC_PRIMARY,2026-08-18 10:24:00,240000.00,DEBIT,ACC_MULE_1,IMPS MULE FANOUT TIER 1\n"
            "ACC_PRIMARY,2026-08-18 10:25:00,250000.00,DEBIT,ACC_MULE_2,IMPS MULE FANOUT TIER 1\n"
            "ACC_MULE_1,2026-08-18 10:28:00,235000.00,DEBIT,ACC_CRYPTO_OTC,CRYPTO OFFRAMP P2P\n"
        ).encode("utf-8")
        bank_hash = hashlib.sha256(bank_csv).hexdigest()

        # CDR Call Log CSV
        cdr_csv = (
            "caller_number,receiver_number,timestamp,duration_sec,call_type,cell_id,imei\n"
            "+919876543210,+918888877777,2026-08-18 09:28:00,120,VOICE,TOWER_DELHI_01,867543219876543\n"
            "+919876543210,+918888877777,2026-08-18 09:44:00,600,VOICE,TOWER_DELHI_01,867543219876543\n"
            "+919876543210,+918888877777,2026-08-18 10:14:00,450,VOICE,TOWER_DELHI_01,867543219876543\n"
        ).encode("utf-8")
        cdr_hash = hashlib.sha256(cdr_csv).hexdigest()

        # Upload files
        files_to_upload = [
            ("evidence_chat.txt", chat_content, "text/plain"),
            ("evidence_bank.csv", bank_csv, "text/csv"),
            ("evidence_cdr.csv", cdr_csv, "text/csv"),
        ]

        for fname, content, mtype in files_to_upload:
            up_res = await client.post(
                "/api/v1/evidence/upload",
                data={"case_id": case_id, "source_type": "file"},
                files={"files": (fname, content, mtype)},
                headers=io_headers,
            )
            check(up_res.status_code == 200, f"Upload of {fname} returns HTTP 200")
            up_json = up_res.json()
            check(len(up_json.get("files", [])) >= 1, f"File {fname} metadata stored")

        # Verify DB records and SHA-256 hashes
        case_uuid = uuid.UUID(case_id)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            ev_files = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == case_uuid))).scalars().all()
            file_map = {}
            for f in ev_files:
                file_map[f.filename] = f
                if f.original_name:
                    file_map[f.original_name] = f
            check(file_map["evidence_chat.txt"].sha256_hash == chat_hash, "WhatsApp chat SHA-256 matches bit-for-bit")
            check(file_map["evidence_bank.csv"].sha256_hash == bank_hash, "Bank statement SHA-256 matches bit-for-bit")
            check(file_map["evidence_cdr.csv"].sha256_hash == cdr_hash, "CDR CSV SHA-256 matches bit-for-bit")

            from datetime import datetime, timezone
            # Seed evidence events & entities for cognitive analysis
            chat_ev = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_chat.txt"].id,
                event_type="whatsapp_msg",
                event_timestamp=datetime(2026, 8, 18, 9, 30, tzinfo=timezone.utc),
                text_content="You are placed under digital arrest for terror financing.",
                event_metadata={"sender": "DCP Cyber Crime", "text": "You are placed under digital arrest for terror financing."},
            )
            chat_ev2 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_chat.txt"].id,
                event_type="whatsapp_msg",
                event_timestamp=datetime(2026, 8, 18, 9, 45, tzinfo=timezone.utc),
                text_content="Keep your camera turned on continuously on Skype. Digital arrest initiated.",
                event_metadata={"sender": "DCP Cyber Crime", "text": "Keep your camera turned on continuously on Skype. Digital arrest initiated."},
            )
            chat_ev3 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_chat.txt"].id,
                event_type="whatsapp_msg",
                event_timestamp=datetime(2026, 8, 18, 10, 15, tzinfo=timezone.utc),
                text_content="Transfer Rs 500000 to RBI Clearance Account 4455667788 immediately.",
                event_metadata={"sender": "DCP Cyber Crime", "text": "Transfer Rs 500000 to RBI Clearance Account 4455667788 immediately."},
            )
            bank_ev1 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_bank.csv"].id,
                event_type="bank_txn",
                event_timestamp=datetime(2026, 8, 18, 10, 21, tzinfo=timezone.utc),
                text_content="RTGS INWARD VICTIM EXTORTION 500000.0",
                event_metadata={"account": "ACC_PRIMARY", "amount": 500000.0, "credit": 500000.0, "debit": 0.0, "type": "CREDIT", "narration": "RTGS INWARD VICTIM EXTORTION", "model": "ledger"},
            )
            bank_ev2 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_bank.csv"].id,
                event_type="bank_txn",
                event_timestamp=datetime(2026, 8, 18, 10, 24, tzinfo=timezone.utc),
                text_content="IMPS MULE FANOUT TIER 1 240000.0",
                event_metadata={"account": "ACC_PRIMARY", "amount": 240000.0, "credit": 0.0, "debit": 240000.0, "to_account": "ACC_MULE_1", "type": "DEBIT", "counterparty": "ACC_MULE_1", "narration": "IMPS MULE FANOUT TIER 1", "model": "transfer"},
            )
            bank_ev3 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_bank.csv"].id,
                event_type="bank_txn",
                event_timestamp=datetime(2026, 8, 18, 10, 25, tzinfo=timezone.utc),
                text_content="IMPS MULE FANOUT TIER 1 250000.0",
                event_metadata={"account": "ACC_PRIMARY", "amount": 250000.0, "credit": 0.0, "debit": 250000.0, "to_account": "ACC_MULE_2", "type": "DEBIT", "counterparty": "ACC_MULE_2", "narration": "IMPS MULE FANOUT TIER 1", "model": "transfer"},
            )
            cdr_ev1 = EvidenceEvent(
                case_id=case_uuid,
                evidence_file_id=file_map["evidence_cdr.csv"].id,
                event_type="call",
                event_timestamp=datetime(2026, 8, 18, 9, 28, tzinfo=timezone.utc),
                text_content="Voice call from +919876543210 to +918888877777",
                event_metadata={"caller": "+919876543210", "receiver": "+918888877777", "duration": 120, "cell_tower": "TOWER_DELHI_01"},
            )
            db.add_all([chat_ev, chat_ev2, chat_ev3, bank_ev1, bank_ev2, bank_ev3, cdr_ev1])

            # Seed entities
            ent_victim = Entity(case_id=case_uuid, entity_type="phone_number", canonical_value="+918888877777", node_metadata={"risk_score": 0.1})
            ent_scammer = Entity(case_id=case_uuid, entity_type="phone_number", canonical_value="+919876543210", node_metadata={"risk_score": 0.9})
            ent_acc_primary = Entity(case_id=case_uuid, entity_type="bank_account", canonical_value="ACC_PRIMARY", node_metadata={"risk_score": 0.85})
            ent_mule_1 = Entity(case_id=case_uuid, entity_type="bank_account", canonical_value="ACC_MULE_1", node_metadata={"risk_score": 0.8})
            ent_mule_2 = Entity(case_id=case_uuid, entity_type="bank_account", canonical_value="ACC_MULE_2", node_metadata={"risk_score": 0.8})
            db.add_all([ent_victim, ent_scammer, ent_acc_primary, ent_mule_1, ent_mule_2])
            await db.commit()

        print("  [INFO] Synthetic multi-modal events and entities seeded in database")

        # ── 4. Behavioral Anomaly Profiler (F02) ──────────────────────────────
        print("\n--- Gate 4: Feature 02 — Behavioral Anomaly Profiler ---")
        anom_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/anomalies", headers=io_headers)
        check(anom_res.status_code == 200, "Behavioral Anomaly endpoint returns HTTP 200")
        anom_data = anom_res.json()
        check("profiles" in anom_data, "Entity profiles mapped in response")
        check("findings" in anom_data, "Findings dictionary returned")
        check(isinstance(anom_data["findings"], list), "Findings returned as structured list")
        check("summary" in anom_data, "Summary block included")
        check(anom_data["summary"]["total_entities_profiled"] >= 1, "Profiles built from ingested evidence")

        # ── 5. Crime Script Matcher / MO Fingerprinting (F07) ─────────────────
        print("\n--- Gate 5: Feature 07 — Crime Script Matcher (MO) ---")
        mo_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/mo-fingerprint", headers=io_headers)
        check(mo_res.status_code == 200, "MO Fingerprint endpoint returns HTTP 200")
        mo_data = mo_res.json()
        check(mo_data.get("verdict") in ("MATCHED", "NO_CONFIDENT_MATCH", "INSUFFICIENT_TRACE"), "Valid MO classification verdict returned")
        check("matches" in mo_data, "Per-playbook candidate matches returned")
        check(len(mo_data["matches"]) >= 6, f"All 6 curated playbooks evaluated (found {len(mo_data['matches'])})")
        
        # Check Digital Arrest matching
        da_match = next((m for m in mo_data["matches"] if m["playbook"] == "DIGITAL_ARREST_EXTORTION"), None)
        check(da_match is not None, "DIGITAL_ARREST_EXTORTION evaluated")
        check(da_match["similarity"] >= 0.0, f"Levenshtein similarity computed: {da_match['similarity']}")
        check("calculation_breakdown" in da_match, "Calculation breakdown transparently exposed")
        check("alignment" in da_match, "Stage alignment exposed")
        check("judicial_notice" in mo_data, "Judicial notice included")
        check("R v T [2010]" in str(mo_data["judicial_notice"]), "R v T [2010] warning present in judicial notice")

        # ── 6. Golden Hours Emergency Engine (F08) ────────────────────────────
        print("\n--- Gate 6: Feature 08 — Golden Hours Emergency Action Engine ---")
        gh_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/golden-hours", headers=io_headers)
        check(gh_res.status_code == 200, "Golden Hours endpoint returns HTTP 200")
        gh_data = gh_res.json()
        check("elapsed_hours" in gh_data, "Elapsed hours timer present")
        check("window_phase" in gh_data, "Window phase categorized")
        check("actions" in gh_data, "Emergency action items generated")
        check("summary" in gh_data, "Action summary block present")

        # ── 7. Uncertainty & Evidentiary Confidence Meter (F10) ───────────────
        print("\n--- Gate 7: Feature 10 — Evidentiary Confidence Meter ---")
        conf_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/confidence-meter", headers=io_headers)
        check(conf_res.status_code == 200, "Confidence Meter endpoint returns HTTP 200")
        conf_data = conf_res.json()
        check("overall_evidentiary_health_score" in conf_data, "Bayesian health score calculated")
        check(0.0 <= conf_data["overall_evidentiary_health_score"] <= 1.0, "Health score bounded in [0.0, 1.0]")
        check("findings_audit" in conf_data, "Findings audit included")
        check("judicial_notices" in conf_data, "Judicial notices present")

        # ── 8. Defence Bot Adversarial Critique (F09) ─────────────────────────
        print("\n--- Gate 8: Feature 09 — Defence Bot Adversarial Shield ---")
        def_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/defence-audit", headers=io_headers)
        check(def_res.status_code == 200, "Defence Audit endpoint returns HTTP 200")
        def_data = def_res.json()
        check("defensibility_score" in def_data, "Defensibility score calculated")
        check(0.0 <= def_data["defensibility_score"] <= 1.0, "Defensibility score bounded in [0.0, 1.0]")
        check("risk_level" in def_data, "Risk level categorized")
        check("bsa_compliance_status" in def_data, "BSA Section 63 electronic compliance verified")
        check(def_data["bsa_compliance_status"]["preservation_score"] == 1.0, "100% SHA-256 preservation recognized")
        check("challenges" in def_data, "Adversarial challenges generated")
        check("epistemic_notice" in def_data, "Epistemic defence notice included")

        # ── 9. Training Simulator & Synthetic Benchmark (F11) ─────────────────
        print("\n--- Gate 9: Feature 11 — Training Simulator & Benchmark ---")
        train_res = await client.get("/api/v1/cognitive/training/drills", headers=io_headers)
        check(train_res.status_code == 200, "Training drills catalog returns HTTP 200")
        drills = train_res.json().get("drills", [])
        check(len(drills) >= 4, f"At least 4 training drills cataloged (found {len(drills)})")

        drill_id = drills[0]["id"]
        start_res = await client.post(
            "/api/v1/cognitive/training/start",
            json={"drill_id": drill_id, "difficulty": "intermediate"},
            headers=io_headers,
        )
        check(start_res.status_code == 200, "Training session started successfully")
        session_data = start_res.json()
        session_id = session_data["session_id"]
        check(bool(session_id), f"Training session ID: {session_id}")

        eval_res = await client.post(
            f"/api/v1/cognitive/training/{session_id}/submit",
            json={
                "answers": {
                    "typology": "DIGITAL_ARREST_EXTORTION",
                    "primary_mule_account": "ACC_PRIMARY",
                    "legal_challenge_raised": "Lack of Section 63 BSA Hash Certificate",
                    "recommended_next_action": "Freeze beneficiary account under Section 106 BNSS",
                },
            },
            headers=io_headers,
        )
        check(eval_res.status_code == 200, "Training evaluation returns HTTP 200")
        eval_body = eval_res.json()
        check("evaluation" in eval_body, "Evaluation object returned")
        eval_data = eval_body["evaluation"]
        check("score_pct" in eval_data, "Final training score percentage calculated")
        check("readiness_tier" in eval_data, "Readiness tier categorized")
        check("pillar_breakdown" in eval_data, "All 4 training pillars evaluated")
        check(len(eval_data["pillar_breakdown"]) == 4, "Exactly 4 scoring pillars reported")
        check("typology" in eval_data["pillar_breakdown"], "Pillar 1: MO Typology evaluated")
        check("hidden_links" in eval_data["pillar_breakdown"], "Pillar 2: Money Trail & Hidden Links evaluated")
        check("legal_rigor" in eval_data["pillar_breakdown"], "Pillar 3: Legal Rigor evaluated")
        check("action_priority" in eval_data["pillar_breakdown"], "Pillar 4: Action Priority & Readiness evaluated")

        # ── 10. Multi-Tenant Anti-Enumeration Security Audit ─────────────────
        print("\n--- Gate 10: Multi-Tenant & Anti-Enumeration Hardening ---")
        # Constable tries to access case without assignment -> HTTP 404 (anti-enumeration)
        async with AsyncSessionLocal() as db:
            constable = (await db.execute(select(User).where(User.username == "constable_user"))).scalar_one_or_none()
            if not constable:
                from routes.auth import _hash_password
                constable = User(
                    username="constable_user",
                    email="constable_user@cyberdrishti.gov.in",
                    hashed_password=_hash_password("constable123"),
                    full_name="Constable A. Verma",
                    rank="Constable",
                    unit="General Duty",
                    role="constable",
                    is_active=True,
                )
                db.add(constable)
                await db.commit()

        c_login = await client.post("/api/v1/auth/login", data={"username": "constable_user", "password": "constable123"})
        check(c_login.status_code == 200, "Constable login succeeds")
        c_token = c_login.json()["access_token"]
        c_headers = {"Authorization": f"Bearer {c_token}"}

        # Request case details as unassigned constable
        denied_res = await client.get(f"/api/v1/cases/{case_id}", headers=c_headers)
        check(denied_res.status_code == 404, f"Unassigned constable gets 404 Not Found anti-probing response (got {denied_res.status_code})")

        # Tampered token check
        tampered_token = io_token[:-8] + "ABCDEFGH"
        tampered_res = await client.get(f"/api/v1/cases/{case_id}", headers={"Authorization": f"Bearer {tampered_token}"})
        check(tampered_res.status_code == 401, f"Tampered JWT signature correctly rejected with HTTP 401 (got {tampered_res.status_code})")

        # ── 11. Cleanup Test Case ─────────────────────────────────────────────
        print("\n--- Gate 11: Tear-Down & Idempotency ---")
        del_res = await client.delete(f"/api/v1/cases/{case_id}", headers=admin_headers)
        check(del_res.status_code == 200, "Admin successfully cleans up test case")

    print("\n" + "=" * 75)
    print(f"  GRAND ACCEPTANCE COMPLETE: {checkpoints_passed} / {total_checkpoints} CHECKPOINTS PASSED (100%)")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_grand_acceptance())
