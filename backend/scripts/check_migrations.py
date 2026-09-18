#!/usr/bin/env python3
"""
CI Guard: Ensure all SQLAlchemy model changes in db/models.py have corresponding Alembic revisions.

1. Boots a temporary SQLite database.
2. Applies all current revisions via 'alembic upgrade head'.
3. Runs 'alembic check' to verify that models and migrations are completely synchronized.
4. Exits with 0 if models match migrations, or 1 if uncommitted model changes are detected.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from alembic import command
from alembic.config import Config


def main() -> int:
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="migration_guard_"))
    db_path = tmp_dir / "check_migrations.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    ini_path = backend_dir / "alembic.ini"
    if not ini_path.exists():
        print(f"🛑 [MIGRATION GUARD] alembic.ini not found at {ini_path}")
        return 1

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    print("==> Checking migration synchronization...")
    try:
        command.upgrade(cfg, "head")
        command.check(cfg)
        print("✅ [MIGRATION GUARD] All models are fully synchronized with Alembic migrations.")
        return 0
    except Exception as exc:
        print(f"🛑 [MIGRATION GUARD] Unmigrated model changes detected or check failed: {exc}")
        return 1
    finally:
        if db_path.exists():
            db_path.unlink()
        try:
            tmp_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
