"""
Unit test suite for Feature 07: Crime Script Matcher (MO Fingerprinting)

Tests:
1. Playbook library loading and schema validation
2. Levenshtein edit distance & normalized similarity metrics
3. Multi-modal behavioral trace building (text, bank txns, CDR, network logs)
4. Isolated per-playbook tracing (no cross-typology pollution)
5. Granular stage alignment & gap detection (in-order, out-of-order, missing)
6. Supporting evidence citations attached to each stage
7. Transparent calculation breakdown exposure
8. Configurable threshold gating and honest abstention
9. Epistemic humility & Section 193 BNSS / Section 63 BSA / R v T [2010] notices
10. Orchestration MOEngine adapter integration
"""
from __future__ import annotations

import os
import pytest
from cognitive import data_path
from cognitive.mo import (
    classify_case,
    classify_case_evidence,
    build_behavioral_trace_from_evidence,
    load_playbooks,
    levenshtein_distance,
    normalized_levenshtein,
    JUDICIAL_NOTICE,
)
from orchestration.contracts import (
    MO_MATCH,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    CaseContext,
)
from orchestration.engines.mo import SPEC as MO_SPEC, applies as mo_applies, run as mo_run


@pytest.fixture(scope="module")
def playbooks():
    return load_playbooks(data_path("playbooks.json"))


# ── 1. Playbook Catalog & Validation ─────────────────────────────────────────

def test_playbook_catalog_loading_and_structure(playbooks):
    assert "playbooks" in playbooks
    pbs = playbooks["playbooks"]
    assert len(pbs) >= 6

    names = {p["name"] for p in pbs}
    expected_names = {
        "DIGITAL_ARREST_EXTORTION",
        "INVESTMENT_TASK_FRAUD",
        "ROMANCE_BAITING",
        "MULE_HARVESTING_AND_OFFRAMP",
        "LOAN_APP_HARASSMENT_EXTORTION",
        "SIM_BOX_CALL_FORWARDING",
    }
    assert expected_names <= names

    for pb in pbs:
        assert pb.get("name")
        assert pb.get("description")
        assert pb.get("source")
        assert len(pb.get("stages", [])) >= 3
        assert isinstance(pb.get("detectors"), dict)
        for stage in pb["stages"]:
            assert stage in pb["detectors"], f"Stage {stage} missing detectors in {pb['name']}"
            assert len(pb["detectors"][stage]) > 0


# ── 2. Levenshtein Distance & Normalized Similarity ──────────────────────────

def test_levenshtein_distance_and_similarity_properties():
    # Identity
    seq = ["A", "B", "C", "D"]
    assert levenshtein_distance(seq, seq) == 0
    assert normalized_levenshtein(seq, seq) == 1.0

    # Total transposition
    assert levenshtein_distance(["A", "B"], ["B", "A"]) == 2
    assert normalized_levenshtein(["A", "B"], ["B", "A"]) == 0.0

    # Single insertion / deletion
    assert levenshtein_distance(["A", "B", "C"], ["A", "B"]) == 1
    assert normalized_levenshtein(["A", "B", "C"], ["A", "B"]) == pytest.approx(2 / 3, 0.01)

    # Empty handling
    assert levenshtein_distance([], []) == 0
    assert normalized_levenshtein([], []) == 1.0
    assert levenshtein_distance([], ["A", "B"]) == 2
    assert normalized_levenshtein([], ["A", "B"]) == 0.0


# ── 3. Multi-Modal Evidence Trace Building ───────────────────────────────────

def test_multi_modal_behavioral_trace_extraction(playbooks):
    digital_arrest_pb = next(p for p in playbooks["playbooks"] if p["name"] == "DIGITAL_ARREST_EXTORTION")

    evidence_items = [
        {
            "type": "whatsapp_msg",
            "event_id": "ev-01",
            "evidence_file_id": "file-101",
            "filename": "whatsapp_chat.txt",
            "sender": "Fake_Inspector_Sharma",
            "text": "Sir CBI Crime branch notice issued in narcotics parcel case against your Aadhaar",
            "timestamp": "2026-08-18T09:00:00Z",
        },
        {
            "type": "call",
            "event_id": "ev-02",
            "evidence_file_id": "file-102",
            "filename": "cdr_call_log.csv",
            "caller": "+91-9876543210",
            "callee": "+91-9123456789",
            "duration_sec": 720,  # 12 minutes isolation call
            "text": "WhatsApp video call Skype room lock isolated interrogation",
            "timestamp": "2026-08-18T09:15:00Z",
        },
        {
            "type": "whatsapp_msg",
            "event_id": "ev-03",
            "evidence_file_id": "file-101",
            "filename": "whatsapp_chat.txt",
            "sender": "Fake_Inspector_Sharma",
            "text": "Supreme Court order andar jaoge non-bailable arrest warrant remand",
            "timestamp": "2026-08-18T09:30:00Z",
        },
        {
            "type": "bank_txn",
            "event_id": "ev-04",
            "evidence_file_id": "file-103",
            "filename": "bank_statement.pdf",
            "amount": 250000.0,
            "narration": "Transfer clearance verification RBI security deposit to supervisory account",
            "timestamp": "2026-08-18T10:00:00Z",
        },
        {
            "type": "whatsapp_msg",
            "event_id": "ev-05",
            "evidence_file_id": "file-101",
            "filename": "whatsapp_chat.txt",
            "sender": "Fake_Inspector_Sharma",
            "text": "Kaam ho gaya, now delete chat and block this number immediately",
            "timestamp": "2026-08-18T10:15:00Z",
        },
    ]

    trace_res = build_behavioral_trace_from_evidence(evidence_items, digital_arrest_pb)
    seq = trace_res["sequence"]
    assert seq == [
        "SPOOF_LE_NOTICE",
        "ISOLATION_VIDEO_CALL",
        "THREAT_ARREST",
        "EXTRACTION_TRANSFER",
        "DISPOSAL_BLOCK",
    ]
    assert len(trace_res["evidence"]) == 5

    # Check evidence citations attached to each stage
    for hit in trace_res["evidence"]:
        assert hit["event_id"].startswith("ev-")
        assert hit["evidence_file_id"].startswith("file-")
        assert hit["filename"]
        assert hit["matched_text"]


# ── 4. Per-Playbook Isolated Tracing (No Cross-Contamination) ─────────────────

def test_isolated_per_playbook_tracing(playbooks):
    # Chat with phrases specific to investment scam only
    items = [
        {"type": "message", "text": "daily profit complete part time task bonus", "event_id": "e1"},
        {"type": "message", "text": "VIP level 3 prepaid task upgrade", "event_id": "e2"},
        {"type": "message", "text": "deposit 50000 capital investment recharge", "event_id": "e3"},
    ]

    res = classify_case_evidence(items, playbooks)
    assert res["verdict"] == "MATCHED"
    assert res["best_match"]["playbook"] == "INVESTMENT_TASK_FRAUD"

    # Digital arrest playbook should have 0 stages observed here
    da_match = next(m for m in res["matches"] if m["playbook"] == "DIGITAL_ARREST_EXTORTION")
    assert da_match["observed_sequence"] == []
    assert da_match["similarity"] == 0.0


# ── 5. Stage Alignment & Gap Analysis ────────────────────────────────────────

def test_stage_alignment_and_missing_stage_detection(playbooks):
    # Only 3 of 5 stages present, in correct order
    items = [
        {"type": "message", "text": "CBI police arrest warrant notice", "event_id": "e1"},
        {"type": "message", "text": "jail non-bailable arrest warrant remand", "event_id": "e2"},
        {"type": "message", "text": "transfer verification clearance security deposit", "event_id": "e3"},
    ]

    res = classify_case_evidence(items, playbooks)
    da = next(m for m in res["matches"] if m["playbook"] == "DIGITAL_ARREST_EXTORTION")

    alignment = da["alignment"]
    status_map = {a["stage"]: a["status"] for a in alignment if a["in_playbook"]}

    assert status_map["SPOOF_LE_NOTICE"] == "MATCHED_IN_ORDER"
    assert status_map["THREAT_ARREST"] == "MATCHED_OUT_OF_ORDER"  # observed pos 2 instead of expected 3
    assert status_map["ISOLATION_VIDEO_CALL"] == "MISSING"
    assert status_map["DISPOSAL_BLOCK"] == "MISSING"

    # Coverage ratio should be 3 / 5 = 0.60
    assert da["coverage_ratio"] == 0.60


# ── 6. Transparent Calculation Breakdown Exposure ────────────────────────────

def test_calculation_breakdown_transparency(playbooks):
    items = [
        {"type": "message", "text": "CBI notice", "event_id": "e1"},
        {"type": "message", "text": "video call", "event_id": "e2"},
        {"type": "message", "text": "non-bailable jail", "event_id": "e3"},
        {"type": "message", "text": "transfer clearance", "event_id": "e4"},
        {"type": "message", "text": "block number", "event_id": "e5"},
    ]

    res = classify_case_evidence(items, playbooks, config={"match_threshold": 0.60})
    best = res["best_match"]
    assert best is not None

    cb = best["calculation_breakdown"]
    assert cb["formula"] == "1.0 - (levenshtein_distance / max(len_observed, len_expected))"
    assert cb["observed_length"] == 5
    assert cb["expected_length"] == 5
    assert cb["levenshtein_distance"] == 0
    assert cb["coverage_ratio"] == 1.0
    assert cb["raw_similarity"] == 1.0
    assert cb["threshold"] == 0.60
    assert cb["is_confident"] is True


# ── 7. Threshold Gating & Abstention ─────────────────────────────────────────

def test_threshold_gating_abstention(playbooks):
    # Only 1 stage matched out of 5
    items = [
        {"type": "message", "text": "CBI notice issued", "event_id": "e1"},
    ]

    res = classify_case_evidence(items, playbooks, config={"match_threshold": 0.60})
    # Similarity for 1 stage vs 5 stages: dist = 4, max_len = 5 -> sim = 1 - 4/5 = 0.20
    assert res["verdict"] == "NO_CONFIDENT_MATCH"
    assert res["best_match"] is None
    assert res["candidate_best"] is not None
    assert res["candidate_best"]["similarity"] < 0.60


def test_insufficient_trace_when_no_hits(playbooks):
    items = [
        {"type": "message", "text": "Hello, how are you today?", "event_id": "e1"},
        {"type": "message", "text": "The weather in Bengaluru is pleasant.", "event_id": "e2"},
    ]

    res = classify_case_evidence(items, playbooks)
    assert res["verdict"] == "INSUFFICIENT_TRACE"
    assert res["observed_sequence"] == []
    assert res["best_match"] is None


# ── 8. Epistemic & Judicial Disclaimers ───────────────────────────────────────

def test_judicial_disclaimer_standards(playbooks):
    items = [
        {"type": "message", "text": "CBI arrest warrant notice", "event_id": "e1"},
    ]
    res = classify_case_evidence(items, playbooks)

    jn = res["judicial_notice"]
    assert "Section 193 BNSS" in jn["statutory_standard"]
    assert "Section 63 BSA" in jn["statutory_standard"]
    assert "R v T [2010]" in jn["r_v_t_compliance"]
    assert jn["corroboration_required"] is True
    assert "attribution" in res["note"]


# ── 9. Mule Harvesting Playbook Detection ────────────────────────────────────

def test_mule_harvesting_script_detection(playbooks):
    items = [
        {"type": "message", "text": "student account rent commission atm kit deliver", "event_id": "e1"},
        {"type": "message", "text": "change mobile number netbanking password registered number changed", "event_id": "e2"},
        {"type": "bank_txn", "narration": "inbound transfer multiple credits victim deposit", "event_id": "e3"},
        {"type": "bank_txn", "narration": "immediate transfer layer2 fan out rapid forwarding", "event_id": "e4"},
        {"type": "bank_txn", "narration": "atm cash withdrawal usdt p2p offramp", "event_id": "e5"},
    ]

    res = classify_case_evidence(items, playbooks)
    assert res["verdict"] == "MATCHED"
    assert res["best_match"]["playbook"] == "MULE_HARVESTING_AND_OFFRAMP"
    assert res["best_match"]["similarity"] >= 0.80


# ── 10. Orchestration MOEngine Adapter ───────────────────────────────────────

def test_orchestration_mo_engine_adapter_execution():
    context = CaseContext(
        case_id="case-test-mo",
        events=[
            {
                "id": "msg-01",
                "evidence_file_id": "evfile-01",
                "event_type": "whatsapp_msg",
                "text_content": "CBI arrest warrant notice issued in customs parcel",
                "event_metadata": {"sender": "+91-9999988888", "filename": "chat.txt"},
                "event_timestamp": "2026-08-18T09:00:00Z",
            },
            {
                "id": "msg-02",
                "evidence_file_id": "evfile-01",
                "event_type": "whatsapp_msg",
                "text_content": "video call skype room lock stay on call",
                "event_metadata": {"sender": "+91-9999988888", "filename": "chat.txt"},
                "event_timestamp": "2026-08-18T09:05:00Z",
            },
            {
                "id": "msg-03",
                "evidence_file_id": "evfile-01",
                "event_type": "whatsapp_msg",
                "text_content": "non-bailable jail remand arrest hone supreme court",
                "event_metadata": {"sender": "+91-9999988888", "filename": "chat.txt"},
                "event_timestamp": "2026-08-18T09:10:00Z",
            },
            {
                "id": "txn-04",
                "evidence_file_id": "evfile-02",
                "event_type": "bank_txn",
                "text_content": "transfer verification clearance security deposit rbi",
                "event_metadata": {"amount": 150000.0, "filename": "bank.pdf"},
                "event_timestamp": "2026-08-18T09:15:00Z",
            },
            {
                "id": "msg-05",
                "evidence_file_id": "evfile-01",
                "event_type": "whatsapp_msg",
                "text_content": "block number delete chat close kar",
                "event_metadata": {"sender": "+91-9999988888", "filename": "chat.txt"},
                "event_timestamp": "2026-08-18T09:20:00Z",
            },
        ],
    )

    assert mo_applies(context) is True

    findings = mo_run(context)
    assert len(findings) == 1
    f = findings[0]
    assert f.finding_type == MO_MATCH
    assert "DIGITAL_ARREST_EXTORTION" in f.title
    assert f.confidence >= 0.80
    assert f.severity == SEVERITY_HIGH
    assert f.source_engine == "MOEngine"
    assert f.engine_version == "2.0"
    assert "msg-01" in f.event_refs
    assert "evfile-01" in f.evidence_refs
    assert len(f.citations) >= 4
    assert f.component_scores["calculation_breakdown"]["is_confident"] is True
