"""add_role_requests_table

Revision ID: 005
Revises: 004
Create Date: 2026-03-18

Adds role_requests table for tracking role upgrade requests.
Allows non-SAML users to request elevated roles (court_official, interpreter)
with admin approval workflow.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create role_requests table."""
    op.create_table(
        "role_requests",
        sa.Column(
            "request_id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "requested_role_id",
            sa.Integer(),
            sa.ForeignKey("roles.role_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "reviewed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Add check constraint for status
    op.create_check_constraint(
        "check_role_request_status",
        "role_requests",
        "status IN ('pending', 'approved', 'rejected')",
    )

    # Add indexes
    op.create_index(
        "idx_role_requests_user_id",
        "role_requests",
        ["user_id"],
    )
    op.create_index(
        "idx_role_requests_status",
        "role_requests",
        ["status"],
    )


def downgrade() -> None:
    """Drop role_requests table."""
    op.drop_index("idx_role_requests_status", table_name="role_requests")
    op.drop_index("idx_role_requests_user_id", table_name="role_requests")
    op.drop_constraint("check_role_request_status", "role_requests", type_="check")
    op.drop_table("role_requests")
