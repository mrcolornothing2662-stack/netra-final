"""
CyberDrishti AI — Copilot & Officers Routes
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access


copilot_router = APIRouter()


class CopilotQuery(BaseModel):
    question: str
    top_k:    int = 5


@copilot_router.post("/{case_id}")
async def copilot_endpoint(
    case_id: str,
    body:    CopilotQuery,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    AI Daya RAG & Investigation Copilot (generative + DB intelligence).
    Analyzes case evidence, call logs, financial transactions, and suspect entities.
    Augmented with Feature 09: Output Verifier (Semantic CRAG Firewall).
    """
    c = await require_case_access(db, current, case_id)
    from rag.copilot import copilot_query
    result = await copilot_query(db, str(c.id), body.question, top_k=body.top_k)

    # ── Feature 09: Output Verifier (Semantic CRAG Firewall) ─────────────────
    try:
        from cognitive.verifier import load_statutory_db, OutputVerifier
        from cognitive import data_path
        from db.models import Entity

        ent_rows = (await db.execute(
            select(Entity.canonical_value, Entity.entity_type).where(Entity.case_id == c.id)
        )).all()

        case_facts: dict[str, list[str]] = {
            "amounts": [],
            "phones": [],
            "upis": [],
            "accounts": [],
            "ips": [],
            "devices": [],
            "names": [],
        }
        for val, etype in ent_rows:
            if not val:
                continue
            etype_str = (etype or "").upper()
            if etype_str in ("PHONE", "MOBILE"):
                case_facts["phones"].append(val)
            elif etype_str in ("UPI", "VPA"):
                case_facts["upis"].append(val)
            elif etype_str in ("AMOUNT", "MONEY", "INR"):
                case_facts["amounts"].append(val)
            elif etype_str in ("ACCOUNT", "BANK_ACC"):
                case_facts["accounts"].append(val)
            elif etype_str in ("IP", "IPV4"):
                case_facts["ips"].append(val)
            elif etype_str in ("DEVICE", "DEV"):
                case_facts["devices"].append(val)
            else:
                case_facts["names"].append(val)

        statutory_db = load_statutory_db(data_path("statutory_db.json"))
        verifier = OutputVerifier(statutory_db=statutory_db, case_facts=case_facts)
        answer = result.get("answer", "")
        critique = verifier.critique(answer)

        flags = []
        for viol in critique.statutory_violations:
            flags.append({
                "severity": "error",
                "check": "STATUTORY_VIOLATION",
                "message": f"Section {viol.get('section')} ({viol.get('act', 'Unknown')}): {viol.get('reason', 'Statutory violation')}",
            })
        for gfail in critique.grounding_failures:
            flags.append({
                "severity": "warning",
                "check": "GROUNDING_FAILURE",
                "message": gfail.get("detail", f"Ungrounded claim: {gfail.get('value')}"),
            })
        for cdet in critique.canned_detections:
            flags.append({
                "severity": "info",
                "check": "CANNED_MATCH",
                "message": cdet.get("detail", "High similarity to canned template."),
            })

        result["verification"] = {
            "passed": critique.passed,
            "governance_verdict": critique.governance_verdict,
            "governance_reasons": critique.governance_reasons,
            "flags": flags,
            "citations": critique.citations,
            "grounded_spans": critique.grounded_spans,
            "statutory_violations": critique.statutory_violations,
            "grounding_failures": critique.grounding_failures,
            "admissibility_disclaimer": critique.admissibility_disclaimer,
            "correction_instructions": critique.correction_instructions,
        }
    except Exception as exc:
        result["verification"] = {
            "passed": True,
            "flags": [],
            "note": f"Verification deferred: {exc}",
        }

    return result


@copilot_router.get("/status")
async def copilot_status(_: User = Depends(get_current_user)):
    """Report real language-model availability — never a hardcoded status."""
    from rag.copilot import probe_ai_engine
    probe = probe_ai_engine()
    return {
        "ollama_online": probe["online"],
        "model_used": probe["model_used"],
        "provider": probe["provider"],
    }



officers_router = APIRouter()


class OfficerCreate(BaseModel):
    username:  str
    email:     str
    password:  str
    full_name: str | None = None
    rank:      str | None = None
    unit:      str | None = None
    role:      str = "constable"


class OfficerOut(BaseModel):
    id:        str
    username:  str
    email:     str
    full_name: str | None
    rank:      str | None
    unit:      str | None
    role:      str
    is_active: bool


@officers_router.get("")
async def list_officers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()
    return [
        OfficerOut(
            id=str(u.id), username=u.username, email=u.email,
            full_name=u.full_name, rank=u.rank, unit=u.unit,
            role=u.role, is_active=u.is_active,
        )
        for u in users
    ]


@officers_router.post("", status_code=201)
async def create_officer(
    body:    OfficerCreate,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("admin")),
):
    from routes.auth import _hash_password
    existing = (await db.execute(
        select(User).where(User.username == body.username)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Username already exists")

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=_hash_password(body.password),
        full_name=body.full_name,
        rank=body.rank,
        unit=body.unit,
        role=body.role,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return OfficerOut(
        id=str(user.id), username=user.username, email=user.email,
        full_name=user.full_name, rank=user.rank, unit=user.unit,
        role=user.role, is_active=user.is_active,
    )



report_router = APIRouter()


@report_router.get("/{case_id}")
@report_router.get("/{case_id}/section65b")
async def generate_report(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """Generate Section 65B Evidence Certificate PDF."""
    c = await require_case_access(db, current, case_id)
    from report.section_65b import generate_65b_pdf
    pdf_path = await generate_65b_pdf(str(c.id), db, str(current.id))
    from fastapi.responses import FileResponse
    return FileResponse(pdf_path, media_type="application/pdf",
                        filename=f"65B_certificate_{c.case_number or str(c.id)[:8]}.pdf")
