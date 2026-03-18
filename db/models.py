"""
db/models.py

SQLAlchemy async ORM models for the CourtAccess AI system.
Models match the Cloud SQL schema exactly.

Tables:
  roles               — Role definitions (public, court_official, interpreter, admin)
  users               — Registered user accounts with Firebase auth
  role_requests       — Role upgrade requests pending admin approval
  sessions            — Real-time or document translation sessions
  translation_requests — Individual translation requests within sessions
  audit_logs          — Immutable audit trail
  form_catalog        — Pre-translated court forms catalog
  form_versions       — Version history for each form
  form_appearances    — Where each form appears in court divisions
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db.database import Base

# ══════════════════════════════════════════════════════════════════════════════
# Model 1 — Role
# ══════════════════════════════════════════════════════════════════════════════


class Role(Base):
    """
    Role definitions for RBAC.
    Roles:
      public          — Default role, basic document translation and form access
      court_official  — Real-time speech translation access
      interpreter     — Side-by-side translation review and correction
      admin           — Full system access, user management, monitoring
    """

    __tablename__ = "roles"

    role_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    users: Mapped[list[User]] = relationship("User", back_populates="role_obj")

    def __repr__(self) -> str:
        return f"<Role role_id={self.role_id} role_name={self.role_name!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 2 — User
# ══════════════════════════════════════════════════════════════════════════════


class User(Base):
    """
    Registered user account with Firebase authentication.
    Firebase fields:
      firebase_uid       — Unique Firebase user ID
      auth_provider      — Authentication method (google.com, password, saml.massgov)
      email_verified     — Email verification status
      mfa_enabled        — Multi-factor authentication status
    """

    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Role (foreign key to roles table)
    role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.role_id"),
        nullable=False,
        server_default="1",  # Default to 'public' role
    )

    # Firebase authentication fields
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128),
        unique=True,
        nullable=True,
        comment="Firebase user ID",
    )
    auth_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="password",
        comment="Auth method: google.com, microsoft.com, password, saml.massgov",
    )
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # Role approval tracking
    role_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    role_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    role_obj: Mapped[Role] = relationship("Role", back_populates="users", foreign_keys=[role_id])
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="user")
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="user")

    # Indexes
    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_firebase_uid", "firebase_uid"),
    )

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id!s} email={self.email!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 3 — RoleRequest
# ══════════════════════════════════════════════════════════════════════════════


class RoleRequest(Base):
    """
    Role upgrade requests from users.
    Status values:
      pending  — Awaiting admin review
      approved — Admin approved, role granted
      rejected — Admin rejected request
    """

    __tablename__ = "role_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    requested_role_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roles.role_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    requested_role: Mapped[Role] = relationship("Role", foreign_keys=[requested_role_id])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])

    # Indexes and constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="check_role_request_status",
        ),
        Index("idx_role_requests_user_id", "user_id"),
        Index("idx_role_requests_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<RoleRequest request_id={self.request_id!s} user_id={self.user_id!s} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 4 — Session
# ══════════════════════════════════════════════════════════════════════════════


class Session(Base):
    """
    A translation session (realtime or document-based).
    Types:
      realtime  — Real-time speech interpretation session
      document  — Document translation session
    Target languages:
      spa_Latn  — Spanish (Latin script)
      por_Latn  — Portuguese (Latin script)
    """

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Session type: realtime or document",
    )
    target_language: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Target language: spa_Latn or por_Latn",
    )
    input_file_gcs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="active",
        comment="Status: active, processing, completed, failed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")
    translation_requests: Mapped[list[TranslationRequest]] = relationship(
        "TranslationRequest",
        back_populates="session",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="session")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("type IN ('realtime', 'document')", name="sessions_type_check"),
        CheckConstraint(
            "target_language IN ('spa_Latn', 'por_Latn')",
            name="sessions_target_language_check",
        ),
        CheckConstraint(
            "status IN ('active', 'processing', 'completed', 'failed', 'ended')",
            name="sessions_status_check",
        ),
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<Session session_id={self.session_id!s} type={self.type!r} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 5 — TranslationRequest
# ══════════════════════════════════════════════════════════════════════════════


class TranslationRequest(Base):
    """
    Individual translation request within a session.
    Tracks classification, PII detection, LLM corrections, and output.
    """

    __tablename__ = "translation_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id"),
        nullable=False,
    )
    target_language: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Target language: spa_Latn or por_Latn",
    )
    classification_result: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Classification: LEGAL or NOT_LEGAL",
    )
    output_file_gcs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    avg_confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pii_findings_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    llama_corrections_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="processing",
        comment="Status: processing, completed, failed, rejected",
    )
    signed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_url_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="translation_requests")
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="request")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "target_language IN ('spa_Latn', 'por_Latn')",
            name="translation_requests_target_language_check",
        ),
        CheckConstraint(
            "classification_result IN ('LEGAL', 'NOT_LEGAL')",
            name="translation_requests_classification_check",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'rejected')",
            name="translation_requests_status_check",
        ),
        Index("idx_translation_requests_session_id", "session_id"),
    )

    def __repr__(self) -> str:
        return f"<TranslationRequest request_id={self.request_id!s} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 6 — AuditLog
# ══════════════════════════════════════════════════════════════════════════════


class AuditLog(Base):
    """
    Immutable audit trail for all user actions.
    """

    __tablename__ = "audit_logs"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id"),
        nullable=True,
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("translation_requests.request_id"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default="{}",
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="audit_logs")
    session: Mapped[Session | None] = relationship("Session", back_populates="audit_logs")
    request: Mapped[TranslationRequest | None] = relationship(
        "TranslationRequest",
        back_populates="audit_logs",
    )

    # Indexes
    __table_args__ = (
        Index("idx_audit_logs_user_id", "user_id"),
        Index("idx_audit_logs_session_id", "session_id"),
        Index("idx_audit_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog audit_id={self.audit_id!s} action_type={self.action_type!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 7 — FormCatalog
# ══════════════════════════════════════════════════════════════════════════════


class FormCatalog(Base):
    """
    Pre-translated court forms catalog.
    """

    __tablename__ = "form_catalog"

    form_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    form_name: Mapped[str] = mapped_column(String(500), nullable=False)
    form_slug: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="active",
        comment="Status: active or archived",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    preprocessing_flags: Mapped[list | None] = mapped_column(
        JSONB,
        server_default="[]",
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_scraped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    versions: Mapped[list[FormVersion]] = relationship("FormVersion", back_populates="form")
    appearances: Mapped[list[FormAppearance]] = relationship("FormAppearance", back_populates="form")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="form_catalog_status_check"),
        Index("idx_form_catalog_status", "status"),
        Index("idx_form_catalog_slug", "form_slug"),
    )

    def __repr__(self) -> str:
        return f"<FormCatalog form_id={self.form_id!s} form_name={self.form_name!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 8 — FormVersion
# ══════════════════════════════════════════════════════════════════════════════


class FormVersion(Base):
    """
    Version history for each form.
    """

    __tablename__ = "form_versions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form_catalog.form_id"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_path_original: Mapped[str] = mapped_column(Text, nullable=False)
    file_path_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path_pt: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_type_es: Mapped[str | None] = mapped_column(String(10), nullable=True)
    file_type_pt: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    form: Mapped[FormCatalog] = relationship("FormCatalog", back_populates="versions")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("form_id", "version", name="form_versions_form_id_version_key"),
        Index("idx_form_versions_form_id", "form_id"),
    )

    def __repr__(self) -> str:
        return f"<FormVersion version_id={self.version_id!s} form_id={self.form_id!s} version={self.version}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 9 — FormAppearance
# ══════════════════════════════════════════════════════════════════════════════


class FormAppearance(Base):
    """
    Where each form appears in court divisions.
    """

    __tablename__ = "form_appearances"

    appearance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("form_catalog.form_id"),
        nullable=False,
    )
    division: Mapped[str] = mapped_column(String(255), nullable=False)
    section_heading: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    form: Mapped[FormCatalog] = relationship("FormCatalog", back_populates="appearances")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "form_id",
            "division",
            "section_heading",
            name="form_appearances_form_id_division_section_heading_key",
        ),
        Index("idx_form_appearances_form_id", "form_id"),
        Index("idx_form_appearances_division", "division"),
    )

    def __repr__(self) -> str:
        return f"<FormAppearance appearance_id={self.appearance_id!s} division={self.division!r}>"
