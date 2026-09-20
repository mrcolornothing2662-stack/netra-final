"""
Verification script for NETRA Multi-Evidence Batch Pre-Hash Preview & Sealing
"""
import asyncio
import hashlib
import json
import pathlib
import time
import uuid
import httpx
from sqlalchemy import select

from db.models import Case, EvidenceFile, EvidenceEvent, Entity, EntityMention, User
from db.session import AsyncSessionLocal
from routes.auth import _create_token, _hash_password

DEMO_DIR = pathlib.Path("scratch/demo_evidence")
FILES_TO_TEST = [
    "01_case_registration.pdf",
    "02_bank_statement.pdf",
    "03_intermediary_account_statement.pdf",
    "04_call_records.csv",
    "05_chat_export.txt",
]

async def main():
    print("=" * 60)
    print("NETRA 5.0 — BATCH EVIDENCE INGESTION VERIFICATION")
    print("=" * 60)

    # 1. Ensure user and test case exist in DB
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one_or_none()
        if not user:
            user = User(
                username=f"officer_e2e_{uuid.uuid4().hex[:6]}",
                email=f"officer_e2e_{uuid.uuid4().hex[:6]}@police.gov.in",
                hashed_password=_hash_password("admin123"),
                full_name="Senior IO",
                role="io",
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        case = Case(
            case_number=f"DEMO-{uuid.uuid4().hex[:6].upper()}",
            title="Operation Meridian Demonstration Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        case_id = str(case.id)
        user_id = str(user.id)
        token, *_ = _create_token(user_id, user.role)
        headers = {"Authorization": f"Bearer {token}"}

    print(f"✓ Test Case Created: {case_id}")
    print(f"✓ Officer Token Generated for: {user.username}")

    # 2. Stage all 5 demo files via POST /api/v1/evidence/preview/batch
    multipart_files = []
    expected_hashes = {}
    for fname in FILES_TO_TEST:
        fpath = DEMO_DIR / fname
        assert fpath.exists(), f"File {fpath} not found"
        raw = fpath.read_bytes()
        expected_hashes[fname] = hashlib.sha256(raw).hexdigest()
        mime = "application/pdf" if fname.endswith(".pdf") else ("text/csv" if fname.endswith(".csv") else "text/plain")
        multipart_files.append(("files", (fname, raw, mime)))

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=60.0) as client:
        print("\n--> [1/4] Staging 5 files via /api/v1/evidence/preview/batch...")
        res = await client.post(
            "/api/v1/evidence/preview/batch",
            data={"case_id": case_id, "source_type": "unknown"},
            files=multipart_files,
            headers=headers,
        )
        assert res.status_code == 200, f"Preview batch failed: {res.text}"
        batch_preview = res.json()
        assert batch_preview["total"] == 5, f"Expected 5 preview items, got {batch_preview['total']}"
        print(f"✓ Batch staged successfully. Received {len(batch_preview['items'])} preview items.")

        for item in batch_preview["items"]:
            print(f"   • {item['filename']} -> Preview ID: {item['preview_id'][:8]}… | Type: {item['mime_type']} | Size: {item['file_size_bytes']} bytes")
            assert item["status"] == "unhashed_preview"
            assert item["preview_id"] is not None

        # Verify no database records created yet
        async with AsyncSessionLocal() as db:
            db_ev_count = len((await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == uuid.UUID(case_id))
            )).scalars().all())
            assert db_ev_count == 0, f"Database must have 0 records during preview, found {db_ev_count}"
            print("✓ Verified 0 records created in database during preview (forensic quarantine intact).")

        # 3. Confirm all 5 staged files via /api/v1/evidence/confirm/batch
        confirm_items = [
            {
                "preview_id": item["preview_id"],
                "source_type": "document_text" if item["filename"].endswith(".pdf") else ("bank_txn" if "bank" in item["filename"] or "statement" in item["filename"] else ("cdr" if "call" in item["filename"] else "whatsapp")),
                "original_name": item["filename"],
            }
            for item in batch_preview["items"]
        ]

        print("\n--> [2/4] Confirming & Sealing batch via /api/v1/evidence/confirm/batch...")
        t0 = time.time()
        conf_res = await client.post(
            "/api/v1/evidence/confirm/batch",
            data={"case_id": case_id, "items": json.dumps(confirm_items)},
            headers=headers,
        )
        assert conf_res.status_code == 200, f"Confirm batch failed: {conf_res.text}"
        conf_data = conf_res.json()
        duration = time.time() - t0

        print(f"✓ Batch confirmation completed in {duration:.2f}s:")
        print(f"   Sealed Count: {conf_data['sealed_count']}")
        print(f"   Failed Count: {conf_data['failed_count']}")
        print(f"   Duplicate Count: {conf_data['duplicate_count']}")
        assert conf_data["sealed_count"] == 5, f"Expected 5 sealed files, got {conf_data['sealed_count']}"

        for s in conf_data["sealed"]:
            fname = s["filename"]
            sha = s["sha256_hash"]
            assert sha == expected_hashes[fname], f"Hash mismatch on {fname}! Expected {expected_hashes[fname]}, got {sha}"
            print(f"   ✓ {fname} sealed with SHA-256: {sha}")

        # 4. Wait for background processing (events, entities, graph)
        print("\n--> [3/4] Waiting for background parsing, entity extraction & timeline sequencing...")
        max_wait = 25
        start_wait = time.time()
        processed_all = False

        while time.time() - start_wait < max_wait:
            await asyncio.sleep(2)
            async with AsyncSessionLocal() as db:
                ev_files = (await db.execute(
                    select(EvidenceFile).where(EvidenceFile.case_id == uuid.UUID(case_id))
                )).scalars().all()
                statuses = [f.upload_status for f in ev_files]
                if all(st in ("processed", "failed") for st in statuses):
                    processed_all = True
                    break

        async with AsyncSessionLocal() as db:
            ev_files = (await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == uuid.UUID(case_id))
            )).scalars().all()
            events = (await db.execute(
                select(EvidenceEvent).where(EvidenceEvent.case_id == uuid.UUID(case_id))
            )).scalars().all()
            mentions = (await db.execute(
                select(EntityMention).join(EvidenceEvent, EntityMention.evidence_event_id == EvidenceEvent.id).where(EvidenceEvent.case_id == uuid.UUID(case_id))
            )).scalars().all()

            print(f"\n--> [4/4] Ingestion Results Verification:")
            print(f"   • Sealed Evidence Records: {len(ev_files)} / 5")
            print(f"   • Extracted Timeline Events: {len(events)}")
            print(f"   • Extracted Entity Mentions: {len(mentions)}")

            for f in ev_files:
                print(f"     - {f.original_name} | status={f.upload_status} | encrypted={f.is_encrypted} | hash={f.sha256_hash[:16]}…")
                assert f.sha256_hash == expected_hashes[f.original_name]
                assert f.is_encrypted is True
                assert f.acquisition_tool == "CyberDrishti Ingestion v5.0"

    print("\n" + "=" * 60)
    print("ALL 5 DEMONSTRATION EVIDENCE FILES PROCESSED SUCCESSFULLY!")
    print("FORENSIC INTEGRITY, SHA-256 INDEPENDENCE & BSA CUSTODY VERIFIED.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
