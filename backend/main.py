"""
CyberDrishti AI — FastAPI Application Entry Point
Mounts all routers, initialises the audit chain, loads ML models at startup.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from config import settings
from db.session import engine, db_context, get_db
from db.models import Base, AuditLog
from sqlalchemy.ext.asyncio import AsyncSession


# ── Lifespan: startup & shutdown ─────────────────────────────────────────────

def _validate_production_secrets() -> None:
    """Fail-fast: refuse to start in production with missing/weak secrets.

    §2.3 of DELIVERY_REQUIREMENTS.md — every required var must be real,
    secret, and validated at boot.
    """
    if settings.environment != "production":
        return
    errors: list[str] = []
    if settings.secret_key in ("", "CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN"):
        errors.append("SECRET_KEY is unset or still the default placeholder")
    elif len(settings.secret_key) < 32:
        errors.append(f"SECRET_KEY is only {len(settings.secret_key)} chars (minimum 32)")
    if "sqlite" in settings.database_url:
        errors.append("DATABASE_URL points at SQLite — production requires PostgreSQL")
    if not settings.initial_admin_password or settings.initial_admin_password in (
        "admin123", "admin", "password", "changeme",
    ):
        errors.append("INITIAL_ADMIN_PASSWORD is unset or a well-known default")
    if errors:
        msg = "\n".join(f"  • {e}" for e in errors)
        raise RuntimeError(
            f"\n🛑 [PRODUCTION BOOT BLOCKED] The following secrets are missing or insecure:\n{msg}\n"
            f"Set these environment variables and restart."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before yielding to request handling."""
    # 0. Production safety gate (§2.3)
    _validate_production_secrets()

    # 1. Create or migrate tables
    try:
        if settings.environment == "production":
            from alembic.config import Config
            from alembic import command
            alembic_cfg = Config(str(Path(__file__).resolve().parent / "alembic.ini"))
            command.upgrade(alembic_cfg, "head")
        else:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        await _check_integrity_schema()

        # 2. Ensure audit genesis row exists
        await _ensure_audit_genesis()

        # 3. Idempotent admin seed (replaces the removed login backdoor/auto-create)
        await _ensure_admin_seed()
    except Exception as exc:
        if isinstance(exc, RuntimeError) and "integrity migration" in str(exc).lower():
            raise
        print(f"\n⚠️ [DATABASE WARNING] Could not connect to PostgreSQL: {exc}")
        print("💡 [SOLUTION]:")
        print("   Option 1: Start PostgreSQL via Docker: 'docker compose up db -d'")
        print("   Option 2: Run SQLite locally by updating backend/.env to:")
        print("             DATABASE_URL=sqlite+aiosqlite:///./cyberdrishti.db\n")

    # 3. Pre-load ML models into app state
    app.state.models = await _load_models()

    yield

    # 4. Graceful shutdown — dispose DB pool
    try:
        await engine.dispose()
    except Exception:
        pass



async def _ensure_audit_genesis():
    """Insert the audit chain genesis entry if it doesn't exist yet."""
    genesis_hash = hashlib.sha256(
        settings.audit_genesis_seed.encode()
    ).hexdigest()
    async with db_context() as db:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT id FROM audit_log LIMIT 1")
        )
        if result.first() is None:
            genesis_entry = AuditLog(
                prev_hash="0" * 64,
                entry_hash=genesis_hash,
                action="GENESIS",
                resource_type="system",
                resource_id="genesis",
                details_json={"seed": settings.audit_genesis_seed},
            )
            db.add(genesis_entry)


async def _ensure_admin_seed():
    """
    Idempotently seed the initial administrator account.

    Base.metadata.create_all never runs db/init_db.sql, so without this the
    login backdoor removal in routes/auth.py would lock everyone out. Credentials
    come from INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD (documented dev
    defaults in .env.example) and are stored bcrypt-hashed. If the account already
    exists this is a no-op — the password is never reset.
    """
    from sqlalchemy import select
    from db.models import User
    from routes.auth import _hash_password

    username = settings.initial_admin_username.strip()
    if not username:
        return

    password = settings.initial_admin_password
    # In production, refuse to seed with a well-known default password (§2.2).
    if settings.environment == "production" and password in (
        "", "admin123", "admin", "password", "changeme",
    ):
        print("🛑 [ADMIN SEED] Skipped — INITIAL_ADMIN_PASSWORD is a default/empty value in production.")
        return

    async with db_context() as db:
        existing = (await db.execute(
            select(User).where(User.username == username)
        )).scalar_one_or_none()
        if existing is not None:
            return
        db.add(User(
            username=username,
            email=settings.initial_admin_email,
            hashed_password=_hash_password(password),
            full_name=settings.initial_admin_full_name,
            rank="Inspector",
            unit="Cyber Cell",
            role="admin",
            is_active=True,
            must_change_password=True,
        ))
        print(f"✅ [ADMIN SEED] Created initial administrator '{username}' (must change password on first login).")


async def _check_integrity_schema() -> None:
    """Warn loudly when an existing PostgreSQL schema has not applied trust constraints."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import text
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = 'uq_evidence_case_sha256'
        """))
        if result.first() is None:
            raise RuntimeError(
                "Evidence integrity migration is required: "
                "backend/db/migrations/20260902_evidence_integrity.sql"
            )


async def _load_models() -> dict:
    """
    Load CyberDrishtiLM, HingBERT, CRF, and hidden-link model into memory.
    Returns a dict keyed by model name; each value is the loaded object or None
    if the artifact doesn't exist yet.
    """
    import pickle, pathlib

    loaded: dict = {
        "cyberdrishtilm": None,
        "hingbert": None,
        "crf": None,
        "hidden_link_lr": None,
    }

    # CyberDrishtiLM
    model_dir = pathlib.Path(settings.cyberdrishtilm_dir)
    if model_dir.exists():
        try:
            from nlp.cyberdrishtilm.model import CyberDrishtiLM
            from nlp.cyberdrishtilm.tokenizer import CDTokenizer
            tokenizer = CDTokenizer.load(str(model_dir))
            model = CyberDrishtiLM.load(str(model_dir))
            loaded["cyberdrishtilm"] = {"model": model, "tokenizer": tokenizer}
        except Exception as exc:
            print(f"[WARN] CyberDrishtiLM not loaded: {exc}")

    # HingBERT
    hingbert_dir = pathlib.Path(settings.hingbert_dir)
    if hingbert_dir.exists():
        try:
            from transformers import AutoTokenizer, AutoModelForTokenClassification
            loaded["hingbert"] = {
                "tokenizer": AutoTokenizer.from_pretrained(str(hingbert_dir)),
                "model": AutoModelForTokenClassification.from_pretrained(str(hingbert_dir)),
            }
        except Exception as exc:
            print(f"[WARN] HingBERT not loaded: {exc}")

    # CRF
    crf_path = pathlib.Path(settings.crf_path)
    if crf_path.exists():
        try:
            with open(crf_path, "rb") as f:
                loaded["crf"] = pickle.load(f)
        except Exception as exc:
            print(f"[WARN] CRF not loaded: {exc}")

    # Hidden-link logistic regression
    hl_path = pathlib.Path(settings.hidden_link_model_path)
    if hl_path.exists():
        try:
            from graph.hidden_link_engine import HiddenLinkEngine
            loaded["hidden_link_lr"] = HiddenLinkEngine.load(hl_path)
        except Exception as exc:
            print(f"[WARN] Hidden-link LR not loaded: {exc}")

    print("[STARTUP] Models loaded:", {k: v is not None for k, v in loaded.items()})
    return loaded


# ── App factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Enterprise AI Investigation Copilot for Indian Cyber Crime Cells",
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url="/api/redoc" if settings.environment != "production" else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        trace_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Trace-ID")
            or uuid.uuid4().hex
        )
        request.state.trace_id = trace_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = trace_id
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Routers ──────────────────────────────────────────────────────────────
    from routes.auth          import router as auth_router
    from routes.cases         import router as cases_router
    from routes.analytics     import router as analytics_router, intel_router, events_router
    from routes.evidence      import router as evidence_router
    from routes.graph         import router as graph_router, timeline_router, query_router, relationships_router
    from routes.copilot       import copilot_router, report_router, officers_router
    from routes.audit         import router as audit_router
    from routes.agent         import router as agent_router
    from routes.correlations  import router as correlations_router
    from routes.intelligence  import router as intelligence_router
    from routes.cognitive     import router as cognitive_router

    prefix = "/api/v1"
    app.include_router(auth_router,         prefix=f"{prefix}/auth",         tags=["auth"])
    app.include_router(cases_router,        prefix=f"{prefix}/cases",        tags=["cases"])
    app.include_router(analytics_router,    prefix=f"{prefix}/cases",        tags=["analytics"])
    app.include_router(evidence_router,     prefix=f"{prefix}/evidence",     tags=["evidence"])
    app.include_router(graph_router,        prefix=f"{prefix}/graph",        tags=["graph"])
    app.include_router(timeline_router,     prefix=f"{prefix}/timeline",     tags=["timeline"])
    app.include_router(query_router,        prefix=f"{prefix}/query",        tags=["query"])
    app.include_router(relationships_router, prefix=f"{prefix}/relationships", tags=["relationships"])
    app.include_router(copilot_router,      prefix=f"{prefix}/copilot",      tags=["copilot"])
    app.include_router(report_router,       prefix=f"{prefix}/report",       tags=["report"])
    app.include_router(audit_router,        prefix=f"{prefix}/audit",        tags=["audit"])
    app.include_router(officers_router,     prefix=f"{prefix}/officers",     tags=["officers"])
    app.include_router(agent_router,        prefix=f"{prefix}/agent",        tags=["agent"])
    app.include_router(intel_router,        prefix=f"{prefix}/intel",        tags=["intel"])
    app.include_router(events_router,       prefix=f"{prefix}/events",       tags=["events"])
    app.include_router(correlations_router, prefix=f"{prefix}/correlations", tags=["correlations"])
    app.include_router(intelligence_router, prefix=f"{prefix}/intelligence", tags=["intelligence"])
    app.include_router(cognitive_router,    prefix=f"{prefix}/cognitive",     tags=["cognitive"])

    @app.get(f"{prefix}/ml/models", tags=["ml"])
    async def get_ml_models():
        """Return live status of all registered ML models."""
        from ml.registry import get_model_registry
        from dataclasses import asdict
        reg = get_model_registry()
        return {
            name: asdict(info) for name, info in reg.load_all_models().items()
        }

    @app.get(f"{prefix}/settings/integrations", tags=["system"])
    async def get_integrations():
        """Return truthful status of external platform integrations and neural models."""
        models_loaded = {
            k: (v is not None) for k, v in getattr(app.state, "models", {}).items()
        }
        has_models = any(models_loaded.values()) if models_loaded else False
        return {
            "ncrp_1930": {
                "name": "NCRP 1930 Portal Connector",
                "status": "simulated",
                "badge": "SIMULATED / FILE-BASED",
                "endpoint": "CSV parser active (live NCRP gateway unconfigured)",
                "sync_mode": "On-demand evidence ingest (manual / batch upload)",
                "description": "National Cybercrime Reporting Portal real-time fraud complaint CSV ingestion & freeze gateway.",
            },
            "dot_cms": {
                "name": "Telecom DoT CMS / CDR & IPDR Pipeline",
                "status": "simulated",
                "badge": "FILE-BASED / OFFLINE",
                "endpoint": "CSV & CDR parser active (live CMS direct feed unconfigured)",
                "sync_mode": "On-demand CDR/IPDR import with cell tower coordinates",
                "description": "Central Monitoring System telecom data ingestion and cell tower triangulation.",
            },
            "fiu_ind": {
                "name": "FIU-IND Finnet 2.0 Banking Gateway",
                "status": "simulated",
                "badge": "FILE-BASED / OFFLINE",
                "endpoint": "Bank statement/ledger parser active (Finnet 2.0 switch unconfigured)",
                "sync_mode": "On-demand transaction CSV ingest & mule hop tracing",
                "description": "Financial Intelligence Unit suspicious transaction reporting & multi-bank mule tracing.",
            },
            "ml_neural_engine": {
                "name": "AI Neural Inference Engine",
                "status": "active" if has_models else "fallback",
                "badge": "ACTIVE (LOCAL WEIGHTS)" if has_models else "HEURISTIC FALLBACK",
                "endpoint": "Local PyTorch / Transformers Backend",
                "sync_mode": "In-process deterministic inference",
                "description": "Local DayaLLM inference engine, HingBERT cross-lingual NER, and hidden relationship predictor.",
                "models": models_loaded,
            },
        }

    @app.get("/health", tags=["system"])
    @app.get(f"{prefix}/health", tags=["system"])
    async def health(db: AsyncSession = Depends(get_db)):
        """Comprehensive infrastructure and dependency readiness probe."""
        db_status = "connected"
        try:
            from sqlalchemy import text
            await db.execute(text("SELECT 1"))
        except Exception as exc:
            db_status = f"error: {str(exc)}"

        chroma_status = "connected"
        try:
            from rag.copilot import get_vector_store
            vs = get_vector_store()
            chroma_status = "active"
        except Exception as exc:
            chroma_status = f"error: {str(exc)}"

        import shutil
        from pathlib import Path
        Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(settings.upload_dir)
        free_gb = round(disk.free / (1024 ** 3), 2)

        models_loaded = {
            k: (v is not None) for k, v in getattr(app.state, "models", {}).items()
        }

        overall = "healthy" if db_status == "connected" else "degraded"

        return {
            "status": overall,
            "version": settings.app_version,
            "environment": settings.environment,
            "dependencies": {
                "postgresql": db_status,
                "chromadb": chroma_status,
                "disk_free_gb": free_gb,
                "models": models_loaded,
            },
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

