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
    Lean parent session. One row per translation event.
    type='document'  → one DocumentTranslationRequest child
    type='realtime'  → one RealtimeTranslationRequest child
    One session = one target language. Second language = second session row.
    """

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, comment="realtime or document")
    target_language: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="spa_Latn or por_Latn. One session = one language always."
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="sessions")
    document_request: Mapped[DocumentTranslationRequest | None] = relationship(
        "DocumentTranslationRequest", back_populates="session", uselist=False, passive_deletes=True
    )
    realtime_request: Mapped[RealtimeTranslationRequest | None] = relationship(
        "RealtimeTranslationRequest", back_populates="session", uselist=False, passive_deletes=True
    )
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="session", passive_deletes=True)
    pipeline_steps: Mapped[list[PipelineStep]] = relationship(
        "PipelineStep", back_populates="session", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("type IN ('realtime', 'document')", name="sessions_type_check"),
        CheckConstraint("target_language IN ('spa_Latn', 'por_Latn')", name="sessions_target_language_check"),
        CheckConstraint(
            # 'ended' removed — use 'completed' for both session types
            "status IN ('active', 'processing', 'completed', 'failed')",
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


class DocumentTranslationRequest(Base):
    """
    Document pipeline data for sessions where type='document'.
    One-to-one with Session.
    Deduplication: before creating a new session+row, the API checks
    content_hash + target_language + user_id for an existing completed row.
    If found, the existing signed_url is returned — no re-processing.
    input_file_gcs_path is reused from the matched row for a second-language
    request on the same file.
    """

    __tablename__ = "document_translation_requests"

    doc_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # enforces 1-to-1
    )

    # Source file — moved here from sessions
    input_file_gcs_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="GCS path of the uploaded original. Reused for second-language requests."
    )
    content_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 of uploaded file bytes. Nullable for legacy rows; required for all new inserts.",
    )

    # Processing
    target_language: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Denormalized from session for query convenience"
    )
    classification_result: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="LEGAL or NOT_LEGAL")
    avg_confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pii_findings_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    llama_corrections_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Output
    output_file_gcs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_url_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="document_request")
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog", back_populates="document_request", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("target_language IN ('spa_Latn', 'por_Latn')", name="doc_requests_target_language_check"),
        CheckConstraint(
            "classification_result IS NULL OR classification_result IN ('LEGAL', 'NOT_LEGAL')",
            name="doc_requests_classification_check",
        ),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'rejected')", name="doc_requests_status_check"
        ),
        Index("idx_doc_requests_session_id", "session_id"),
        Index("idx_doc_requests_content_hash", "content_hash"),
    )

    def __repr__(self) -> str:
        return f"<DocumentTranslationRequest doc_request_id={self.doc_request_id!s} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 6 — RealtimeTranslationRequest
# ══════════════════════════════════════════════════════════════════════════════


class RealtimeTranslationRequest(Base):
    """
    Real-time session data for sessions where type='realtime'.
    One-to-one with Session.

    Room lifecycle:
      waiting → court official created room, code is valid, no one joined yet
      active  → LEP individual joined (authenticated or guest), session running
      ended   → session closed by either party or timeout

    Guest join: partner_user_id is NULL when the LEP individual joins without
    an account. partner_name (typed by the court official at setup) is the
    display name in that case.

    Transcript: utterance data is held in memory during the session (never
    written to DB per-turn). On session end, the full JSON transcript is
    uploaded to GCS and transcript_gcs_path + stats are written here in a
    single DB update.
    """

    __tablename__ = "realtime_translation_requests"

    rt_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # enforces 1-to-1
    )

    # Room setup — filled by court official at creation
    room_code: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        unique=True,
        comment="Short alphanumeric join code e.g. A3K7P2. Valid until room_code_expires_at or phase→active.",
    )
    room_code_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="30 minutes from creation. Code rejected after this even if phase is still 'waiting'.",
    )
    court_division: Mapped[str | None] = mapped_column(String(100), nullable=True)
    courtroom: Mapped[str | None] = mapped_column(String(50), nullable=True)
    case_docket: Mapped[str | None] = mapped_column(String(50), nullable=True)
    consent_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="Court official confirmed both parties consent before starting.",
    )

    # Participants
    creator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False, comment="court_official who created the room."
    )
    partner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
        comment="LEP individual's user_id if they signed in. NULL if they joined as a guest.",
    )
    partner_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="LEP individual's name typed by court official at setup. Used as display name for guests.",
    )
    partner_joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Timestamp when the LEP individual joined. NULL until joined."
    )

    # Phase
    phase: Mapped[str] = mapped_column(String(20), nullable=False, server_default="waiting")

    # Transcript — all NULL during session, written once on session end
    transcript_gcs_path: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="gs://courtaccess-ai-transcripts/{session_id}/transcript.json. Set on session end."
    )
    transcript_signed_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_signed_url_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Summary stats — computed in-memory, written once on session end
    total_utterances: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    session: Mapped[Session] = relationship("Session", back_populates="realtime_request")
    creator: Mapped[User] = relationship("User", foreign_keys=[creator_user_id])
    partner: Mapped[User | None] = relationship("User", foreign_keys=[partner_user_id])
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog", back_populates="realtime_request", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("phase IN ('waiting', 'active', 'ended')", name="rt_requests_phase_check"),
        Index("idx_rt_requests_session_id", "session_id"),
        Index("idx_rt_requests_room_code", "room_code"),
        Index("idx_rt_requests_phase", "phase"),
    )

    def __repr__(self) -> str:
        return f"<RealtimeTranslationRequest rt_request_id={self.rt_request_id!s} phase={self.phase!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 7 — AuditLog
# ══════════════════════════════════════════════════════════════════════════════


class AuditLog(Base):
    """
    Immutable audit trail. request_id split into two nullable FKs —
    one per child table — so a single audit row can reference either
    a document request or a realtime request without a polymorphic hack.
    """

    __tablename__ = "audit_logs"

    audit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.user_id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    # One of these two will be set, the other NULL, depending on session type
    doc_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_translation_requests.doc_request_id", ondelete="SET NULL"),
        nullable=True,
    )
    rt_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("realtime_translation_requests.rt_request_id", ondelete="SET NULL"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, server_default="{}", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="audit_logs")
    session: Mapped[Session | None] = relationship("Session", back_populates="audit_logs")
    document_request: Mapped[DocumentTranslationRequest | None] = relationship(
        "DocumentTranslationRequest", back_populates="audit_logs"
    )
    realtime_request: Mapped[RealtimeTranslationRequest | None] = relationship(
        "RealtimeTranslationRequest", back_populates="audit_logs"
    )

    __table_args__ = (
        Index("idx_audit_logs_user_id", "user_id"),
        Index("idx_audit_logs_session_id", "session_id"),
        Index("idx_audit_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog audit_id={self.audit_id!s} action_type={self.action_type!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 8 — FormCatalog
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
    last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last content change (hash change or new form). Not updated on rename or translation.",
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
# Model 9 — FormVersion
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
# Model 10 — FormAppearance
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


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    step_metadata: Mapped[dict | None] = mapped_column(JSONB, name="metadata", server_default="{}", nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session: Mapped[Session] = relationship("Session", back_populates="pipeline_steps")

    __table_args__ = (
        UniqueConstraint("session_id", "step_name", name="pipeline_steps_session_step_key"),
        CheckConstraint("status IN ('running', 'success', 'failed', 'skipped')", name="pipeline_steps_status_check"),
        Index("idx_pipeline_steps_session_id", "session_id"),
    )
