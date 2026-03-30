"""add_firebase_auth_fields

Revision ID: 002
Revises: 001
Create Date: 2026-03-17

Adds Firebase authentication fields to the users table:
- firebase_uid: Unique Firebase user ID (indexed for fast lookups)
- auth_provider: Authentication method (google.com, password, saml.massgov, etc.)
- email_verified: Whether the email is verified (mirrors Firebase emailVerified)
- mfa_enabled: Whether MFA is enabled
- name: User's display name from Firebase or signup form
- role_approved_by: FK to user who approved a role upgrade
- role_approved_at: Timestamp of role approval

Also makes hashed_password nullable (unused with Firebase auth).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Firebase auth fields to users table."""
    # Add new columns
    # firebase_uid is nullable so existing rows stay NULL rather than being
    # populated with a shared empty-string default that would break the unique
    # constraint. Rows are backfilled at login time via get_or_create_user().
    op.add_column(
        "users",
        sa.Column(
            "firebase_uid",
            sa.String(length=128),
            nullable=True,
            comment="Firebase user ID — queried on every authenticated request",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "auth_provider",
            sa.String(length=50),
            nullable=False,
            comment="Auth method: google.com, microsoft.com, password, saml.massgov",
            server_default="password",  # Default for existing rows
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Mirrors Firebase emailVerified field",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether user has enabled multi-factor authentication",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            server_default="",
            comment="From Firebase displayName or signup form",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "role_approved_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Admin who approved a role upgrade",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "role_approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of role approval",
        ),
    )

    # Remove server_default from auth_provider after backfill
    op.alter_column("users", "auth_provider", server_default=None)

    # Make hashed_password nullable (unused with Firebase auth)
    op.alter_column("users", "hashed_password", nullable=True)

    # Partial unique index: only enforce uniqueness for rows where firebase_uid
    # is NOT NULL, so existing rows with NULL don't collide with each other.
    op.create_index(
        "ix_users_firebase_uid",
        "users",
        ["firebase_uid"],
        unique=True,
        postgresql_where=sa.text("firebase_uid IS NOT NULL"),
    )

    # Create index on auth_provider for analytics
    op.create_index(
        "ix_users_auth_provider",
        "users",
        ["auth_provider"],
        unique=False,
    )

    # Add foreign key constraint for role_approved_by
    op.create_foreign_key(
        "fk_users_role_approved_by",
        "users",
        "users",
        ["role_approved_by"],
        ["user_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove Firebase auth fields from users table."""
    # Drop foreign key
    op.drop_constraint("fk_users_role_approved_by", "users", type_="foreignkey")

    # Drop indexes
    op.drop_index("ix_users_auth_provider", table_name="users")
    op.drop_index("ix_users_firebase_uid", table_name="users")

    # Make hashed_password non-nullable again
    op.alter_column("users", "hashed_password", nullable=False)

    # Drop columns
    op.drop_column("users", "role_approved_at")
    op.drop_column("users", "role_approved_by")
    op.drop_column("users", "name")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "firebase_uid")
