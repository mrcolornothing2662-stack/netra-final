"""
NETRA 5.0 — Complete Database Case Purge Script
Removes all cases and all cascading child records from the PostgreSQL database,
cleans uploads and vector storage, preserving users and system configuration.
"""

import asyncio
import os
import shutil
from pathlib import Path
from sqlalchemy import text
from db.session import db_context

CASE_RELATED_TABLES = [
    "entity_mentions",
    "relationships",
    "findings",
    "evidence_events",
    "entities",
    "correlations",
    "analysis_runs",
    "case_intelligence_state",
    "case_collaborators",
    "dossier_export_approvals",
    "agent_holds",
    "agent_actions",
    "agent_sessions",
    "evidence_files",
    "cases",
]

async def purge_all_cases():
    print("[*] Connecting to PostgreSQL database...")
    async with db_context() as db:
        # Check initial counts
        initial_counts = {}
        for t in CASE_RELATED_TABLES:
            cnt = (await db.execute(text(f'SELECT count(*) FROM "{t}";'))).scalar()
            initial_counts[t] = cnt
        print(f"[*] Initial case count: {initial_counts.get('cases', 0)}")
        print(f"[*] Initial evidence_files count: {initial_counts.get('evidence_files', 0)}")
        print(f"[*] Initial entities count: {initial_counts.get('entities', 0)}")
        print(f"[*] Initial relationships count: {initial_counts.get('relationships', 0)}")

        # Execute DELETE FROM cases;
        print("[*] Executing DELETE FROM cases (triggering cascading deletes)...")
        await db.execute(text('DELETE FROM cases;'))
        await db.commit()

        # Check post-deletion counts
        print("\n[*] Verifying post-deletion record counts:")
        all_zero = True
        for t in CASE_RELATED_TABLES:
            cnt = (await db.execute(text(f'SELECT count(*) FROM "{t}";'))).scalar()
            status = "CLEARED" if cnt == 0 else f"REMAINING: {cnt}"
            if cnt != 0:
                all_zero = False
            print(f"    - {t}: {cnt} ({status})")

        # Verify users and system rules are intact
        user_cnt = (await db.execute(text('SELECT count(*) FROM "users";'))).scalar()
        fw_cnt = (await db.execute(text('SELECT count(*) FROM "sandbox_firewall_rules";'))).scalar()
        print(f"\n[*] System & User accounts preserved:")
        print(f"    - users: {user_cnt} active")
        print(f"    - sandbox_firewall_rules: {fw_cnt} active")

    # Clean uploads directory
    uploads_dir = Path("./uploads")
    if uploads_dir.exists():
        print(f"\n[*] Cleaning evidence uploads directory ({uploads_dir})...")
        for item in uploads_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                print(f"    [!] Warning removing {item}: {e}")
        print("    [+] Uploads directory cleaned.")

    # Clean Chroma DB directory
    chroma_dir = Path("./artifacts/chroma_db")
    if chroma_dir.exists():
        print(f"[*] Cleaning Chroma vector store ({chroma_dir})...")
        for item in chroma_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                print(f"    [!] Warning removing {item}: {e}")
        print("    [+] Chroma DB storage reset.")

    print("\n========================================================")
    if all_zero:
        print(">>> ALL CASES AND EVIDENCE PURGED SUCCESSFULLY (100% CLEAN) <<<")
    else:
        print(">>> WARNING: SOME CASE RECORDS REMAIN <<<")
    print("========================================================\n")

if __name__ == "__main__":
    asyncio.run(purge_all_cases())
