"""Initial schema — creates all 5 core tables.

Revision ID: 001
Revises:     None
Create Date: 2024-01-01 00:00:00

Tables created:
  - users
  - sessions
  - translation_requests
  - audit_logs
  - form_catalog

Indexes and UniqueConstraints are created alongside each table.
PostgreSQL extensions: pgcrypto (gen_random_uuid), intarray (GIN on ARRAY).

Rollback: All tables are dropped in reverse dependency order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Enable PostgreSQL extensions ──────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── Enum types ────────────────────────────────────────────────────────────
    # Create enums before the tables that reference them
    user_role_enum = postgresql.ENUM(
        "public",
        "court_official",
        "interpreter",
        "admin",
        name="user_role_enum",
    )
    session_status_enum = postgresql.ENUM(
        "active",
        "paused",
        "ended",
        name="session_status_enum",
    )
    doc_status_enum = postgresql.ENUM(
        "pending",
        "processing",
        "translated",
        "approved",
        "rejected",
        "error",
        name="doc_status_enum",
    )
    form_status_enum = postgresql.ENUM(
        "active",
        "archived",
        name="form_status_enum",
    )

    user_role_enum.create(op.get_bind(), checkfirst=True)
    session_status_enum.create(op.get_bind(), checkfirst=True)
    doc_status_enum.create(op.get_bind(), checkfirst=True)
    form_status_enum.create(op.get_bind(), checkfirst=True)

    # ══════════════════════════════════════════════════════════════════════════
    # Table: users
    # ══════════════════════════════════════════════════════════════════════════
    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "public",
                "court_official",
                "interpreter",
                "admin",
                name="user_role_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="public",
        ),
        sa.Column("preferred_language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_role", "users", ["role"])

    # ══════════════════════════════════════════════════════════════════════════
    # Table: sessions
    # ══════════════════════════════════════════════════════════════════════════
    op.create_table(
        "sessions",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "creator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM("active", "paused", "ended", name="session_status_enum", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("source_language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("target_language", sa.String(8), nullable=False, server_default="es"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transcript_gcs_uri", sa.Text(), nullable=True),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "participants",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='[{"user_id": "...", "role": "creator|interpreter|observer"}]',
        ),
    )
    op.create_index("ix_sessions_creator_id", "sessions", ["creator_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])

    # ══════════════════════════════════════════════════════════════════════════
    # Table: translation_requests
    # ══════════════════════════════════════════════════════════════════════════
    op.create_table(
        "translation_requests",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "processing",
                "translated",
                "approved",
                "rejected",
                "error",
                name="doc_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("upload_gcs_uri", sa.Text(), nullable=True),
        sa.Column(
            "target_languages",
            postgresql.ARRAY(sa.String(8)),
            nullable=True,
        ),
        sa.Column(
            "translated_uris",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "legal_review_status",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("pii_findings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "reviewer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("airflow_dag_run_id", sa.String(256), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("submitter_notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_translation_requests_user_id", "translation_requests", ["user_id"])
    op.create_index("ix_translation_requests_status", "translation_requests", ["status"])
    op.create_index("ix_translation_requests_created_at", "translation_requests", ["created_at"])
    op.create_index("ix_translation_requests_airflow_run", "translation_requests", ["airflow_dag_run_id"])

    # ══════════════════════════════════════════════════════════════════════════
    # Table: audit_logs
    # ══════════════════════════════════════════════════════════════════════════
    op.create_table(
        "audit_logs",
        sa.Column(
            "log_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "actor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(256), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Freeform event details — NEVER store PII or secret values here",
        ),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ══════════════════════════════════════════════════════════════════════════
    # Table: form_catalog
    # ══════════════════════════════════════════════════════════════════════════
    op.create_table(
        "form_catalog",
        sa.Column("form_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("form_name", sa.String(512), nullable=False),
        sa.Column("form_slug", sa.String(256), nullable=False, unique=True),
        sa.Column("source_url", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "status",
            postgresql.ENUM("active", "archived", name="form_status_enum", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("has_spanish", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_portuguese", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("languages_available", postgresql.ARRAY(sa.String(8)), nullable=True),
        sa.Column("divisions", postgresql.ARRAY(sa.String(256)), nullable=True),
        sa.Column(
            "versions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "last_reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_notes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("form_slug", name="uq_form_catalog_slug"),
    )
    op.create_index("ix_form_catalog_status", "form_catalog", ["status"])
    op.create_index("ix_form_catalog_has_spanish", "form_catalog", ["has_spanish"])
    op.create_index("ix_form_catalog_has_portuguese", "form_catalog", ["has_portuguese"])
    op.create_index("ix_form_catalog_needs_review", "form_catalog", ["needs_human_review"])
    op.create_index("ix_form_catalog_last_scraped", "form_catalog", ["last_scraped_at"])
    # GIN index for fast ARRAY containment queries: WHERE 'Probate' = ANY(divisions)
    op.create_index(
        "ix_form_catalog_divisions_gin",
        "form_catalog",
        ["divisions"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    # Drop in reverse dependency order (audit_logs/form_catalog first, users last)
    op.drop_table("form_catalog")
    op.drop_table("audit_logs")
    op.drop_table("translation_requests")
    op.drop_table("sessions")
    op.drop_table("users")

    # Drop enum types
    postgresql.ENUM(name="form_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="doc_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="session_status_enum").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="user_role_enum").drop(op.get_bind(), checkfirst=True)
