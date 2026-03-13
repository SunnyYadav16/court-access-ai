"""
db/models.py

SQLAlchemy async ORM models for the CourtAccess AI system.

Tables:
  users               — Registered user accounts (LEP individuals, court officials, etc.)
  sessions            — Real-time court interpretation sessions
  translation_requests — User-uploaded document translation jobs
  audit_logs          — Immutable audit trail: form reviews, PII findings, DAG events

Design principles:
  - All primary keys are UUIDs (server-generated via gen_random_uuid())
  - All timestamps are stored as TIMESTAMP WITH TIME ZONE (UTC)
  - VARCHAR lengths chosen conservatively; TEXT for unbounded fields
  - No soft-delete columns — use AuditLog instead of deleted_at
  - Foreign key constraints with ON DELETE CASCADE where appropriate
  - Indexes on all foreign keys + high-cardinality WHERE-clause columns
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db.database import Base

# ── Shared column helpers ─────────────────────────────────────────────────────


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Standard UUID primary key, server-generated."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


def _now() -> Mapped[datetime]:
    """Timestamp column that defaults to now() on INSERT."""
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Model 1 — User
# ══════════════════════════════════════════════════════════════════════════════


class User(Base):
    """
    Registered user account.

    Roles:
      public          — Self-registered LEP individual
      court_official  — Courthouse staff with elevated access
      interpreter     — Court-certified interpreter
      admin           — System administrator

    username and email are unique and indexed.
    hashed_password stores a bcrypt hash (never plain text).
    Firebase auth fields are populated on first OAuth/Firebase login.
    """

    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("public", "court_official", "interpreter", "admin", name="user_role_enum"),
        nullable=False,
        server_default="public",
    )
    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Firebase auth fields ──────────────────────────────────────────────────
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    auth_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    role_approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    sessions: Mapped[list[Session]] = relationship("Session", back_populates="creator", cascade="all, delete-orphan")
    # translation_requests: Mapped[list[TranslationRequest]] = relationship(
    #     "TranslationRequest", back_populates="user", cascade="all, delete-orphan"
    # )

    translation_requests: Mapped[list[TranslationRequest]] = relationship(
    "TranslationRequest",
    back_populates="user",
    cascade="all, delete-orphan",
    foreign_keys="[TranslationRequest.user_id]",    
    )
    
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="actor", cascade="all, delete-orphan")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_username", "username"),
        Index("ix_users_role", "role"),
        Index("ix_users_firebase_uid", "firebase_uid"),
    )

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id!s} username={self.username!r} role={self.role!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 2 — Session
# ══════════════════════════════════════════════════════════════════════════════


class Session(Base):
    """
    A real-time court interpretation session.

    Lifecycle: active → paused → ended
    Each session has one creator (the court official or interpreter who opens it)
    and optionally many participants (observers, other interpreters).

    transcript_gcs_uri: When the session ends, the full transcript is flushed
    to GCS as a JSONL file and the URI stored here for audit purposes.
    """

    __tablename__ = "sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "ended", name="session_status_enum"),
        nullable=False,
        server_default="active",
    )
    source_language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="en")
    target_language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="es")

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Transcript storage ────────────────────────────────────────────────────
    transcript_gcs_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # ── Metadata ──────────────────────────────────────────────────────────────
    # JSONB for flexible participant tracking without a separate join table.
    participants: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment='[{"user_id": "...", "role": "creator|interpreter|observer"}]',
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    creator: Mapped[User] = relationship("User", back_populates="sessions")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_sessions_creator_id", "creator_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Session session_id={self.session_id!s} status={self.status!r}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 3 — TranslationRequest
# ══════════════════════════════════════════════════════════════════════════════


class TranslationRequest(Base):
    """
    A single user-uploaded document translation job.

    Lifecycle: pending → processing → translated → approved | rejected | error

    GCS paths:
      upload_gcs_uri          — Original PDF (auto-deleted after 24h)
      translated_uris         — JSONB map: {"es": "gs://...", "pt": "gs://..."}

    The document_pipeline_dag writes back status updates via the Airflow REST API.
    In the future, a webhook from Airflow can directly update this row.
    """

    __tablename__ = "translation_requests"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "processing",
            "translated",
            "approved",
            "rejected",
            "error",
            name="doc_status_enum",
        ),
        nullable=False,
        server_default="pending",
    )

    # ── File metadata ─────────────────────────────────────────────────────────
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_gcs_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_languages: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(8)),
        nullable=True,
        comment="e.g. ['es', 'pt']",
    )

    # ── Translation results ───────────────────────────────────────────────────
    translated_uris: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='{"es": "gs://courtaccess-translated/...", "pt": "gs://..."}'
    )
    legal_review_status: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment='{"es": "ok", "pt": "skipped"}'
    )

    # ── PII & review flags ────────────────────────────────────────────────────
    pii_findings_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Airflow tracking ──────────────────────────────────────────────────────
    airflow_dag_run_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitter_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="translation_requests", foreign_keys=[user_id])

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_translation_requests_user_id", "user_id"),
        Index("ix_translation_requests_status", "status"),
        Index("ix_translation_requests_created_at", "created_at"),
        Index("ix_translation_requests_airflow_run", "airflow_dag_run_id"),
    )

    def __repr__(self) -> str:
        return f"<TranslationRequest document_id={self.document_id!s} status={self.status!r} user_id={self.user_id!s}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 4 — AuditLog
# ══════════════════════════════════════════════════════════════════════════════


class AuditLog(Base):
    """
    Immutable audit trail for security-sensitive events.

    Events captured:
      - user.register, user.login, user.logout
      - document.upload, document.delete
      - translation.completed, translation.approved, translation.rejected
      - form.reviewed, form.review_approved, form.review_rejected
      - pii.detected (count only — no PII text is stored)
      - session.created, session.ended
      - dag.triggered, dag.completed, dag.failed

    This table is append-only — no UPDATE or DELETE is ever performed.
    Retention policy: 7 years (legal requirement for court records).
    Foreign keys use ON DELETE SET NULL so log entries survive user deletion.
    """

    __tablename__ = "audit_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # ── Who did it ────────────────────────────────────────────────────────────
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,  # NULL for system/DAG-initiated events
    )

    # ── What happened ─────────────────────────────────────────────────────────
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="'user', 'document', 'form', 'session', 'dag'",
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="UUID of the affected resource as a string",
    )

    # ── Extra context ─────────────────────────────────────────────────────────
    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Freeform event details — NEVER store PII or secret values here",
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 max = 45 chars
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── When ──────────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    actor: Mapped[User | None] = relationship("User", back_populates="audit_logs")

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog log_id={self.log_id!s} event_type={self.event_type!r} actor_id={self.actor_id!s}>"


# ══════════════════════════════════════════════════════════════════════════════
# Model 5 — FormCatalog
# ══════════════════════════════════════════════════════════════════════════════


class FormCatalog(Base):
    """
    Database mirror of the form_catalog.json maintained by form_scraper_dag.

    This table enables:
      - Fast indexed search vs full JSON file scan
      - Human review tracking with foreign key to the reviewer
      - Query-based filtering by division, language coverage, status

    The raw JSON versions array is stored in JSONB (versions_json) alongside
    the denormalized current_version fields for fast access.

    Sync strategy: form_scraper_dag upserts rows after each weekly run.
    Primary key is the form_id from the catalog (a UUID assigned on first scrape).
    """

    __tablename__ = "form_catalog"

    form_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        comment="UUID assigned by form_scraper_dag on first scrape",
    )
    form_name: Mapped[str] = mapped_column(String(512), nullable=False)
    form_slug: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        Enum("active", "archived", name="form_status_enum"),
        nullable=False,
        server_default="active",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    # ── Language availability ─────────────────────────────────────────────────
    # Denormalized from latest version for fast filtering.
    has_spanish: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_portuguese: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    languages_available: Mapped[list[str] | None] = mapped_column(ARRAY(String(8)), nullable=True)

    # ── Court divisions ───────────────────────────────────────────────────────
    # Denormalized list of division names for searchability.
    divisions: Mapped[list[str] | None] = mapped_column(ARRAY(String(256)), nullable=True)

    # ── Full version history ──────────────────────────────────────────────────
    versions_json: Mapped[list[dict] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full versions array from form_catalog.json",
    )

    # ── Human review ─────────────────────────────────────────────────────────
    needs_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audit_notes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_form_catalog_status", "status"),
        Index("ix_form_catalog_has_spanish", "has_spanish"),
        Index("ix_form_catalog_has_portuguese", "has_portuguese"),
        Index("ix_form_catalog_needs_review", "needs_human_review"),
        Index("ix_form_catalog_last_scraped", "last_scraped_at"),
        # GIN index for fast ARRAY containment queries on divisions
        Index("ix_form_catalog_divisions_gin", "divisions", postgresql_using="gin"),
        UniqueConstraint("form_slug", name="uq_form_catalog_slug"),
    )

    def __repr__(self) -> str:
        return f"<FormCatalog form_id={self.form_id!s} form_name={self.form_name!r} status={self.status!r}>"
