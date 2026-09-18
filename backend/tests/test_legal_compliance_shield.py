"""
Unit and Integration Tests for Feature 09: Legal Compliance Shield
Validates:
1. Statutory DB post-July-2024 compliance, bidirectional mapping, and judicial authorities.
2. Legal Citation AST Parser (standard, colloquial u/s, compound, subsections, inverted).
3. Multi-entity span grounding (Amounts, Accounts, Phones, UPIs, IPs, Devices, Hashes).
4. Section 63 BSA Evidence Integrity Audit (hash preservation, custody memo).
5. Governance verdict firewall (COMPLIANT, NEEDS_REVIEW, GOVERNANCE_BLOCKED).
6. API endpoints: /cognitive/verify-draft and /cognitive/cases/{case_id}/compliance-shield.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from fastapi import FastAPI
from cognitive.verifier import OutputVerifier, LegalCitationNode, EvidenceIntegrityAudit
from db.models import EvidenceFile, Case, InvestigationFinding
from routes.auth import get_current_user
from routes.cognitive import router as cognitive_router
import uuid

app = FastAPI()
app.include_router(cognitive_router, prefix="/api/v1/cognitive")


@pytest.fixture(autouse=True)
def override_auth():
    mock_user = MagicMock()
    mock_user.id = uuid.uuid4()
    mock_user.username = "investigator"
    mock_user.role = "admin"
    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def statutory_db():
    candidates = [
        Path(__file__).resolve().parent.parent / "cognitive" / "data" / "statutory_db.json",
        Path("cognitive/data/statutory_db.json"),
        Path("backend/cognitive/data/statutory_db.json"),
    ]
    db_path = next((p for p in candidates if p.exists()), None)
    assert db_path is not None and db_path.exists(), "statutory_db.json must exist"
    with open(db_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def verifier():
    return OutputVerifier()


@pytest.fixture
def mock_case_facts():
    return {
        "amounts": [50000.0, 125000.0],
        "phones": ["9876543210", "+919876543210"],
        "upis": ["fraudster@okaxis", "mule@ybl"],
        "accounts": ["987654321012", "123456789012"],
        "ips": ["192.168.1.100", "10.0.0.1"],
        "devices": ["IMEI-867530901234567", "00:1A:2B:3C:4D:5E"],
        "hashes": ["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
        "named_entities": ["John Doe", "SBI Bank", "Alpha Corp"],
    }


# ── 1. Statutory Database Verification ──────────────────────────────────────────

def test_statutory_db_coverage(statutory_db):
    """Verify statutory DB covers at least 30 provisions across BNS, BNSS, BSA, IT Act, DPDP, PMLA."""
    sections_list = statutory_db.get("sections", [])
    assert len(sections_list) >= 30, f"Expected at least 30 provisions, found {len(sections_list)}"
    sec_dict = {f"{s['act']} {s['section']}": s for s in sections_list}

    # Core BNS provisions
    assert "BNS 318" in sec_dict
    assert sec_dict["BNS 318"]["status"] == "in_force"
    assert sec_dict["BNS 318"]["replaces"] == "IPC 420"

    # Core BNSS provisions
    assert "BNSS 106" in sec_dict
    assert sec_dict["BNSS 106"]["replaces"] == "CrPC 102"
    assert "BNSS 173" in sec_dict
    assert "BNSS 187" in sec_dict

    # Core BSA provisions
    assert "BSA 63" in sec_dict
    assert sec_dict["BSA 63"]["replaces"] == "IEA 65B"

    # Struck down statute
    assert "IT Act 66A" in sec_dict
    assert sec_dict["IT Act 66A"]["status"] == "struck_down"
    assert "Shreya Singhal" in sec_dict["IT Act 66A"].get("source", "") or "Shreya Singhal" in sec_dict["IT Act 66A"].get("mandatory_notes", "")

    # OutputVerifier replaces_index resolution
    verifier = OutputVerifier(statutory_db)
    assert ("IPC", "420") in verifier.replaces_index
    assert verifier.replaces_index[("IPC", "420")]["section"] == "318"
    assert ("CrPC", "102") in verifier.replaces_index
    assert verifier.replaces_index[("CrPC", "102")]["section"] == "106"
    assert ("IEA", "65B") in verifier.replaces_index
    assert verifier.replaces_index[("IEA", "65B")]["section"] == "63"


# ── 2. AST Legal Citation Parsing ─────────────────────────────────────────────

def test_parse_standard_citations(verifier):
    """Verify parsing standard citations like 'Section 318(4) BNS' and 'Section 63 BSA'."""
    text = "The suspect was charged under Section 318(4) BNS and evidence was secured under Section 63 BSA."
    nodes = verifier.parse_legal_citations(text)
    assert len(nodes) >= 2

    sec_bns = next((n for n in nodes if n.base_section == "318"), None)
    assert sec_bns is not None
    assert sec_bns.act == "BNS"
    assert sec_bns.status == "in_force"

    sec_bsa = next((n for n in nodes if n.base_section == "63"), None)
    assert sec_bsa is not None
    assert sec_bsa.act == "BSA"
    assert sec_bsa.status == "in_force"


def test_parse_colloquial_us_citations(verifier):
    """Verify parsing colloquial 'u/s 66D IT Act' and 'sec. 106 BNSS'."""
    text = "Case registered u/s 66D IT Act with freeze initiated under sec. 106 BNSS."
    nodes = verifier.parse_legal_citations(text)
    assert len(nodes) >= 2

    node_it = next((n for n in nodes if n.base_section == "66D"), None)
    assert node_it is not None
    assert node_it.act == "IT Act"
    assert node_it.status == "in_force"

    node_bnss = next((n for n in nodes if n.base_section == "106"), None)
    assert node_bnss is not None
    assert node_bnss.act == "BNSS"
    assert node_bnss.status == "in_force"


def test_parse_compound_citations(verifier):
    """Verify parsing compound citations: 'Sections 318 and 319 of BNS'."""
    text = "Offences committed under Sections 318 and 319 of BNS."
    nodes = verifier.parse_legal_citations(text)
    assert len(nodes) >= 2
    sections = [n.base_section for n in nodes]
    assert "318" in sections
    assert "319" in sections
    for n in nodes:
        assert n.act == "BNS"


def test_parse_pre_transition_citations(verifier):
    """Verify legacy IPC/CrPC/IEA citations are correctly flagged as pre_transition_act."""
    text = "Charges framed under Section 420 IPC and notice issued under Section 102 CrPC with 65B certificate."
    nodes = verifier.parse_legal_citations(text)
    assert len(nodes) >= 2

    ipc_node = next((n for n in nodes if n.act == "IPC" or n.base_section == "420"), None)
    assert ipc_node is not None
    assert ipc_node.status == "pre_transition_act"
    assert "318" in (ipc_node.replacement or "")


def test_parse_struck_down_citation(verifier):
    """Verify struck down statute (IT Act 66A) is parsed with judicial authority."""
    text = "Officer issued notice under Section 66A of Information Technology Act 2000."
    nodes = verifier.parse_legal_citations(text)
    assert len(nodes) >= 1
    node_66a = next((n for n in nodes if n.base_section == "66A"), None)
    assert node_66a is not None
    assert node_66a.status == "struck_down"
    assert "Shreya Singhal" in (node_66a.judicial_authority or "")


# ── 3. Multi-Entity Span Grounding ─────────────────────────────────────────────

def test_grounding_grounded_claims(statutory_db, mock_case_facts):
    """Verify grounded claims across amounts, accounts, phones, UPIs, IPs, devices."""
    v = OutputVerifier(statutory_db=statutory_db, case_facts=mock_case_facts)
    text = "Suspect sent Rs 50,000 from account 987654321012 using phone 9876543210 and UPI fraudster@okaxis from IP 192.168.1.100."
    all_spans, failures = v.check_grounding_spans(text)
    grounded_spans = [s for s in all_spans if s.grounded]

    assert len(failures) == 0
    assert len(grounded_spans) >= 4
    types_found = {s.claim_type for s in grounded_spans}
    assert "amounts" in types_found
    assert "phones" in types_found
    assert "upis" in types_found
    assert "ips" in types_found


def test_grounding_hallucinated_claims(statutory_db, mock_case_facts):
    """Verify ungrounded/hallucinated entities are flagged as failures."""
    v = OutputVerifier(statutory_db=statutory_db, case_facts=mock_case_facts)
    text = "Suspect transferred Rs 999,999 to account ACCT-FAKE-999 from IP 203.0.113.5."
    all_spans, failures = v.check_grounding_spans(text)

    assert len(failures) >= 2
    failure_types = {f["claim_type"] for f in failures}
    assert "amounts" in failure_types
    assert "ips" in failure_types or "accounts" in failure_types


# ── 4. Section 63 BSA Evidence Integrity Audit ────────────────────────────────

def test_evidence_integrity_audit_all_hashed():
    """Verify 100% integrity when all evidence files are SHA-256 preserved."""
    verifier = OutputVerifier()
    files = [
        {"id": "f1", "original_name": "04_call_detail_record.csv", "sha256_hash": "a" * 64, "upload_status": "processed"},
        {"id": "f2", "original_name": "07_upi_transaction_report.pdf", "sha256_hash": "b" * 64, "upload_status": "processed"},
        {"id": "f3", "original_name": "10_chain_of_custody_memo.pdf", "sha256_hash": "c" * 64, "upload_status": "processed"},
    ]
    audit = verifier.audit_evidence_integrity(files)
    assert audit.total_files == 3
    assert audit.hashed_files == 3
    assert audit.integrity_score == 1.0
    assert audit.has_custody_memo is True
    assert audit.status == "VERIFIED_INTEGRITY"
    assert len(audit.warnings) == 0


def test_evidence_integrity_audit_missing_hash():
    """Verify DEFICIENT_INTEGRITY when files lack SHA-256 hash."""
    verifier = OutputVerifier()
    files = [
        {"id": "f1", "original_name": "04_cdr.csv", "sha256_hash": "a" * 64, "upload_status": "processed"},
        {"id": "f2", "original_name": "unhashed_file.pdf", "sha256_hash": None, "upload_status": "processed"},
    ]
    audit = verifier.audit_evidence_integrity(files)
    assert audit.total_files == 2
    assert audit.hashed_files == 1
    assert audit.unhashed_files == 1
    assert audit.integrity_score == 0.5
    assert audit.status == "DEFICIENT_INTEGRITY"
    assert any("lack a SHA-256" in w for w in audit.warnings)


# ── 5. Governance Evaluation & Critique ────────────────────────────────────────

def test_governance_verdict_compliant(mock_case_facts):
    """Verify COMPLIANT verdict when draft uses post-2024 laws and grounded facts."""
    verifier = OutputVerifier(case_facts=mock_case_facts)
    draft = "Offence investigated under Section 173 BNSS reveals fraud under Section 318(4) BNS. Rs 50,000 was moved via phone 9876543210. Evidence certified under Section 63 BSA."
    evidence_files = [
        {"id": "f1", "original_name": "10_custody_memo.pdf", "sha256_hash": "a" * 64, "upload_status": "processed"}
    ]
    res = verifier.critique(draft, evidence_files=evidence_files)
    assert res.governance_verdict == "COMPLIANT"
    assert res.passed is True
    assert len(res.citations) >= 3


def test_governance_verdict_needs_review_legacy(mock_case_facts):
    """Verify NEEDS_REVIEW verdict when draft uses legacy pre-transition statutes."""
    verifier = OutputVerifier(case_facts=mock_case_facts)
    draft = "FIR lodged under Section 420 IPC and Section 102 CrPC. Rs 50,000 involved."
    res = verifier.critique(draft)
    assert res.governance_verdict == "NEEDS_REVIEW"
    assert res.passed is False
    assert any("STATUTORY MIGRATION" in r for r in res.governance_reasons)


def test_governance_verdict_governance_blocked(mock_case_facts):
    """Verify GOVERNANCE_BLOCKED verdict when draft uses struck-down statute (IT Act 66A)."""
    verifier = OutputVerifier(case_facts=mock_case_facts)
    draft = "Summons issued under Section 66A of Information Technology Act 2000 for defamatory statements."
    res = verifier.critique(draft)
    assert res.governance_verdict == "GOVERNANCE_BLOCKED"
    assert res.passed is False
    assert any("PROHIBITED STATUTE" in r for r in res.governance_reasons)


# ── 6. API Integration Tests ───────────────────────────────────────────────────

def test_api_verify_draft_endpoint():
    """Verify POST /cognitive/verify-draft endpoint returns enriched legal compliance metadata."""
    client = TestClient(app)
    payload = {
        "draft_text": "Case registered under Section 318(4) BNS and Section 66D IT Act with Section 63 BSA compliance."
    }
    response = client.post("/api/v1/cognitive/verify-draft", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "governance_verdict" in data
    assert data["governance_verdict"] == "COMPLIANT"
    assert "citations" in data
    assert len(data["citations"]) >= 2
    assert "admissibility_disclaimer" in data
    assert "Section 63" in data["admissibility_disclaimer"]


def test_api_verify_draft_struck_down():
    """Verify POST /cognitive/verify-draft immediately blocks IT Act 66A."""
    client = TestClient(app)
    payload = {
        "draft_text": "Charges brought under Section 66A IT Act."
    }
    response = client.post("/api/v1/cognitive/verify-draft", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["governance_verdict"] == "GOVERNANCE_BLOCKED"
    assert data["passed"] is False
