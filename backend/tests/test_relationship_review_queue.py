import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from db.models import Case, CaseCollaborator, Entity, Relationship, User
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_relationship_review_queue_and_adjudication():
    async with AsyncSessionLocal() as db:
        constable = User(
            id=uuid.uuid4(),
            username=f"constable_{uuid.uuid4().hex[:6]}",
            email=f"constable_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="constable",
            hashed_password="hash",
            is_active=True,
        )
        io = User(
            id=uuid.uuid4(),
            username=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            email=f"io_{uuid.uuid4().hex[:6]}@police.gov.in",
            role="io",
            hashed_password="hash",
            is_active=True,
        )
        case = Case(
            id=uuid.uuid4(),
            case_number=f"QUEUE-{uuid.uuid4().hex[:6]}",
            title="Review Queue Test Case",
            status="open",
            state_version=1,
            assigned_officer_id=io.id,
        )
        collab_constable = CaseCollaborator(
            id=uuid.uuid4(),
            case_id=case.id,
            user_id=constable.id,
            role="io",
        )
        e1 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Acc-Alpha", entity_type="ACCOUNT")
        e2 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Acc-Beta", entity_type="ACCOUNT")
        e3 = Entity(id=uuid.uuid4(), case_id=case.id, canonical_value="Acc-Gamma", entity_type="ACCOUNT")

        # Inferred unreviewed edge (should be in pending review queue)
        rel_inferred = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e2.id,
            relationship_type=RT.CONNECTED_TO,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_UNREVIEWED,
            confidence=0.85,
        )
        # Observed edge (already canonical)
        rel_observed = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=e1.id,
            target_entity_id=e3.id,
            relationship_type=RT.TRANSFERRED_TO,
            epistemic_status=RT.OBSERVED,
            verification_status=RT.REVIEW_UNREVIEWED,
            confidence=1.0,
        )
        db.add_all([case, constable, io, collab_constable, e1, e2, e3, rel_inferred, rel_observed])
        await db.commit()

        io_token, _, _ = _create_access_token(str(io.id), io.role)
        constable_token, _, _ = _create_access_token(str(constable.id), constable.role)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test canonical_sql_predicate filter on GET /api/v1/relationships/{case_id}
        res_canon = await client.get(
            f"/api/v1/relationships/{case.id}?is_canonical=true",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_canon.status_code == 200
        canon_data = res_canon.json()
        assert canon_data["canonical_count"] >= 1
        canon_ids = {r["id"] for r in canon_data["relationships"]}
        assert str(rel_observed.id) in canon_ids
        assert str(rel_inferred.id) not in canon_ids

        res_non_canon = await client.get(
            f"/api/v1/relationships/{case.id}?is_canonical=false",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_non_canon.status_code == 200
        non_canon_ids = {r["id"] for r in res_non_canon.json()["relationships"]}
        assert str(rel_inferred.id) in non_canon_ids
        assert str(rel_observed.id) not in non_canon_ids

        # 2. Test GET /api/v1/relationships/{case_id}/review-queue
        res_queue = await client.get(
            f"/api/v1/relationships/{case.id}/review-queue",
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_queue.status_code == 200
        qdata = res_queue.json()
        assert qdata["pending_count"] >= 1
        assert qdata["capabilities"]["can_confirm"] is True
        assert qdata["capabilities"]["can_reject"] is True

        queue_ids = {item["id"] for item in qdata["review_queue"]}
        assert str(rel_inferred.id) in queue_ids

        # 3. Test Constable attempting review -> 403 Forbidden
        res_deny = await client.post(
            f"/api/v1/relationships/{case.id}/{rel_inferred.id}/review",
            json={"verdict": "accept", "reason": "Officer note"},
            headers={"Authorization": f"Bearer {constable_token}"},
        )
        assert res_deny.status_code == 403

        # 4. Test IO approving the relationship -> Dispatched through Investigation Brain
        res_accept = await client.post(
            f"/api/v1/relationships/{case.id}/{rel_inferred.id}/review",
            json={"verdict": "accept", "reason": "Verified against transaction ledger"},
            headers={"Authorization": f"Bearer {io_token}"},
        )
        assert res_accept.status_code == 200
        accept_data = res_accept.json()
        assert accept_data["success"] is True
        assert accept_data["new_state_version"] == 2

    # Verify database state after acceptance
    async with AsyncSessionLocal() as db:
        updated_case = await db.get(Case, case.id)
        updated_rel = await db.get(Relationship, rel_inferred.id)
        assert updated_case.state_version == 2
        assert updated_rel.verification_status == RT.REVIEW_ACCEPTED
        assert updated_rel.is_canonical is True
        assert updated_rel.verified_by == io.id
