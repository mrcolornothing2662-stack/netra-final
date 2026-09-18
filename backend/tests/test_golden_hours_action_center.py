"""
Unit and Integration Tests for Feature 06: Golden Hours Action Center
Validates:
1. Multi-window exponential decay curves (2h, 24h, 48h) and window phase classification.
2. Transparent VoI weighted utility ranking and missing field blockers.
3. Grounded evidence gap derivation (ENTITY_ATTRIBUTION, DEVICE_ATTRIBUTION, UNKNOWN_ENDPOINT, TEMPORAL_RECONCILIATION, INFERRED_LINK_CORROBORATION, OPEN_UNCERTAINTY).
4. Pre-filled statutory notice drafting with mandatory DRAFT banner under Section 193 BNSS.
5. Orchestration adapter (NextBestEngine) compatibility and CognitiveResult emission.
6. API Handlers for GET /cases/{case_id}/next-best-actions and POST /cases/{case_id}/actions/{action_code}/draft.
"""
from __future__ import annotations

import math
import uuid
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from cognitive.nextbest import (
    load_catalog,
    rank_actions,
    compute_urgency,
    classify_window_phase,
    extract_evidence_gap_actions,
    render_statutory_notice,
    BANNER_REQUIRED_SUBSTRING,
    PHASE_CRITICAL,
    PHASE_EXTENDED,
    PHASE_DECAYED,
)
from cognitive import data_path
from orchestration.contracts import (
    NEXT_BEST_ACTION,
    CaseContext,
    CognitiveResult,
)
from orchestration.engines.nextbest import SPEC as nextbest_spec, applies, run as nextbest_run
from routes.cognitive import get_next_best_actions, generate_action_draft, ActionDraftRequest
from db.models import Case, EvidenceFile, InvestigationFinding, EvidenceEvent, Relationship, User


# ── Analytical Core Tests ───────────────────────────────────────────────────

def test_multi_window_urgency_decay_and_phases():
    """Verify exponential decay curves and phase transitions."""
    # At t = 0
    assert compute_urgency(0.0, 2.0) == 1.0
    assert classify_window_phase(0.0, 2.0) == PHASE_CRITICAL

    # At t = 1.0h
    u_1h = compute_urgency(1.0, 2.0)
    assert 0.60 < u_1h < 0.61  # exp(-0.5) ≈ 0.6065
    assert classify_window_phase(1.0, 2.0) == PHASE_CRITICAL

    # At t = 2.0h (threshold)
    assert classify_window_phase(2.0, 2.0) == PHASE_CRITICAL

    # At t = 5.0h
    assert classify_window_phase(5.0, 2.0) == PHASE_EXTENDED

    # At t = 25.0h
    assert classify_window_phase(25.0, 2.0) == PHASE_DECAYED

    # Compare 2h vs 48h decay rates at t = 2h
    u_freeze = compute_urgency(2.0, 2.0)  # exp(-1) ≈ 0.3679
    u_cdr = compute_urgency(2.0, 48.0)    # exp(-2/48) ≈ 0.9592
    assert u_cdr > u_freeze, "Telecom CDR has longer persistence window than bank stop-payment"


def test_catalog_ranking_and_missing_field_blocking():
    """Verify transparent utility scoring and missing field blocking."""
    catalog = load_catalog(data_path("action_catalog.json"))
    assert catalog["golden_hours"] == 2.0

    # Case state with complete bank info -> ready action
    case_state_ready = {
        "elapsed_hours_since_first_credit": 0.5,
        "complaint_ref": "FIR-2026-001",
        "accounts_at_risk": [{
            "account": "1234567890",
            "ifsc": "HDFC0001234",
            "bank_name": "HDFC Bank",
            "amount_unwithdrawn": 250000.0,
        }],
        "unresolved_phones": [],
        "crime_window_cells": [],
    }
    ranked = rank_actions(case_state_ready, catalog)
    assert ranked["window_phase"] == PHASE_CRITICAL
    actions = ranked["ranked_actions"]
    assert len(actions) >= 1

    freeze_action = next((a for a in actions if a["action_code"] == "FREEZE_ACCOUNT_EVIDENCE"), None)
    assert freeze_action is not None
    assert freeze_action["status"] == "ready"
    assert freeze_action["utility_score"] is not None
    assert freeze_action["utility_score"] > 0
    assert freeze_action["missing_fields"] == []
    assert BANNER_REQUIRED_SUBSTRING in freeze_action["draft"]

    # Case state with missing IFSC and bank_name -> blocked action
    case_state_blocked = {
        "elapsed_hours_since_first_credit": 0.5,
        "complaint_ref": "FIR-2026-001",
        "accounts_at_risk": [{
            "account": "1234567890",
            "ifsc": None,
            "bank_name": None,
            "amount_unwithdrawn": 250000.0,
        }],
        "unresolved_phones": [],
        "crime_window_cells": [],
    }
    ranked_blocked = rank_actions(case_state_blocked, catalog)
    freeze_blocked = next((a for a in ranked_blocked["ranked_actions"] if a["action_code"] == "FREEZE_ACCOUNT_EVIDENCE"), None)
    assert freeze_blocked is not None
    assert freeze_blocked["status"] == "blocked_missing_fields"
    assert "ifsc" in freeze_blocked["missing_fields"]
    assert "bank_name" in freeze_blocked["missing_fields"]
    assert freeze_blocked["draft"] is None


def test_evidence_gap_action_derivation():
    """Verify grounded evidence gaps are converted into concrete actions."""
    context = {
        "events": [
            {
                "id": "ev_bank_1",
                "event_type": "bank_txn",
                "evidence_file_id": "file_1",
                "metadata": {"to_account": "ACCT-MULE-99", "amount": 150000.0},
            },
            {
                "id": "ev_call_1",
                "event_type": "call",
                "evidence_file_id": "file_2",
                "metadata": {"caller": "+919876543210", "callee": "UNKNOWN"},
            },
        ],
        "entities": [
            {"id": "e1", "canonical_value": "ACCT-MULE-99", "entity_type": "ACCOUNT"},
            {"id": "e2", "canonical_value": "+919876543210", "entity_type": "PHONE"},
        ],
        "relationships": [
            {
                "source_value": "ACCT-MULE-99",
                "target_value": "+919876543210",
                "epistemic_status": "INFERRED",
                "confidence": 0.85,
                "event_refs": ["ev_bank_1"],
                "evidence_refs": ["file_1"],
            }
        ],
        "findings": [],
    }

    gaps = extract_evidence_gap_actions(context, max_gap_actions=6)
    gap_types = {g["gap"] for g in gaps}

    assert "ENTITY_ATTRIBUTION" in gap_types
    assert "DEVICE_ATTRIBUTION" in gap_types
    assert "UNKNOWN_ENDPOINT" in gap_types
    assert "TEMPORAL_RECONCILIATION" in gap_types
    assert "INFERRED_LINK_CORROBORATION" in gap_types

    # Check that each action carries provenance and legal basis
    for g in gaps:
        assert g["statutory_basis"] is not None
        assert g["banner"] is not None
        assert g["information_value"] in ("HIGH", "MEDIUM", "LOW")
        assert g["evidence_refs"] or g["event_refs"] or g["entity_refs"]


def test_statutory_notice_draft_rendering():
    """Verify legal notice generation under Sections 106, 94 BNSS & I4C 1930."""
    case_meta = {
        "fir_number": "FIR-2026-CYBER-88",
        "case_number": "CYB-2026-88",
        "police_station": "Cyber Crime PS Cyberabad",
    }

    # 1. Section 106 BNSS Freeze Notice
    res_freeze = render_statutory_notice(
        action_code="FREEZE_ACCOUNT_EVIDENCE",
        target={
            "account": "987654321098",
            "ifsc": "SBIN0001234",
            "bank_name": "State Bank of India",
            "amount_unwithdrawn": "1,85,000.00",
        },
        case_meta=case_meta,
    )
    assert res_freeze["statute"] == "Section 106 BNSS, 2023"
    assert BANNER_REQUIRED_SUBSTRING in res_freeze["banner"]
    assert "SECTION 106" in res_freeze["notice_text"]
    assert "987654321098" in res_freeze["notice_text"]
    assert "State Bank of India" in res_freeze["notice_text"]
    assert "Section 106(3) BNSS" in res_freeze["notice_text"]  # Magistrate reporting

    # 2. Section 94 BNSS CDR Requisition
    res_cdr = render_statutory_notice(
        action_code="REQUISITION_CDR_IPDR",
        target={
            "phone": "+919876543210",
            "period_start": "2026-08-18 00:00 UTC",
            "period_end": "2026-08-18 23:59 UTC",
        },
        case_meta=case_meta,
    )
    assert res_cdr["statute"] == "Section 94 BNSS, 2023"
    assert "SECTION 94 BNSS" in res_cdr["notice_text"]
    assert "+919876543210" in res_cdr["notice_text"]
    assert "Section 63(4)" in res_cdr["notice_text"]


# ── Orchestration Engine Adapter Tests ──────────────────────────────────────

def test_nextbest_engine_spec_adapter():
    """Test NextBestEngine adapter contracts and CognitiveResult emission."""
    ctx_empty = CaseContext(case_id="c_empty", evidence_files=[], events=[], entities=[])
    assert applies(ctx_empty) is False

    ctx = CaseContext(
        case_id="c_active",
        case_created_at="2026-08-18T10:00:00Z",
        evidence_files=[{"id": "f1", "filename": "bank.pdf"}],
        events=[
            {
                "id": "ev_1",
                "event_type": "bank_txn",
                "evidence_file_id": "f1",
                "event_metadata": {"account": "ACCT-999", "balance": 120000.0},
            }
        ],
        entities=[{"canonical_value": "ACCT-999", "entity_type": "ACCOUNT"}],
    )
    assert applies(ctx) is True

    results = nextbest_run(ctx)
    assert isinstance(results, list)
    assert len(results) >= 1

    for r in results:
        assert isinstance(r, CognitiveResult)
        assert r.finding_type == NEXT_BEST_ACTION
        assert r.source_engine == "NextBestEngine"
        assert r.dedup_key is not None
        assert "urgency_factor" in r.component_scores or "evidence_gap" in r.component_scores


# ── API Route Handler Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_next_best_actions_handler():
    """Test get_next_best_actions route handler with mocked DB session."""
    mock_case_id = str(uuid.uuid4())
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid.uuid4()
    mock_user.role = "admin"

    mock_case = MagicMock(spec=Case)
    mock_case.id = uuid.UUID(mock_case_id)
    mock_case.assigned_officer_id = mock_user.id
    mock_case.fir_number = "FIR-2026-099"
    mock_case.case_number = "CYB-2026-099"
    mock_case.created_at = None

    mock_db = AsyncMock()

    with patch("routes.cognitive.require_case_access", new=AsyncMock(return_value=mock_case)), \
         patch("routes.cognitive._get_bank_events", new=AsyncMock(return_value=[
             {"account": "ACCT-MULE", "balance": 95000.0, "amount_val": 95000.0}
         ])), \
         patch("routes.cognitive._get_case_entities", new=AsyncMock(return_value=[
             {"id": "e1", "value": "ACCT-MULE", "entity_type": "ACCOUNT"},
             {"id": "e2", "value": "+919876543210", "entity_type": "PHONE"},
         ])):

        def execute_side_effect(stmt):
            res = MagicMock()
            res.scalars.return_value.all.return_value = []
            return res

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        res = await get_next_best_actions(case_id=mock_case_id, db=mock_db, current=mock_user)
        assert isinstance(res, dict)
        assert res["case_id"] == mock_case_id
        assert "ranked_actions" in res
        assert "summary" in res
        assert "window_phase" in res
        assert "financial_exposure" in res
        assert res["financial_exposure"] == 95000.0


@pytest.mark.asyncio
async def test_generate_action_draft_handler():
    """Test generate_action_draft route handler."""
    mock_case_id = str(uuid.uuid4())
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid.uuid4()
    mock_user.role = "admin"

    mock_case = MagicMock(spec=Case)
    mock_case.id = uuid.UUID(mock_case_id)
    mock_case.assigned_officer_id = mock_user.id
    mock_case.fir_number = "FIR-2026-101"
    mock_case.case_number = "CYB-2026-101"
    mock_case.police_station = "Cyber Crime Unit"

    mock_db = AsyncMock()
    body = ActionDraftRequest(target={
        "account": "1122334455",
        "ifsc": "SBIN0000001",
        "bank_name": "State Bank of India",
        "amount_unwithdrawn": "50,000",
    })

    with patch("routes.cognitive.require_case_access", new=AsyncMock(return_value=mock_case)):
        res = await generate_action_draft(
            case_id=mock_case_id,
            action_code="FREEZE_ACCOUNT_EVIDENCE",
            body=body,
            db=mock_db,
            current=mock_user,
        )
        assert isinstance(res, dict)
        assert res["action_code"] == "FREEZE_ACCOUNT_EVIDENCE"
        assert res["statute"] == "Section 106 BNSS, 2023"
        assert "1122334455" in res["notice_text"]
        assert BANNER_REQUIRED_SUBSTRING in res["banner"]
