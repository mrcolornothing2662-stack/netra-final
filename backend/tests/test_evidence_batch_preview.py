"""
NETRA 5.0 — Forensic Evidence Batch Pre-Hash Preview & Sealing Acceptance Test Suite

Tests:
1. Batch Preview Stages Multiple Files without creating database records.
2. Preview Metadata & Viewports Extracted Independently per file in batch.
3. Batch Cancel Safely Purges All Staged Quarantine Files.
4. Batch Confirm Computes Authoritative SHA-256 for Each File and Seals Evidence Records.
5. Partial Batch Failure: 1 invalid/failed file does NOT rollback valid sealed evidence files.
6. Duplicate Detection: Duplicate files in a batch are detected via SHA-256 without aborting other files.
7. ZIP Inside Batch: Archive container extracts members with individual EvidenceFile records & hashes.
8. Case Isolation & RBAC Security: Cross-case or unauthorized batch preview/confirm rejected (404/401).
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import uuid
import zipfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from db.models import Case, EvidenceFile, User
from db.session import AsyncSessionLocal
from main import create_app
from routes.auth import _create_token, _hash_password
from routes.evidence import STAGING_DIR


@pytest.mark.asyncio
async def test_batch_preview_stages_files_without_db_records():
    """Requirement: Selecting multiple files stages previews without creating EvidenceFile rows."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        user = User(
            username=f"officer_batch_{uuid.uuid4().hex[:6]}",
            email=f"officer_batch_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Batch Forensic Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        case = Case(
            case_number=f"BATCH-{uuid.uuid4().hex[:6].upper()}",
            title="Batch Ingestion Test Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        token, *_ = _create_token(str(user.id), "io")

        files = [
            ("files", ("01_case_registration.txt", b"FIR Registration Details: Offense reported under Sec 66D IT Act.", "text/plain")),
            ("files", ("02_bank_statement.csv", b"Account,Amount,Date\nAC-1001,45000,2026-09-01\nAC-1002,12000,2026-09-02\n", "text/csv")),
            ("files", ("03_chat_export.txt", b"Investigator: Has the suspect been located?\nOfficer: Tracing IP in sector 4.", "text/plain")),
        ]

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case.id), "source_type": "unknown"},
                files=files,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["total"] == 3
            assert len(data["items"]) == 3

            preview_ids = []
            for item in data["items"]:
                assert item["status"] == "unhashed_preview"
                assert "STATUS: PRE-HASH PREVIEW" in item["warning"]
                assert item["preview_id"] is not None
                assert item["file_size_bytes"] > 0
                assert "metadata" in item
                preview_ids.append(item["preview_id"])

            # Verify ZERO EvidenceFile records in database after preview
            post_preview_count = len((await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == case.id)
            )).scalars().all())
            assert post_preview_count == 0, "Batch preview must never insert database records"

            # Verify staged quarantine files exist on disk
            case_staging = STAGING_DIR / str(case.id)
            for pid in preview_ids:
                matches = list(case_staging.glob(f"{pid}*"))
                assert len(matches) == 1, f"Staged quarantine file for {pid} must exist"

            # Cancel the batch
            cancel_resp = client.post(
                "/api/v1/evidence/preview/cancel/batch",
                data={"case_id": str(case.id), "preview_ids": preview_ids},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert cancel_resp.status_code == 200
            assert cancel_resp.json()["status"] == "discarded"
            assert cancel_resp.json()["purged_count"] == 3

            # Verify quarantine files were wiped
            for pid in preview_ids:
                matches = list(case_staging.glob(f"{pid}*"))
                assert len(matches) == 0, f"Staged quarantine file for {pid} must be purged after cancel"


@pytest.mark.asyncio
async def test_batch_confirm_independent_hashes_and_sealing():
    """Requirement: Every file receives its OWN SHA-256, evidence record, and background task."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        user = User(
            username=f"officer_seal_{uuid.uuid4().hex[:6]}",
            email=f"officer_seal_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Sealing Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        case = Case(
            case_number=f"SEAL-{uuid.uuid4().hex[:6].upper()}",
            title="Batch Sealing Test Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        token, *_ = _create_token(str(user.id), "io")

        file1_bytes = b"PDF-1-RAW-CONTENT-MOCK"
        file2_bytes = b"CSV-2-TRANSACTIONS-MOCK,100,200"
        file3_bytes = b"TXT-3-CHAT-LOG-SUSPECT-COMMUNICATION"

        expected_hash1 = hashlib.sha256(file1_bytes).hexdigest()
        expected_hash2 = hashlib.sha256(file2_bytes).hexdigest()
        expected_hash3 = hashlib.sha256(file3_bytes).hexdigest()

        with TestClient(app) as client:
            # Step 1: Stage batch preview
            files = [
                ("files", ("01_doc.pdf", file1_bytes, "application/pdf")),
                ("files", ("02_stmt.csv", file2_bytes, "text/csv")),
                ("files", ("03_chat.txt", file3_bytes, "text/plain")),
            ]
            prev_resp = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case.id), "source_type": "unknown"},
                files=files,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert prev_resp.status_code == 200
            prev_items = prev_resp.json()["items"]
            assert len(prev_items) == 3

            confirm_payload = [
                {"preview_id": prev_items[0]["preview_id"], "source_type": "document_text", "original_name": "01_doc.pdf"},
                {"preview_id": prev_items[1]["preview_id"], "source_type": "bank_txn", "original_name": "02_stmt.csv"},
                {"preview_id": prev_items[2]["preview_id"], "source_type": "whatsapp", "original_name": "03_chat.txt"},
            ]

            # Step 2: Confirm batch
            conf_resp = client.post(
                "/api/v1/evidence/confirm/batch",
                data={"case_id": str(case.id), "items": json.dumps(confirm_payload)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert conf_resp.status_code == 200, conf_resp.text
            conf_data = conf_resp.json()
            assert conf_data["status"] == "batch_completed"
            assert conf_data["sealed_count"] == 3
            assert conf_data["failed_count"] == 0

            sealed_files = conf_data["sealed"]
            assert len(sealed_files) == 3

            returned_hashes = {f["filename"]: f["sha256_hash"] for f in sealed_files}
            assert returned_hashes["01_doc.pdf"] == expected_hash1
            assert returned_hashes["02_stmt.csv"] == expected_hash2
            assert returned_hashes["03_chat.txt"] == expected_hash3

            # Verify database records in DB
            db_records = (await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == case.id)
            )).scalars().all()
            assert len(db_records) == 3

            db_hashes = {r.original_name: r.sha256_hash for r in db_records}
            assert db_hashes["01_doc.pdf"] == expected_hash1
            assert db_hashes["02_stmt.csv"] == expected_hash2
            assert db_hashes["03_chat.txt"] == expected_hash3

            for r in db_records:
                assert r.is_encrypted is True
                assert r.encrypted_dek is not None
                assert r.acquisition_tool == "CyberDrishti Ingestion v5.0"
                assert pathlib.Path(r.storage_path).exists()


@pytest.mark.asyncio
async def test_batch_partial_failure_does_not_rollback_valid_files():
    """Requirement: 1 failed file does NOT roll back already valid evidence files."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        user = User(
            username=f"officer_partial_{uuid.uuid4().hex[:6]}",
            email=f"officer_partial_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Partial Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        case = Case(
            case_number=f"PARTIAL-{uuid.uuid4().hex[:6].upper()}",
            title="Partial Failure Test Case",
            priority="medium",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        token, *_ = _create_token(str(user.id), "io")

        # Stage two valid files
        valid_bytes1 = b"Valid content 1"
        valid_bytes2 = b"Valid content 2"
        files = [
            ("files", ("valid_1.txt", valid_bytes1, "text/plain")),
            ("files", ("valid_2.txt", valid_bytes2, "text/plain")),
        ]

        with TestClient(app) as client:
            prev_resp = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case.id), "source_type": "unknown"},
                files=files,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert prev_resp.status_code == 200
            prev_items = prev_resp.json()["items"]

            # Confirm 3 items: 2 valid and 1 non-existent/bogus preview_id
            confirm_payload = [
                {"preview_id": prev_items[0]["preview_id"], "source_type": "document_text", "original_name": "valid_1.txt"},
                {"preview_id": "non_existent_fake_preview_id", "source_type": "unknown", "original_name": "corrupt_file.xyz"},
                {"preview_id": prev_items[1]["preview_id"], "source_type": "document_text", "original_name": "valid_2.txt"},
            ]

            conf_resp = client.post(
                "/api/v1/evidence/confirm/batch",
                data={"case_id": str(case.id), "items": json.dumps(confirm_payload)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert conf_resp.status_code == 200
            conf_data = conf_resp.json()

            assert conf_data["status"] == "batch_completed"
            assert conf_data["sealed_count"] == 2
            assert conf_data["failed_count"] == 1
            assert len(conf_data["failed"]) == 1
            assert conf_data["failed"][0]["filename"] == "corrupt_file.xyz"

            # Verify DB still has the 2 successfully sealed files
            db_records = (await db.execute(
                select(EvidenceFile).where(EvidenceFile.case_id == case.id)
            )).scalars().all()
            assert len(db_records) == 2
            saved_names = {r.original_name for r in db_records}
            assert "valid_1.txt" in saved_names
            assert "valid_2.txt" in saved_names


@pytest.mark.asyncio
async def test_batch_duplicate_detection_preserves_policy():
    """Requirement: Duplicates within a batch or against existing evidence are handled gracefully."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        user = User(
            username=f"officer_dup_{uuid.uuid4().hex[:6]}",
            email=f"officer_dup_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Dup Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        case = Case(
            case_number=f"DUP-{uuid.uuid4().hex[:6].upper()}",
            title="Batch Duplicate Test Case",
            priority="low",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        token, *_ = _create_token(str(user.id), "io")

        shared_bytes = b"IDENTICAL-FORENSIC-PAYLOAD-FOR-DEDUPLICATION-TEST"
        unique_bytes = b"COMPLETELY-DIFFERENT-PAYLOAD-FOR-UNIQUE-TEST"

        files = [
            ("files", ("file_copy_a.txt", shared_bytes, "text/plain")),
            ("files", ("file_copy_b.txt", shared_bytes, "text/plain")),
            ("files", ("unique_file.txt", unique_bytes, "text/plain")),
        ]

        with TestClient(app) as client:
            prev_resp = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case.id)},
                files=files,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert prev_resp.status_code == 200
            items = prev_resp.json()["items"]
            assert len(items) == 3

            conf_payload = [{"preview_id": it["preview_id"], "original_name": it["filename"]} for it in items]
            conf_resp = client.post(
                "/api/v1/evidence/confirm/batch",
                data={"case_id": str(case.id), "items": json.dumps(conf_payload)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert conf_resp.status_code == 200
            conf_data = conf_resp.json()

            # 2 unique files sealed, 1 duplicate detected
            assert conf_data["sealed_count"] == 2
            assert conf_data["duplicate_count"] == 1
            assert len(conf_data["duplicates"]) == 1
            assert conf_data["duplicates"][0]["sha256_hash"] == hashlib.sha256(shared_bytes).hexdigest()


@pytest.mark.asyncio
async def test_batch_zip_container_extraction():
    """Requirement: ZIP file in batch extracts member evidence files with distinct SHA-256 and records."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        user = User(
            username=f"officer_zip_{uuid.uuid4().hex[:6]}",
            email=f"officer_zip_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Zip Officer",
            role="io",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        case = Case(
            case_number=f"ZIP-{uuid.uuid4().hex[:6].upper()}",
            title="Batch Zip Container Case",
            priority="high",
            status="open",
            assigned_officer_id=user.id,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        token, *_ = _create_token(str(user.id), "io")

        # Create in-memory ZIP with 2 files
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            zf.writestr("member_1.txt", "Archive member 1 contents")
            zf.writestr("member_2.csv", "ColA,ColB\n1,2\n3,4\n")
        zip_bytes = zip_buffer.getvalue()

        standalone_bytes = b"Standalone file outside zip"

        files = [
            ("files", ("archive.zip", zip_bytes, "application/zip")),
            ("files", ("standalone.txt", standalone_bytes, "text/plain")),
        ]

        with TestClient(app) as client:
            prev_resp = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case.id)},
                files=files,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert prev_resp.status_code == 200
            items = prev_resp.json()["items"]
            assert len(items) == 2

            # Verify preview metadata shows members for zip
            zip_item = next(i for i in items if i["filename"] == "archive.zip")
            assert zip_item["preview"]["member_count"] == 2
            assert "member_1.txt" in zip_item["preview"]["members"]

            conf_payload = [{"preview_id": it["preview_id"], "original_name": it["filename"]} for it in items]
            conf_resp = client.post(
                "/api/v1/evidence/confirm/batch",
                data={"case_id": str(case.id), "items": json.dumps(conf_payload)},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert conf_resp.status_code == 200
            conf_data = conf_resp.json()

            # Parent archive.zip + 2 members extracted from zip + 1 standalone file = 4 total sealed evidence records
            assert conf_data["sealed_count"] == 4
            sealed_names = {f["filename"] for f in conf_data["sealed"]}
            assert "archive.zip" in sealed_names
            assert "member_1.txt" in sealed_names
            assert "member_2.csv" in sealed_names
            assert "standalone.txt" in sealed_names


@pytest.mark.asyncio
async def test_batch_case_isolation_and_rbac():
    """Requirement: Multi-tenant isolation and authentication enforced on batch endpoints."""
    app = create_app()

    async with AsyncSessionLocal() as db:
        officer_a = User(
            username=f"io_iso_a_{uuid.uuid4().hex[:6]}",
            email=f"io_iso_a_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Officer Iso Alpha",
            role="io",
            is_active=True,
        )
        officer_b = User(
            username=f"io_iso_b_{uuid.uuid4().hex[:6]}",
            email=f"io_iso_b_{uuid.uuid4().hex[:6]}@police.gov.in",
            hashed_password=_hash_password("pass123"),
            full_name="Officer Iso Beta",
            role="io",
            is_active=True,
        )
        db.add_all([officer_a, officer_b])
        await db.commit()

        case_a = Case(
            case_number=f"ISOB-{uuid.uuid4().hex[:6].upper()}",
            title="Batch Isolation Case A",
            priority="high",
            status="open",
            assigned_officer_id=officer_a.id,
        )
        db.add(case_a)
        await db.commit()

        token_b, *_ = _create_token(str(officer_b.id), "io")
        headers_b = {"Authorization": f"Bearer {token_b}"}

        files = [("files", ("test.txt", b"secret data", "text/plain"))]

        with TestClient(app) as client:
            # 1. Unauthenticated batch preview -> 401
            no_auth = client.post("/api/v1/evidence/preview/batch", data={"case_id": str(case_a.id)}, files=files)
            assert no_auth.status_code == 401

            # 2. Officer B accessing Officer A's case -> 404
            cross_case = client.post(
                "/api/v1/evidence/preview/batch",
                data={"case_id": str(case_a.id)},
                files=files,
                headers=headers_b,
            )
            assert cross_case.status_code == 404

            # 3. Cross-case batch confirmation -> 404
            cross_conf = client.post(
                "/api/v1/evidence/confirm/batch",
                data={"case_id": str(case_a.id), "preview_ids": ["fake_pid"]},
                headers=headers_b,
            )
            assert cross_conf.status_code == 404
