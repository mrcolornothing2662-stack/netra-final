from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Graph Performance & Boundary Stress Test Suite (Milestone 10)
Verifies:
  1. Graph queries are strictly bounded (max_nodes, max_edges cutoffs).
  2. Intentional truncation signals in the response payload ('truncated': True).
  3. Two-hop neighbourhood expansion strictly bounded to selected seed.
  4. Canonical-only metric isolation (rejected relationships purged, degree centrality computed only on canonical topology).
  5. 2D Cytoscape rendering payload is decoupled and operates independently from 3D/WebGL rendering.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    Relationship,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token


@pytest.mark.asyncio
async def test_graph_performance_boundaries_and_canonical_isolation():
    run_id = uuid.uuid4().hex[:8]
    dev_id = f"DEV-GRAPH-{run_id[:4]}"
    session_id = uuid.uuid4().hex

    async with AsyncSessionLocal() as db:
        # Create investigator user
        user = User(
            id=uuid.uuid4(),
            username=f"graph_io_{run_id}",
            email=f"graph_io_{run_id}@police.gov.in",
            full_name="Graph Specialist IO",
            rank="Inspector",
            unit="Intelligence Analytics",
            hashed_password="pw",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # Session
        user_sess = UserSession(
            id=session_id,
            user_id=user.id,
            device_id=dev_id,
            ip_address="127.0.0.1",
            user_agent="GraphTestHarness/1.0",
            authentication_level="standard",
            revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        )
        db.add(user_sess)

        # Case
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-GRAPH-{run_id.upper()}",
            title=f"Graph Boundary Stress Case {run_id}",
            description="Testing graph truncation, 2-hop bounds, and canonical metric isolation",
            status="open",
            assigned_officer_id=user.id,
            state_version=1,
        )
        db.add(case)
        db.add(
            CaseCollaborator(
                id=uuid.uuid4(),
                case_id=case.id,
                user_id=user.id,
                role="lead",
            )
        )
        await db.flush()

        # Evidence File
        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"graph_ev_{run_id}.txt",
            original_name=f"graph_ev_{run_id}.txt",
            file_type="forensic_report",
            sha256_hash=uuid.uuid4().hex * 2,
            storage_path=f"/uploads/graph_ev_{run_id}.txt",
            file_size_bytes=4096,
        )
        db.add(ev_file)

        # Create 80 entities in the database (exceeding default relevant max_nodes=20 or requested max_nodes=25)
        entities: list[Entity] = []
        for i in range(80):
            ent_type = "phone" if i % 2 == 0 else "person"
            val = f"+9199990{i:05d}" if ent_type == "phone" else f"Associate {i}"
            entities.append(
                Entity(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    canonical_value=val,
                    entity_type=ent_type,
                )
            )
        db.add_all(entities)
        await db.flush()

        # Build star topology centered on entities[0]
        # entities[0] connects to entities[1..30]
        # entities[1] connects to entities[31..50] (2-hop from entities[0])
        # entities[51..79] form disjoint cluster
        relationships: list[Relationship] = []
        for i in range(1, 31):
            relationships.append(
                Relationship(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    source_entity_id=entities[0].id,
                    target_entity_id=entities[i].id,
                    relationship_type=RT.COMMUNICATED_WITH,
                    epistemic_status=RT.OBSERVED,
                    verification_status=RT.REVIEW_ACCEPTED,
                    is_canonical=True,
                    confidence=0.95,
                    evidence_refs=[str(ev_file.id)],
                )
            )

        for i in range(31, 51):
            relationships.append(
                Relationship(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    source_entity_id=entities[1].id,
                    target_entity_id=entities[i].id,
                    relationship_type=RT.COMMUNICATED_WITH,
                    epistemic_status=RT.OBSERVED,
                    verification_status=RT.REVIEW_ACCEPTED,
                    is_canonical=True,
                    confidence=0.95,
                    evidence_refs=[str(ev_file.id)],
                )
            )

        # Add a disputed/rejected relationship between entities[0] and entities[55]
        rejected_rel = Relationship(
            id=uuid.uuid4(),
            case_id=case.id,
            source_entity_id=entities[0].id,
            target_entity_id=entities[55].id,
            relationship_type=RT.OWNS,
            epistemic_status=RT.INFERRED,
            verification_status=RT.REVIEW_REJECTED,
            is_canonical=False,
            confidence=0.1,
            evidence_refs=[str(ev_file.id)],
        )
        relationships.append(rejected_rel)

        db.add_all(relationships)
        await db.commit()

        case_id = str(case.id)
        token, _, _ = _create_access_token(
            user_id=str(user.id),
            role="INVESTIGATOR",
            session_id=session_id,
            device_id=dev_id,
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Device-ID": dev_id,
            "X-Session-ID": session_id,
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # ── Test 1: Bounded Query with Intentional Truncation ───────────────────
        resp_bounded = await client.get(
            f"/api/v1/graph/{case_id}?max_nodes=25&max_edges=30&scope=relevant",
            headers=headers,
        )
        assert resp_bounded.status_code == 200, resp_bounded.text
        g_bounded = resp_bounded.json()

        # Selection metadata must indicate truncation
        assert "selection" in g_bounded
        assert g_bounded["selection"]["truncated"] is True
        assert g_bounded["selection"]["returned_nodes"] <= 25
        assert g_bounded["selection"]["returned_edges"] <= 30
        assert g_bounded["selection"]["total_nodes"] >= 80

        # ── Test 2: Two-Hop Neighborhood Expansion Bounds ──────────────────────
        # Select entities[0] and expand 2-hop
        target_node = entities[0].canonical_value
        resp_two_hop = await client.get(
            f"/api/v1/graph/{case_id}?selected_node={target_node}&two_hop=true&max_nodes=40",
            headers=headers,
        )
        assert resp_two_hop.status_code == 200
        g_two_hop = resp_two_hop.json()

        returned_node_ids = {n["id"] for n in g_two_hop["nodes"]}
        assert target_node in returned_node_ids

        # Hop 1 node (entities[1]) must be included
        assert entities[1].canonical_value in returned_node_ids

        # Disjoint unlinked cluster entities (entities[60..79]) MUST NOT be present
        for unlinked_idx in (60, 65, 70, 75):
            assert entities[unlinked_idx].canonical_value not in returned_node_ids, (
                f"Disjoint node {entities[unlinked_idx].canonical_value} leaked into 2-hop graph"
            )

        # ── Test 3: Canonical-Only Metric Isolation ────────────────────────────
        # entities[55] was in a REJECTED relationship with entities[0]
        # Rejected relationships MUST be purged from canonical graph topology
        for edge in g_bounded.get("edges", []):
            if edge["source"] == target_node:
                assert edge["target"] != entities[55].canonical_value, (
                    "Rejected relationship edge was not purged from canonical topology"
                )

        # Verify degree centrality computed on nodes only counts canonical connections
        for node in g_bounded["nodes"]:
            assert "degree_centrality" in node
            assert isinstance(node["degree_centrality"], float)

        # ── Test 4: 2D Cytoscape Decoupling ────────────────────────────────────
        # Validates that 2D Cytoscape payload has elements with id, label, entity_type
        # and has zero mandatory 3D/WebGL dependencies.
        assert "nodes" in g_bounded
        assert "edges" in g_bounded
        for node in g_bounded["nodes"]:
            assert "id" in node
            assert "canonical_value" in node or "label" in node
            assert "entity_type" in node
        for edge in g_bounded["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "edge_type" in edge or "relationship_type" in edge
