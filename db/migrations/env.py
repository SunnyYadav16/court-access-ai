"""
db/migrations/env.py

Alembic environment configuration for CourtAccess AI.

Supports both:
  1. Online mode (direct DB connection) — used for `alembic upgrade head`
  2. Offline mode (SQL script generation) — used for `alembic upgrade head --sql`

The DB URL is read from courtaccess.core.config (which reads from .env),
so no database URL needs to be hardcoded in this file.

Usage (from project root):
    # Apply pending migrations
    alembic --config db/migrations/alembic.ini upgrade head

    # Auto-generate a new migration from model changes
    alembic --config db/migrations/alembic.ini revision --autogenerate -m "add column X"

    # Roll back one migration
    alembic --config db/migrations/alembic.ini downgrade -1

    # Show current migration state
    alembic --config db/migrations/alembic.ini current
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Ensure project root is on sys.path so imports work ───────────────────────
# This is needed when Alembic is invoked from inside db/migrations/ rather
# than from the project root.
_project_root = Path(__file__).resolve().parents[2]  # db/migrations/ → db/ → project root
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ── Import all models so Alembic can see their metadata ──────────────────────
# If you add a new model file, import it here.
import db.models  # noqa: F401, E402 — registers all models with Base.metadata
from db.database import SYNC_DATABASE_URL, Base  # noqa: E402

# ── Alembic Config object (wraps alembic.ini) ─────────────────────────────────
config = context.config

# Override sqlalchemy.url with the value from our settings (reads from .env).
# This means alembic.ini does NOT need a hardcoded URL.
config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)

# ── Logging ───────────────────────────────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Metadata for auto-generation ─────────────────────────────────────────────
target_metadata = Base.metadata


# ══════════════════════════════════════════════════════════════════════════════
# Offline mode — generate SQL script without a live DB connection
# ══════════════════════════════════════════════════════════════════════════════


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        version_table="courtaccess_alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


# ══════════════════════════════════════════════════════════════════════════════
# Online mode — connect to a live DB and run migrations
# ══════════════════════════════════════════════════════════════════════════════


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            version_table="courtaccess_alembic_version",
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
