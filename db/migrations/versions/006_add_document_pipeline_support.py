"""006_add_document_pipeline_support

Revision ID: 006
Revises: 005
Create Date: 2026-03-24

Two changes:

  1. translation_requests.error_message (new column)
     — Pipeline failure reason shown in the frontend error state.
     — Set by the DAG on classify_document rejection or any task failure.

  2. pipeline_steps (new table)
     — One row per task per DAG run, upserted by the DAG.
     — Polled by GET /documents/{session_id}/steps for the
       frontend progress screen (step name, status, detail text, metadata).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. translation_requests.error_message ─────────────────────────────────
    op.add_column(
        "translation_requests",
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Pipeline failure message shown in the frontend error state",
        ),
    )

    # ── 2. pipeline_steps ─────────────────────────────────────────────────────
    op.create_table(
        "pipeline_steps",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            comment="running | success | failed | skipped",
        ),
        sa.Column(
            "detail",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="Human-readable summary shown in the progress UI",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="Structured metrics (region counts, confidence scores, etc.)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # One row per step per session — DAG upserts on this pair
        sa.UniqueConstraint(
            "session_id",
            "step_name",
            name="pipeline_steps_session_step_key",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped')",
            name="pipeline_steps_status_check",
        ),
    )
    op.create_index(
        "idx_pipeline_steps_session_id",
        "pipeline_steps",
        ["session_id"],
    )
    op.create_index(
        "idx_pipeline_steps_status",
        "pipeline_steps",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("pipeline_steps")
    op.drop_column("translation_requests", "error_message")
