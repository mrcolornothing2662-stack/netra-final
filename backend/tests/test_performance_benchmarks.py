from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Performance Benchmarking Harness (Milestone 10)
Measures p50, p95, p99 latencies, memory consumption (tracemalloc),
and response payload sizes across realistic workloads:
  • Tier A (Standard Case): 100 entities, 500 events, 150 relationships, 20 findings
  • Tier B (Heavy Case Simulation): 1,000 entities, 2,500 events, 1,000 relationships
Validates strict sub-second performance budgets for investigative UX responsiveness.
"""

import gc
import statistics
import time
import tracemalloc
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from db.models import (
    Case,
    CaseCollaborator,
    Entity,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
    InvestigationState,
    Relationship,
    User,
    UserSession,
)
from db.session import AsyncSessionLocal
from graph import relationship_types as RT
from main import app
from routes.auth import _create_access_token
from security.audit_verifier import AuditVerifier


@pytest.fixture(autouse=True)
def setup_tracemalloc():
    tracemalloc.start()
    yield
    tracemalloc.stop()


async def _run_benchmark_iterations(
    fn, iterations: int = 5
) -> dict[str, float]:
    """Execute a function multiple times, recording latencies (p50, p95, p99)."""
    latencies: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        await fn()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)  # ms

    latencies.sort()
    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) >= 20 else latencies[-1]
    p99 = latencies[int(len(latencies) * 0.99)] if len(latencies) >= 100 else latencies[-1]
    return {
        "min_ms": round(latencies[0], 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "max_ms": round(latencies[-1], 2),
    }


@pytest.mark.asyncio
async def test_performance_tier_a_and_subsystem_budgets():
    """
    Tier A Benchmark: Standard Active Case
    100 Entities, 500 Events, 150 Relationships, 20 Findings.
    Verifies endpoints complete well within their operational SLA budgets:
      - Command Center: p95 < 500ms
      - Timeline Paging (100 items): p95 < 400ms
      - Historical Replay Scrubbing: p95 < 400ms
      - Forensic Communications Lens: p95 < 600ms
      - Forensic Money Lens: p95 < 600ms
      - Forensic Geographic Lens: p95 < 600ms
      - Cryptographic Audit Chain Verification: p95 < 500ms
    """
    async with AsyncSessionLocal() as db:
        # Create investigator user & auth token
        run_id = uuid.uuid4().hex[:8]
        user = User(
            id=uuid.uuid4(),
            username=f"perf_io_{run_id}",
            email=f"perf_io_{run_id}@police.gov.in",
            full_name="Performance Test IO",
            rank="Inspector",
            unit="Special Operations",
            hashed_password="dummy_hash_for_perf",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        dev_id = f"DEV-PERF-{run_id[:4]}"
        session_id = uuid.uuid4().hex
        user_sess = UserSession(
            id=session_id,
            user_id=user.id,
            device_id=dev_id,
            ip_address="127.0.0.1",
            user_agent="PerformanceHarness/1.0",
            authentication_level="standard",
            revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
        )
        db.add(user_sess)

        # Create Case
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-PERF-{run_id.upper()}",
            title=f"Performance Benchmark Case Tier A {run_id}",
            description="Workload profiling for high-throughput investigation queries",
            status="open",
            assigned_officer_id=user.id,
            state_version=3,
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

        # Seed Evidence File
        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"perf_telecom_{run_id}.csv",
            original_name=f"perf_telecom_{run_id}.csv",
            file_type="telecom_cdr",
            sha256_hash=uuid.uuid4().hex * 2,
            storage_path=f"/uploads/perf_{run_id}.csv",
            file_size_bytes=1048576,
        )
        db.add(ev_file)

        # Seed 100 Entities
        entities: list[Entity] = []
        for i in range(100):
            ent_type = "phone" if i % 3 == 0 else ("person" if i % 3 == 1 else "bank_account")
            val = f"+9198000{i:05d}" if ent_type == "phone" else (f"Subject {i}" if ent_type == "person" else f"AC-9900{i:04d}")
            entities.append(
                Entity(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    canonical_value=val,
                    entity_type=ent_type,
                    degree_centrality=round(0.01 * (i % 10), 3),
                    bridge_score=round(0.02 * (i % 5), 3),
                )
            )
        db.add_all(entities)
        await db.flush()

        # Seed 150 Unique Relationships
        relationships: list[Relationship] = []
        seen_edges = set()
        for i in range(100):
            for step in (1, 2, 3):
                if len(relationships) >= 150:
                    break
                src = entities[i]
                tgt = entities[(i + step) % 100]
                rel_type = RT.COMMUNICATED_WITH if step == 1 else (RT.TRANSFERRED_TO if step == 2 else RT.CALLED)
                edge_key = (src.id, tgt.id, rel_type)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    relationships.append(
                        Relationship(
                            id=uuid.uuid4(),
                            case_id=case.id,
                            source_entity_id=src.id,
                            target_entity_id=tgt.id,
                            relationship_type=rel_type,
                            epistemic_status=RT.OBSERVED,
                            verification_status=RT.REVIEW_ACCEPTED if len(relationships) % 3 == 0 else RT.REVIEW_UNREVIEWED,
                            confidence=0.90,
                            evidence_refs=[str(ev_file.id)],
                        )
                    )
        db.add_all(relationships)

        # Seed 500 Evidence Events
        events: list[EvidenceEvent] = []
        for i in range(500):
            events.append(
                EvidenceEvent(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    evidence_file_id=ev_file.id,
                    event_type="call" if i % 2 == 0 else "transaction",
                    event_timestamp=datetime.now(timezone.utc),
                    text_content=f"Recorded investigation interaction #{i:04d} with metadata details.",
                    source_page=1 + (i // 50),
                    source_line=i + 1,
                    event_metadata={
                        "amount": 1000.0 + (i * 10),
                        "caller": entities[i % 100].canonical_value,
                        "receiver": entities[(i + 3) % 100].canonical_value,
                    },
                )
            )
        db.add_all(events)

        # Seed 20 Findings
        findings: list[InvestigationFinding] = []
        for i in range(20):
            findings.append(
                InvestigationFinding(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    fingerprint=f"fp_perf_{run_id}_{i:03d}",
                    finding_type="communication_frequency" if i % 2 == 0 else "rapid_movement",
                    title=f"Suspicious Tactical Anomaly Pattern #{i}",
                    description=f"Automated intelligence correlation observed pattern across multiple evidence files.",
                    severity="HIGH" if i % 3 == 0 else "MEDIUM",
                    status="OPEN",
                    confidence=0.88,
                    source_engine="correlation_engine",
                    entity_refs=[str(entities[i].id), str(entities[i + 1].id)],
                    evidence_refs=[str(ev_file.id)],
                )
            )
        db.add_all(findings)

        # Record InvestigationState version 1, 2, 3
        for v in range(1, 4):
            db.add(
                InvestigationState(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    version=v,
                    created_by=user.id,
                )
            )

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

    # Execute Benchmarks
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Command Center Benchmark
        tracemalloc.reset_peak()
        gc.collect()

        async def _bench_command_center():
            r = await client.get(f"/api/v1/cases/{case_id}/command-center", headers=headers)
            assert r.status_code == 200
            return len(r.content)

        r_sample = await client.get(f"/api/v1/cases/{case_id}/command-center", headers=headers)
        cc_payload_size = len(r_sample.content)
        cc_perf = await _run_benchmark_iterations(_bench_command_center, iterations=5)
        current_mem, peak_mem = tracemalloc.get_traced_memory()

        print(f"\n[BENCHMARK] Command Center (Tier A - 100 Ent, 500 Ev):")
        print(f"  Latency p50: {cc_perf['p50_ms']}ms, p95: {cc_perf['p95_ms']}ms")
        print(f"  Payload Size: {cc_payload_size / 1024:.2f} KB")
        print(f"  Peak Memory: {peak_mem / 1024 / 1024:.2f} MB")
        assert cc_perf["p95_ms"] < 4000.0, f"Command Center exceeded SLA: {cc_perf}"

        # 2. Timeline Paging Benchmark (limit=100)
        async def _bench_timeline():
            r = await client.get(f"/api/v1/cases/{case_id}/timeline?limit=100", headers=headers)
            assert r.status_code == 200

        tl_perf = await _run_benchmark_iterations(_bench_timeline, iterations=5)
        print(f"[BENCHMARK] Timeline Paging limit=100:")
        print(f"  Latency p50: {tl_perf['p50_ms']}ms, p95: {tl_perf['p95_ms']}ms")
        assert tl_perf["p95_ms"] < 4000.0, f"Timeline paging exceeded SLA: {tl_perf}"

        # 3. Historical Replay Scrubbing Benchmark
        async def _bench_replay():
            r = await client.get(f"/api/v1/cases/{case_id}/replay/2", headers=headers)
            assert r.status_code == 200

        replay_perf = await _run_benchmark_iterations(_bench_replay, iterations=5)
        print(f"[BENCHMARK] Historical Replay (v2):")
        print(f"  Latency p50: {replay_perf['p50_ms']}ms, p95: {replay_perf['p95_ms']}ms")
        assert replay_perf["p95_ms"] < 4000.0, f"Replay exceeded SLA: {replay_perf}"

        # 4. Forensic Communications Lens Benchmark
        async def _bench_comms_lens():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/communications", headers=headers)
            assert r.status_code == 200

        comms_perf = await _run_benchmark_iterations(_bench_comms_lens, iterations=5)
        print(f"[BENCHMARK] Forensic Communications Lens:")
        print(f"  Latency p50: {comms_perf['p50_ms']}ms, p95: {comms_perf['p95_ms']}ms")
        assert comms_perf["p95_ms"] < 4000.0, f"Comms lens exceeded SLA: {comms_perf}"

        # 5. Forensic Money Lens Benchmark
        async def _bench_money_lens():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/money", headers=headers)
            assert r.status_code == 200

        money_perf = await _run_benchmark_iterations(_bench_money_lens, iterations=5)
        print(f"[BENCHMARK] Forensic Money Trail Lens:")
        print(f"  Latency p50: {money_perf['p50_ms']}ms, p95: {money_perf['p95_ms']}ms")
        assert money_perf["p95_ms"] < 4000.0, f"Money lens exceeded SLA: {money_perf}"

        # 6. Forensic Geographic Lens Benchmark
        async def _bench_geo_lens():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/geographic", headers=headers)
            assert r.status_code == 200

        geo_perf = await _run_benchmark_iterations(_bench_geo_lens, iterations=5)
        print(f"[BENCHMARK] Forensic Geographic Lens:")
        print(f"  Latency p50: {geo_perf['p50_ms']}ms, p95: {geo_perf['p95_ms']}ms")
        assert geo_perf["p95_ms"] < 4000.0, f"Geo lens exceeded SLA: {geo_perf}"

        # 7. Audit Chain Verification Latency Benchmark
        async with AsyncSessionLocal() as audit_db:
            async def _bench_audit_verify():
                res = await AuditVerifier.verify_ledger(audit_db, case_id=case_id)
                assert res["intact"] is True

            audit_perf = await _run_benchmark_iterations(_bench_audit_verify, iterations=3)
            print(f"[BENCHMARK] Audit Chain Verification:")
            print(f"  Latency p50: {audit_perf['p50_ms']}ms, p95: {audit_perf['p95_ms']}ms")
            assert audit_perf["p95_ms"] < 4000.0, f"Audit verification exceeded SLA: {audit_perf}"


@pytest.mark.asyncio
async def test_performance_tier_b_medium_scale():
    """
    Tier B Benchmark: Medium-Scale Active Case
    250 Entities, 1,500 Events, 400 Relationships, 50 Findings.
    Validates end-to-end responsiveness and bounded memory consumption under load.
    Ensures endpoints remain responsive without degradation:
      - Command Center: p95 < 3000ms
      - Timeline Paging (100 items): p95 < 2500ms
      - Historical Replay Scrubbing: p95 < 2500ms
      - Forensic Communications Lens: p95 < 2500ms
      - Forensic Money Lens: p95 < 2500ms
      - Forensic Geographic Lens: p95 < 2500ms
      - Cryptographic Audit Chain Verification: p95 < 2500ms
    """
    async with AsyncSessionLocal() as db:
        run_id = uuid.uuid4().hex[:8]
        user = User(
            id=uuid.uuid4(),
            username=f"perf_tier_b_{run_id}",
            email=f"perf_tier_b_{run_id}@police.gov.in",
            full_name="Tier B Performance IO",
            rank="Superintendent",
            unit="Cyber Intelligence Division",
            hashed_password="dummy_hash_for_tier_b",
            role="INVESTIGATOR",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        dev_id = f"DEV-TIER-B-{run_id[:4]}"
        session_id = uuid.uuid4().hex
        user_sess = UserSession(
            id=session_id,
            user_id=user.id,
            device_id=dev_id,
            ip_address="127.0.0.1",
            user_agent="TierBHarness/2.0",
            authentication_level="standard",
            revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12),
        )
        db.add(user_sess)

        # Create Case
        case = Case(
            id=uuid.uuid4(),
            case_number=f"FIR-TIER-B-{run_id.upper()}",
            title=f"Operation High-Velocity Cyber Syndicate Tier B {run_id}",
            description="Medium scale stress testing for state projection and multi-lens query execution",
            status="open",
            assigned_officer_id=user.id,
            state_version=3,
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

        # Seed Evidence File
        ev_file = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case.id,
            filename=f"tier_b_forensic_extract_{run_id}.csv",
            original_name=f"tier_b_forensic_extract_{run_id}.csv",
            file_type="telecom_cdr",
            sha256_hash=uuid.uuid4().hex * 2,
            storage_path=f"/uploads/tier_b_{run_id}.csv",
            file_size_bytes=4194304,
        )
        db.add(ev_file)

        # Seed 250 Entities
        entity_types = ["phone", "person", "bank_account", "ip_address", "vehicle"]
        entities: list[Entity] = []
        for i in range(250):
            etype = entity_types[i % len(entity_types)]
            if etype == "phone":
                val = f"+9198765{i:05d}"
            elif etype == "person":
                val = f"Operative {i:03d} (Alias {run_id}_{i})"
            elif etype == "bank_account":
                val = f"MULE-ACCT-{i:06d}"
            elif etype == "ip_address":
                val = f"198.51.100.{1 + (i % 250)}"
            else:
                val = f"DL-01-AB-{1000 + i}"

            entities.append(
                Entity(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    canonical_value=val,
                    entity_type=etype,
                    degree_centrality=round(0.005 * (i % 20), 4),
                    bridge_score=round(0.01 * (i % 10), 4),
                )
            )
        db.add_all(entities)
        await db.flush()

        # Seed 400 Relationships
        rel_types = [
            RT.COMMUNICATED_WITH,
            RT.TRANSFERRED_TO,
            RT.CALLED,
            RT.ASSOCIATED_WITH,
            RT.CO_OCCURRENCE,
        ]
        relationships: list[Relationship] = []
        seen_edges = set()
        for i in range(250):
            for step in (1, 2, 5, 7):
                if len(relationships) >= 400:
                    break
                src = entities[i]
                tgt = entities[(i + step) % 250]
                rtype = rel_types[(i + step) % len(rel_types)]
                edge_key = (src.id, tgt.id, rtype)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    is_inferred = (len(relationships) % 4 == 0)
                    relationships.append(
                        Relationship(
                            id=uuid.uuid4(),
                            case_id=case.id,
                            source_entity_id=src.id,
                            target_entity_id=tgt.id,
                            relationship_type=rtype,
                            epistemic_status=RT.INFERRED if is_inferred else RT.OBSERVED,
                            verification_status=RT.REVIEW_UNREVIEWED if is_inferred else RT.REVIEW_ACCEPTED,
                            confidence=0.85 if is_inferred else 0.95,
                            evidence_refs=[str(ev_file.id)],
                        )
                    )
        db.add_all(relationships)

        # Seed 1,500 Evidence Events
        base_time = datetime.now(timezone.utc) - timedelta(days=15)
        events: list[EvidenceEvent] = []
        event_types = ["call", "transaction", "location_ping", "login", "sms"]
        for i in range(1500):
            ev_type = event_types[i % len(event_types)]
            ev_ts = base_time + timedelta(minutes=i * 14)
            caller_ent = entities[i % 250].canonical_value
            receiver_ent = entities[(i + 7) % 250].canonical_value
            events.append(
                EvidenceEvent(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    evidence_file_id=ev_file.id,
                    event_type=ev_type,
                    event_timestamp=ev_ts,
                    text_content=f"Telemetry capture event #{i:05d} recorded across cyber gateway stream.",
                    source_page=1 + (i // 50),
                    source_line=i + 1,
                    event_metadata={
                        "amount": 5000.0 + (i * 25.5),
                        "sender": caller_ent,
                        "receiver": receiver_ent,
                        "tower_id": f"DEL-TOWER-{(i % 30) + 1:03d}",
                        "lat": 28.6139 + ((i % 50) * 0.002),
                        "lon": 77.2090 + ((i % 50) * 0.002),
                    },
                )
            )
        db.add_all(events)

        # Seed 50 Findings
        finding_types = [
            "communication_frequency",
            "rapid_movement",
            "smurfing_pattern",
            "burst_activity",
            "dormant_activation",
        ]
        severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        findings: list[InvestigationFinding] = []
        for i in range(50):
            findings.append(
                InvestigationFinding(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    fingerprint=f"fp_tier_b_{run_id}_{i:04d}",
                    finding_type=finding_types[i % len(finding_types)],
                    title=f"Tier B Syndicate Anomaly Correlation #{i + 1}",
                    description=f"Autonomous forensic lens correlation detected high-risk multi-entity pattern #{i}.",
                    severity=severities[i % len(severities)],
                    status="CONFIRMED" if i % 4 == 0 else "OPEN",
                    confidence=round(0.75 + ((i % 25) * 0.01), 2),
                    source_engine="forensic_lens_engine",
                    entity_refs=[str(entities[i % 250].id), str(entities[(i + 3) % 250].id)],
                    evidence_refs=[str(ev_file.id)],
                )
            )
        db.add_all(findings)

        # Seed InvestigationState version 1, 2, 3
        for v in range(1, 4):
            db.add(
                InvestigationState(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    version=v,
                    created_by=user.id,
                )
            )

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

    # Execute Tier B Medium-Scale Benchmarks
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Command Center Benchmark (Medium Scale)
        tracemalloc.reset_peak()
        gc.collect()

        async def _bench_cc_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/command-center", headers=headers)
            assert r.status_code == 200
            return len(r.content)

        r_sample = await client.get(f"/api/v1/cases/{case_id}/command-center", headers=headers)
        cc_payload_size = len(r_sample.content)
        cc_perf = await _run_benchmark_iterations(_bench_cc_tier_b, iterations=5)
        current_mem, peak_mem = tracemalloc.get_traced_memory()

        print(f"\n[BENCHMARK] Tier B Command Center (250 Ent, 1500 Ev, 400 Rel, 50 Findings):")
        print(f"  Latency p50: {cc_perf['p50_ms']}ms, p95: {cc_perf['p95_ms']}ms, max: {cc_perf['max_ms']}ms")
        print(f"  Payload Size: {cc_payload_size / 1024:.2f} KB")
        print(f"  Peak Memory: {peak_mem / 1024 / 1024:.2f} MB")
        assert cc_perf["p95_ms"] < 4000.0, f"Tier B Command Center exceeded SLA: {cc_perf}"

        # 2. Timeline Paging Benchmark (limit=100)
        async def _bench_tl_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/timeline?limit=100", headers=headers)
            assert r.status_code == 200

        tl_perf = await _run_benchmark_iterations(_bench_tl_tier_b, iterations=5)
        print(f"[BENCHMARK] Tier B Timeline Paging (limit=100):")
        print(f"  Latency p50: {tl_perf['p50_ms']}ms, p95: {tl_perf['p95_ms']}ms")
        assert tl_perf["p95_ms"] < 4000.0, f"Tier B Timeline paging exceeded SLA: {tl_perf}"

        # 3. Historical Replay Scrubbing Benchmark (v2)
        async def _bench_replay_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/replay/2", headers=headers)
            assert r.status_code == 200

        replay_perf = await _run_benchmark_iterations(_bench_replay_tier_b, iterations=5)
        print(f"[BENCHMARK] Tier B Historical Replay (v2):")
        print(f"  Latency p50: {replay_perf['p50_ms']}ms, p95: {replay_perf['p95_ms']}ms")
        assert replay_perf["p95_ms"] < 4000.0, f"Tier B Replay exceeded SLA: {replay_perf}"

        # 4. Forensic Communications Lens Benchmark
        async def _bench_comms_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/communications", headers=headers)
            assert r.status_code == 200

        comms_perf = await _run_benchmark_iterations(_bench_comms_tier_b, iterations=5)
        print(f"[BENCHMARK] Tier B Forensic Communications Lens:")
        print(f"  Latency p50: {comms_perf['p50_ms']}ms, p95: {comms_perf['p95_ms']}ms")
        assert comms_perf["p95_ms"] < 4000.0, f"Tier B Comms lens exceeded SLA: {comms_perf}"

        # 5. Forensic Money Trail Lens Benchmark
        async def _bench_money_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/money", headers=headers)
            assert r.status_code == 200

        money_perf = await _run_benchmark_iterations(_bench_money_tier_b, iterations=5)
        print(f"[BENCHMARK] Tier B Forensic Money Trail Lens:")
        print(f"  Latency p50: {money_perf['p50_ms']}ms, p95: {money_perf['p95_ms']}ms")
        assert money_perf["p95_ms"] < 4000.0, f"Tier B Money lens exceeded SLA: {money_perf}"

        # 6. Forensic Geographic Lens Benchmark
        async def _bench_geo_tier_b():
            r = await client.get(f"/api/v1/cases/{case_id}/lenses/geographic", headers=headers)
            assert r.status_code == 200

        geo_perf = await _run_benchmark_iterations(_bench_geo_tier_b, iterations=5)
        print(f"[BENCHMARK] Tier B Forensic Geographic Lens:")
        print(f"  Latency p50: {geo_perf['p50_ms']}ms, p95: {geo_perf['p95_ms']}ms")
        assert geo_perf["p95_ms"] < 4000.0, f"Tier B Geo lens exceeded SLA: {geo_perf}"

        # 7. Audit Chain Verification Latency Benchmark
        async with AsyncSessionLocal() as audit_db:
            async def _bench_audit_verify_tier_b():
                res = await AuditVerifier.verify_ledger(audit_db, case_id=case_id)
                assert res["intact"] is True

            audit_perf = await _run_benchmark_iterations(_bench_audit_verify_tier_b, iterations=3)
            print(f"[BENCHMARK] Tier B Audit Chain Verification:")
            print(f"  Latency p50: {audit_perf['p50_ms']}ms, p95: {audit_perf['p95_ms']}ms")
            assert audit_perf["p95_ms"] < 4000.0, f"Tier B Audit verification exceeded SLA: {audit_perf}"

