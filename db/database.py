"""
db/database.py

Async SQLAlchemy engine and session factory for the CourtAccess AI API.

Usage in FastAPI dependency (api/dependencies.py):
    from db.database import AsyncSessionLocal, engine

    async def get_db():
        async with AsyncSessionLocal() as session:
            yield session

Usage in Alembic env.py (sync migration driver):
    from db.database import SYNC_DATABASE_URL
    url = SYNC_DATABASE_URL

Design notes:
  - Uses asyncpg driver (postgresql+asyncpg) for all async ORM operations
  - Uses psycopg2 driver (postgresql+psycopg2) for sync Alembic migrations
  - pool_size=10 / max_overflow=20 handles moderate concurrent API load
  - pool_pre_ping=True reconnects stale connections silently
"""

from __future__ import annotations

import functools

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from courtaccess.core.config import get_settings

settings = get_settings()

# ── Async engine (FastAPI / runtime) ─────────────────────────────────────────
engine = create_async_engine(
    settings.database_url,  # postgresql+asyncpg://...
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Silently reconnect stale pool connections
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=settings.debug,  # Log SQL in development only
)

# ── Async session factory ─────────────────────────────────────────────────────
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep ORM objects usable after commit
    autoflush=False,
    autocommit=False,
)

# ── Sync URL for Alembic migrations ──────────────────────────────────────────
# asyncpg is not usable with Alembic's sync migration runner.
# Replace the driver component for psycopg2 (sync).
SYNC_DATABASE_URL: str = settings.database_url.replace(
    "postgresql+asyncpg://",
    "postgresql+psycopg2://",
)


# ── Base class for all ORM models ─────────────────────────────────────────────


class Base(DeclarativeBase):
    """
    Shared declarative base.
    All ORM models in db/models.py inherit from this class.
    Alembic uses Base.metadata to auto-generate migration scripts.
    """

    pass


# ── Connection pool lifecycle helpers ─────────────────────────────────────────
# Called from api/main.py lifespan.


async def init_db() -> None:
    """
    Verify the connection pool is healthy on startup.
    Does NOT run migrations — use Alembic for schema changes.

    api/main.py lifespan should call this on startup:
        app.state.db_engine = engine
        await init_db()
    """
    async with engine.begin() as conn:
        # Simple connectivity check — will raise if DB is unreachable.
        await conn.run_sync(lambda _: None)


async def close_db() -> None:
    """
    Dispose the connection pool on shutdown.
    Call from api/main.py lifespan teardown.
    """
    await engine.dispose()


# ── Sync engine for Airflow DAG tasks ────────────────────────────────────────
# DAG tasks run in sync processes and cannot use asyncpg.  They call this
# function instead of creating their own engine inline, so pool settings and
# the URL derivation are centralised in one place.
#
# lru_cache(maxsize=1) makes this a module-level singleton: the first call
# creates the engine; every subsequent call returns the same object.


@functools.lru_cache(maxsize=1)
def get_sync_engine() -> sa.Engine:
    """
    Return a cached synchronous SQLAlchemy engine using ``SYNC_DATABASE_URL``.

    Called by Airflow DAG tasks that need to write to the DB without asyncpg.
    Uses the same psycopg2-backed URL already used by Alembic migrations.

    Example (inside a DAG task):
        from db.database import get_sync_engine
        from sqlalchemy.orm import Session

        with Session(get_sync_engine()) as session:
            session.execute(sa.text("SELECT 1"))
    """
    return sa.create_engine(
        SYNC_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=2,  # DAG tasks are short-lived; small pool is sufficient
        max_overflow=3,
    )
