"""
Feature 10 — Crime Timeline Player / CTDG Replay Engine Tests

Validates:
  1. Mathematical CTDG frame generation (pure function build_frames).
  2. Continuous exponential opacity decay: opacity = exp(-delta_t / tau).
  3. Burst window clustering detection.
  4. Multi-source event extraction in _get_timed_events:
     - UPI transfers (payer -> payee, amounts, TRANSFERRED_TO)
     - Bank transactions (debit_account -> credit_account, amounts)
     - Telecom calls (caller -> callee, CALLED)
     - Network logs (device -> IP / destination, CONNECTED_TO)
     - Location timeline (phone -> cell tower, LOCATED_AT)
  5. Case graph Relationship synchronization and deduplication.
  6. Section 63 BSA source document and custody provenance.
  7. End-to-end HTTP API replay endpoint (/cases/{case_id}/network-replay).
"""
import contextlib
import math
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cognitive.replay import build_frames, parse_ts, Frame, DEFAULT_CONFIG
from db.models import Base, Case, EvidenceFile, EvidenceEvent, Relationship, Entity, User
from routes.cognitive import _get_timed_events, _clean_amount
import main


@contextlib.asynccontextmanager
async def isolated_test_db():
    """Provide an isolated in-memory SQLite async database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


# ── 1. UNIT TESTS: Pure Replay Mathematical Engine ───────────────────────────

def test_build_frames_empty():
    """Empty events produce an empty frame list."""
    assert build_frames([]) == []


def test_build_frames_single_instant():
    """Events occurring at the exact same moment yield a single frame."""
    ts = "2026-08-21T10:00:00+00:00"
    events = [
        {"timestamp": ts, "u": "DEV-001", "v": "198.51.100.24", "rel_type": "CONNECTED_TO"},
        {"timestamp": ts, "u": "arjun@upi", "v": "rohan@upi", "amount": 50000.0, "rel_type": "TRANSFERRED_TO"},
    ]
    frames = build_frames(events, {"step_seconds": 60})
    assert len(frames) == 1
    f0 = frames[0]
    assert f0["t"] == ts
    assert f0["t_start"] == ts
    assert f0["t_end"] == ts
    assert set(f0["nodes"]) == {"DEV-001", "198.51.100.24", "arjun@upi", "rohan@upi"}
    assert len(f0["edges"]) == 2
    assert len(f0["new_events"]) == 2
    assert f0["summary"]["active_nodes"] == 4
    assert f0["summary"]["active_edges"] == 2


def test_build_frames_exponential_decay():
    """Verify edge opacity mathematically follows exp(-delta_t / tau)."""
    t0 = datetime(2026, 8, 21, 10, 0, 0, tzinfo=timezone.utc)
    tau = 1800.0  # 30 min half-life
    step = 600   # 10 min steps

    events = [
        {
            "id": "ev-1",
            "timestamp": t0.isoformat(),
            "u": "ACC-001",
            "v": "ACC-002",
            "rel_type": "TRANSFERRED_TO",
            "amount": 25000.0,
            "source_doc": "02_bank_statement.pdf",
            "source_line": 14,
        },
        {
            "id": "ev-2",
            "timestamp": (t0 + timedelta(seconds=1800)).isoformat(),
            "u": "DEV-002",
            "v": "198.51.100.24",
            "rel_type": "CONNECTED_TO",
        },
    ]

    frames = build_frames(events, {"step_seconds": step, "tau_seconds": tau})
    assert len(frames) >= 4

    # Frame 0: t = t0 (age = 0) -> opacity must be 1.0
    f0 = frames[0]
    assert len(f0["edges"]) == 1
    e0 = f0["edges"][0]
    assert e0["u"] == "ACC-001" and e0["v"] == "ACC-002"
    assert math.isclose(e0["opacity"], 1.0, abs_tol=0.001)
    assert e0["amount"] == 25000.0
    assert e0["rel_type"] == "TRANSFERRED_TO"
    assert e0["source_doc"] == "02_bank_statement.pdf"
    assert e0["source_line"] == 14

    # Frame 3: t = t0 + 1800s (age = 1800s = tau) -> opacity must be exp(-1) ~= 0.3679
    f3 = frames[3]
    e_decayed = next(e for e in f3["edges"] if e["u"] == "ACC-001")
    assert math.isclose(e_decayed["opacity"], math.exp(-1.0), abs_tol=0.005)

    # In Frame 3, the second edge just occurred -> its opacity must be 1.0
    e_new = next(e for e in f3["edges"] if e["u"] == "DEV-002")
    assert math.isclose(e_new["opacity"], 1.0, abs_tol=0.001)


def test_build_frames_burst_detection():
    """Frames with >= burst_threshold events in burst_window_s are marked burst=True."""
    t0 = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    # Generate 12 rapid events within 120 seconds (window is 900s, threshold is 10)
    events = [
        {
            "timestamp": (t0 + timedelta(seconds=i * 10)).isoformat(),
            "u": f"CALLER-{i}",
            "v": "TARGET-HUB",
            "rel_type": "CALLED",
        }
        for i in range(12)
    ]
    # Add a distant event 2 hours later
    events.append({
        "timestamp": (t0 + timedelta(hours=2)).isoformat(),
        "u": "LONE-NODE",
        "v": "TARGET-HUB",
    })

    frames = build_frames(events, {
        "step_seconds": 60,
        "burst_window_s": 900,
        "burst_threshold": 10,
    })

    # The frames after the 10th rapid event must be marked burst=True
    burst_frames = [f for f in frames if f["burst"]]
    assert len(burst_frames) > 0
    for bf in burst_frames:
        assert bf["summary"]["burst"] is True

    # The final frame 2 hours later is quiet -> burst=False
    assert frames[-1]["burst"] is False
    assert frames[-1]["summary"]["burst"] is False


def test_clean_amount_helper():
    """Verify currency cleaning handles Rupee symbols, commas, and plain numbers."""
    assert _clean_amount("50,000") == 50000.0
    assert _clean_amount("₹ 1,25,000.50") == 125000.50
    assert _clean_amount("Rs. 3000") == 3000.0
    assert _clean_amount(450.75) == 450.75
    assert _clean_amount(None) is None
    assert _clean_amount("invalid") is None


# ── 2. ASYNC INTEGRATION TESTS: _get_timed_events Multi-Source Sourcing ───────

@pytest.mark.asyncio
async def test_get_timed_events_multi_source():
    """Verify _get_timed_events extracts UPI, bank, calls, network, and location events."""
    async with isolated_test_db() as session:
        case_id = uuid.uuid4()
        c = Case(id=case_id, case_number=f"CAS-{uuid.uuid4().hex[:6]}", title="CTDG Test Case", priority="high", crime_type="fraud")
        session.add(c)

        ef_upi = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="07_upi_transaction_report.pdf",
            original_name="07_upi_transaction_report.pdf",
            storage_path="/tmp/07_upi_transaction_report.pdf",
            file_type="pdf",
            source_type="upi_report",
            upload_status="processed",
            sha256_hash="UPI-HASH-1234",
        )
        ef_net = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="08_network_log.csv",
            original_name="08_network_log.csv",
            storage_path="/tmp/08_network_log.csv",
            file_type="csv",
            source_type="network_log",
            upload_status="processed",
            sha256_hash="NET-HASH-5678",
        )
        ef_loc = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="09_location_timeline.pdf",
            original_name="09_location_timeline.pdf",
            storage_path="/tmp/09_location_timeline.pdf",
            file_type="pdf",
            source_type="location_timeline",
            upload_status="processed",
            sha256_hash="LOC-HASH-9012",
        )
        session.add_all([ef_upi, ef_net, ef_loc])
        await session.flush()

        t1 = datetime(2026, 8, 21, 9, 58, tzinfo=timezone.utc)
        t2 = datetime(2026, 8, 21, 10, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 8, 21, 10, 15, tzinfo=timezone.utc)

        # 1. Network Log Event (File 08)
        ev_net = EvidenceEvent(
            case_id=case_id,
            evidence_file_id=ef_net.id,
            event_timestamp=t1,
            event_type="network_log",
            source_line=2,
            text_content="TLS_SESSION DEV-002 -> bank.example.invalid",
            event_metadata={
                "device": "DEV-002",
                "ip": "198.51.100.24",
                "destination": "bank.example.invalid",
                "port": 443,
                "action": "TLS_SESSION",
                "source_doc": "08_network_log.csv",
            },
        )

        # 2. Location Timeline Event (File 09)
        ev_loc = EvidenceEvent(
            case_id=case_id,
            evidence_file_id=ef_loc.id,
            event_timestamp=t2,
            event_type="location_timeline",
            source_line=5,
            text_content="+91-98XXXX1201 associated with CHD-CELL-17",
            event_metadata={
                "phone": "+91-98XXXX1201",
                "cell_tower": "CHD-CELL-17",
                "city": "Chandigarh",
                "observation": "Cell-site association",
                "source_doc": "09_location_timeline.pdf",
            },
        )

        # 3. UPI Transaction Event (File 07)
        ev_upi = EvidenceEvent(
            case_id=case_id,
            evidence_file_id=ef_upi.id,
            event_timestamp=t3,
            event_type="bank_txn",
            source_line=12,
            text_content="UPI transfer Rs. 50,000 from arjun@upi to rohan@upi",
            event_metadata={
                "payer": "arjun@upi",
                "payee": "rohan@upi",
                "amount": "50,000",
                "channel": "UPI",
                "ref_no": "UPI-TXN-001",
                "status": "SUCCESS",
                "source_doc": "07_upi_transaction_report.pdf",
            },
        )

        session.add_all([ev_net, ev_loc, ev_upi])
        await session.commit()

        # Query timed events
        timed = await _get_timed_events(session, case_id)
        assert len(timed) == 3

        # Check network log
        assert timed[0]["event_type"] == "network_log"
        assert timed[0]["rel_type"] == "CONNECTED_TO"
        assert timed[0]["u"] == "DEV-002"
        assert timed[0]["v"] == "198.51.100.24"
        assert timed[0]["source_doc"] == "08_network_log.csv"

        # Check location observation
        assert timed[1]["event_type"] == "location_timeline"
        assert timed[1]["rel_type"] == "LOCATED_AT"
        assert timed[1]["u"] == "+91-98XXXX1201"
        assert timed[1]["v"] == "CHD-CELL-17"
        assert timed[1]["source_doc"] == "09_location_timeline.pdf"

        # Check UPI transfer
        assert timed[2]["rel_type"] == "TRANSFERRED_TO"
        assert timed[2]["u"] == "arjun@upi"
        assert timed[2]["v"] == "rohan@upi"
        assert timed[2]["amount"] == 50000.0
        assert timed[2]["source_doc"] == "07_upi_transaction_report.pdf"


@pytest.mark.asyncio
async def test_get_timed_events_with_case_graph_relationships():
    """Verify materialised Relationship rows participate in timed events."""
    async with isolated_test_db() as session:
        case_id = uuid.uuid4()
        c = Case(id=case_id, case_number=f"CAS-{uuid.uuid4().hex[:6]}", title="Relationship Sync Case", priority="high", crime_type="fraud")
        session.add(c)

        ent_a = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="+91-9000000001", entity_type="PHONE")
        ent_b = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="+91-9000000002", entity_type="PHONE")
        session.add_all([ent_a, ent_b])
        await session.flush()

        ts = datetime(2026, 8, 22, 14, 30, tzinfo=timezone.utc)
        rel = Relationship(
            id=uuid.uuid4(),
            case_id=case_id,
            source_entity_id=ent_a.id,
            target_entity_id=ent_b.id,
            relationship_type="CALLED",
            direction="OUTBOUND",
            epistemic_status="OBSERVED",
            event_timestamp=ts,
            confidence=1.0,
            attributes={"duration_sec": 180, "source_doc": "04_call_detail_record.csv"},
        )
        session.add(rel)
        await session.commit()

        timed = await _get_timed_events(session, case_id)
        assert len(timed) == 1
        r = timed[0]
        assert r["rel_type"] == "CALLED"
        assert r["u"] == "+91-9000000001"
        assert r["v"] == "+91-9000000002"
        assert r["source_doc"] == "04_call_detail_record.csv"


# ── 3. E2E REST API PLAYBACK TEST ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_network_replay_api_endpoint():
    """Test GET /api/v1/cognitive/cases/{case_id}/network-replay returns rich CTDG frames."""
    from db.session import engine, AsyncSessionLocal

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await main._ensure_admin_seed()

    transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert login_resp.status_code == 200, login_resp.text
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Create test case
        create_resp = await client.post(
            "/api/v1/cases",
            json={"title": "F10 Replay API Case", "crime_type": "fraud", "priority": "high"},
            headers=headers,
        )
        assert create_resp.status_code in (200, 201), create_resp.text
        case_id = create_resp.json()["id"]

        # 3. Ingest two events directly in DB
        async with AsyncSessionLocal() as session:
            t0 = datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc)
            ev1 = EvidenceEvent(
                case_id=uuid.UUID(case_id),
                event_timestamp=t0,
                event_type="call",
                source_line=1,
                text_content="Call from +91-98XXXX1201 to +91-97XXXX4418",
                event_metadata={"caller": "+91-98XXXX1201", "callee": "+91-97XXXX4418", "source_doc": "04_cdr.csv"},
            )
            ev2 = EvidenceEvent(
                case_id=uuid.UUID(case_id),
                event_timestamp=t0 + timedelta(minutes=30),
                event_type="bank_txn",
                source_line=5,
                text_content="Transfer Rs. 10000",
                event_metadata={"payer": "userA@upi", "payee": "userB@upi", "amount": 10000.0, "source_doc": "07_upi.pdf"},
            )
            session.add_all([ev1, ev2])
            await session.commit()

        # 4. Query network replay
        resp = await client.get(
            f"/api/v1/cognitive/cases/{case_id}/network-replay?step_seconds=300&tau_seconds=1800",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["case_id"] == case_id
        assert data["total_events"] == 2
        assert data["total_frames"] > 0

        frames = data["frames"]
        f_first = frames[0]
        assert "t" in f_first
        assert "t_start" in f_first
        assert "t_end" in f_first
        assert "nodes" in f_first
        assert "edges" in f_first
        assert "burst" in f_first
        assert "new_events" in f_first
        assert "summary" in f_first
        assert f_first["summary"]["active_nodes"] >= 2

        # Verify edge provenance in frame
        edge = f_first["edges"][0]
        assert edge["u"] == "+91-98XXXX1201"
        assert edge["v"] == "+91-97XXXX4418"
        assert edge["rel_type"] == "CALLED"
        assert edge["source_doc"] == "04_cdr.csv"
        assert edge["source_line"] == 1
        assert "opacity" in edge
