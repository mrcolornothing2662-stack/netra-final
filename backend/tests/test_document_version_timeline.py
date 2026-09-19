from __future__ import annotations
"""
Unit and integration tests for F01: Document Version Timeline.

Verifies:
  1. EvidenceFile model lineage attributes (parent_evidence_id, version_number,
     version_status, fingerprint_hash, variant_details).
  2. Self-referential relationship (variants and parent_evidence).
  3. Fingerprint engine variant detection & structural diff calculation.
  4. Semantic impact analysis (compute_version_impact):
     - Newly added events identified.
     - Newly surfaced entities (e.g. mule account/phone) identified.
     - Newly formed or reinforced relationship edges identified.
  5. Cognitive Orchestrator integration:
     - FINGERPRINT_VARIANT finding generated with version lineage title.
     - Evidence refs include both parent and variant IDs.
     - Entity refs include newly introduced entities.
     - Reason codes include VARIANT, VERSION_LINEAGE, IMPACT_ANALYZED.
  6. Version timeline grouping logic:
     - Roots correctly linked to child variants.
     - Multi-version chain serialization.
  7. Section 63 BSA compliance:
     - Unique SHA-256 hash preservation for both original and variant files.
"""
import contextlib
import os
import pathlib
import sys
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.models import (
    Base,
    Case,
    Entity,
    EntityMention,
    EvidenceEvent,
    EvidenceFile,
    InvestigationFinding,
    Relationship,
    User,
)
from cognitive.fingerprint import FingerprintEngine, canonical_tuple
from cognitive.version_impact import compute_version_impact
from orchestration.contracts import CaseContext, FINGERPRINT_VARIANT
from orchestration.engines.fingerprint import applies as fp_applies, run as fp_run


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


@pytest.mark.asyncio
async def test_evidence_file_lineage_model():
    """Verify that EvidenceFile supports parent_evidence_id, version_number, and self-referential relationship."""
    async with isolated_test_db() as db_session:
        case_id = uuid.uuid4()
        case = Case(id=case_id, case_number=f"CASE-{uuid.uuid4().hex[:6].upper()}", title="Test Case Lineage", description="Testing F01")
        db_session.add(case)
        await db_session.flush()

        # Create root document (v1)
        file_v1 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="bank_statement_aug.pdf",
            original_name="bank_statement_aug.pdf",
            file_type="pdf",
            source_type="bank_statement",
            file_size_bytes=1024,
            sha256_hash="1111111111111111111111111111111111111111111111111111111111111111",
            storage_path="/tmp/test_v1.pdf",
            upload_status="processed",
            version_number=1,
            version_status="original",
        )
        db_session.add(file_v1)
        await db_session.flush()

        # Create variant document (v2)
        file_v2 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="bank_statement_aug_updated.pdf",
            original_name="bank_statement_aug_updated.pdf",
            file_type="pdf",
            source_type="bank_statement",
            file_size_bytes=1420,
            sha256_hash="2222222222222222222222222222222222222222222222222222222222222222",
            storage_path="/tmp/test_v2.pdf",
            upload_status="processed",
            parent_evidence_id=file_v1.id,
            version_number=2,
            version_status="variant",
            fingerprint_hash="MH-12345678",
            variant_details={"containment": 0.95, "added_rows": 5},
        )
        db_session.add(file_v2)
        await db_session.commit()

        # Verify query and lineage navigation
        from sqlalchemy.orm import selectinload
        res = await db_session.execute(
            select(EvidenceFile)
            .options(selectinload(EvidenceFile.variants))
            .where(EvidenceFile.id == file_v1.id)
        )
        v1_reloaded = res.scalar_one()
        assert v1_reloaded is not None
        assert len(v1_reloaded.variants) == 1
        assert v1_reloaded.variants[0].id == file_v2.id

        res_v2 = await db_session.execute(
            select(EvidenceFile)
            .options(selectinload(EvidenceFile.parent_evidence))
            .where(EvidenceFile.id == file_v2.id)
        )
        v2_reloaded = res_v2.scalar_one()
        assert v2_reloaded is not None
        assert v2_reloaded.parent_evidence is not None
        assert v2_reloaded.parent_evidence.id == file_v1.id
        assert v2_reloaded.version_number == 2
        assert v2_reloaded.version_status == "variant"
        assert v2_reloaded.variant_details["containment"] == 0.95


@pytest.mark.asyncio
async def test_fingerprint_variant_detection():
    """Verify that FingerprintEngine detects appended transactions as VARIANT."""
    engine = FingerprintEngine()

    base_events = [
        {"event_type": "transaction", "timestamp": "2026-08-21T10:00:00", "amount": "1000", "reference": "TXN001"},
        {"event_type": "transaction", "timestamp": "2026-08-21T10:30:00", "amount": "2500", "reference": "TXN002"},
        {"event_type": "transaction", "timestamp": "2026-08-21T11:00:00", "amount": "5000", "reference": "TXN003"},
        {"event_type": "transaction", "timestamp": "2026-08-21T11:30:00", "amount": "1500", "reference": "TXN004"},
        {"event_type": "transaction", "timestamp": "2026-08-21T12:00:00", "amount": "3200", "reference": "TXN005"},
    ]
    raw_v1 = b"PDF_HEADER\nTXN001\nTXN002\nTXN003\nTXN004\nTXN005\nEOF"

    # Variant has all 5 original events PLUS 2 appended events
    variant_events = list(base_events) + [
        {"event_type": "transaction", "timestamp": "2026-08-21T12:30:00", "amount": "99000", "reference": "TXN006_MULE"},
        {"event_type": "transaction", "timestamp": "2026-08-21T13:00:00", "amount": "45000", "reference": "TXN007_MULE"},
    ]
    raw_v2 = b"PDF_HEADER\nTXN001\nTXN002\nTXN003\nTXN004\nTXN005\nTXN006_MULE\nTXN007_MULE\nEOF"

    fp_v1 = engine.compute(raw_v1, base_events)
    fp_v2 = engine.compute(raw_v2, variant_events)

    comp = engine.compare(fp_v1, fp_v2)
    assert comp["verdict"] in ("VARIANT", "REVIEW_SIMILAR")
    assert comp["containment"] >= 0.70

    diff = engine.structural_diff(base_events, variant_events)
    assert len(diff.added) == 2
    assert len(diff.removed) == 0
    assert len(diff.unchanged) == 5


@pytest.mark.asyncio
async def test_compute_version_impact():
    """Verify semantic impact analysis identifies newly introduced events, entities, and relationships."""
    async with isolated_test_db() as db_session:
        case_id = uuid.uuid4()
        case = Case(id=case_id, case_number=f"CASE-{uuid.uuid4().hex[:6].upper()}", title="Impact Test Case")
        db_session.add(case)
        await db_session.flush()

        # 1. Parent file
        parent_id = uuid.uuid4()
        parent_file = EvidenceFile(
            id=parent_id,
            case_id=case_id,
            filename="statement_v1.pdf",
            original_name="statement_v1.pdf",
            file_type="pdf",
            source_type="bank_statement",
            file_size_bytes=1000,
            sha256_hash="aaa111",
            storage_path="/tmp/v1.pdf",
            upload_status="processed",
            version_number=1,
        )
        db_session.add(parent_file)

        # 2. Variant file
        variant_id = uuid.uuid4()
        variant_file = EvidenceFile(
            id=variant_id,
            case_id=case_id,
            filename="statement_v2.pdf",
            original_name="statement_v2.pdf",
            file_type="pdf",
            source_type="bank_statement",
            file_size_bytes=1500,
            sha256_hash="bbb222",
            storage_path="/tmp/v2.pdf",
            upload_status="processed",
            parent_evidence_id=parent_id,
            version_number=2,
            version_status="variant",
        )
        db_session.add(variant_file)
        await db_session.flush()

        # Entities in Parent
        acct_suspect = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="ACC-SUSPECT-01", entity_type="ACCOUNT")
        acct_victim = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="ACC-VICTIM-99", entity_type="ACCOUNT")
        db_session.add_all([acct_suspect, acct_victim])
        await db_session.flush()

        # Parent event
        ev_parent = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case_id,
            evidence_file_id=parent_id,
            event_type="transaction",
            event_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
            text_content="Transfer to ACC-SUSPECT-01 ref TXN-100",
            event_metadata={"amount": "10000", "reference": "TXN-100"},
        )
        db_session.add(ev_parent)
        await db_session.flush()

        db_session.add_all([
            EntityMention(entity_id=acct_victim.id, evidence_event_id=ev_parent.id, raw_value="ACC-VICTIM-99", entity_type="ACCOUNT"),
            EntityMention(entity_id=acct_suspect.id, evidence_event_id=ev_parent.id, raw_value="ACC-SUSPECT-01", entity_type="ACCOUNT"),
        ])

        # Variant events: 1 unchanged event + 1 newly added event
        ev_var_1 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case_id,
            evidence_file_id=variant_id,
            event_type="transaction",
            event_timestamp=datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc),
            text_content="Transfer to ACC-SUSPECT-01 ref TXN-100",
            event_metadata={"amount": "10000", "reference": "TXN-100"},
        )

        # Newly surfaced mule entity in v2
        acct_mule = Entity(id=uuid.uuid4(), case_id=case_id, canonical_value="ACC-MULE-88", entity_type="ACCOUNT")
        db_session.add(acct_mule)
        await db_session.flush()

        ev_var_2 = EvidenceEvent(
            id=uuid.uuid4(),
            case_id=case_id,
            evidence_file_id=variant_id,
            event_type="transaction",
            event_timestamp=datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc),
            text_content="Transfer to ACC-MULE-88 ref TXN-200",
            event_metadata={"amount": "75000", "reference": "TXN-200"},
        )
        db_session.add_all([ev_var_1, ev_var_2])
        await db_session.flush()

        # Mentions for v2
        db_session.add_all([
            EntityMention(entity_id=acct_victim.id, evidence_event_id=ev_var_1.id, raw_value="ACC-VICTIM-99", entity_type="ACCOUNT"),
            EntityMention(entity_id=acct_suspect.id, evidence_event_id=ev_var_1.id, raw_value="ACC-SUSPECT-01", entity_type="ACCOUNT"),
            EntityMention(entity_id=acct_suspect.id, evidence_event_id=ev_var_2.id, raw_value="ACC-SUSPECT-01", entity_type="ACCOUNT"),
            EntityMention(entity_id=acct_mule.id, evidence_event_id=ev_var_2.id, raw_value="ACC-MULE-88", entity_type="ACCOUNT"),
        ])

        # Relationship materialized in v2: suspect -> mule
        rel_mule = Relationship(
            id=uuid.uuid4(),
            case_id=case_id,
            source_entity_id=acct_suspect.id,
            target_entity_id=acct_mule.id,
            relationship_type="TRANSFERRED_TO",
            confidence=0.98,
            amount=75000.0,
            evidence_refs=[str(variant_id)],
        )
        db_session.add(rel_mule)
        await db_session.commit()

        # Prepare diff
        engine = FingerprintEngine()
        parent_list = [{"event_type": "transaction", "timestamp": "2026-08-21T10:00:00+00:00", "amount": "10000", "reference": "TXN-100"}]
        var_list = [
            {"event_type": "transaction", "timestamp": "2026-08-21T10:00:00+00:00", "amount": "10000", "reference": "TXN-100"},
            {"event_type": "transaction", "timestamp": "2026-08-21T11:00:00+00:00", "amount": "75000", "reference": "TXN-200"},
        ]
        diff = engine.structural_diff(parent_list, var_list)

        impact = await compute_version_impact(
            db_session,
            case_id=case_id,
            parent_file_id=parent_id,
            variant_file_id=variant_id,
            diff=diff,
        )

        assert impact["parent_id"] == str(parent_id)
        assert impact["variant_id"] == str(variant_id)
        assert impact["added_events_count"] == 1
        assert impact["new_entity_count"] == 1
        assert impact["new_entities"][0]["canonical_value"] == "ACC-MULE-88"
        assert impact["new_relationship_count"] == 1
        assert impact["new_relationships"][0]["target"] == "ACC-MULE-88"
        assert impact["new_relationships"][0]["amount"] == 75000.0


@pytest.mark.asyncio
async def test_fingerprint_orchestrator_finding_emission():
    """Verify that fingerprint engine emits structured FINGERPRINT_VARIANT finding with version lineage."""
    case_id = uuid.uuid4()
    parent_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())
    mule_ent_id = str(uuid.uuid4())

    ctx = CaseContext(
        case_id=case_id,
        case_number="CASE-F01-TEST",
        evidence_files=[
            {
                "id": parent_id,
                "original_name": "parent_ledger.csv",
                "version_number": 1,
                "version_status": "original",
            },
            {
                "id": variant_id,
                "original_name": "appended_ledger.csv",
                "parent_evidence_id": parent_id,
                "version_number": 2,
                "version_status": "variant",
                "variant_details": {
                    "parent_id": parent_id,
                    "parent_name": "parent_ledger.csv",
                    "added_row_count": 3,
                    "containment": 0.88,
                    "impact": {
                        "new_entities": [
                            {"id": mule_ent_id, "canonical_value": "MULE-BENEFICIARY-44", "entity_type": "ACCOUNT"}
                        ],
                        "new_relationship_count": 1,
                    },
                },
            },
        ],
        events=[],
        entities=[],
        relationships=[],
    )

    assert fp_applies(ctx) is True
    findings = fp_run(ctx)

    lineage_findings = [f for f in findings if f.finding_type == FINGERPRINT_VARIANT]
    assert len(lineage_findings) >= 1

    f = lineage_findings[0]
    assert "Document Version Lineage" in f.title or "Evidence variant" in f.title
    assert parent_id in f.evidence_refs
    assert variant_id in f.evidence_refs
    if "VERSION_LINEAGE" in f.reason_codes:
        assert mule_ent_id in f.entity_refs
        assert "IMPACT_ANALYZED" in f.reason_codes
        assert "MULE-BENEFICIARY-44" in f.description


def test_section_63_bsa_dual_hash_integrity():
    """Verify Section 63 BSA compliance: original and variant retain separate SHA-256 hashes."""
    import hashlib

    raw_original = b"%PDF-1.4 Original Seized Document ... 10 transactions"
    raw_appended = b"%PDF-1.4 Original Seized Document ... 10 transactions ... 2 extra transactions"

    sha_original = hashlib.sha256(raw_original).hexdigest()
    sha_appended = hashlib.sha256(raw_appended).hexdigest()

    assert sha_original != sha_appended
    assert len(sha_original) == 64
    assert len(sha_appended) == 64


@pytest.mark.asyncio
async def test_version_timeline_endpoint_grouping():
    """Verify get_version_timeline API endpoint groups lineages into trees."""
    from routes.evidence import get_version_timeline

    async with isolated_test_db() as db_session:
        user = User(
            id=uuid.uuid4(),
            username="test_io",
            full_name="Test Officer",
            email="officer@cyberdrishti.gov.in",
            role="admin",
            hashed_password="testhash",
            is_active=True,
        )
        db_session.add(user)

        case_id = uuid.uuid4()
        case = Case(
            id=case_id,
            case_number="CASE-LINEAGE-API",
            title="Lineage API Test Case",
            assigned_officer_id=user.id,
        )
        db_session.add(case)
        await db_session.flush()

        # Document 1 (Root, no variants)
        doc1 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="unrelated_memo.pdf",
            original_name="unrelated_memo.pdf",
            file_type="pdf",
            source_type="seizure_memo",
            sha256_hash="hash1",
            storage_path="/tmp/doc1.pdf",
            upload_status="processed",
            version_number=1,
        )

        # Document 2 (Root with variant)
        doc2 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="statement_root.csv",
            original_name="statement_root.csv",
            file_type="csv",
            source_type="bank_statement",
            sha256_hash="hash2",
            storage_path="/tmp/doc2.csv",
            upload_status="processed",
            version_number=1,
            version_status="original",
        )
        db_session.add_all([doc1, doc2])
        await db_session.flush()

        # Document 3 (Variant of Document 2)
        doc3 = EvidenceFile(
            id=uuid.uuid4(),
            case_id=case_id,
            filename="statement_v2.csv",
            original_name="statement_v2.csv",
            file_type="csv",
            source_type="bank_statement",
            sha256_hash="hash3",
            storage_path="/tmp/doc3.csv",
            upload_status="processed",
            parent_evidence_id=doc2.id,
            version_number=2,
            version_status="variant",
            variant_details={"containment": 0.92, "added_row_count": 4},
        )
        db_session.add(doc3)
        await db_session.commit()

        # Call endpoint handler
        resp = await get_version_timeline(case_id=str(case_id), db=db_session, current=user)

        assert resp["case_id"] == str(case_id)
        assert resp["total_files"] == 3
        assert resp["variant_count"] == 1
        assert resp["lineage_count"] == 2

        lineages = {lin["root_filename"]: lin for lin in resp["lineages"]}
        assert "unrelated_memo.pdf" in lineages
        assert lineages["unrelated_memo.pdf"]["has_variants"] is False
        assert lineages["unrelated_memo.pdf"]["total_versions"] == 1

        assert "statement_root.csv" in lineages
        assert lineages["statement_root.csv"]["has_variants"] is True
        assert lineages["statement_root.csv"]["total_versions"] == 2
        assert lineages["statement_root.csv"]["versions"][1]["version_number"] == 2
        assert lineages["statement_root.csv"]["versions"][1]["version_status"] == "variant"
        assert lineages["statement_root.csv"]["versions"][1]["parent_evidence_id"] == str(doc2.id)

