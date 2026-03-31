"""pipeline_steps session_id FK ON DELETE CASCADE

Revision ID: c3f1a9b2d5e7
Revises:     64c7ad1631e8
Create Date: 2026-03-31 18:15:00.000000

Without ON DELETE CASCADE the database FK is a plain RESTRICT constraint.
SQLAlchemy with passive_deletes=True on Session.pipeline_steps defers child
deletion to the DB — so the DB-level cascade is required for session deletes
to succeed without SQLAlchemy trying to NULL the non-nullable session_id.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a9b2d5e7"
down_revision: str | None = "64c7ad1631e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the existing plain FK constraint and recreate with ON DELETE CASCADE.
    # PostgreSQL requires dropping and re-adding the constraint to change its
    # referential action; ALTER CONSTRAINT cannot change the action clause.
    op.drop_constraint(
        "pipeline_steps_session_id_fkey",
        "pipeline_steps",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pipeline_steps_session_id_fkey",
        "pipeline_steps",
        "sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Revert to plain FK (RESTRICT behaviour).
    op.drop_constraint(
        "pipeline_steps_session_id_fkey",
        "pipeline_steps",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "pipeline_steps_session_id_fkey",
        "pipeline_steps",
        "sessions",
        ["session_id"],
        ["session_id"],
    )
