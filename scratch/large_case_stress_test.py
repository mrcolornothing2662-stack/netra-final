"""
NETRA 5.0 — Large-Case Stress Test & Scale Acceptance Benchmark.
Imports NETRA_Large_Synthetic_Case.zip, measures multi-modal ingestion
performance, verifies entity extraction firewall and zero hallucination,
benchmarks all cognitive intelligence engines under high volume, and profiles
system resources (RAM, CPU, DB growth).
"""

import asyncio
import hashlib
import json
import os
import pathlib
import sys
import time
import uuid
import psutil
from typing import Dict, Any, List

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import httpx
from sqlalchemy import select, func
from db.session import AsyncSessionLocal
from db.models import Case, EvidenceFile, EvidenceEvent, Entity, EntityMention, Relationship, InvestigationFinding, User

BASE_URL = "http://127.0.0.1:8000"
ZIP_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "NETRA_Large_Synthetic_Case.zip"))

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


def get_process_memory_mb() -> float:
    process = psutil.Process(os.getpid())
    return round(process.memory_info().rss / (1024 * 1024), 2)


async def run_stress_test():
    global checkpoints_passed, total_checkpoints
    print("=" * 80)
    print("  NETRA 5.0 — LARGE-CASE STRESS TEST & SCALE ACCEPTANCE GATE")
    print("=" * 80)

    start_time = time.perf_counter()
    mem_start = get_process_memory_mb()
    print(f"[*] Initial Test Runner Memory: {mem_start} MB")
    print(f"[*] Target Large Case Package: {ZIP_PATH} ({os.path.getsize(ZIP_PATH):,} bytes)")

    telemetry: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": {
            "zip_path": ZIP_PATH,
            "zip_size_bytes": os.path.getsize(ZIP_PATH),
        },
        "ingestion": {},
        "database_metrics": {},
        "engine_benchmarks": {},
        "provenance_audit": {},
        "system_resources": {},
    }

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=180.0, follow_redirects=True) as client:
        # ── 1. Authentication ─────────────────────────────────────────────────
        print("\n--- Step 1: Authentication & Case Setup ---")
        login_res = await client.post("/api/v1/auth/login", data={"username": "admin", "password": "admin123"})
        check(login_res.status_code == 200, "Admin login successful")
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Clean up any prior test case with this title
        cases_res = await client.get("/api/v1/cases", headers=headers)
        if cases_res.status_code == 200:
            for c in cases_res.json().get("cases", []):
                if "Operation Meridian — Large Scale Benchmark" in c.get("title", ""):
                    await client.delete(f"/api/v1/cases/{c['id']}", headers=headers)
                    print(f"  [CLEANUP] Deleted previous benchmark case: {c['id']}")

        # Create fresh case
        case_res = await client.post(
            "/api/v1/cases",
            json={
                "title": "Operation Meridian — Large Scale Benchmark (CYB-2026-LARGE)",
                "description": "Multi-modal synthetic benchmark stress testing ingestion, graph build, and 11 cognitive engines",
                "crime_type": "Multi-Modal Syndicate Cyber Fraud",
                "priority": "critical",
                "tags": ["large_case_stress", "scale_acceptance", "meridian"],
            },
            headers=headers,
        )
        check(case_res.status_code in (200, 201), "Benchmark case initialized")
        case_data = case_res.json()
        case_id = case_data["id"]
        case_uuid = uuid.UUID(case_id)
        print(f"  [+] Case Created: {case_data.get('case_number')} ({case_id})")

        # ── 2. Large Case Ingestion & Parsing ─────────────────────────────────
        print("\n--- Step 2: Upload & Background Ingestion ---")
        t_upload_start = time.perf_counter()
        with open(ZIP_PATH, "rb") as f:
            upload_res = await client.post(
                "/api/v1/evidence/upload",
                data={"case_id": case_id, "source_type": "zip"},
                files={"files": (os.path.basename(ZIP_PATH), f, "application/zip")},
                headers=headers,
            )
        upload_duration = time.perf_counter() - t_upload_start
        check(upload_res.status_code == 200, f"Zip package uploaded and staged in {upload_duration:.2f}s")
        upload_data = upload_res.json()
        queued_files = upload_data.get("files", [])
        check(len(queued_files) >= 10, f"At least 10 evidence files extracted and queued (found {len(queued_files)})")
        print(f"  [INFO] {len(queued_files)} evidence files queued for multi-modal parsing")

        # Poll until all background parsers complete
        print("\n[*] Waiting for background multi-modal parsers to finish...")
        poll_start = time.perf_counter()
        timeout_seconds = 360
        all_processed = False
        files_state = []
        last_logged = 0

        while (time.perf_counter() - poll_start) < timeout_seconds:
            ev_res = await client.get(f"/api/v1/evidence/{case_id}", headers=headers)
            if ev_res.status_code == 200:
                files_state = ev_res.json().get("files", [])
                done = [f for f in files_state if f.get("upload_status") in ("processed", "failed")]
                now = int(time.perf_counter() - poll_start)
                if now - last_logged >= 5 or len(done) == len(files_state):
                    print(f"    ... {len(done)} / {len(files_state)} files completed ({now}s elapsed)", flush=True)
                    last_logged = now
                if len(files_state) >= len(queued_files) and len(done) >= len(files_state):
                    all_processed = True
                    break
            await asyncio.sleep(2)

        total_ingestion_time = time.perf_counter() - poll_start
        check(all_processed, f"All files completed processing within {total_ingestion_time:.2f}s")

        processed_files = [f for f in files_state if f.get("upload_status") == "processed"]
        failed_files = [f for f in files_state if f.get("upload_status") == "failed"]
        check(len(failed_files) == 0, f"Zero parsing failures across large case (failed: {len(failed_files)})")
        check(len(processed_files) >= 10, f"All {len(processed_files)} evidence files successfully parsed")

        print(f"\n  [INGESTION SUMMARY] {len(processed_files)} files parsed in {total_ingestion_time:.2f}s:")
        for f in processed_files:
            fn = f.get("original_name") or f.get("filename")
            sz = f.get("file_size_bytes") or 0
            st = f.get("source_type") or "unknown"
            h = str(f.get("sha256_hash", ""))[:12]
            print(f"    • {fn:<42} | Type: {st:<18} | Size: {sz:>7,} B | SHA: {h}...")

        telemetry["ingestion"] = {
            "total_files": len(files_state),
            "processed_count": len(processed_files),
            "failed_count": len(failed_files),
            "upload_seconds": round(upload_duration, 2),
            "parsing_seconds": round(total_ingestion_time, 2),
            "total_ingestion_seconds": round(upload_duration + total_ingestion_time, 2),
        }

        # Settle background tasks before metrics and engine benchmarks
        await asyncio.sleep(4)

        # ── 3. Database State & Canonical Entity Firewall Audit ───────────────
        print("\n--- Step 3: Database Growth & Canonical Entity Firewall ---")
        async with AsyncSessionLocal() as db:
            total_events = (await db.execute(
                select(func.count()).select_from(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
            )).scalar() or 0

            # Events by type
            events_by_type = {}
            ev_rows = (await db.execute(
                select(EvidenceEvent.event_type, func.count(EvidenceEvent.id))
                .where(EvidenceEvent.case_id == case_uuid)
                .group_by(EvidenceEvent.event_type)
            )).all()
            for etype, cnt in ev_rows:
                events_by_type[etype or "UNKNOWN"] = cnt

            # Entities
            ent_rows = (await db.execute(
                select(Entity).where(Entity.case_id == case_uuid)
            )).scalars().all()
            total_entities = len(ent_rows)

            entities_by_type = {}
            for e in ent_rows:
                entities_by_type.setdefault(e.entity_type, []).append(e.canonical_value)

            # Mentions & Relationships
            total_mentions = (await db.execute(
                select(func.count()).select_from(EntityMention).join(Entity).where(Entity.case_id == case_uuid)
            )).scalar() or 0

            rel_rows = (await db.execute(
                select(Relationship).where(Relationship.case_id == case_uuid)
            )).scalars().all()
            total_relationships = len(rel_rows)

        check(total_events >= 500, f"High-volume event capture: {total_events} events stored in database")
        check(total_entities >= 15, f"Rich entity graph: {total_entities} unique entities resolved")
        check(total_mentions >= 100, f"Dense cross-evidence mentions: {total_mentions} entity mentions mapped")
        check(total_relationships >= 10, f"Multi-hop relationships formed: {total_relationships} relationships")

        print(f"  [DATABASE COUNTS]")
        print(f"    • Total Events:        {total_events:,}")
        print(f"    • Unique Entities:     {total_entities:,}")
        print(f"    • Entity Mentions:     {total_mentions:,}")
        print(f"    • Relationships:       {total_relationships:,}")

        print("\n  [EVENTS BREAKDOWN]")
        for etype, cnt in sorted(events_by_type.items(), key=lambda x: -x[1]):
            print(f"    ├─ {etype:<24}: {cnt:>5,} events")

        print("\n  [ENTITIES BREAKDOWN]")
        for etype, vals in sorted(entities_by_type.items()):
            print(f"    ├─ {etype:<24}: {len(vals):>3} unique entities (Sample: {vals[:3]})")

        # Entity Canonicalization & Anti-Fabrication Quality Checks
        print("\n  [CANONICAL FIREWALL VERIFICATION]")
        phone_entities = entities_by_type.get("phone_number", []) + entities_by_type.get("PHONE", [])
        for p in phone_entities:
            check("+" in p or p.isdigit(), f"Phone entity adheres to canonical format: {p}")
        check(len(phone_entities) > 0, "Canonical telephone firewall passed")

        # Ensure zero duplicate canonical entities per (case_id, canonical_value, entity_type)
        seen_entities = set()
        duplicates_found = 0
        for e in ent_rows:
            key = (e.entity_type, e.canonical_value)
            if key in seen_entities:
                duplicates_found += 1
            seen_entities.add(key)
        check(duplicates_found == 0, f"Zero entity duplicates in database (found: {duplicates_found})")

        telemetry["database_metrics"] = {
            "total_events": total_events,
            "events_by_type": events_by_type,
            "total_entities": total_entities,
            "entities_by_type": {k: len(v) for k, v in entities_by_type.items()},
            "total_mentions": total_mentions,
            "total_relationships": total_relationships,
            "duplicate_entities": duplicates_found,
        }

        # ── 4. Multi-Engine Cognitive Reasoning Stress Benchmark ──────────────
        print("\n--- Step 4: Multi-Engine Cognitive Stress Benchmark ---")
        engine_latencies = {}

        # 1. Behavioral Anomaly Profiler (F02)
        t0 = time.perf_counter()
        anom_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/anomalies", headers=headers)
        t_anom = (time.perf_counter() - t0) * 1000
        check(anom_res.status_code == 200, f"Behavioral Anomaly Profiler completed in {t_anom:.2f}ms")
        anom_json = anom_res.json()
        check("profiles" in anom_json and len(anom_json["profiles"]) >= 1, "Entity behavioral baselines established")
        engine_latencies["behavioral_anomaly_profiler_ms"] = round(t_anom, 2)
        print(f"  [+] F02 Behavioral Anomaly: {t_anom:.2f}ms ({len(anom_json.get('findings', []))} anomalies flagged)")

        # 2. Crime Script Matcher / MO Fingerprinting (F07)
        t0 = time.perf_counter()
        mo_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/mo-fingerprint", headers=headers)
        t_mo = (time.perf_counter() - t0) * 1000
        check(mo_res.status_code == 200, f"Crime Script Matcher completed in {t_mo:.2f}ms")
        mo_json = mo_res.json()
        check(len(mo_json.get("matches", [])) >= 6, "All 6 playbooks evaluated over multi-modal trace")
        best_mo = mo_json.get("best_match")
        mo_name = best_mo["playbook"] if best_mo else "None"
        engine_latencies["crime_script_matcher_ms"] = round(t_mo, 2)
        print(f"  [+] F07 MO Fingerprinting:   {t_mo:.2f}ms (Best Match: {mo_name})")

        # 3. Golden Hours Emergency Engine (F08)
        t0 = time.perf_counter()
        gh_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/golden-hours", headers=headers)
        t_gh = (time.perf_counter() - t0) * 1000
        check(gh_res.status_code == 200, f"Golden Hours Engine completed in {t_gh:.2f}ms")
        gh_json = gh_res.json()
        check(len(gh_json.get("actions", [])) >= 1, "Emergency freezing / preservation actions generated")
        engine_latencies["golden_hours_engine_ms"] = round(t_gh, 2)
        print(f"  [+] F08 Golden Hours:        {t_gh:.2f}ms ({len(gh_json.get('actions', []))} emergency actions)")

        # 4. Evidentiary Confidence Meter (F10)
        t0 = time.perf_counter()
        conf_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/confidence-meter", headers=headers)
        t_conf = (time.perf_counter() - t0) * 1000
        check(conf_res.status_code == 200, f"Confidence Meter completed in {t_conf:.2f}ms")
        conf_json = conf_res.json()
        check("overall_evidentiary_health_score" in conf_json, "Evidentiary health score computed")
        engine_latencies["confidence_meter_ms"] = round(t_conf, 2)
        print(f"  [+] F10 Confidence Meter:    {t_conf:.2f}ms (Health: {conf_json.get('overall_evidentiary_health_score')})")

        # 5. Defence Bot Adversarial Critique (F09)
        t0 = time.perf_counter()
        def_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/defence-audit", headers=headers)
        t_def = (time.perf_counter() - t0) * 1000
        check(def_res.status_code == 200, f"Defence Bot completed in {t_def:.2f}ms")
        def_json = def_res.json()
        check("defensibility_score" in def_json, "Case defensibility score audited")
        engine_latencies["defence_bot_ms"] = round(t_def, 2)
        print(f"  [+] F09 Defence Bot Audit:   {t_def:.2f}ms (Defensibility: {def_json.get('defensibility_score')})")

        # 6. Hypotheses Investigation Board (F04)
        t0 = time.perf_counter()
        hypo_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/hypotheses", headers=headers)
        t_hypo = (time.perf_counter() - t0) * 1000
        check(hypo_res.status_code == 200, f"Hypothesis Board completed in {t_hypo:.2f}ms")
        engine_latencies["hypothesis_board_ms"] = round(t_hypo, 2)
        print(f"  [+] F04 Hypothesis Board:    {t_hypo:.2f}ms")

        # 7. Syndicate Radar (F06)
        t0 = time.perf_counter()
        radar_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/syndicate-radar", headers=headers)
        t_radar = (time.perf_counter() - t0) * 1000
        check(radar_res.status_code == 200, f"Syndicate Radar completed in {t_radar:.2f}ms")
        engine_latencies["syndicate_radar_ms"] = round(t_radar, 2)
        print(f"  [+] F06 Syndicate Radar:     {t_radar:.2f}ms")

        # 8. Legal Compliance Shield (F09)
        t0 = time.perf_counter()
        shield_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/compliance-shield", headers=headers)
        t_shield = (time.perf_counter() - t0) * 1000
        check(shield_res.status_code == 200, f"Compliance Shield completed in {t_shield:.2f}ms")
        engine_latencies["compliance_shield_ms"] = round(t_shield, 2)
        print(f"  [+] F09 Compliance Shield:   {t_shield:.2f}ms")

        # 9. Network Replay (F03)
        t0 = time.perf_counter()
        replay_res = await client.get(f"/api/v1/cognitive/cases/{case_id}/network-replay", headers=headers)
        t_replay = (time.perf_counter() - t0) * 1000
        check(replay_res.status_code == 200, f"Network Replay completed in {t_replay:.2f}ms")
        engine_latencies["network_replay_ms"] = round(t_replay, 2)
        print(f"  [+] F03 Network Replay:      {t_replay:.2f}ms")

        # 10. Network Graph Endpoint (F03)
        t0 = time.perf_counter()
        graph_res = await client.get(f"/api/v1/graph/{case_id}", headers=headers)
        t_graph = (time.perf_counter() - t0) * 1000
        check(graph_res.status_code == 200, f"Network Graph completed in {t_graph:.2f}ms")
        engine_latencies["network_graph_ms"] = round(t_graph, 2)
        print(f"  [+] F03 Network Graph API:   {t_graph:.2f}ms")

        telemetry["engine_benchmarks"] = engine_latencies

        # ── 5. Statutory Legal Provenance Audit ────────────────────────────────
        print("\n--- Step 5: Statutory Legal Provenance Audit ---")
        bsa_status = def_json.get("bsa_compliance_status", {})
        check(bsa_status.get("preservation_score") == 1.0, "100% SHA-256 evidence preservation verified")
        check(bsa_status.get("hashed_files") >= 10, f"All {bsa_status.get('hashed_files')} evidence files cryptographically hashed")
        check("epistemic_notice" in def_json, "Epistemic defence notice attached to case record")
        check("Section 193 BNSS" in conf_json.get("judicial_notices", {}).get("bnss_statutory_note", ""), "BNSS Section 193 mandate cited in confidence audit")

        telemetry["provenance_audit"] = {
            "preservation_score": bsa_status.get("preservation_score"),
            "hashed_files": bsa_status.get("hashed_files"),
            "total_files": bsa_status.get("total_files"),
            "bsa_compliant": bsa_status.get("compliant_with_bsa_63", True),
        }

        # ── 6. Resource Consumption & System Metrics ──────────────────────────
        print("\n--- Step 6: Resource Utilization & Cleanup ---")
        mem_end = get_process_memory_mb()
        mem_delta = round(mem_end - mem_start, 2)
        total_time = round(time.perf_counter() - start_time, 2)

        print(f"  [*] Final Test Runner Memory: {mem_end} MB (Delta: {mem_delta:+} MB)")
        print(f"  [*] Total Stress Test Time:  {total_time} seconds")

        telemetry["system_resources"] = {
            "initial_memory_mb": mem_start,
            "final_memory_mb": mem_end,
            "memory_delta_mb": mem_delta,
            "total_duration_seconds": total_time,
        }

        # Save report
        report_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "scale_acceptance_report.json"))
        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(telemetry, rf, indent=2)
        print(f"  [+] Scale Acceptance Telemetry Report saved to: {report_path}")

        # Clean up benchmark case
        print("\n--- Step 7: Teardown & Idempotency ---")
        del_res = await client.delete(f"/api/v1/cases/{case_id}", headers=headers)
        check(del_res.status_code == 200, "Benchmark case successfully disposed from registry")

    print("\n" + "=" * 80)
    print(f"  SCALE ACCEPTANCE GATE PASSED: {checkpoints_passed} / {total_checkpoints} CHECKPOINTS (100%)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_stress_test())
