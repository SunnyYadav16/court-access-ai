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


# Role ID to role name mapping (matches db/models.py Role table)
ROLE_ID_TO_NAME: dict[int, str] = {
    1: UserRole.PUBLIC,
    2: UserRole.COURT_OFFICIAL,
    3: UserRole.INTERPRETER,
    4: UserRole.ADMIN,
}


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
    """States for a session."""

    ACTIVE = "active"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ENDED = "ended"


class SessionType(StrEnum):
    """Session types."""

    REALTIME = "realtime"
    DOCUMENT = "document"


class TargetLanguage(StrEnum):
    """Target languages for translation."""

    SPANISH = "spa_Latn"
    PORTUGUESE = "por_Latn"


class TranslationRequestStatus(StrEnum):
    """Translation request statuses."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ClassificationResult(StrEnum):
    """Document classification results."""

    LEGAL = "LEGAL"
    NOT_LEGAL = "NOT_LEGAL"


# ══════════════════════════════════════════════════════════════════════════════
# Role schemas
# ══════════════════════════════════════════════════════════════════════════════


class RoleResponse(BaseModel):
    """Role definition."""

    model_config = ConfigDict(from_attributes=True)

    role_id: int
    role_name: str
    description: str | None
    created_at: datetime


# ══════════════════════════════════════════════════════════════════════════════
# Auth schemas
# ══════════════════════════════════════════════════════════════════════════════


class UserResponse(BaseModel):
    """Public user representation — matches actual database schema."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    user_id: uuid.UUID
    email: EmailStr
    name: str
    role: str = Field(default="unknown", description="Role name: public, court_official, interpreter, admin")
    firebase_uid: str | None
    auth_provider: str
    email_verified: bool
    mfa_enabled: bool
    role_approved_by: uuid.UUID | None
    role_approved_at: datetime | None
    created_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_orm_user(cls, user) -> UserResponse:
        """Create UserResponse from User ORM object with role name mapping."""
        return cls(
            user_id=user.user_id,
            email=user.email,
            name=user.name,
            role=ROLE_ID_TO_NAME.get(user.role_id, "unknown"),
            firebase_uid=user.firebase_uid,
            auth_provider=user.auth_provider,
            email_verified=user.email_verified,
            mfa_enabled=user.mfa_enabled,
            role_approved_by=user.role_approved_by,
            role_approved_at=user.role_approved_at,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class RoleUpdateRequest(BaseModel):
    """Request body for role selection."""

    selected_role: UserRole = Field(description="Role to assign: public, court_official, or interpreter")


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
    """
    Response returned immediately after a successful document upload.
    session_id is the polling key for all subsequent /documents/* requests.
    """

    session_id: uuid.UUID  # polling key — use for GET /documents/{session_id}
    request_id: uuid.UUID  # the translation_request row for this language run
    status: DocumentStatus  # always 'processing' on upload
    gcs_input_path: str  # gs://courtaccess-ai-uploads/{session_id}/{filename}
    target_language: str  # 'es' or 'pt'
    created_at: datetime
    estimated_completion_seconds: int = Field(default=300)


class TranslationStatusResponse(BaseModel):
    """
    Returned by GET /documents/{session_id}.
    Backed by a join of sessions + translation_requests.
    """

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    status: DocumentStatus  # mapped from translation_requests.status (see route)
    target_language: str  # 'es' or 'pt'
    created_at: datetime
    completed_at: datetime | None = None

    # Output — populated once DAG reaches upload_to_gcs
    signed_url: str | None = None
    signed_url_expires_at: datetime | None = None
    gcs_output_path: str | None = None

    # Metrics — populated once DAG completes
    avg_confidence_score: float | None = None
    llama_corrections_count: int = 0
    processing_time_seconds: float | None = None

    # Error state
    error_message: str | None = None


class PipelineStepResponse(BaseModel):
    """One step row from pipeline_steps — returned by GET /documents/{session_id}/steps."""

    model_config = ConfigDict(from_attributes=True)

    step_name: str
    status: str  # running | success | failed | skipped
    detail: str
    metadata: dict = Field(default_factory=dict)
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated list of document sessions for the current user."""

    items: list[TranslationStatusResponse]
    total: int
    page: int
    page_size: int


# ══════════════════════════════════════════════════════════════════════════════
# Session schemas
# ══════════════════════════════════════════════════════════════════════════════


class SessionCreateRequest(BaseModel):
    """Create a new session (realtime or document)."""

    type: SessionType
    target_language: TargetLanguage = TargetLanguage.SPANISH
    source_language: str = "en"


class SessionResponse(BaseModel):
    """Session metadata."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    user_id: uuid.UUID | None = None
    type: SessionType | None = None
    target_language: TargetLanguage | str
    source_language: str | None = None
    input_file_gcs_path: str | None = None
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None = None
    websocket_url: str | None = Field(default=None, description="WebSocket endpoint for realtime sessions")


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
# Translation Request schemas
# ══════════════════════════════════════════════════════════════════════════════


class TranslationRequestResponse(BaseModel):
    """Translation request details."""

    model_config = ConfigDict(from_attributes=True)

    request_id: uuid.UUID
    session_id: uuid.UUID
    target_language: TargetLanguage
    classification_result: ClassificationResult | None
    output_file_gcs_path: str | None
    avg_confidence_score: float | None
    pii_findings_count: int
    llama_corrections_count: int
    processing_time_seconds: float | None
    status: TranslationRequestStatus
    signed_url: str | None
    signed_url_expires_at: datetime | None
    created_at: datetime
    completed_at: datetime | None


# ══════════════════════════════════════════════════════════════════════════════
# Audit Log schemas
# ══════════════════════════════════════════════════════════════════════════════


class AuditLogResponse(BaseModel):
    """Audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    audit_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    request_id: uuid.UUID | None
    action_type: str
    details: dict[str, Any] | None
    created_at: datetime


# ══════════════════════════════════════════════════════════════════════════════
# Form catalog schemas
# ══════════════════════════════════════════════════════════════════════════════


class FormAppearanceResponse(BaseModel):
    """A single court division + section heading where this form appears."""

    model_config = ConfigDict(from_attributes=True)

    appearance_id: uuid.UUID
    form_id: uuid.UUID
    division: str
    section_heading: str


class FormVersionResponse(BaseModel):
    """One version record for a court form."""

    model_config = ConfigDict(from_attributes=True)

    version_id: uuid.UUID
    form_id: uuid.UUID
    version: int
    content_hash: str
    file_type: str
    file_path_original: str
    file_path_es: str | None
    file_path_pt: str | None
    signed_url_original: str | None = None
    signed_url_es: str | None = None
    signed_url_pt: str | None = None
    file_type_es: str | None
    file_type_pt: str | None
    created_at: datetime


class FormResponse(BaseModel):
    """A single court form from the catalog."""

    model_config = ConfigDict(from_attributes=True)

    form_id: uuid.UUID
    form_name: str
    form_slug: str
    source_url: str
    file_type: str
    status: str = Field(description="'active' or 'archived'")
    content_hash: str
    current_version: int
    needs_human_review: bool
    preprocessing_flags: list[Any] | None
    created_at: datetime
    last_scraped_at: datetime | None

    # Related data (populated via joins)
    versions: list[FormVersionResponse] = Field(default_factory=list)
    appearances: list[FormAppearanceResponse] = Field(default_factory=list)


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
