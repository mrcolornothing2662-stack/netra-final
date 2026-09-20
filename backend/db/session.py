"""
CyberDrishti AI — Database Session & Connection Pool
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

db_url = settings.database_url
if db_url.startswith("sqlite"):
    if not db_url.startswith("sqlite+aiosqlite"):
        _async_url = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    else:
        _async_url = db_url
    engine = create_async_engine(
        _async_url,
        echo=settings.debug,
    )
else:
    _async_url = db_url.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    ).replace(
        "psycopg2", "asyncpg", 1
    )
    engine = create_async_engine(
        _async_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=settings.debug,
    )


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a database session, rolls back on error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside request handlers (e.g. startup tasks)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
