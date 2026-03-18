"""add_ended_session_status

Revision ID: 004
Revises: 003
Create Date: 2026-03-18

Adds 'ended' as a valid status value for sessions.status.
Updates the check constraint to include: active, processing, completed, failed, ended.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 'ended' to sessions.status constraint."""
    # Drop the old constraint
    op.drop_constraint("sessions_status_check", "sessions", type_="check")

    # Create new constraint with 'ended' included
    op.create_check_constraint(
        "sessions_status_check",
        "sessions",
        "status IN ('active', 'processing', 'completed', 'failed', 'ended')",
    )


def downgrade() -> None:
    """Remove 'ended' from sessions.status constraint."""
    # Migrate any 'ended' rows to 'completed' before reinstating the old
    # constraint, which does not include 'ended'.  Skipping this step would
    # cause the CREATE CHECK CONSTRAINT call to fail immediately because
    # PostgreSQL validates all existing rows on constraint creation.
    op.execute("UPDATE sessions SET status = 'completed' WHERE status = 'ended'")

    op.drop_constraint("sessions_status_check", "sessions", type_="check")

    op.create_check_constraint(
        "sessions_status_check",
        "sessions",
        "status IN ('active', 'processing', 'completed', 'failed')",
    )
