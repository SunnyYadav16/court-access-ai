"""
db/tests/conftest.py

Sets dummy Postgres env vars before any db.* import occurs.
db/database.py builds the SQLAlchemy engine at module-load time using
os.getenv(), so these must be present before the first import.
No real DB connection is made; all tests use mocked sessions/connections.
"""

import os

# Must precede all db.* imports
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_password")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("DEBUG", "false")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture()
def mock_db() -> AsyncMock:
    """
    Mock AsyncSession matching the pattern used across the project.

    execute() returns a result mock that supports:
      .scalar_one_or_none() → None
      .scalar_one()         → 0
      .scalars().all()      → []
    Individual tests can override execute.return_value / side_effect.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar_one = MagicMock(return_value=0)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.delete = AsyncMock()
    return db


@pytest.fixture()
def mock_sync_session() -> MagicMock:
    """Mock synchronous SQLAlchemy Session for Airflow-style sync query tests."""
    session = MagicMock()
    session.execute.return_value = MagicMock(
        scalars=MagicMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=None), all=MagicMock(return_value=[]))
        )
    )
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.get = MagicMock(return_value=None)
    session.query = MagicMock()
    return session


@pytest.fixture()
def mock_sync_conn() -> MagicMock:
    """Mock synchronous SQLAlchemy Connection for write_audit_sync tests."""
    conn = MagicMock()
    conn.execute = MagicMock()
    return conn
