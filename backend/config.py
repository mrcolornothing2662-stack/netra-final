"""
CyberDrishti AI — Application Configuration
Loaded once at startup via Pydantic Settings (reads from environment / .env file).
"""
from functools import lru_cache
from typing import Literal
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CyberDrishti AI"
    app_version: str = "1.0.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True

    secret_key: str = "CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours for investigation sessions

    database_url: str = "postgresql://cyberdrishti:cyberdrishti_secret@localhost:5432/cyberdrishti"
    db_pool_size: int = 25
    db_max_overflow: int = 50

    redis_url: str = "redis://localhost:6379/0"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"
    ollama_timeout: int = 120

    gemini_api_key: str = ""
    allow_cloud_ai: bool = True

    artifacts_dir: str = str(_BASE_DIR / "artifacts")
    cyberdrishtilm_dir: str = str(_BASE_DIR / "artifacts" / "cyberdrishtilm")
    hingbert_dir: str = str(_BASE_DIR / "artifacts" / "hingbert")
    crf_path: str = str(_BASE_DIR / "artifacts" / "crf" / "crf_model.pkl")
    hidden_link_model_path: str = str(_BASE_DIR / "artifacts" / "hidden_link_model.pkl")

    chroma_persist_dir: str = str(_BASE_DIR / "artifacts" / "chroma_db")

    upload_dir: str = str(_BASE_DIR / "uploads")
    max_upload_size_mb: int = 100

    enable_cognitive_orchestration: bool = True
    # Cross-case blind-index analysis reaches across case boundaries; it stays
    # off unless an administrator explicitly authorises it.
    enable_cross_case_analysis: bool = False

    fuzzy_merge_threshold: float = 0.85
    hidden_link_temporal_tau: float = 3600.0   # seconds
    hidden_link_fin_tau: float = 7200.0         # seconds
    hidden_link_min_precision: float = 0.90

    report_output_dir: str = str(_BASE_DIR / "reports")
    report_template_dir: str = str(_BASE_DIR / "report" / "templates")

    cors_origins: list[str] = [
        "http://localhost:3000",   # Next.js dev
        "http://localhost:3001",
        "http://localhost:3100",
        "http://localhost:5173",   # Vite dev
        "http://127.0.0.1:3000",  # IPv4 localhost (common Windows browser URL)
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3100",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://cyberdrishti.railway.app",
    ]

    audit_genesis_seed: str = "CYBERDRISHTI_GENESIS"

    # Idempotent startup admin seed. Because Base.metadata.create_all never runs
    # db/init_db.sql, the initial administrator is seeded from these values at
    # startup (bcrypt-hashed). Change them in production via environment variables.
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin123"
    initial_admin_email: str = "admin@cyberdrishti.gov.in"
    initial_admin_full_name: str = "Administrator"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


settings = get_settings()
