"""fix CASCADE and SET NULL ondelete for session/request FKs

Revision ID: d8e2f4a61b93
Revises:     c3f1a9b2d5e7
Create Date: 2026-04-01 22:45:00.000000

Three FK constraints lack the correct ON DELETE action, making
DELETE /documents/{session_id} fail with IntegrityError in production:

1. translation_requests.session_id  — needs ON DELETE CASCADE
   (deleting a session must delete its translation requests)

2. audit_logs.session_id            — needs ON DELETE SET NULL
   (audit trail survives deletion; FK reference becomes NULL)

3. audit_logs.request_id            — needs ON DELETE SET NULL
   (same reasoning — cascaded request deletion must not block)

PostgreSQL cannot ALTER a constraint's referential action in place;
each must be dropped and recreated.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e2f4a61b93"
down_revision: str | None = "c3f1a9b2d5e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. translation_requests.session_id → ON DELETE CASCADE ────────────
    op.drop_constraint(
        "translation_requests_session_id_fkey",
        "translation_requests",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "translation_requests_session_id_fkey",
        "translation_requests",
        "sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )

    # ── 2. audit_logs.session_id → ON DELETE SET NULL ─────────────────────
    op.drop_constraint(
        "audit_logs_session_id_fkey",
        "audit_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_session_id_fkey",
        "audit_logs",
        "sessions",
        ["session_id"],
        ["session_id"],
        ondelete="SET NULL",
    )

    # ── 3. audit_logs.request_id → ON DELETE SET NULL ─────────────────────
    op.drop_constraint(
        "audit_logs_request_id_fkey",
        "audit_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_request_id_fkey",
        "audit_logs",
        "translation_requests",
        ["request_id"],
        ["request_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Revert all three to plain RESTRICT (no ondelete clause).

    op.drop_constraint(
        "audit_logs_request_id_fkey",
        "audit_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_request_id_fkey",
        "audit_logs",
        "translation_requests",
        ["request_id"],
        ["request_id"],
    )

    op.drop_constraint(
        "audit_logs_session_id_fkey",
        "audit_logs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "audit_logs_session_id_fkey",
        "audit_logs",
        "sessions",
        ["session_id"],
        ["session_id"],
    )

    op.drop_constraint(
        "translation_requests_session_id_fkey",
        "translation_requests",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "translation_requests_session_id_fkey",
        "translation_requests",
        "sessions",
        ["session_id"],
        ["session_id"],
    )
