from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Production Configuration Safety Validation (Milestone 10)
Validates:
  1. Fail-fast validation prevents startup in production mode with default/weak secrets.
  2. Debug mode rejection in production.
  3. CORS wildcard '*' prohibition in production.
  4. SQLite rejection in production.
  5. Default admin password prohibition in production.
  6. Perfectly valid production configuration passes without errors.
  7. Database pool sizing and upload boundaries.
"""

import pytest
from unittest.mock import patch

from config import Settings
from main import _validate_production_secrets


def test_production_rejects_default_or_short_secret_key():
    # Placeholder secret
    s_default = Settings(
        environment="production",
        debug=False,
        secret_key="CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN",
        initial_admin_password="VeryStrongProductionPassword!#2026",
        database_url="postgresql://user:pass@localhost:5432/netra",
        cors_origins=["https://netra.gov.in"],
    )
    with patch("main.settings", s_default):
        with pytest.raises(RuntimeError) as exc_info:
            _validate_production_secrets()
        assert "SECRET_KEY is unset or still the default placeholder" in str(exc_info.value)

    # Short secret
    s_short = Settings(
        environment="production",
        debug=False,
        secret_key="too_short_key",
        initial_admin_password="VeryStrongProductionPassword!#2026",
        database_url="postgresql://user:pass@localhost:5432/netra",
        cors_origins=["https://netra.gov.in"],
    )
    with patch("main.settings", s_short):
        with pytest.raises(RuntimeError) as exc_info:
            _validate_production_secrets()
        assert "SECRET_KEY is only" in str(exc_info.value)


def test_production_rejects_debug_mode():
    s_debug = Settings(
        environment="production",
        debug=True,
        secret_key="A" * 64,
        initial_admin_password="VeryStrongProductionPassword!#2026",
        database_url="postgresql://user:pass@localhost:5432/netra",
        cors_origins=["https://netra.gov.in"],
    )
    with patch("main.settings", s_debug):
        with pytest.raises(RuntimeError) as exc_info:
            _validate_production_secrets()
        assert "DEBUG mode must be disabled in production" in str(exc_info.value)


def test_production_rejects_cors_wildcard():
    s_cors = Settings(
        environment="production",
        debug=False,
        secret_key="A" * 64,
        initial_admin_password="VeryStrongProductionPassword!#2026",
        database_url="postgresql://user:pass@localhost:5432/netra",
        cors_origins=["*", "https://netra.gov.in"],
    )
    with patch("main.settings", s_cors):
        with pytest.raises(RuntimeError) as exc_info:
            _validate_production_secrets()
        assert "CORS wildcard '*' is prohibited in production" in str(exc_info.value)


def test_production_rejects_sqlite():
    s_sqlite = Settings(
        environment="production",
        debug=False,
        secret_key="A" * 64,
        initial_admin_password="VeryStrongProductionPassword!#2026",
        database_url="sqlite+aiosqlite:///./cyberdrishti.db",
        cors_origins=["https://netra.gov.in"],
    )
    with patch("main.settings", s_sqlite):
        with pytest.raises(RuntimeError) as exc_info:
            _validate_production_secrets()
        assert "DATABASE_URL points at SQLite" in str(exc_info.value)


def test_production_rejects_weak_admin_password():
    for bad_pw in [None, "admin", "admin123", "password", "changeme"]:
        s_pw = Settings(
            environment="production",
            debug=False,
            secret_key="A" * 64,
            initial_admin_password=bad_pw,
            database_url="postgresql://user:pass@localhost:5432/netra",
            cors_origins=["https://netra.gov.in"],
        )
        with patch("main.settings", s_pw):
            with pytest.raises(RuntimeError) as exc_info:
                _validate_production_secrets()
            assert "INITIAL_ADMIN_PASSWORD is unset or a well-known default" in str(exc_info.value)


def test_production_valid_configuration_passes():
    s_valid = Settings(
        environment="production",
        debug=False,
        secret_key="c9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8",
        initial_admin_password="UltraSecure#Netra#Production#2026!Key",
        database_url="postgresql+asyncpg://netra_app:secure_pass@db.netra.internal:5432/netra_prod",
        cors_origins=["https://netra.gov.in", "https://investigate.netra.gov.in"],
        db_pool_size=25,
        db_max_overflow=50,
        max_upload_size_mb=100,
    )
    with patch("main.settings", s_valid):
        # Must execute without raising any exception
        _validate_production_secrets()


def test_database_and_upload_resource_bounds():
    s = Settings()
    assert s.db_pool_size >= 10, "db_pool_size must support minimum concurrent investigators"
    assert s.db_max_overflow >= 20, "db_max_overflow must support concurrency bursts"
    assert 10 <= s.max_upload_size_mb <= 500, "max_upload_size_mb must be safely bounded"


@pytest.mark.asyncio
async def test_admin_seed_skips_when_password_unset_and_never_overwrites_on_restart():
    from unittest.mock import patch
    from main import _ensure_admin_seed
    from db.models import User, Base
    from db.session import engine, AsyncSessionLocal
    from sqlalchemy import select

    # Setup isolated test schema
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1. When INITIAL_ADMIN_PASSWORD is empty/unset, NO admin user is created
    s_no_pw = Settings(initial_admin_username="admin_test_unseeded", initial_admin_password=None)
    with patch("main.settings", s_no_pw):
        await _ensure_admin_seed()

    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.username == "admin_test_unseeded")
        )).scalar_one_or_none()
        assert user is None, "Admin user must NOT be created when INITIAL_ADMIN_PASSWORD is unset"

    # 2. When INITIAL_ADMIN_PASSWORD is provided, admin user is created
    s_with_pw = Settings(initial_admin_username="admin_test_seeded", initial_admin_password="InitialPassword!123")
    with patch("main.settings", s_with_pw):
        await _ensure_admin_seed()

    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.username == "admin_test_seeded")
        )).scalar_one_or_none()
        assert user is not None
        original_hash = user.hashed_password

    # 3. On reboot/subsequent startup, existing user password MUST NOT be overwritten or reset
    s_reboot = Settings(initial_admin_username="admin_test_seeded", initial_admin_password="DifferentPassword!456")
    with patch("main.settings", s_reboot):
        await _ensure_admin_seed()

    async with AsyncSessionLocal() as session:
        user = (await session.execute(
            select(User).where(User.username == "admin_test_seeded")
        )).scalar_one_or_none()
        assert user is not None
        assert user.hashed_password == original_hash, "Server reboot must NEVER overwrite an existing user's password!"


def test_init_db_sql_zero_default_users_and_evidence_types():
    from pathlib import Path
    init_sql_path = Path(__file__).resolve().parents[1] / "db" / "init_db.sql"
    content = init_sql_path.read_text(encoding="utf-8")

    # 1. Zero default users inserted
    assert "INSERT INTO users" not in content, "init_db.sql must create ZERO default users"
    assert "CyberDrishti@2024" not in content, "Legacy default password must not exist in init_db.sql"

    # 2. Evidence files does not have obsolete restrictive check constraint
    assert "CHECK (file_type IN ('pdf'" not in content, "init_db.sql must not restrict file_type to legacy PDF/CSV subset"

    # 3. User roles includes supervisor and all supported roles
    assert "'supervisor'" in content, "init_db.sql must support supervisor role"
    assert "'investigator'" in content, "init_db.sql must support investigator role"
