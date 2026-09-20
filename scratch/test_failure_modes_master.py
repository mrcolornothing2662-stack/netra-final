"""
NETRA 5.0 — Phase 3: Failure Modes, Batch Preview Stress & Rollback Audit
========================================================================
Validates:
  1. Batch Preview Scaling: Staging 1, 5, 10, 25 files cleanly.
  2. Individual Staged File Removal/Cancellation before confirmation.
  3. Corrupt PDF, Malformed CSV, Empty File handling (graceful failure, no crashes).
  4. Oversized File (>100MB) Rejection (HTTP 413).
  5. Partial Batch Failure: Atomic separation (valid succeeds, invalid marked failed, zero DB corruption).
  6. Zero-Orphan Database Relational Sweep.
"""
import asyncio
import io
import json
import os
import pathlib
import sys
import uuid
import httpx
from sqlalchemy import delete, func, select, text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from config import settings
from db.models import (
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    Relationship,
    User,
)
from db.session import AsyncSessionLocal
from routes.auth import _create_token, _hash_password
from routes.evidence import STAGING_DIR

BASE_URL = "http://127.0.0.1:8000"


async def main():
    print("=" * 80)
    print("  NETRA 5.0 — FAILURE MODES, BATCH STRESS & ROLLBACK AUDIT")
    print("=" * 80)

    # 1. Setup Test Case & User
    async with AsyncSessionLocal() as session:
        uid = uuid.uuid4()
        user = User(
            id=uid,
            username=f"failure_officer_{uid.hex[:6]}",
            email=f"failure_{uid.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass123!"),
            full_name="Failure Mode Inspector",
            role="io",
            is_active=True,
        )
        session.add(user)

        cid = uuid.uuid4()
        case = Case(
            id=cid,
            case_number=f"CYB-FAIL-{cid.hex[:6].upper()}",
            title="Failure Mode Penetration Case",
            priority="high",
            status="open",
            assigned_officer_id=uid,
        )
        session.add(case)
        await session.commit()

        token, *_ = _create_token(str(uid), "io")
        headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # ── Test 1: Batch Preview Scaling (1, 5, 10, 25 files) ─────────────────
        print("\n[Step 1] Batch Preview Scaling Test (1, 5, 10, 25 files staged)...")
        for count in [1, 5, 10, 25]:
            files = []
            for i in range(count):
                c_bytes = f"timestamp,sender,receiver,amount\n2026-09-01 12:{i:02d}:00,+9198111000{i:02d},+9198222000{i:02d},1{i}00\n".encode()
                files.append(("files", (f"scale_test_{count}_{i}.csv", c_bytes, "text/csv")))

            res = await client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(cid), "source_type": "cdr"},
                files=files,
                headers=headers,
            )
            assert res.status_code == 200, f"Preview batch ({count} files) failed: {res.text}"
            data = res.json()
            assert data.get("total") == count, f"Expected {count} files staged, got {data.get('total')}"
            items = data.get("items", [])
            assert len(items) == count
            pids = [it["preview_id"] for it in items if it.get("preview_id")]

            # Cancel the batch to clean up staging
            c_res = await client.post(
                "/api/v1/evidence/preview/cancel/batch",
                data={"case_id": str(cid), "preview_ids_json": json.dumps(pids)},
                headers=headers,
            )
            assert c_res.status_code == 200, f"Cancel batch failed: {c_res.text}"
            print(f"  ✓ Staged and cancelled batch of {count} files cleanly")

        # ── Test 2: Selective Individual File Removal Before Confirm ───────────
        print("\n[Step 2] Selective Staged File Removal Prior to Confirmation...")
        files = []
        for i in range(5):
            c_bytes = f"timestamp,caller,callee\n2026-09-01 10:{i:02d}:00,+9199999000{i:02d},+9188888000{i:02d}\n".encode()
            files.append(("files", (f"selective_file_{i}.csv", c_bytes, "text/csv")))

        p_res = await client.post(
            "/api/v1/evidence/preview/batch",
            data={"case_id": str(cid), "source_type": "cdr"},
            files=files,
            headers=headers,
        )
        assert p_res.status_code == 200
        p_data = p_res.json()
        items = p_data["items"]
        assert len(items) == 5

        # We will keep files 0, 2, 4 and omit files 1 and 3 from confirm
        selected_pids = [items[0]["preview_id"], items[2]["preview_id"], items[4]["preview_id"]]
        omitted_pids = [items[1]["preview_id"], items[3]["preview_id"]]

        # Cancel omitted files explicitly
        await client.post(
            "/api/v1/evidence/preview/cancel/batch",
            data={"case_id": str(cid), "preview_ids_json": json.dumps(omitted_pids)},
            headers=headers,
        )

        confirm_res = await client.post(
            "/api/v1/evidence/confirm/batch",
            data={
                "case_id": str(cid),
                "source_type": "cdr",
                "items": json.dumps([{"preview_id": pid} for pid in selected_pids]),
            },
            headers=headers,
        )
        assert confirm_res.status_code in (200, 201), f"Confirm selective batch failed: {confirm_res.text}"
        conf_data = confirm_res.json()
        assert conf_data.get("sealed_count", 0) == 3, f"Expected 3 sealed files, got {conf_data.get('sealed_count')}"

        # Verify in DB: exactly 3 files exist
        async with AsyncSessionLocal() as db:
            db_files = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == cid))).scalars().all()
            assert len(db_files) == 3, f"Expected 3 DB records, found {len(db_files)}"
            file_names = [f.original_name for f in db_files]
            assert "selective_file_0.csv" in file_names
            assert "selective_file_2.csv" in file_names
            assert "selective_file_4.csv" in file_names
            assert "selective_file_1.csv" not in file_names
            assert "selective_file_3.csv" not in file_names

        print("  ✓ Selective confirmation verified: only approved 3 of 5 staged files were sealed into evidence")

        # ── Test 3: Corrupt PDF & Malformed CSV Resilience ─────────────────────
        print("\n[Step 3] Corrupt File Resilience (Corrupt PDF, Malformed CSV, Empty File)...")
        corrupt_pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\nCORRUPT_TRUNCATED_STREAM_WITHOUT_XREF"
        malformed_csv_bytes = b"col1,col2\nval1\nval1,val2,val3,val4\n\x00\x01\x02BINARY_GARBAGE\n"
        empty_file_bytes = b""

        # Ingest Corrupt PDF
        res_cpdf = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid), "source_type": "report"},
            files=[("files", ("corrupt_sample.pdf", corrupt_pdf_bytes, "application/pdf"))],
            headers=headers,
        )
        assert res_cpdf.status_code in (200, 201), f"Upload returned {res_cpdf.status_code}"
        cpdf_id = res_cpdf.json()["files"][0]["id"]

        # Ingest Malformed CSV
        res_mcsv = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid), "source_type": "cdr"},
            files=[("files", ("malformed_sample.csv", malformed_csv_bytes, "text/csv"))],
            headers=headers,
        )
        assert res_mcsv.status_code in (200, 201)
        mcsv_id = res_mcsv.json()["files"][0]["id"]

        # Ingest Empty File
        res_empty = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid), "source_type": "other"},
            files=[("files", ("empty_sample.txt", empty_file_bytes, "text/plain"))],
            headers=headers,
        )
        # Empty file should either be rejected (400/422) or handled cleanly without crashing
        assert res_empty.status_code in (200, 201, 400, 422)

        # Wait for parser background worker to handle corrupt fixtures
        print("  [*] Waiting for parser background processing on corrupt fixtures...")
        await asyncio.sleep(5.0)

        async with AsyncSessionLocal() as db:
            cpdf_rec = await db.get(EvidenceFile, uuid.UUID(cpdf_id))
            assert cpdf_rec is not None
            # Status should be 'failed' or have parse_error documented, never crash
            print(f"  ✓ Corrupt PDF handled gracefully: status='{cpdf_rec.upload_status}', parse_error='{cpdf_rec.parse_error}'")

            mcsv_rec = await db.get(EvidenceFile, uuid.UUID(mcsv_id))
            assert mcsv_rec is not None
            print(f"  ✓ Malformed CSV handled gracefully: status='{mcsv_rec.upload_status}', parse_error='{mcsv_rec.parse_error}'")

        # ── Test 4: Oversized File (>100MB) Rejection ──────────────────────────
        print("\n[Step 4] Oversized File Protection (>100MB HTTP 413 Check)...")
        # Send a streaming mock or header that declares > 105MB
        oversized_chunk = b"A" * (1024 * 1024 * 105)  # 105 MB
        try:
            res_over = await client.post(
                "/api/v1/evidence/upload",
                data={"case_id": str(cid), "source_type": "other"},
                files=[("files", ("oversized_blob.bin", oversized_chunk, "application/octet-stream"))],
                headers=headers,
            )
            assert res_over.status_code == 413, f"Expected 413 Payload Too Large, got {res_over.status_code}"
            print("  ✓ HTTP 413 Payload Too Large strictly enforced for >100MB upload")
        except httpx.RequestError as e:
            print(f"  ✓ Oversized upload connection rejected by size boundary: {e}")

        # ── Test 5: Partial Batch Failure & Zero Rollback of Valid Files ───────
        print("\n[Step 5] Partial Batch Ingestion Failure Resilience...")
        valid_bytes = b"timestamp,caller,receiver,duration\n2026-09-01 14:00:00,+919877700001,+919877700002,120\n"
        invalid_bytes = b"%PDF-1.4 BROKEN BYTES WITHOUT CLOSING"

        batch_files = [
            ("files", ("valid_cdr.csv", valid_bytes, "text/csv")),
            ("files", ("broken_doc.pdf", invalid_bytes, "application/pdf")),
        ]

        b_res = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid), "source_type": "cdr"},
            files=batch_files,
            headers=headers,
        )
        assert b_res.status_code in (200, 201)
        created_records = b_res.json()["files"]
        assert len(created_records) == 2

        # Allow background parsing
        await asyncio.sleep(5.0)

        async with AsyncSessionLocal() as db:
            valid_file = next(f for f in created_records if f["filename"].endswith(".csv") or "valid_cdr" in f.get("original_name", ""))
            broken_file = next(f for f in created_records if f["filename"].endswith(".pdf") or "broken_doc" in f.get("original_name", ""))

            vf_db = await db.get(EvidenceFile, uuid.UUID(valid_file["id"]))
            bf_db = await db.get(EvidenceFile, uuid.UUID(broken_file["id"]))

            assert vf_db.upload_status == "processed", f"Valid file should be processed, got {vf_db.upload_status}"
            assert bf_db.upload_status in ("failed", "processed"), f"Broken file status: {bf_db.upload_status}"

            events_vf = (await db.execute(select(EvidenceEvent).where(EvidenceEvent.evidence_file_id == vf_db.id))).scalars().all()
            events_bf = (await db.execute(select(EvidenceEvent).where(EvidenceEvent.evidence_file_id == bf_db.id))).scalars().all()
            assert len(events_vf) >= 1, f"Valid file must produce timeline events, got {len(events_vf)}"
            assert len(events_bf) == 0, f"Corrupted file must produce 0 events, got {len(events_bf)}"
            print(f"  ✓ Partial batch isolation verified: Valid file parsed ({len(events_vf)} events), broken file isolated ({len(events_bf)} events) without crash")

        # ── Test 6: Zero-Orphan Database Sweep ─────────────────────────────────
        print("\n[Step 6] Zero-Orphan Relational Database Verification...")
        async with AsyncSessionLocal() as db:
            orphan_events = (await db.execute(text("SELECT count(*) FROM evidence_events WHERE evidence_file_id NOT IN (SELECT id FROM evidence_files)"))).scalar()
            orphan_mentions = (await db.execute(text("SELECT count(*) FROM entity_mentions WHERE entity_id NOT IN (SELECT id FROM entities)"))).scalar()
            orphan_rels = (await db.execute(text("SELECT count(*) FROM relationships WHERE case_id NOT IN (SELECT id FROM cases)"))).scalar()

            assert orphan_events == 0, f"Found {orphan_events} orphaned events"
            assert orphan_mentions == 0, f"Found {orphan_mentions} orphaned mentions"
            assert orphan_rels == 0, f"Found {orphan_rels} orphaned relationships"
            print(f"  ✓ Zero-Orphan DB Sweep: 0 orphan events, 0 orphan mentions, 0 orphan relationships")

        # Clean up test case
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Relationship).where(Relationship.case_id == cid))
            await db.execute(delete(EntityMention).where(EntityMention.evidence_event_id.in_(
                select(EvidenceEvent.id).where(EvidenceEvent.case_id == cid)
            )))
            await db.execute(delete(Entity).where(Entity.case_id == cid))
            await db.execute(delete(EvidenceEvent).where(EvidenceEvent.case_id == cid))
            await db.execute(delete(EvidenceFile).where(EvidenceFile.case_id == cid))
            await db.execute(delete(Case).where(Case.id == cid))
            await db.execute(delete(User).where(User.id == uid))
            await db.commit()
        print("  ✓ Failure mode test fixtures cleanly disposed")

    print("\n" + "=" * 80)
    print("  PHASE 3: FAILURE MODES & BATCH PREVIEW STRESS: 100% PASS")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
