"""
Hardening & Provenance Acceptance Test Suite — NETRA 5.0
Workstream 3: Evidence Provenance, Chain of Custody & Statutory Legal Rigor.

Tests:
1. SHA-256 hash immutability & tamper detection across evidence lifecycle
2. Document Version Timeline (F01) lineage & parent-child variant hash tracking
3. Section 105 BNSS search & seizure panchnama mandatory videography validation
4. Section 63 BSA electronic certificate compliance & Defence Bot adversarial audit
5. Section 193 BNSS chargesheet hypothesis report generation & judicial disclaimers
"""
from __future__ import annotations

import hashlib
import uuid
import pytest
from datetime import datetime, timezone

from db.models import Case, EvidenceFile, User
from db.session import AsyncSessionLocal
from cognitive.defence import audit_case_defensibility, EPISTEMIC_DEFENCE_NOTICE


# ── 1. SHA-256 Hash Immutability & Tamper Detection ──────────────────────────

def test_sha256_hash_immutability():
    """Verify cryptographic hash computation and tamper detection."""
    clean_content = b"2026-08-18 09:00:00 | +91-9876540001 | CBI digital arrest notice"
    expected_hash = hashlib.sha256(clean_content).hexdigest()

    # Tampered content (single byte difference)
    tampered_content = b"2026-08-18 09:00:00 | +91-9876540002 | CBI digital arrest notice"
    tampered_hash = hashlib.sha256(tampered_content).hexdigest()

    assert expected_hash != tampered_hash
    assert len(expected_hash) == 64
    assert len(tampered_hash) == 64


# ── 2. Document Version Timeline (F01) Lineage & Variant Hash ────────────────

@pytest.mark.asyncio
async def test_evidence_lineage_and_version_tracking():
    """Verify that secondary evidence variants maintain strict cryptographic lineage."""
    async with AsyncSessionLocal() as db:
        case = Case(
            case_number=f"PROV-{uuid.uuid4().hex[:6].upper()}",
            title="Lineage Provenance Case",
            priority="medium",
            status="open",
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)

        orig_data = b"Original Panchnama Seizure Memo content signed by IO and Panchas"
        orig_hash = hashlib.sha256(orig_data).hexdigest()

        original_file = EvidenceFile(
            case_id=case.id,
            filename="seizure_memo_original.txt",
            original_name="seizure_memo_original.txt",
            file_type="document",
            file_size_bytes=len(orig_data),
            sha256_hash=orig_hash,
            storage_path=f"evidence://{case.id}/original.txt",
            upload_status="processed",
            version_number=1,
            version_status="original",
        )
        db.add(original_file)
        await db.commit()
        await db.refresh(original_file)

        # Variant file uploaded with modifications (e.g. redactions or forged edits)
        var_data = b"Altered Panchnama Seizure Memo content missing witness signature"
        var_hash = hashlib.sha256(var_data).hexdigest()

        variant_file = EvidenceFile(
            case_id=case.id,
            filename="seizure_memo_variant.txt",
            original_name="seizure_memo_variant.txt",
            file_type="document",
            file_size_bytes=len(var_data),
            sha256_hash=var_hash,
            storage_path=f"evidence://{case.id}/variant.txt",
            upload_status="processed",
            parent_evidence_id=original_file.id,
            version_number=2,
            version_status="variant",
            variant_details={"diff_detected": True, "parent_sha256": orig_hash},
        )
        db.add(variant_file)
        await db.commit()
        await db.refresh(variant_file)

        assert variant_file.parent_evidence_id == original_file.id
        assert variant_file.sha256_hash != original_file.sha256_hash
        assert variant_file.version_number == 2
        assert variant_file.version_status == "variant"


# ── 3. Section 105 BNSS Panchnama & Seizure Memo Validation ──────────────────

def test_section_105_bnss_panchnama_compliance():
    """Verify statutory panchnama validation including mandatory videography and tabular schema."""
    from parsers.seizure_memo_parser import is_seizure_memo_header
    from cognitive.benchmark import BenchmarkGenerator, load_json
    from cognitive import data_path

    # 1. Tabular schema verification
    valid_header = ["Evidence ID", "Item", "Source", "Condition"]
    assert is_seizure_memo_header(valid_header) is True
    assert is_seizure_memo_header(["Unknown", "Column"]) is False

    # 2. Statutory Panchnama under Section 105 BNSS
    gen = BenchmarkGenerator(load_json(data_path("pools.json")), load_json(data_path("typologies.json")))
    case = gen.generate_case("DIGITAL_ARREST", seed=101)
    memo = case["artifacts"]["evidence_seizure_memo.txt"]

    assert "RECORD OF SEIZURE UNDER SECTION 105" in memo
    assert "Section 105 BNSS" in memo
    assert "SHA-256" in memo
    assert "AUDIO-VIDEO ELECTRONIC RECORDING" in memo
    assert "Panch Witnesses" in memo


# ── 4. Section 63 BSA Secondary Evidence Audit & Defence Bot ──────────────────

def test_section_63_bsa_defence_audit():
    """Verify that Defence Bot detects uncertified electronic records under Section 63 BSA."""
    # Synthetic case files without Section 63 BSA certificates
    uncertified_files = [
        {"filename": "cdr_target.csv", "sha256_hash": "1" * 64, "file_type": "cdr"},
        {"filename": "bank_statement.csv", "sha256_hash": "2" * 64, "file_type": "bank_statement"},
    ]
    events = [
        {"type": "call", "caller": "+91-9876543210", "timestamp": "2026-08-18T10:00:00Z"},
        {"type": "bank_txn", "account": "MULE_ACCT_01", "amount": 500000, "timestamp": "2026-08-18T10:30:00Z"},
    ]

    report = audit_case_defensibility(
        case_id=str(uuid.uuid4()),
        evidence_files=uncertified_files,
        events=events,
        findings=[],
        entity_profiles={},
    )

    assert report.defensibility_score < 1.0
    assert report.bsa_compliance_status["compliant_with_bsa_63"] is False

    # Check that a Section 63 challenge was mounted
    bsa_challenges = [
        c for c in report.challenges
        if any("Section 63" in v.get("statute", "") or "BSA" in v.get("statute", "") for v in c.statutory_vulnerabilities)
    ]
    assert len(bsa_challenges) >= 1
    assert any(len(c.rebuttal_strategy) > 0 for c in bsa_challenges)
    assert report.epistemic_notice == EPISTEMIC_DEFENCE_NOTICE
