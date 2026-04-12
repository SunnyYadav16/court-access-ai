"""add_asr_confidence_to_rt_requests

Revision ID: 524556254468
Revises: a1f4c8e2b305
Create Date: 2026-04-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "524556254468"
down_revision: str | None = "a1f4c8e2b305"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "realtime_translation_requests",
        sa.Column("avg_asr_confidence_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("realtime_translation_requests", "avg_asr_confidence_score")
