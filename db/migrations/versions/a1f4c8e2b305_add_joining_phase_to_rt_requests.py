"""add_joining_phase_to_rt_requests

Revision ID: a1f4c8e2b305
Revises: 0513a32dd83f
Create Date: 2026-04-07 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1f4c8e2b305"
down_revision: str | None = "0513a32dd83f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("rt_requests_phase_check", "realtime_translation_requests", type_="check")
    op.create_check_constraint(
        "rt_requests_phase_check",
        "realtime_translation_requests",
        "phase IN ('waiting', 'joining', 'active', 'ended')",
    )


def downgrade() -> None:
    op.drop_constraint("rt_requests_phase_check", "realtime_translation_requests", type_="check")
    op.create_check_constraint(
        "rt_requests_phase_check",
        "realtime_translation_requests",
        "phase IN ('waiting', 'active', 'ended')",
    )
