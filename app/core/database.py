"""Async database engine and session lifecycle.

Driver is psycopg3 (``postgresql+psycopg://``). asyncpg is deliberately avoided:
it has historically lagged new CPython releases, and this project targets 3.14.
"""

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _build_engine() -> AsyncEngine:
    url = settings.sqlalchemy_url
    # Accept a bare postgresql:// URL and upgrade it to the async driver, so a
    # standard connection string from a cloud provider works unmodified.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    return create_async_engine(
        url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        # Verifies a connection before handing it out. Costs a round trip but
        # prevents the classic "server closed the connection unexpectedly"
        # after a network blip or a database failover.
        pool_pre_ping=True,
    )


engine: AsyncEngine = _build_engine()

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # Attributes stay usable after commit, so a handler can still serialise an
    # object it just wrote without triggering a lazy reload on a closed session.
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a session scoped to one request.

    The session is NOT auto-committed. Endpoints commit explicitly, which keeps
    transaction boundaries visible at the call site — important for the
    multi-step flows in this spec (cart → order, handoff, address default
    reassignment) where a partial write would corrupt state.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database() -> dict[str, Any]:
    """Readiness probe: confirms the connection AND that PostGIS is present."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        version = (await conn.execute(text("SELECT postgis_version()"))).scalar_one()
    return {"status": "ok", "postgis": version}


async def dispose_engine() -> None:
    await engine.dispose()
