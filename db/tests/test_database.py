"""
db/tests/test_database.py

Unit tests for db/database.py.

Tests the private URL-builder helpers and the DEBUG flag parser,
all without making any real database connections.

Coverage:
  - _make_async_url: assembles postgresql+asyncpg:// URL from env vars
  - _make_sync_url:  replaces asyncpg driver with psycopg2
  - _make_debug:     parses DEBUG env var to bool
  - SYNC_DATABASE_URL: module-level constant uses psycopg2 driver
  - get_sync_engine: returns a cached Engine instance (lru_cache)
"""

from __future__ import annotations

import os
from unittest.mock import patch

# ---------------------------------------------------------------------------
# _make_async_url
# ---------------------------------------------------------------------------


class TestMakeAsyncUrl:
    def test_builds_url_from_env_vars(self):
        from db.database import _make_async_url

        with patch.dict(
            os.environ,
            {
                "POSTGRES_USER": "alice",
                "POSTGRES_PASSWORD": "secret",
                "POSTGRES_HOST": "db.example.com",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "courtaccess",
            },
        ):
            url = _make_async_url()

        assert url == "postgresql+asyncpg://alice:secret@db.example.com:5432/courtaccess"

    def test_uses_asyncpg_driver(self):
        from db.database import _make_async_url

        url = _make_async_url()
        assert url.startswith("postgresql+asyncpg://")

    def test_default_port_is_5432(self):
        from db.database import _make_async_url

        env = {
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "POSTGRES_HOST": "h",
            "POSTGRES_DB": "d",
        }
        # Remove POSTGRES_PORT to test default
        env_without_port = {k: v for k, v in os.environ.items() if k != "POSTGRES_PORT"}
        env_without_port.update(env)

        with patch.dict(os.environ, env_without_port, clear=True):
            url = _make_async_url()

        assert ":5432/" in url

    def test_custom_port_used(self):
        from db.database import _make_async_url

        with patch.dict(os.environ, {"POSTGRES_PORT": "5433"}):
            url = _make_async_url()

        assert ":5433/" in url

    def test_url_contains_host(self):
        from db.database import _make_async_url

        with patch.dict(os.environ, {"POSTGRES_HOST": "my-cloud-db.internal"}):
            url = _make_async_url()

        assert "my-cloud-db.internal" in url

    def test_url_contains_db_name(self):
        from db.database import _make_async_url

        with patch.dict(os.environ, {"POSTGRES_DB": "mydb"}):
            url = _make_async_url()

        assert url.endswith("/mydb")


# ---------------------------------------------------------------------------
# _make_sync_url
# ---------------------------------------------------------------------------


class TestMakeSyncUrl:
    def test_uses_psycopg2_driver(self):
        from db.database import _make_sync_url

        url = _make_sync_url()
        assert "psycopg2" in url
        assert "asyncpg" not in url

    def test_replaces_only_the_driver_component(self):
        from db.database import _make_async_url, _make_sync_url

        async_url = _make_async_url()
        sync_url = _make_sync_url()
        expected = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
        assert sync_url == expected

    def test_starts_with_psycopg2_scheme(self):
        from db.database import _make_sync_url

        url = _make_sync_url()
        assert url.startswith("postgresql+psycopg2://")

    def test_host_and_db_preserved(self):
        from db.database import _make_sync_url

        with patch.dict(
            os.environ,
            {"POSTGRES_HOST": "prod-db", "POSTGRES_DB": "production"},
        ):
            url = _make_sync_url()

        assert "prod-db" in url
        assert "production" in url


# ---------------------------------------------------------------------------
# _make_debug
# ---------------------------------------------------------------------------


class TestMakeDebug:
    def test_false_when_debug_not_set(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {}, clear=False):
            env_copy = os.environ.copy()
            env_copy.pop("DEBUG", None)
            with patch.dict(os.environ, env_copy, clear=True):
                assert _make_debug() is False

    def test_false_when_debug_is_false_string(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "false"}):
            assert _make_debug() is False

    def test_true_when_debug_is_true_lowercase(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "true"}):
            assert _make_debug() is True

    def test_true_when_debug_is_true_uppercase(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "TRUE"}):
            assert _make_debug() is True

    def test_true_when_debug_is_true_mixed_case(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "True"}):
            assert _make_debug() is True

    def test_false_when_debug_is_1(self):
        """Only the string 'true' (case-insensitive) enables debug — not '1'."""
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "1"}):
            assert _make_debug() is False

    def test_false_when_debug_is_yes(self):
        from db.database import _make_debug

        with patch.dict(os.environ, {"DEBUG": "yes"}):
            assert _make_debug() is False

    def test_returns_bool_type(self):
        from db.database import _make_debug

        result = _make_debug()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleLevelConstants:
    def test_sync_database_url_uses_psycopg2(self):
        from db.database import SYNC_DATABASE_URL

        assert "psycopg2" in SYNC_DATABASE_URL
        assert "asyncpg" not in SYNC_DATABASE_URL

    def test_sync_database_url_is_string(self):
        from db.database import SYNC_DATABASE_URL

        assert isinstance(SYNC_DATABASE_URL, str)

    def test_engine_is_created(self):
        """engine object exists and is an AsyncEngine."""
        from sqlalchemy.ext.asyncio import AsyncEngine

        from db.database import engine

        assert isinstance(engine, AsyncEngine)

    def test_async_session_local_is_callable(self):
        """AsyncSessionLocal is a session factory (callable)."""
        from db.database import AsyncSessionLocal

        assert callable(AsyncSessionLocal)


# ---------------------------------------------------------------------------
# get_sync_engine — lru_cache singleton
# ---------------------------------------------------------------------------


class TestGetSyncEngine:
    def test_returns_sqlalchemy_engine(self):
        import sqlalchemy as sa

        from db.database import get_sync_engine

        result = get_sync_engine()
        assert isinstance(result, sa.engine.Engine)

    def test_same_instance_returned_on_repeated_calls(self):
        from db.database import get_sync_engine

        first = get_sync_engine()
        second = get_sync_engine()
        assert first is second  # lru_cache guarantees identity

    def test_engine_url_uses_psycopg2(self):
        from db.database import get_sync_engine

        eng = get_sync_engine()
        assert "psycopg2" in str(eng.url)
