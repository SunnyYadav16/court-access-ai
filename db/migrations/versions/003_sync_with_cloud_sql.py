"""sync_with_cloud_sql

Revision ID: 003
Revises: 002
Create Date: 2026-03-17

Syncs local database schema with existing Cloud SQL schema.
This migration creates the exact table structure that already exists in Cloud SQL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Sync with Cloud SQL schema — non-destructive, idempotent.

    All CREATE TABLE and CREATE INDEX calls use IF NOT EXISTS so this
    migration is safe to run against:
      • A fresh local dev database (creates everything from scratch).
      • Cloud SQL or any database where the schema already exists
        (every statement is a no-op).

    For Cloud SQL specifically, prefer advancing the revision pointer
    without executing SQL:
        alembic stamp 003   # or: alembic stamp head

    The original DROP TABLE … CASCADE statements have been removed to
    prevent accidental data loss on databases that contain real data.
    """

    # 1. Roles table with seed data
    op.create_table(
        "roles",
        sa.Column("role_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("role_name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("role_id"),
        sa.UniqueConstraint("role_name"),
        if_not_exists=True,
    )

    # Seed data — ON CONFLICT DO NOTHING makes this idempotent on re-runs
    op.execute("""
        INSERT INTO roles (role_name, description) VALUES
        ('public', 'Default role, basic document translation and form access'),
        ('court_official', 'Real-time speech translation access'),
        ('interpreter', 'Side-by-side translation review and correction'),
        ('admin', 'Full system access, user management, monitoring')
        ON CONFLICT (role_name) DO NOTHING
    """)

    # 2. Users table
    op.create_table(
        "users",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("firebase_uid", sa.String(length=128), nullable=True),
        sa.Column("auth_provider", sa.String(length=50), nullable=False, server_default="password"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("role_approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.role_id"]),
        sa.ForeignKeyConstraint(["role_approved_by"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("firebase_uid"),
        if_not_exists=True,
    )

    op.create_index("idx_users_email", "users", ["email"], if_not_exists=True)
    op.create_index("idx_users_firebase_uid", "users", ["firebase_uid"], if_not_exists=True)

    # 3. Sessions table
    op.create_table(
        "sessions",
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("target_language", sa.String(length=20), nullable=False),
        sa.Column("input_file_gcs_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("type IN ('realtime', 'document')", name="sessions_type_check"),
        sa.CheckConstraint("target_language IN ('spa_Latn', 'por_Latn')", name="sessions_target_language_check"),
        sa.CheckConstraint(
            "status IN ('active', 'processing', 'completed', 'failed', 'ended')", name="sessions_status_check"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("session_id"),
        if_not_exists=True,
    )

    op.create_index("idx_sessions_user_id", "sessions", ["user_id"], if_not_exists=True)
    op.create_index("idx_sessions_status", "sessions", ["status"], if_not_exists=True)

    # 4. Translation requests table
    op.create_table(
        "translation_requests",
        sa.Column(
            "request_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_language", sa.String(length=20), nullable=False),
        sa.Column("classification_result", sa.String(length=20), nullable=True),
        sa.Column("output_file_gcs_path", sa.Text(), nullable=True),
        sa.Column("avg_confidence_score", sa.Float(), nullable=True),
        sa.Column("pii_findings_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("llama_corrections_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("processing_time_seconds", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="processing"),
        sa.Column("signed_url", sa.Text(), nullable=True),
        sa.Column("signed_url_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_language IN ('spa_Latn', 'por_Latn')", name="translation_requests_target_language_check"
        ),
        sa.CheckConstraint(
            "classification_result IN ('LEGAL', 'NOT_LEGAL')", name="translation_requests_classification_check"
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'rejected')", name="translation_requests_status_check"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.PrimaryKeyConstraint("request_id"),
        if_not_exists=True,
    )

    op.create_index("idx_translation_requests_session_id", "translation_requests", ["session_id"], if_not_exists=True)

    # 5. Audit logs table
    op.create_table(
        "audit_logs",
        sa.Column(
            "audit_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"]),
        sa.ForeignKeyConstraint(["request_id"], ["translation_requests.request_id"]),
        sa.PrimaryKeyConstraint("audit_id"),
        if_not_exists=True,
    )

    op.create_index("idx_audit_logs_user_id", "audit_logs", ["user_id"], if_not_exists=True)
    op.create_index("idx_audit_logs_session_id", "audit_logs", ["session_id"], if_not_exists=True)
    op.create_index("idx_audit_logs_created_at", "audit_logs", ["created_at"], if_not_exists=True)

    # 6. Form catalog table
    op.create_table(
        "form_catalog",
        sa.Column("form_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("form_name", sa.String(length=500), nullable=False),
        sa.Column("form_slug", sa.String(length=500), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("preprocessing_flags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="form_catalog_status_check"),
        sa.PrimaryKeyConstraint("form_id"),
        sa.UniqueConstraint("form_slug"),
        if_not_exists=True,
    )

    op.create_index("idx_form_catalog_status", "form_catalog", ["status"], if_not_exists=True)
    op.create_index("idx_form_catalog_slug", "form_catalog", ["form_slug"], if_not_exists=True)

    # 7. Form versions table
    op.create_table(
        "form_versions",
        sa.Column(
            "version_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("form_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("file_path_original", sa.Text(), nullable=False),
        sa.Column("file_path_es", sa.Text(), nullable=True),
        sa.Column("file_path_pt", sa.Text(), nullable=True),
        sa.Column("file_type_es", sa.String(length=10), nullable=True),
        sa.Column("file_type_pt", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["form_id"], ["form_catalog.form_id"]),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("form_id", "version", name="form_versions_form_id_version_key"),
        if_not_exists=True,
    )

    op.create_index("idx_form_versions_form_id", "form_versions", ["form_id"], if_not_exists=True)

    # 8. Form appearances table
    op.create_table(
        "form_appearances",
        sa.Column(
            "appearance_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("form_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("division", sa.String(length=255), nullable=False),
        sa.Column("section_heading", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["form_id"], ["form_catalog.form_id"]),
        sa.PrimaryKeyConstraint("appearance_id"),
        sa.UniqueConstraint(
            "form_id", "division", "section_heading", name="form_appearances_form_id_division_section_heading_key"
        ),
        if_not_exists=True,
    )

    op.create_index("idx_form_appearances_form_id", "form_appearances", ["form_id"], if_not_exists=True)
    op.create_index("idx_form_appearances_division", "form_appearances", ["division"], if_not_exists=True)


def downgrade() -> None:
    """
    Drop all Cloud SQL schema tables in reverse dependency order.

    NOTE: This will destroy all data in the tables listed below.
    On Cloud SQL, use 'alembic stamp 002' to revert the revision
    pointer without executing any SQL.
    """
    op.drop_table("form_appearances", if_exists=True)
    op.drop_table("form_versions", if_exists=True)
    op.drop_table("form_catalog", if_exists=True)
    op.drop_table("audit_logs", if_exists=True)
    op.drop_table("translation_requests", if_exists=True)
    op.drop_table("sessions", if_exists=True)
    op.drop_table("users", if_exists=True)
    op.drop_table("roles", if_exists=True)
