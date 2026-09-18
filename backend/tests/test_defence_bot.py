"""
Unit and Integration Tests for Defence Bot — Adversarial Hypothesis Stress-Testing
Validates:
1. Pure analytical core (cognitive.defence.audit_case_defensibility & stress_test_claim).
2. Grounded adversarial challenges for mule pass-throughs, telecom CDR, network IP, and Section 63 BSA custody.
3. Quantitative Defensibility Index (0.0 - 1.0) and Risk Level rating.
4. Epistemic humility compliance (judicial disclaimer, no guilt/innocence declarations).
5. Orchestration adapter (DefenceBotEngine EngineSpec) mapping to DEFENCE_CHALLENGE CognitiveResults.
6. API Handlers: get_defence_audit and defence_stress_test.
"""
import uuid
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from cognitive.defence import (
    audit_case_defensibility,
    stress_test_claim,
    DefenceChallenge,
    DefenceAuditReport,
    EPISTEMIC_DEFENCE_NOTICE,
)
from orchestration.contracts import (
    DEFENCE_CHALLENGE,
    CaseContext,
    CognitiveResult,
)
from orchestration.engines.defence import SPEC as defence_spec, applies, run as defence_run
from routes.cognitive import get_defence_audit, defence_stress_test, DefenceStressTestRequest
from db.models import Case, EvidenceFile, InvestigationFinding, EvidenceEvent, User


# ── Analytical Core Tests ───────────────────────────────────────────────────

def test_audit_bsa_preservation_vulnerabilities():
    """Test that missing hashes and absence of seizure memo triggers Section 63 BSA challenge."""
    files = [
        {"id": "f1", "filename": "statement.csv", "sha256_hash": ""},  # No hash
        {"id": "f2", "filename": "chats.txt", "sha256_hash": "abc"},   # Invalid hash
    ]
    report = audit_case_defensibility(
        case_id="case_101",
        evidence_files=files,
        events=[],
        findings=[],
    )

    assert isinstance(report, DefenceAuditReport)
    assert report.case_id == "case_101"
    assert report.bsa_compliance_status["compliant_with_bsa_63"] is False
    assert report.bsa_compliance_status["has_seizure_memo"] is False
    assert report.bsa_compliance_status["preservation_score"] == 0.0

    # Section 63 BSA challenge should be present with CRITICAL severity
    bsa_challenges = [c for c in report.challenges if c.target_hypothesis == "DIGITAL_EVIDENCE_AUTHENTICITY"]
    assert len(bsa_challenges) == 1
    ch = bsa_challenges[0]
    assert ch.vulnerability_severity == "CRITICAL"
    assert any("Section 63(4)" in m.get("statutory_rule", "") for m in ch.missing_evidence)
    assert any("Section 105 BNSS" in m.get("statutory_rule", "") for m in ch.missing_evidence)
    assert len(ch.reasonable_doubts) >= 2


def test_audit_mule_pass_through_challenge():
    """Test that behavioral anomaly findings (rapid pass-through) generate targeted mule defenses."""
    files = [
        {"id": "f1", "filename": "File_02_Bank_Statement.csv", "sha256_hash": "a" * 64},
        {"id": "f2", "filename": "File_10_Seizure_Memo.pdf", "sha256_hash": "b" * 64},
    ]
    findings = [
        {
            "finding_type": "BEHAVIORAL_ANOMALY",
            "entity": "rohan@upi",
            "evidence_refs": ["f1"],
            "event_refs": ["ev_1", "ev_2"],
            "component_scores": {"entity": "rohan@upi"},
        }
    ]

    report = audit_case_defensibility(
        case_id="case_meridian",
        evidence_files=files,
        events=[],
        findings=findings,
    )

    mule_challenges = [c for c in report.challenges if c.target_hypothesis == "LAYER1_MULE_ACCUSATION"]
    assert len(mule_challenges) == 1
    m_ch = mule_challenges[0]
    assert m_ch.target_entity == "rohan@upi"
    assert "account compromise" in m_ch.defense_counter_hypothesis.lower() or "commercial" in m_ch.defense_counter_hypothesis.lower()
    assert any("mens rea" in d.lower() for d in m_ch.reasonable_doubts)
    assert any("KYC" in m.get("item", "") for m in m_ch.missing_evidence)
    assert any("94 BNSS" in r.get("recommendation", "") for r in m_ch.rebuttal_strategy)


def test_audit_telecom_and_network_challenges():
    """Test CDR and network log cross-examination."""
    files = [
        {"id": "f1", "filename": "File_03_Telecom_CDR.csv", "sha256_hash": "c" * 64},
        {"id": "f2", "filename": "File_07_Network_IP_Logs.csv", "sha256_hash": "d" * 64},
        {"id": "f3", "filename": "File_10_Seizure_Memo.pdf", "sha256_hash": "e" * 64},
    ]
    events = [
        {"event_type": "call", "caller": "+919876543210", "receiver": "+911122334455"},
        {"event_type": "call", "caller": "+919876543210", "receiver": "+919988776655"},
    ]

    report = audit_case_defensibility(
        case_id="case_telecom",
        evidence_files=files,
        events=events,
        findings=[],
    )

    telecom_ch = next((c for c in report.challenges if c.target_hypothesis == "COMMUNICATION_CONSPIRACY"), None)
    assert telecom_ch is not None
    assert telecom_ch.target_entity == "+919876543210"
    assert any("tower" in d.lower() for d in telecom_ch.reasonable_doubts)
    assert any("CAF" in m.get("item", "") for m in telecom_ch.missing_evidence)

    ip_ch = next((c for c in report.challenges if c.target_hypothesis == "IP_ADDRESS_ATTRIBUTION"), None)
    assert ip_ch is not None
    assert any("NAT" in d or "proxy" in d for d in ip_ch.reasonable_doubts)


def test_epistemic_humility_standard():
    """Verify strictly epistemic phrasing: judicial disclaimer present, zero guilty declarations."""
    report = audit_case_defensibility(
        case_id="case_test",
        evidence_files=[],
        events=[],
        findings=[],
    )
    assert EPISTEMIC_DEFENCE_NOTICE in report.epistemic_notice
    assert "Section 193 BNSS" in report.epistemic_notice
    assert "trial court" in report.epistemic_notice

    # Check to_dict serialization
    d = report.to_dict()
    assert d["case_id"] == "case_test"
    assert "challenges" in d
    assert "defensibility_score" in d
    assert "risk_level" in d


def test_stress_test_claim_presets():
    """Test on-demand claim stress testing for mule, telecom, and forensic claims."""
    # 1. Mule claim
    res1 = stress_test_claim("Rohan is an active money mule who laundered the proceeds via UPI")
    assert "mule" in res1["counter_hypotheses"][0].lower() or "compromised" in res1["counter_hypotheses"][0].lower()
    assert any("mens rea" in d.lower() for d in res1["reasonable_doubts"])
    assert any("login ip" in p.lower() or "device" in p.lower() for p in res1["missing_proof_checklist"])
    assert res1["epistemic_status"] == "ADVERSARIAL_SIMULATION"

    # 2. Telecom claim
    res2 = stress_test_claim("The suspect made 45 calls from cell tower location X to coordinate the extortion")
    assert any("tower" in d.lower() or "signal" in d.lower() for d in res2["reasonable_doubts"])
    assert any("caf" in p.lower() or "handset" in p.lower() for p in res2["missing_proof_checklist"])

    # 3. Digital evidence claim
    res3 = stress_test_claim("Seized WhatsApp chats prove criminal conspiracy")
    assert any("63 bsa" in d.lower() or "panch" in d.lower() or "custody" in d.lower() for d in res3["reasonable_doubts"])


# ── Orchestration Engine Tests ──────────────────────────────────────────────

def test_defence_engine_spec_contract():
    """Test EngineSpec integration: applies() and run() returning CognitiveResult."""
    ctx_empty = CaseContext(case_id="c_empty", evidence_files=[], events=[], findings=[])
    assert applies(ctx_empty) is False

    ctx = CaseContext(
        case_id="c_active",
        evidence_files=[{"id": "ev_1", "filename": "statement.csv", "sha256_hash": "f" * 64}],
        events=[],
        findings=[{"finding_type": "BEHAVIORAL_ANOMALY", "entity": "mule@upi"}],
    )
    assert applies(ctx) is True

    results = defence_run(ctx)
    assert isinstance(results, list)
    assert len(results) >= 1
    for r in results:
        assert isinstance(r, CognitiveResult)
        assert r.finding_type == DEFENCE_CHALLENGE
        assert r.source_engine == "DefenceBotEngine"
        assert r.engine_version == "1.0"
        assert "defensibility_score" in r.component_scores
        assert "risk_level" in r.component_scores
        assert r.citations is not None
        assert r.dedup_key.startswith("defence:")


# ── Route Handler Integration Tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_defence_audit_handler():
    """Test get_defence_audit route handler with mocked DB session and entities."""
    mock_case_id = str(uuid.uuid4())
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid.uuid4()
    mock_user.role = "admin"

    mock_case = MagicMock(spec=Case)
    mock_case.id = uuid.UUID(mock_case_id)
    mock_case.assigned_officer_id = mock_user.id

    mock_file = MagicMock(spec=EvidenceFile)
    mock_file.id = uuid.uuid4()
    mock_file.original_name = "File_02_Bank_Statement.csv"
    mock_file.file_type = "csv"
    mock_file.source_type = "bank"
    mock_file.sha256_hash = "a" * 64
    mock_file.upload_status = "processed"

    mock_finding = MagicMock(spec=InvestigationFinding)
    mock_finding.id = uuid.uuid4()
    mock_finding.finding_type = "BEHAVIORAL_ANOMALY"
    mock_finding.title = "Pass-Through Anomaly (rohan@upi)"
    mock_finding.description = "Rapid turnaround"
    mock_finding.confidence = 0.9
    mock_finding.severity = "HIGH"
    mock_finding.entity_refs = ["rohan@upi"]
    mock_finding.event_refs = []
    mock_finding.evidence_refs = []
    mock_finding.component_scores = {"entity": "rohan@upi"}

    mock_db = AsyncMock()

    with patch("routes.cognitive.require_case_access", new=AsyncMock(return_value=mock_case)):
        def execute_side_effect(stmt):
            res = MagicMock()
            s_str = str(stmt).lower()
            if "evidence_files" in s_str:
                res.scalars.return_value.all.return_value = [mock_file]
            elif "investigation_findings" in s_str:
                res.scalars.return_value.all.return_value = [mock_finding]
            elif "evidence_events" in s_str:
                res.scalars.return_value.all.return_value = []
            else:
                res.scalars.return_value.all.return_value = []
            return res

        mock_db.execute = AsyncMock(side_effect=execute_side_effect)

        res = await get_defence_audit(case_id=mock_case_id, db=mock_db, current=mock_user)
        assert isinstance(res, dict)
        assert res["case_id"] == mock_case_id
        assert "defensibility_score" in res
        assert "risk_level" in res
        assert "challenges" in res
        assert len(res["challenges"]) >= 1
        assert "epistemic_notice" in res


@pytest.mark.asyncio
async def test_defence_stress_test_handler():
    """Test defence_stress_test route handler with mocked copilot response."""
    mock_case_id = str(uuid.uuid4())
    mock_user = MagicMock(spec=User)
    mock_user.id = uuid.uuid4()
    mock_user.role = "admin"

    mock_case = MagicMock(spec=Case)
    mock_case.id = uuid.UUID(mock_case_id)
    mock_case.assigned_officer_id = mock_user.id

    mock_db = AsyncMock()
    body = DefenceStressTestRequest(claim="Rohan is an active money mule who laundered the extortion funds", top_k=5)

    with patch("routes.cognitive.require_case_access", new=AsyncMock(return_value=mock_case)), \
         patch("rag.copilot.copilot_defence_query", new=AsyncMock(return_value={
             "claim_id": "st_123",
             "tested_claim": body.claim,
             "adversarial_posture": "RED_TEAM_CHALLENGE",
             "counter_hypotheses": ["Innocent account compromise."],
             "reasonable_doubts": ["No mens rea established."],
             "missing_proof_checklist": ["Login IP records"],
             "rebuttal_recommendations": ["Issue Notice 94 BNSS"],
             "epistemic_status": "ADVERSARIAL_SIMULATION",
             "epistemic_notice": EPISTEMIC_DEFENCE_NOTICE,
         })):
        res = await defence_stress_test(case_id=mock_case_id, body=body, db=mock_db, current=mock_user)
        assert isinstance(res, dict)
        assert res["tested_claim"] == body.claim
        assert len(res["counter_hypotheses"]) == 1
        assert len(res["reasonable_doubts"]) == 1
        assert res["epistemic_notice"] == EPISTEMIC_DEFENCE_NOTICE
