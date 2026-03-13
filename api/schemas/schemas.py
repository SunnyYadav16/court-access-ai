"""
api/schemas/schemas.py

Pydantic v2 request/response models for the CourtAccess AI API.

All models use strict typing and field-level validation.
Shared across all route modules — import patterns:
    from api.schemas.schemas import UploadRequest, TranslationStatusResponse
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ══════════════════════════════════════════════════════════════════════════════
# Enums
# ══════════════════════════════════════════════════════════════════════════════


class UserRole(StrEnum):
    """Role-based access control tiers."""

    PUBLIC = "public"  # Self-registered end-users (LEP individuals)
    COURT_OFFICIAL = "court_official"  # Courthouse staff with elevated access
    INTERPRETER = "interpreter"  # Court-certified interpreters
    ADMIN = "admin"  # System administrators


class Language(StrEnum):
    """Supported output languages for translation."""

    ENGLISH = "en"
    SPANISH = "es"
    PORTUGUESE = "pt"


class DocumentStatus(StrEnum):
    """Lifecycle states for a user-uploaded document."""

    PENDING = "pending"  # Uploaded, not yet processed
    PROCESSING = "processing"  # DAG running
    TRANSLATED = "translated"  # Translation complete, awaiting human review
    APPROVED = "approved"  # Human-reviewed and approved
    REJECTED = "rejected"  # Rejected by human reviewer
    ERROR = "error"  # Pipeline failure


class SessionStatus(StrEnum):
    """States for a real-time interpretation session."""

    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


# ══════════════════════════════════════════════════════════════════════════════
# Auth schemas
# ══════════════════════════════════════════════════════════════════════════════


class TokenResponse(BaseModel):
    """JWT token pair returned after successful login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int = Field(description="Seconds until access_token expires")


class TokenRefreshRequest(BaseModel):
    """Request body for refreshing an access token."""

    refresh_token: str


class LoginRequest(BaseModel):
    """Credentials for username/password login."""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    """New user registration payload."""

    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, description="Min 8 chars, must include a digit")
    preferred_language: Language = Language.ENGLISH
    role: UserRole = UserRole.PUBLIC


# class UserResponse(BaseModel):
#     """Public user representation (no password fields)."""

#     model_config = ConfigDict(from_attributes=True)

#     user_id: uuid.UUID
#     username: str
#     email: EmailStr
#     role: UserRole
#     preferred_language: Language
#     created_at: datetime


# ── CHANGE 1: Update UserResponse (around line 80) ───────────────────────────
# Replace the existing UserResponse class with this:

class UserResponse(BaseModel):
    """Public user representation (no password fields)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    username: str
    email: EmailStr
    role: UserRole
    preferred_language: Language
    created_at: datetime
    # Firebase auth fields (nullable for backward compatibility)
    firebase_uid: str | None = None
    auth_provider: str | None = None
    email_verified: bool = False
    mfa_enabled: bool = False
    last_login_at: datetime | None = None


# ── CHANGE 2: Add these new schemas after UserResponse ───────────────────────

class AuthStatusResponse(BaseModel):
    """Response from GET /auth/me — full auth state for the frontend."""

    is_authenticated: bool
    user: UserResponse
    requires_email_verification: bool
    requires_role_selection: bool


class RoleUpdateRequest(BaseModel):
    """User selects their role after first login."""

    selected_role: str = Field(
        description="One of: public, court_official, interpreter, admin"
    )


class RoleApprovalRequest(BaseModel):
    """Admin approves or revokes a user's role."""

    user_id: str = Field(description="firebase_uid of the target user")
    approved_role: str = Field(
        description="Role to assign: public, court_official, interpreter, admin"
    )

# ══════════════════════════════════════════════════════════════════════════════
# Document upload schemas
# ══════════════════════════════════════════════════════════════════════════════


class UploadRequest(BaseModel):
    """
    Metadata submitted alongside a document upload (multipart form).
    The actual file bytes are handled by FastAPI's UploadFile.
    """

    target_languages: list[Language] = Field(
        default=[Language.SPANISH, Language.PORTUGUESE],
        description="Languages to translate into. Defaults to both ES and PT.",
    )
    notes: str | None = Field(default=None, max_length=500, description="Optional submitter notes")


class DocumentResponse(BaseModel):
    """Response after a successful document upload."""

    document_id: uuid.UUID
    status: DocumentStatus
    upload_path: str
    created_at: datetime
    estimated_completion_seconds: int = Field(
        default=300,
        description="Estimated DAG processing time",
    )


class TranslationStatusResponse(BaseModel):
    """Status check response for an in-progress or completed translation."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    status: DocumentStatus
    created_at: datetime
    completed_at: datetime | None = None
    pii_findings_count: int = Field(
        default=0,
        description="Number of PII instances found (for HIPAA audit log); text not exposed",
    )
    translation_urls: dict[str, str] = Field(
        default_factory=dict,
        description="Signed GCS URLs keyed by language code, e.g. {'es': 'https://...', 'pt': 'https://...'}",
    )
    legal_review_status: dict[str, str] = Field(
        default_factory=dict,
        description="Legal review outcome per language: {'es': 'ok', 'pt': 'skipped'}",
    )
    needs_human_review: bool = True
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated list of documents for the current user."""

    items: list[TranslationStatusResponse]
    total: int
    page: int
    page_size: int


# ══════════════════════════════════════════════════════════════════════════════
# Real-time session schemas
# ══════════════════════════════════════════════════════════════════════════════


class SessionCreateRequest(BaseModel):
    """Create a new real-time interpretation session."""

    target_language: Language = Language.SPANISH
    source_language: Language = Language.ENGLISH


class SessionResponse(BaseModel):
    """Created session metadata returned to the client."""

    session_id: uuid.UUID
    websocket_url: str = Field(description="WebSocket endpoint for this session")
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime
    target_language: Language
    source_language: Language


class SessionParticipantRequest(BaseModel):
    """Add or update a participant in a session."""

    user_id: uuid.UUID
    role: str = Field(
        description="Participant role: 'creator', 'interpreter', 'observer'",
        pattern=r"^(creator|interpreter|observer)$",
    )


class TranscriptSegment(BaseModel):
    """One segment of a real-time ASR transcript pushed over WebSocket."""

    segment_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    speaker_id: str
    original_text: str
    translated_text: str | None = None
    translation_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    language: Language = Language.ENGLISH
    timestamp_ms: int = Field(description="Milliseconds from session start")
    is_final: bool = Field(
        default=False,
        description="True when ASR has committed this segment; False for interim results",
    )


class WebSocketMessage(BaseModel):
    """Envelope for all WebSocket messages (client ↔ server)."""

    type: str = Field(description="Message type: 'audio_chunk', 'transcript', 'error', 'ping', 'pong'")
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: uuid.UUID | None = None
    timestamp_ms: int | None = None


# ══════════════════════════════════════════════════════════════════════════════
# Form catalog schemas
# ══════════════════════════════════════════════════════════════════════════════


class FormAppearance(BaseModel):
    """A single court division + section heading where this form appears."""

    division: str
    section_heading: str


class FormVersion(BaseModel):
    """One version record for a court form."""

    version: int
    content_hash: str
    file_url_original: str | None = Field(default=None, description="Signed GCS URL for original EN PDF")
    file_url_es: str | None = Field(default=None, description="Signed GCS URL for Spanish PDF")
    file_url_pt: str | None = Field(default=None, description="Signed GCS URL for Portuguese PDF")
    created_at: datetime


class FormResponse(BaseModel):
    """A single court form from the catalog."""

    model_config = ConfigDict(from_attributes=True)

    form_id: uuid.UUID
    form_name: str
    form_slug: str
    source_url: str
    status: str = Field(description="'active' or 'archived'")
    current_version: int
    needs_human_review: bool
    languages_available: list[str] = Field(default_factory=list)
    appearances: list[FormAppearance] = Field(default_factory=list)
    latest_version: FormVersion | None = None
    last_scraped_at: datetime | None = None


class FormListResponse(BaseModel):
    """Paginated list of court forms from the catalog."""

    items: list[FormResponse]
    total: int
    page: int
    page_size: int
    filters_applied: dict[str, str] = Field(default_factory=dict)


class FormSearchRequest(BaseModel):
    """Query parameters for searching the form catalog."""

    q: str | None = Field(default=None, max_length=200, description="Keyword search over form names")
    division: str | None = Field(default=None, description="Filter by court division")
    language: Language | None = Field(default=None, description="Only return forms available in this language")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ══════════════════════════════════════════════════════════════════════════════
# Generic / error schemas
# ══════════════════════════════════════════════════════════════════════════════


class HealthResponse(BaseModel):
    """Response from GET /health."""

    status: str = "ok"
    version: str
    environment: str


class ErrorDetail(BaseModel):
    """Standardized error response body."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
