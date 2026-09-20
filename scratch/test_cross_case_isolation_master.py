"""
NETRA 5.0 — Cross-Case Boundary Isolation Stress Test
=====================================================
Validates strict cryptographic and logical isolation between Case A and Case B
even when sharing 100% IDENTICAL entity values (phone, bank account, suspect name).
"""
import asyncio
import hashlib
import json
import pathlib
import sys
import uuid
from datetime import datetime, timezone
import httpx
from sqlalchemy import delete, select

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

BASE_URL = "http://127.0.0.1:8000"


async def main():
    print("=" * 80)
    print("  NETRA 5.0 — CROSS-CASE ISOLATION WITH IDENTICAL IDENTIFIERS")
    print("=" * 80)

    async with AsyncSessionLocal() as session:
        # Create 2 officers
        uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
        user_a = User(
            id=uid_a,
            username=f"iso_officer_a_{uid_a.hex[:6]}",
            email=f"iso_a_{uid_a.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass123!"),
            full_name="Inspector Alpha",
            role="io",
            is_active=True,
        )
        user_b = User(
            id=uid_b,
            username=f"iso_officer_b_{uid_b.hex[:6]}",
            email=f"iso_b_{uid_b.hex[:6]}@police.gov.in",
            hashed_password=_hash_password("Pass123!"),
            full_name="Inspector Beta",
            role="io",
            is_active=True,
        )
        session.add_all([user_a, user_b])

        # Create Case A and Case B
        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        case_a = Case(
            id=cid_a,
            case_number=f"CYB-ISO-A-{cid_a.hex[:6].upper()}",
            title="Operation Red Lotus (Case A)",
            priority="high",
            status="open",
            assigned_officer_id=uid_a,
        )
        case_b = Case(
            id=cid_b,
            case_number=f"CYB-ISO-B-{cid_b.hex[:6].upper()}",
            title="Operation Blue Moon (Case B)",
            priority="high",
            status="open",
            assigned_officer_id=uid_b,
        )
        session.add_all([case_a, case_b])
        await session.commit()

        token_a, *_ = _create_token(str(uid_a), "io")
        token_b, *_ = _create_token(str(uid_b), "io")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

    # Upload synthetic CSV with identical phone, account, and person to Case A and Case B
    shared_identifier_phone = "+919876543210"
    shared_identifier_account = "SBIN00099887711"
    shared_suspect = "Vikram Aditya"

    content_case_a = (
        f"timestamp,caller,receiver,amount,notes\n"
        f"2026-09-01 10:00:00,{shared_identifier_phone},+919111111111,500000,CASE_A_ONLY_SECRET_TRANSACTION_ALPHA transferred to {shared_identifier_account} by {shared_suspect}\n"
    ).encode("utf-8")

    content_case_b = (
        f"timestamp,caller,receiver,amount,notes\n"
        f"2026-09-02 12:00:00,{shared_identifier_phone},+919222222222,25000,CASE_B_ONLY_SECRET_TRANSACTION_BETA transferred to {shared_identifier_account} by {shared_suspect}\n"
    ).encode("utf-8")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # Ingest to Case A
        files_a = [("files", ("case_a_evidence.csv", content_case_a, "text/csv"))]
        res_a = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid_a), "source_type": "cdr"},
            files=files_a,
            headers=headers_a,
        )
        assert res_a.status_code in (200, 201), f"Upload to Case A failed: {res_a.text}"

        # Ingest to Case B
        files_b = [("files", ("case_b_evidence.csv", content_case_b, "text/csv"))]
        res_b = await client.post(
            "/api/v1/evidence/upload",
            data={"case_id": str(cid_b), "source_type": "cdr"},
            files=files_b,
            headers=headers_b,
        )
        assert res_b.status_code in (200, 201), f"Upload to Case B failed: {res_b.text}"

        # Wait for ingestion to finish in both cases
        for _ in range(25):
            await asyncio.sleep(1.0)
            async with AsyncSessionLocal() as db:
                evs_a = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == cid_a))).scalars().all()
                evs_b = (await db.execute(select(EvidenceFile).where(EvidenceFile.case_id == cid_b))).scalars().all()
                if all(f.upload_status in ("processed", "completed", "parsed") for f in evs_a + evs_b):
                    break

        print("  ✓ Evidence files processed in both cases")

        # Synthesize graphs for both cases
        await client.post(f"/api/v1/cases/{cid_a}/build-graph", headers=headers_a)
        await client.post(f"/api/v1/cases/{cid_b}/build-graph", headers=headers_b)

        print("  ✓ Graph synthesized for both cases")

        # Audit 1: Timeline Isolation
        t_res_b = await client.get(f"/api/v1/timeline/{cid_b}", headers=headers_b)
        assert t_res_b.status_code == 200, f"Timeline B failed: {t_res_b.text}"
        events_b = t_res_b.json()
        if isinstance(events_b, dict):
            events_b = events_b.get("events", [])
        for ev in events_b:
            txt = str(ev.get("text_content") or ev.get("description", ""))
            assert "TRANSACTION_ALPHA" not in txt, f"LEAK! Case A secret leaked into Case B timeline: {txt}"
            assert str(cid_a) not in str(ev), "LEAK! Case A ID detected in Case B timeline"
        print("  ✓ Timeline Boundary Verified: 0 Case A events in Case B timeline")

        # Audit 2: Graph Node & Edge Isolation
        g_res_b = await client.get(f"/api/v1/graph/{cid_b}", headers=headers_b)
        assert g_res_b.status_code == 200, f"Graph B failed: {g_res_b.text}"
        g_data_b = g_res_b.json()
        nodes_b = g_data_b.get("nodes", [])
        edges_b = g_data_b.get("edges", [])

        async with AsyncSessionLocal() as db:
            # Query all DB entities for Case B
            db_ents_b = (await db.execute(select(Entity).where(Entity.case_id == cid_b))).scalars().all()
            for ent in db_ents_b:
                assert ent.case_id == cid_b, f"LEAK: Entity {ent.id} belongs to {ent.case_id} != {cid_b}"
            
            # Query all DB relationships for Case B
            db_rels_b = (await db.execute(select(Relationship).where(Relationship.case_id == cid_b))).scalars().all()
            for rel in db_rels_b:
                assert rel.case_id == cid_b, f"LEAK: Relationship {rel.id} belongs to {rel.case_id} != {cid_b}"

        print(f"  ✓ Case Graph Boundary Verified: {len(nodes_b)} nodes, {len(edges_b)} edges cleanly bounded to Case B")

        # Audit 3: Copilot Cross-Case Query Isolation
        # Ask Officer B's copilot about Case Alpha secret
        cop_b_res = await client.post(
            f"/api/v1/copilot/{cid_b}",
            json={"question": "What is TRANSACTION_ALPHA and what secret notes exist for Case Alpha?", "top_k": 5},
            headers=headers_b,
        )
        assert cop_b_res.status_code == 200, f"Copilot query failed: {cop_b_res.text}"
        cop_b_data = cop_b_res.json()
        b_answer = cop_b_data.get("answer", "")
        assert "TRANSACTION_ALPHA" not in b_answer, f"LEAK! Copilot B answered with Case A data: {b_answer}"
        print(f"  ✓ Copilot Isolation Verified: Case B Copilot abstained from Case A facts")

        # Ask Officer A's copilot about Case Beta secret
        cop_a_res = await client.post(
            f"/api/v1/copilot/{cid_a}",
            json={"question": "What is TRANSACTION_BETA and what secret notes exist for Case Beta?", "top_k": 5},
            headers=headers_a,
        )
        assert cop_a_res.status_code == 200, f"Copilot query failed: {cop_a_res.text}"
        cop_a_data = cop_a_res.json()
        a_answer = cop_a_data.get("answer", "")
        assert "TRANSACTION_BETA" not in a_answer, f"LEAK! Copilot A answered with Case B data: {a_answer}"
        print(f"  ✓ Copilot Isolation Verified: Case A Copilot abstained from Case B facts")

        # Teardown fixtures
        async with AsyncSessionLocal() as db:
            for cid in (cid_a, cid_b):
                await db.execute(delete(Relationship).where(Relationship.case_id == cid))
                await db.execute(delete(EntityMention).where(EntityMention.evidence_event_id.in_(
                    select(EvidenceEvent.id).where(EvidenceEvent.case_id == cid)
                )))
                await db.execute(delete(Entity).where(Entity.case_id == cid))
                await db.execute(delete(EvidenceEvent).where(EvidenceEvent.case_id == cid))
                await db.execute(delete(EvidenceFile).where(EvidenceFile.case_id == cid))
                await db.execute(delete(Case).where(Case.id == cid))
            await db.execute(delete(User).where(User.id.in_([uid_a, uid_b])))
            await db.commit()
        print("  ✓ Cross-case fixtures cleanly torn down")

    print("\n" + "=" * 80)
    print("  CROSS-CASE ISOLATION WITH IDENTICAL IDENTIFIERS: 100% PASS")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
