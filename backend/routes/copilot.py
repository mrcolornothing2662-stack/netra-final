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
    NETRA Forensic Copilot endpoint.
    Executes full multi-modal RAG pipeline:
      User Query
      -> Query Understanding (QueryPlanner)
      -> Multi-Modal Hybrid Retrieval (Vector, Graph, Structured, Timeline)
      -> Weighted RRF Fusion
      -> Candidate Reranking & Forensic Signal Scoring
      -> Epistemic Context Building (Observed vs Inferred)
      -> Grounded Prompt Synthesis
      -> Offline-Safe Generator Execution
      -> Fact & Citation Claim Verification
      -> Formatted Forensic Response
    """
    import re
    c = await require_case_access(db, current, case_id)
    clean_case_id = str(c.id)

    from copilot.config import get_copilot_config
    from copilot.query_planner import QueryPlanner
    from copilot.hybrid_retriever import HybridRetriever
    from copilot.vector_store import VectorStore
    from copilot.graph_retriever import GraphRetriever
    from copilot.structured_retriever import StructuredRetriever
    from copilot.reranker import Reranker
    from copilot.context_builder import ContextBuilder
    from copilot.prompt_builder import PromptBuilder
    from copilot.generator import Generator
    from copilot.claim_verifier import ClaimVerifier
    from copilot.schemas import GraphEdgeSnippet, StructuredRecordSnippet, GraphNodeSnippet

    import time
    t_start = time.perf_counter()

    cfg = get_copilot_config()
    planner = QueryPlanner()
    plan = planner.plan(body.question)

    v_store = VectorStore(config=cfg)
    g_retriever = GraphRetriever(config=cfg)
    s_retriever = StructuredRetriever(config=cfg)
    hybrid = HybridRetriever(cfg, v_store, g_retriever, s_retriever)

    fused_items, diag = await hybrid.retrieve(
        db=db,
        case_id=clean_case_id,
        plan=plan,
        limit=max(body.top_k, 25),
    )

    reranker = Reranker(config=cfg)
    reranked_items = await reranker.rerank(
        query=body.question,
        candidates=fused_items,
        plan=plan,
    )
    t_retrieval = time.perf_counter()

    # Extract domain structures from reranked items for context building
    edges: list[GraphEdgeSnippet] = []
    records: list[StructuredRecordSnippet] = []
    nodes: list[GraphNodeSnippet] = []

    for it in reranked_items:
        p = it.raw_payload or {}
        if "source" in p and "target" in p:
            edges.append(
                GraphEdgeSnippet(
                    source_canonical=str(p["source"]),
                    target_canonical=str(p["target"]),
                    relationship_type=str(p.get("type") or p.get("relationship_type")),
                    confidence=float(p.get("confidence", 1.0)),
                    epistemic_status=str(p.get("epistemic_status") or it.epistemic_status or "OBSERVED"),
                    citations=p.get("citations", []),
                )
            )
        elif it.text.startswith("[GRAPH "):
            m = re.search(
                r"\[GRAPH\s+([A-Z_]+)\]\s+(.*?)\s+->\s+(.*?)\s+->\s+(.*?)(?:\s+\(confidence=([0-9.]+)\))?$",
                it.text.strip(),
            )
            if m:
                edges.append(
                    GraphEdgeSnippet(
                        source_canonical=m.group(2).strip(),
                        target_canonical=m.group(4).strip(),
                        relationship_type=m.group(3).strip(),
                        confidence=float(m.group(5)) if m.group(5) else 1.0,
                        epistemic_status=m.group(1).strip(),
                        citations=it.citations or [],
                    )
                )

        if "event_id" in p or "finding_id" in p or any(
            it.text.startswith(f"[{tag}]")
            for tag in (
                "TRANSACTION",
                "WHATSAPP",
                "CALL",
                "LOCATION",
                "TIMELINE",
                "FINDING",
                "DEVICE",
                "NETWORK",
            )
        ):
            records.append(
                StructuredRecordSnippet(
                    record_id=str(p.get("event_id") or p.get("finding_id") or it.id),
                    table_name="findings" if "finding_id" in p or "[FINDING]" in it.text else "evidence_events",
                    record_type=str(p.get("event_type") or p.get("finding_type") or "record"),
                    timestamp=None,
                    summary_text=it.text,
                    source_file=it.source_file,
                    source_line=it.source_line,
                    source_page=it.source_page,
                    exact_payload=p,
                )
            )

        if "canonical_value" in p and "entity_type" in p:
            nodes.append(
                GraphNodeSnippet(
                    entity_id=str(p.get("entity_id") or it.id),
                    canonical_value=str(p["canonical_value"]),
                    entity_type=str(p["entity_type"]),
                    risk_score=float(p.get("risk_score") or 0.0),
                    bridge_score=float(p.get("bridge_score") or 0.0),
                )
            )

    c_builder = ContextBuilder(config=cfg)
    case_snapshot = await c_builder.build_case_snapshot(db=db, case_id=clean_case_id)
    assembled_context = c_builder.build_context(
        case_snapshot=case_snapshot,
        fused_items=reranked_items,
        graph_nodes=nodes,
        graph_edges=edges,
        structured_records=records,
    )

    p_builder = PromptBuilder(config=cfg)
    gen_prompt = p_builder.build_prompt(query=plan, context=assembled_context)
    t_context = time.perf_counter()

    generator = Generator(config=cfg)
    gen_resp = await generator.generate(prompt=gen_prompt)
    t_generation = time.perf_counter()

    verifier = ClaimVerifier(config=cfg)
    verified = verifier.verify(response=gen_resp, context=assembled_context)
    t_verify = time.perf_counter()

    # Build citations list with provenance
    citations_out = []
    seen_citations = set()
    for rank, it in enumerate(reranked_items, start=1):
        if it.source_file and it.source_file not in ("Unknown", "Case Graph (Entities)"):
            c_key = (it.source_file, it.source_line or "", it.source_page or "")
            if c_key not in seen_citations:
                seen_citations.add(c_key)
                citations_out.append({
                    "rank": rank,
                    "file": it.source_file,
                    "line": it.source_line or "",
                    "page": it.source_page or "",
                    "text": it.text,
                    "verified": True,
                    "epistemic_status": it.epistemic_status or "OBSERVED",
                })

    # Separate observed vs inferred relationships/facts
    observed_facts = []
    inferred_facts = []
    for edge in edges:
        edge_repr = f"{edge.source_canonical} -> {edge.relationship_type} -> {edge.target_canonical}"
        if edge.epistemic_status.upper() == "INFERRED":
            if edge_repr not in inferred_facts:
                inferred_facts.append(edge_repr)
        else:
            if edge_repr not in observed_facts:
                observed_facts.append(edge_repr)

    # Calculate stage latencies
    retrieval_ms = round((t_retrieval - t_start) * 1000.0, 2)
    context_ms = round((t_context - t_retrieval) * 1000.0, 2)
    generation_ms = round((t_generation - t_context) * 1000.0, 2)
    verification_ms = round((t_verify - t_generation) * 1000.0, 2)
    total_ms = round((t_verify - t_start) * 1000.0, 2)
    # Construct command mutation proposals targeting the Command Gateway for one-click approval
    mutation_proposals: list[dict] = []
    for edge in edges:
        if edge.epistemic_status.upper() == "INFERRED":
            mutation_proposals.append({
                "command": "CONFIRM_RELATIONSHIP",
                "endpoint": f"/cases/{clean_case_id}/commands",
                "payload": {
                    "source": edge.source_canonical,
                    "target": edge.target_canonical,
                    "relationship_type": edge.relationship_type,
                },
                "description": f"Confirm inferred relationship: {edge.source_canonical} -> {edge.relationship_type} -> {edge.target_canonical}",
                "capability_required": "CAP_RELATIONSHIP_CONFIRM",
            })
    if any(k in body.question.lower() for k in ("hypothesis", "theory", "possibility", "scenario")):
        mutation_proposals.append({
            "command": "CREATE_HYPOTHESIS",
            "endpoint": f"/cases/{clean_case_id}/commands",
            "payload": {
                "title": f"Investigative lead: {body.question[:80]}",
                "description": (verified.text or "")[:400],
            },
            "description": "Create formal hypothesis tracking this investigative lead",
            "capability_required": "CAP_HYPOTHESIS_WRITE",
        })

    return {
        "answer": verified.text,
        "raw_answer": gen_resp.text,
        "citations": citations_out,
        "observed_facts": observed_facts,
        "inferred_facts": inferred_facts,
        "mutation_proposals": mutation_proposals,
        "model_used": gen_resp.model,
        "provider": gen_resp.provider,
        "is_generated": True,
        "fallback_used": gen_resp.used_fallback,
        "abstained": verified.abstained,
        "grounded_ratio": verified.grounded_claim_ratio,
        "grounded_claim_ratio": verified.grounded_claim_ratio,
        "citation_count": len(citations_out),
        "latency_ms": gen_resp.latency_ms,
        "stage_latencies": {
            "retrieval_ms": retrieval_ms,
            "context_ms": context_ms,
            "generation_ms": generation_ms,
            "verification_ms": verification_ms,
            "total_ms": total_ms,
        },
        "status": "ready",
        "verification": {
            "passed": verified.passed,
            "abstained": verified.abstained,
            "grounded_ratio": verified.grounded_claim_ratio,
            "flags": [
                {"severity": "warning", "check": "UNGROUNDED_CLAIM", "message": f"{c.text} ({c.reason or 'Ungrounded claim'})"}
                for c in (verified.report.claims if verified.report else []) if not c.grounded
            ],
        },
        "diagnostics": {
            "intent": plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent),
            "target_modalities": plan.target_modalities,
            "retrieval": diag,
        },
    }


@copilot_router.get("/status")
async def copilot_status(_: User = Depends(get_current_user)):
    """Report Copilot engine availability and active provider configuration."""
    from copilot.config import get_copilot_config
    import httpx
    cfg = get_copilot_config()
    ollama_online = False
    available_models = []
    base_url = getattr(cfg, "ollama_base_url", "http://localhost:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                ollama_online = True
                data = resp.json()
                available_models = [m.get("name") for m in data.get("models", []) if "name" in m]
    except Exception:
        ollama_online = False

    return {
        "ollama_online": ollama_online,
        "available_models": available_models,
        "status": "ready",
        "model_used": cfg.llm_model,
        "provider": cfg.llm_provider,
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
