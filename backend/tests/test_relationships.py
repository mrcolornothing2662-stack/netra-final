"""Regression guards for the unified Case Graph relationship layer.

Covers the Phase-1 data foundation:
  • semantic relationship types derived from structured evidence
  • evidence + event provenance attached to every observed edge
  • phone/account normalisation when metadata and canonical values differ
  • observed vs inferred separation in one store
  • idempotent materialisation (re-processing aggregates instead of duplicating)

The pure derivation tests need no database. The persistence test builds its own
isolated async SQLite engine so it never shares a pool/event loop with the other
HTTP regression files. Dual-mode runnable AND pytest-discoverable.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="rel_test_"))
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP / 'rel.db'}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from db.models import Base, Case, Entity, EntityMention, EvidenceEvent, Relationship  # noqa: E402
from graph import relationship_types as RT  # noqa: E402
from graph.relationships import (  # noqa: E402
    derive_observed_relationships,
    materialize_observed_relationships,
    upsert_relationship,
)


# ── Pure derivation ───────────────────────────────────────────────────────────

def test_derive_bank_transfer_is_typed_and_provenanced():
    events = [{
        "id": "e1",
        "event_type": "bank_txn",
        "event_timestamp": "2026-09-16T10:32:00",
        "evidence_file_id": "ev1",
        "event_metadata": {
            "from_account": "ACCT-A", "to_account": "ACCT-B",
            "amount": 118000, "narration": "RTGS out",
        },
        "entity_mentions": [
            {"canonical_value": "ACCT-A", "entity_type": "ACCOUNT"},
            {"canonical_value": "ACCT-B", "entity_type": "ACCOUNT"},
        ],
    }]
    drafts = derive_observed_relationships(events)

    typed = [d for d in drafts if d.relationship_type == RT.TRANSFERRED_TO]
    assert len(typed) == 1, drafts
    edge = typed[0]
    assert edge.source_value == "ACCT-A" and edge.target_value == "ACCT-B"
    assert edge.direction == RT.OUTBOUND
    assert edge.epistemic_status == RT.OBSERVED
    assert edge.amount == 118000.0
    assert edge.evidence_refs == ["ev1"]
    assert edge.event_refs == ["e1"]
    # The typed pair must not also emit a redundant co-occurrence edge.
    assert all(d.relationship_type != RT.CO_OCCURRENCE for d in drafts)


def test_derive_call_matches_phone_across_formats():
    events = [{
        "id": "e2",
        "event_type": "call",
        "event_timestamp": "2026-09-16T10:18:00",
        "evidence_file_id": "ev2",
        "event_metadata": {"caller": "+91 98765 43210", "callee": "9876543211", "duration_sec": 41},
        # Canonical phone values are stored without separators.
        "entity_mentions": [
            {"canonical_value": "+919876543210", "entity_type": "PHONE"},
            {"canonical_value": "9876543211", "entity_type": "PHONE"},
        ],
    }]
    drafts = derive_observed_relationships(events)
    called = [d for d in drafts if d.relationship_type == RT.CALLED]
    assert len(called) == 1, drafts
    assert {called[0].source_value, called[0].target_value} == {"+919876543210", "9876543211"}
    assert called[0].attributes.get("duration_sec") == 41


def test_derive_whatsapp_sender_messaged_others():
    events = [{
        "id": "e3",
        "event_type": "whatsapp_msg",
        "event_timestamp": "2026-09-16T10:02:00",
        "evidence_file_id": "ev3",
        "event_metadata": {"sender": "Alice", "is_system": False},
        "entity_mentions": [
            {"canonical_value": "Alice", "entity_type": "PER"},
            {"canonical_value": "+919000000001", "entity_type": "PHONE"},
        ],
    }]
    drafts = derive_observed_relationships(events)
    messaged = [d for d in drafts if d.relationship_type == RT.MESSAGED]
    assert len(messaged) == 1, drafts
    assert messaged[0].source_value == "Alice"
    assert messaged[0].target_value == "+919000000001"


def test_derive_falls_back_to_cooccurrence_without_semantics():
    events = [{
        "id": "e4",
        "event_type": "document_text",
        "event_timestamp": None,
        "evidence_file_id": "ev4",
        "event_metadata": {},
        "entity_mentions": [
            {"canonical_value": "Alice", "entity_type": "PER"},
            {"canonical_value": "CASE-42", "entity_type": "ACCOUNT"},
        ],
    }]
    drafts = derive_observed_relationships(events)
    assert len(drafts) == 1
    assert drafts[0].relationship_type == RT.CO_OCCURRENCE
    assert drafts[0].direction == RT.BIDIRECTIONAL


def test_derive_aggregates_repeated_events():
    def _event(eid, file_id):
        return {
            "id": eid, "event_type": "bank_txn", "event_timestamp": None,
            "evidence_file_id": file_id,
            "event_metadata": {"from_account": "ACCT-A", "to_account": "ACCT-B", "amount": 10},
            "entity_mentions": [
                {"canonical_value": "ACCT-A", "entity_type": "ACCOUNT"},
                {"canonical_value": "ACCT-B", "entity_type": "ACCOUNT"},
            ],
        }
    drafts = derive_observed_relationships([_event("e1", "ev1"), _event("e2", "ev2")])
    assert len(drafts) == 1
    edge = drafts[0]
    assert edge.observation_count == 2
    assert edge.event_refs == ["e1", "e2"]
    assert edge.evidence_refs == ["ev1", "ev2"]


# ── Persistence: observed vs inferred, idempotency ────────────────────────────

def test_relationship_persistence_observed_vs_inferred():
    asyncio.run(_persistence_impl())


async def _persistence_impl():
    engine = create_async_engine(f"sqlite+aiosqlite:///{_TMP / 'rel.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            case = Case(
                case_number=f"REL-{uuid.uuid4().hex[:8]}",
                title="Relationship persistence", priority="high", status="open",
            )
            db.add(case)
            await db.flush()

            entity_a = Entity(case_id=case.id, canonical_value="ACCT-A", entity_type="ACCOUNT")
            entity_b = Entity(case_id=case.id, canonical_value="ACCT-B", entity_type="ACCOUNT")
            db.add_all([entity_a, entity_b])
            await db.flush()

            event = EvidenceEvent(
                case_id=case.id, event_type="bank_txn",
                event_timestamp=datetime(2026, 9, 16, 10, 32, tzinfo=timezone.utc),
                event_metadata={"from_account": "ACCT-A", "to_account": "ACCT-B", "amount": 118000},
            )
            db.add(event)
            await db.flush()
            db.add_all([
                EntityMention(entity_id=entity_a.id, evidence_event_id=event.id,
                              raw_value="ACCT-A", entity_type="ACCOUNT"),
                EntityMention(entity_id=entity_b.id, evidence_event_id=event.id,
                              raw_value="ACCT-B", entity_type="ACCOUNT"),
            ])
            await db.flush()

            # 1. First materialisation creates exactly one observed edge.
            first = await materialize_observed_relationships(db, case.id)
            assert first["created"] == 1 and first["updated"] == 0, first

            # 2. Re-materialising the same evidence aggregates, never duplicates.
            second = await materialize_observed_relationships(db, case.id)
            assert second["created"] == 0 and second["updated"] == 1, second

            observed_rows = (await db.execute(
                select(Relationship).where(
                    Relationship.case_id == case.id,
                    Relationship.epistemic_status == RT.OBSERVED,
                )
            )).scalars().all()
            assert len(observed_rows) == 1
            observed = observed_rows[0]
            assert observed.relationship_type == RT.TRANSFERRED_TO
            assert observed.amount == 118000.0
            assert observed.observation_count == 2
            assert observed.event_refs == [str(event.id)]

            # 3. An inferred edge between the same entities is a separate row.
            inferred, created = await upsert_relationship(
                db, case_id=case.id,
                source_entity_id=entity_a.id, target_entity_id=entity_b.id,
                relationship_type=RT.ASSOCIATED_WITH,
                epistemic_status=RT.INFERRED,
                direction=RT.BIDIRECTIONAL,
                confidence=0.87,
                event_refs=[str(event.id)],
                component_scores={"temporal": 0.4},
                reason_codes=["temporal proximity"],
                source_engine="HiddenLinkEngine",
                engine_version="2.0",
            )
            assert created is True
            assert inferred.confidence == 0.87
            assert inferred.source_engine == "HiddenLinkEngine"
            assert inferred.reason_codes == ["temporal proximity"]

            # 4. Re-running the inferred analysis updates in place.
            _, created_again = await upsert_relationship(
                db, case_id=case.id,
                source_entity_id=entity_a.id, target_entity_id=entity_b.id,
                relationship_type=RT.ASSOCIATED_WITH,
                epistemic_status=RT.INFERRED,
                direction=RT.BIDIRECTIONAL,
                confidence=0.91,
                event_refs=[str(event.id)],
                source_engine="HiddenLinkEngine",
                engine_version="2.0",
            )
            assert created_again is False

            all_rows = (await db.execute(
                select(Relationship).where(Relationship.case_id == case.id)
            )).scalars().all()
            statuses = sorted(r.epistemic_status for r in all_rows)
            assert statuses == [RT.INFERRED, RT.OBSERVED], statuses

            # The observed edge's provenance survives the inferred upserts.
            observed = next(r for r in all_rows if r.epistemic_status == RT.OBSERVED)
            assert observed.observation_count == 2
            assert observed.event_refs == [str(event.id)]
            assert observed.relationship_type == RT.TRANSFERRED_TO
    finally:
        await engine.dispose()


# ── Dual-mode runner ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    _tests = [(n, f) for n, f in sorted(globals().items())
              if n.startswith("test_") and callable(f)]
    _failed = 0
    try:
        for _name, _fn in _tests:
            try:
                _fn()
                print(f"[PASS] {_name}")
            except Exception as _e:  # noqa: BLE001
                _failed += 1
                import traceback
                print(f"[FAIL] {_name}: {_e!r}")
                traceback.print_exc()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{len(_tests) - _failed}/{len(_tests)} relationship checks passed")
    sys.exit(1 if _failed else 0)
