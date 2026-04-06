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
from typing import Any, Literal

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


class RoomPhase(StrEnum):
    """
    Lifecycle phase of a two-party real-time room.

    Mirrors the CHECK constraint in db/models.py RealtimeTranslationRequest:
        phase IN ('waiting', 'active', 'ended')
    """

    WAITING = "waiting"  # Room created, waiting for partner to join
    ACTIVE = "active"  # Both parties connected, session in progress
    ENDED = "ended"  # Session ended; transcript written to GCS


class TargetLanguage(StrEnum):
    """Target languages for translation (NLLB Flores-200 BCP-47 codes).

    Used by the document pipeline. The real-time speech pipeline uses short
    ISO 639-1 codes ("en", "es", "pt") via the ``partner_language`` field
    in ``SessionCreateRequest``.
    """

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

    signed_url and signed_url_expires_at are only populated when the upload
    endpoint returns a dedup hit (status=translated). They are None for new
    uploads (status=processing).
    """

    session_id: uuid.UUID  # polling key — use for GET /documents/{session_id}
    request_id: uuid.UUID  # the translation_request row for this language run
    status: DocumentStatus  # 'processing' for new uploads; 'translated' for dedup hits
    gcs_input_path: str  # gs://courtaccess-ai-uploads/{session_id}/{filename}
    target_language: str  # 'es' or 'pt'
    created_at: datetime
    estimated_completion_seconds: int = Field(default=300)

    # Populated only for dedup hits — None for normal new uploads
    signed_url: str | None = None
    signed_url_expires_at: datetime | None = None


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

    # Real-time session fields
    partner_language: str | None = Field(default=None, description="Partner's spoken language code: en, es, or pt")
    court_division: str | None = Field(default=None, description="Court division name, e.g. 'Boston Municipal Court'")
    courtroom: str | None = Field(default=None, description="Courtroom identifier, e.g. 'Courtroom 3'")
    case_docket: str | None = Field(default=None, description="Optional case docket number for session metadata")


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
    room_id: str | None = Field(default=None, description="Short room code for two-party realtime sessions")


class RoomCreateRequest(BaseModel):
    """
    Create a two-party real-time interpretation room.

    Submitted by a court_official or admin via POST /api/sessions/rooms.
    The creator is always the English speaker; the partner is the LEP individual.
    """

    target_language: Literal["es", "pt"] = Field(
        description=(
            "ISO 639-1 code for the LEP partner's spoken language. "
            "The court official is assumed to speak English. "
            "Allowed values: 'es' (Spanish), 'pt' (Portuguese)."
        ),
    )
    court_division: str | None = Field(
        default=None,
        max_length=100,
        description="Court division name, e.g. 'Boston Municipal Court'.",
    )
    courtroom: str | None = Field(
        default=None,
        max_length=50,
        description="Courtroom identifier, e.g. 'Courtroom 3'.",
    )
    case_docket: str | None = Field(
        default=None,
        max_length=50,
        description="Optional case docket number for session metadata and audit trail.",
    )
    partner_name: str = Field(
        max_length=100,
        description="LEP individual's display name, typed by the court official at setup.",
    )
    consent_acknowledged: bool = Field(
        description=(
            "Must be true. Court official confirms that both parties have been informed "
            "that the session will be interpreted and recorded."
        ),
    )


class RoomCreateResponse(BaseModel):
    """Returned after a conversation room is successfully created."""

    session_id: uuid.UUID = Field(description="UUID of the newly created Session row.")
    rt_request_id: uuid.UUID = Field(description="UUID of the RealtimeTranslationRequest row.")
    room_code: str = Field(
        description=(
            "Short alphanumeric join code (up to 8 characters) to share with the LEP partner. "
            "Valid until room_code_expires_at or until the session moves to 'active'."
        ),
    )
    room_code_expires_at: datetime = Field(
        description="UTC timestamp after which the room_code is no longer valid (30 minutes from creation).",
    )
    join_url: str = Field(
        description="Full URL the court official can share with the LEP partner to join the session.",
    )


class RoomJoinRequest(BaseModel):
    """
    Join an existing room using its room code.

    Submitted by the LEP partner (guest) via POST /api/sessions/rooms/join.
    No authentication required — the room_code is the credential.
    """

    room_code: str = Field(
        max_length=8,
        pattern=r"^[A-Z0-9]{4,8}$",
        description="Alphanumeric room code shared by the court official.",
    )
    partner_name: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "Optional display name override. If omitted, the name the court official entered at room creation is used."
        ),
    )


class RoomJoinResponse(BaseModel):
    """Returned after a guest successfully joins a room."""

    session_id: uuid.UUID = Field(description="UUID of the Session to connect to via WebSocket.")
    rt_request_id: uuid.UUID = Field(description="UUID of the RealtimeTranslationRequest row.")
    room_token: str = Field(
        description=(
            "Short-lived JWT (4-hour expiry) signed by the app. "
            "Pass as ?token=<room_token> when opening the WebSocket connection."
        ),
    )
    partner_name: str = Field(description="Display name that will appear in the transcript UI.")
    target_language: Language = Field(
        description="ISO 639-1 code of the LEP partner's spoken language (the language being interpreted).",
    )
    court_division: str | None = Field(default=None, description="Court division, for display in the session UI.")
    courtroom: str | None = Field(default=None, description="Courtroom identifier, for display in the session UI.")


class RoomStatusResponse(BaseModel):
    """Current status of a real-time room — returned by GET /api/sessions/rooms/{session_id}."""

    phase: RoomPhase = Field(description="Current lifecycle phase: 'waiting', 'active', or 'ended'.")
    room_code: str = Field(description="The alphanumeric join code (empty string once phase is 'active' or 'ended').")
    room_code_expires_at: datetime = Field(description="UTC expiry of the room_code.")
    partner_joined_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the LEP partner joined. None until they connect.",
    )


class RoomPreviewResponse(BaseModel):
    """
    Public room info for the guest join page — no auth required.

    Returned by GET /sessions/rooms/{code}/preview.
    Does NOT expose session_id, creator identity, or audit data.
    """

    phase: RoomPhase = Field(description="Current phase: 'waiting', 'active', or 'ended'.")
    target_language: Language = Field(description="LEP partner's spoken language (ISO 639-1).")
    court_division: str | None = Field(default=None, description="Court division name.")
    courtroom: str | None = Field(default=None, description="Courtroom identifier.")
    partner_name: str = Field(description="Display name pre-filled for the LEP individual.")
    room_code_expires_at: datetime = Field(description="UTC expiry of the room code.")


class RoomListResponse(BaseModel):
    """Summary of an active conversation room — returned by GET /sessions/rooms."""

    room_id: str = Field(description="6-character alphanumeric room code")
    language_a: str = Field(description="Creator's spoken language code: en, es, or pt")
    language_b: str = Field(description="Partner's spoken language code: en, es, or pt")
    participants: int = Field(description="Number of currently connected participants (0, 1, or 2)")
    is_full: bool = Field(description="True when both participant slots are occupied")
    created_at: datetime = Field(description="UTC timestamp when the room was created")


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
