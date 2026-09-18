from pathlib import Path
import sys
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def cleanup_db_engine():
    """Ensure database connection pool is disposed at the end of each test."""
    yield
    try:
        from db.session import engine
        engine.sync_engine.dispose()
    except Exception:
        pass
