"""
api/routes/realtime.py

WebSocket and REST endpoints for real-time interpretation sessions.

REST endpoints:
  POST   /sessions/              — Create a session record, get WebSocket URL
  POST   /sessions/rooms         — Create a DB-persisted room + room code (court_official/admin)
  POST   /sessions/rooms/join                   — Join a room via room code (no auth required)
  GET    /sessions/rooms/{room_code}/status    — Poll room phase (creator only)
  POST   /sessions/rooms/{session_id}/end     — End a DB-persisted room session (creator only)
  GET    /sessions/rooms                       — List active in-memory conversation rooms
  GET    /sessions/{session_id}  — Get session metadata
  POST   /sessions/{session_id}/end — End a session

WebSocket endpoint:
  WS     /sessions/{session_id}/ws — Full bidirectional speech pipeline

WebSocket query params (connection setup):
  Create room:  my_lang=en  partner_lang=es  name=Alice
  Join room:    room_id=ABCDEF               name=Bob

Binary control markers (4 bytes, client → server):
  STRT — session_start (creator only)
  ENDS — session_end   (creator only)
  MUTE — mic muted
  UNMT — mic unmuted

Server → client JSON frames:
  room_created / room_joined / partner_joined / partner_left
  session_status  (waiting | ready | active | ended)
  transcript / transcript_partial
  mic_locked / partner_muted / partner_unmuted
  session_artifacts
  error

Server → client binary frames:
  WAV audio bytes (TTS of partner's translated speech)
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import wave
from datetime import UTC, datetime, timedelta
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from api.auth import WebSocketUser, create_room_token, get_websocket_user, verify_firebase_token
from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import (
    ROLE_ID_TO_NAME,
    Language,
    RoomCreateRequest,
    RoomCreateResponse,
    RoomJoinRequest,
    RoomJoinResponse,
    RoomPreviewResponse,
    RoomStatusResponse,
    SessionCreateRequest,
    SessionResponse,
    SessionStatus,
    UserRole,
)
from courtaccess.core import gcs
from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger
from courtaccess.speech.session import (
    VAD_SAMPLE_RATE,
    AudioSession,
    ConversationRoom,
    Participant,
    _generate_room_id,
)
from courtaccess.speech.session_recorder import (
    SESSIONS_DIR,
    SessionRecorder,
    TranscriptLogger,
    upload_wav_tracks,
    write_manifest,
)

# Roles permitted to create/join real-time rooms via WebSocket.
_ALLOWED_WS_ROLES = {UserRole.COURT_OFFICIAL, UserRole.INTERPRETER, UserRole.ADMIN}

# Maps ISO 639-1 short codes (used by RoomCreateRequest) to NLLB Flores-200
# codes stored in sessions.target_language. English is excluded — the court
# official always speaks English; only the partner's language is stored here.
_LANG_TO_NLLB: dict[str, str] = {
    Language.SPANISH: "spa_Latn",
    Language.PORTUGUESE: "por_Latn",
}
# Reverse mapping — used when reading sessions.target_language back for responses.
_NLLB_TO_LANG: dict[str, Language] = {v: k for k, v in _LANG_TO_NLLB.items()}  # type: ignore[misc]

# Optional bearer extractor for endpoints that accept auth but don't require it.
# auto_error=False means missing/malformed Authorization header → None (not 401).
_optional_bearer = HTTPBearer(auto_error=False)

# Roles allowed to view/end any session (not just their own).
# Ownership semantics apply: owners can always act on their own session.
_ROLES_CAN_VIEW_ANY_SESSION = {UserRole.COURT_OFFICIAL, UserRole.ADMIN}

logger = get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["realtime"])

# ── In-memory registries ──────────────────────────────────────────────────────
_sessions: dict[str, dict] = {}
conversation_rooms: dict[str, ConversationRoom] = {}

# ── Control markers (client → server, 4 bytes each) ──────────────────────────
_MARKER_START = b"STRT"
_MARKER_END = b"ENDS"
_MARKER_MUTE = b"MUTE"
_MARKER_UNMUT = b"UNMT"

_VALID_LANGS = {"en", "es", "pt"}


# ══════════════════════════════════════════════════════════════════════════════
# Startup helper (called from api/main.py lifespan)
# ══════════════════════════════════════════════════════════════════════════════


def startup_speech_models() -> None:
    """
    Pre-load speech models into memory.

    Gated behind USE_REAL_SPEECH=true.  When false (default), the API
    starts without loading VAD/ASR/MT/TTS models so local dev is fast.
    Call this from the FastAPI lifespan after DB init.
    """
    from courtaccess.core.config import get_settings

    if not get_settings().use_real_speech:
        logger.info("USE_REAL_SPEECH=false — speech models not loaded")
        return

    from courtaccess.speech.legal_verifier import get_legal_verifier
    from courtaccess.speech.mt_service import get_mt_service
    from courtaccess.speech.transcribe import get_asr_service
    from courtaccess.speech.tts import get_tts_service
    from courtaccess.speech.vad import get_vad_service

    logger.info("Loading VAD model (Silero)...")
    get_vad_service()
    logger.info("VAD model ready")

    logger.info("Loading ASR model (Faster-Whisper)...")
    get_asr_service()
    logger.info("ASR model ready")

    logger.info("Loading MT model (NLLB-200)...")
    get_mt_service()
    logger.info("MT model ready")

    logger.info("Loading TTS voices (Piper)...")
    get_tts_service()
    logger.info("TTS voices ready")

    verifier = get_legal_verifier()
    if verifier:
        logger.info("Legal verifier ready (LLaMA 4 via Vertex AI)")
    else:
        logger.info("Legal verifier disabled (VERTEX_PROJECT_ID not set)")


# ══════════════════════════════════════════════════════════════════════════════
# REST endpoints
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a real-time interpretation session",
)
async def create_session(
    body: SessionCreateRequest,
    user: Annotated[CurrentUser, Depends(require_role("court_official", "admin"))],
    db: DBSession,
) -> SessionResponse:
    """Create a session record and return a WebSocket URL."""
    session_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    _sessions[str(session_id)] = {
        "session_id": session_id,
        "user_id": user.user_id,
        "status": SessionStatus.ACTIVE,
        "created_at": now,
        "target_language": body.target_language,
        "source_language": body.source_language,
    }

    logger.info(
        "Session created: session_id=%s user_id=%s target=%s",
        session_id,
        user.user_id,
        body.target_language,
    )

    return SessionResponse(
        session_id=session_id,
        websocket_url=f"/sessions/{session_id}/ws",
        status=SessionStatus.ACTIVE,
        created_at=now,
        target_language=body.target_language,
        source_language=body.source_language,
    )


@router.post(
    "/rooms",
    response_model=RoomCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a real-time interpretation room",
    description=(
        "Creates a Session row and a RealtimeTranslationRequest row, generates a "
        "collision-safe 6-character room code, and returns a join URL for the LEP partner. "
        "Requires court_official or admin role. consent_acknowledged must be true."
    ),
)
async def create_room(
    body: RoomCreateRequest,
    user: Annotated[CurrentUser, Depends(require_role("court_official", "admin"))],
    db: DBSession,
) -> RoomCreateResponse:
    """
    Full flow:
      1. Validate consent_acknowledged = True.
      2. Generate collision-safe room code (up to 10 attempts against DB).
      3. Create Session row (type='realtime', target_language=NLLB code).
      4. Create RealtimeTranslationRequest row (phase='waiting').
      5. Write audit log (transactional with the above).
      6. Commit all three in a single transaction.
      7. Return RoomCreateResponse with room code + join URL.
    """
    from db.models import RealtimeTranslationRequest
    from db.models import Session as SessionModel
    from db.queries.audit import write_audit

    # ── 1. Consent gate ───────────────────────────────────────────────────────
    if not body.consent_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="consent_acknowledged must be true before creating a room.",
        )

    # ── 2. Language validation ────────────────────────────────────────────────
    # English is not a valid partner language — the court official always speaks English.
    nllb_code = _LANG_TO_NLLB.get(body.target_language)
    if nllb_code is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target_language '{body.target_language}' is not supported. Use 'es' or 'pt'.",
        )

    # ── 3. Collision-safe room code (max 10 attempts) ─────────────────────────
    # _generate_room_id() draws from a 31-char alphabet — collision probability
    # is ~1/31^6 ≈ 1 in 887M. Retrying 10 times is purely defensive.
    room_code: str | None = None
    for _ in range(10):
        candidate = _generate_room_id()
        result = await db.execute(
            select(RealtimeTranslationRequest.room_code).where(RealtimeTranslationRequest.room_code == candidate)
        )
        if result.scalar_one_or_none() is None:
            room_code = candidate
            break
    if room_code is None:
        # Practically impossible, but surface a clear error rather than crashing.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to allocate a unique room code. Please try again.",
        )

    # ── 4. Timestamps ─────────────────────────────────────────────────────────
    now = datetime.now(tz=UTC)
    room_code_expires_at = now + timedelta(minutes=30)

    # ── 5. Create Session row ─────────────────────────────────────────────────
    session_id = uuid.uuid4()
    session = SessionModel(
        session_id=session_id,
        user_id=user.user_id,
        type="realtime",
        target_language=nllb_code,
        status="active",
        created_at=now,
    )
    db.add(session)

    # ── 6. Create RealtimeTranslationRequest row ──────────────────────────────
    rt_request_id = uuid.uuid4()
    rt_request = RealtimeTranslationRequest(
        rt_request_id=rt_request_id,
        session_id=session_id,
        room_code=room_code,
        room_code_expires_at=room_code_expires_at,
        court_division=body.court_division,
        courtroom=body.courtroom,
        case_docket=body.case_docket,
        consent_acknowledged=True,
        creator_user_id=user.user_id,
        partner_name=body.partner_name,
        phase="waiting",
        created_at=now,
    )
    db.add(rt_request)

    # ── 7. Audit log (transactional — committed below with session + rt_request) ──
    await write_audit(
        db,
        user_id=user.user_id,
        action_type="realtime_room_created",
        session_id=session_id,
        rt_request_id=rt_request_id,
        details={
            "room_code": room_code,
            "target_language": body.target_language,
            "court_division": body.court_division,
            "courtroom": body.courtroom,
            "case_docket": body.case_docket,
            "partner_name": body.partner_name,
        },
    )

    await db.commit()

    logger.info(
        "Room created: session_id=%s rt_request_id=%s room_code=%s user_id=%s target=%s",
        session_id,
        rt_request_id,
        room_code,
        user.user_id,
        body.target_language,
    )

    # Pre-populate the in-memory room so the creator can connect to the WS
    # using room_id=<room_code> and the guest can join the same room object.
    # language_a is always "en" (court official); language_b is the LEP language.
    in_mem_room = ConversationRoom(
        room_id=room_code,
        language_a="en",
        language_b=body.target_language,  # Language StrEnum value ("es" / "pt")
    )
    in_mem_room.db_session_id = session_id
    in_mem_room.db_rt_request_id = rt_request_id
    conversation_rooms[room_code] = in_mem_room

    # Dynamically determine the frontend base URL from CORS allowed origins
    settings = get_settings()
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    # Use the first configure origin, or fallback to localhost for dev
    base_url = origins[0] if origins else "http://localhost:5173"

    return RoomCreateResponse(
        session_id=session_id,
        rt_request_id=rt_request_id,
        room_code=room_code,
        room_code_expires_at=room_code_expires_at,
        join_url=f"{base_url}/join/{room_code}",
    )


@router.post(
    "/rooms/join",
    response_model=RoomJoinResponse,
    status_code=status.HTTP_200_OK,
    summary="Join a real-time room via room code",
    description=(
        "No authentication required — the room code is the credential. "
        "Optionally accepts a Firebase Bearer token to record the partner's user_id. "
        "Returns a short-lived room JWT the partner uses to open the WebSocket."
    ),
)
async def join_room(
    body: RoomJoinRequest,
    db: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
) -> RoomJoinResponse:
    """
    Full flow:
      1. Look up RealtimeTranslationRequest by room_code.
      2. Validate: exists (404), phase=='waiting' (409), not expired (410).
      3. Optionally resolve Firebase token → partner_user_id.
      4. Resolve partner_name: body override > pre-filled by court official.
      5. Update rt_request: phase='active', partner_joined_at, partner_user_id.
      6. Update parent Session: status='active' (explicit, idempotent).
      7. Write audit log (realtime_room_joined), commit all in one transaction.
      8. Issue room JWT via create_room_token().
      9. Return RoomJoinResponse with JWT + session context.
    """
    from db.models import RealtimeTranslationRequest
    from db.models import Session as SessionModel
    from db.queries.audit import write_audit

    now = datetime.now(tz=UTC)

    # ── 1. Look up room by code ───────────────────────────────────────────────
    result = await db.execute(
        select(RealtimeTranslationRequest).where(RealtimeTranslationRequest.room_code == body.room_code)
    )
    rt_request = result.scalar_one_or_none()

    if rt_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room code not found.")

    # ── 2. Validate phase and expiry ──────────────────────────────────────────
    if rt_request.phase != "waiting":
        # 409 covers both 'active' (already joined) and 'ended' (session over)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Room is not available for joining (phase='{rt_request.phase}').",
        )
    if rt_request.room_code_expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Room code has expired. Ask the court official to create a new room.",
        )

    # ── 3. Optional Firebase auth → partner_user_id ───────────────────────────
    partner_user_id = None
    audit_user_id = rt_request.creator_user_id  # default to creator for guest joins

    if credentials is not None:
        try:
            claims = verify_firebase_token(credentials.credentials)
            firebase_uid: str = claims["uid"]

            from db.models import User

            user_result = await db.execute(select(User.user_id).where(User.firebase_uid == firebase_uid))
            partner_user_id = user_result.scalar_one_or_none()
            if partner_user_id is not None:
                audit_user_id = partner_user_id
        except HTTPException:
            # Invalid or expired Firebase token — treat as guest, don't block join.
            logger.warning("Firebase token provided for room join was invalid — proceeding as guest.")

    # ── 4. Resolve partner_name ───────────────────────────────────────────────
    # Priority: explicit body override > what the court official pre-filled.
    partner_name: str = (
        body.partner_name.strip()
        if body.partner_name and body.partner_name.strip()
        else (rt_request.partner_name or "Guest")
    )

    # ── 5 & 6. Update rt_request + Session in one transaction ─────────────────
    rt_request.phase = "active"
    rt_request.partner_joined_at = now
    rt_request.partner_name = partner_name
    if partner_user_id is not None:
        rt_request.partner_user_id = partner_user_id

    session_result = await db.execute(select(SessionModel).where(SessionModel.session_id == rt_request.session_id))
    session = session_result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session record missing.")
    session.status = "active"

    # ── 7. Audit log ──────────────────────────────────────────────────────────
    await write_audit(
        db,
        user_id=audit_user_id,
        action_type="realtime_room_joined",
        session_id=rt_request.session_id,
        rt_request_id=rt_request.rt_request_id,
        details={
            "room_code": body.room_code,
            "partner_name": partner_name,
            "is_guest": partner_user_id is None,
            "partner_user_id": str(partner_user_id) if partner_user_id else None,
        },
    )

    await db.commit()

    logger.info(
        "Room joined: session_id=%s rt_request_id=%s partner_name=%s is_guest=%s",
        rt_request.session_id,
        rt_request.rt_request_id,
        partner_name,
        partner_user_id is None,
    )

    # ── 8. Issue room JWT ─────────────────────────────────────────────────────
    room_token = create_room_token(
        session_id=rt_request.session_id,
        rt_request_id=rt_request.rt_request_id,
        partner_name=partner_name,
    )

    # ── 9. Build response (map NLLB code back to ISO 639-1) ───────────────────
    target_language = _NLLB_TO_LANG.get(session.target_language, Language.SPANISH)

    return RoomJoinResponse(
        session_id=rt_request.session_id,
        rt_request_id=rt_request.rt_request_id,
        room_token=room_token,
        partner_name=partner_name,
        target_language=target_language,
        court_division=rt_request.court_division,
        courtroom=rt_request.courtroom,
    )


@router.get(
    "/rooms/{room_code}/preview",
    response_model=RoomPreviewResponse,
    summary="Public room preview for the guest join page",
    description=(
        "No authentication required. Returns safe display fields (language, court info, "
        "partner name pre-fill, expiry) for the LEP individual to see before deciding to join. "
        "Does not expose session_id, creator identity, or any audit data."
    ),
)
async def get_room_preview(
    room_code: str,
    db: DBSession,
) -> RoomPreviewResponse:
    """Return public-safe room details by room code."""
    from db.models import RealtimeTranslationRequest
    from db.models import Session as SessionModel

    result = await db.execute(
        select(RealtimeTranslationRequest).where(RealtimeTranslationRequest.room_code == room_code.upper())
    )
    rt_request = result.scalar_one_or_none()
    if rt_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found.")

    session_result = await db.execute(select(SessionModel).where(SessionModel.session_id == rt_request.session_id))
    session = session_result.scalar_one_or_none()
    target_language = _NLLB_TO_LANG.get(session.target_language, Language.SPANISH) if session else Language.SPANISH

    return RoomPreviewResponse(
        phase=rt_request.phase,
        target_language=target_language,
        court_division=rt_request.court_division,
        courtroom=rt_request.courtroom,
        partner_name=rt_request.partner_name or "Guest",
        room_code_expires_at=rt_request.room_code_expires_at,
    )


@router.get(
    "/rooms/{room_code}/status",
    response_model=RoomStatusResponse,
    summary="Poll room phase (creator only)",
    description=(
        "Returns the current phase, code expiry, and partner join timestamp for a room. "
        "Intended for the court official's lobby screen to detect when the guest has joined. "
        "Only the room creator (or admin) may poll. Returns 404 if room_code is unknown."
    ),
)
async def get_room_status(
    room_code: str,
    user: Annotated[CurrentUser, Depends(require_role("court_official", "admin"))],
    db: DBSession,
) -> RoomStatusResponse:
    """
    Ownership-checked room status poll.

    The room_code path param is normalised to uppercase before the DB lookup
    so callers don't need to worry about case.
    """
    from db.models import RealtimeTranslationRequest

    result = await db.execute(
        select(RealtimeTranslationRequest).where(RealtimeTranslationRequest.room_code == room_code.upper())
    )
    rt_request = result.scalar_one_or_none()

    if rt_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room code not found.")

    # Only the creator or an admin may poll this room's status.
    user_role = ROLE_ID_TO_NAME.get(user.role_id, UserRole.PUBLIC)
    if rt_request.creator_user_id != user.user_id and user_role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return RoomStatusResponse(
        phase=rt_request.phase,
        room_code=rt_request.room_code,
        room_code_expires_at=rt_request.room_code_expires_at,
        partner_joined_at=rt_request.partner_joined_at,
    )


@router.post(
    "/rooms/{session_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End a real-time room session",
    description=(
        "Marks the session as ended in both the RealtimeTranslationRequest and Session rows. "
        "Only the room creator (or admin) may call this. Idempotent: returns 204 if already ended. "
        "Transcript upload is triggered here (Phase 3.4)."
    ),
)
async def end_room(
    session_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(require_role("court_official", "admin"))],
    db: DBSession,
) -> None:
    """
    Flow:
      1. Load RealtimeTranslationRequest by session_id.
      2. Ownership check: creator_user_id == user.user_id or admin.
      3. Idempotency guard: if phase already 'ended', return 204.
      4. Update rt_request: phase='ended', completed_at=now().
      5. Update Session: status='completed', completed_at=now().
      6. TODO Phase 3.4 — trigger GCS transcript upload for in-memory room.
      7. Write audit log, commit all in one transaction.
    """
    from db.models import RealtimeTranslationRequest
    from db.models import Session as SessionModel
    from db.queries.audit import write_audit

    now = datetime.now(tz=UTC)

    # ── 1. Load rt_request by session_id ─────────────────────────────────────
    rt_result = await db.execute(
        select(RealtimeTranslationRequest).where(RealtimeTranslationRequest.session_id == session_id)
    )
    rt_request = rt_result.scalar_one_or_none()

    if rt_request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found.")

    # ── 2. Ownership check ────────────────────────────────────────────────────
    user_role = ROLE_ID_TO_NAME.get(user.role_id, UserRole.PUBLIC)
    if rt_request.creator_user_id != user.user_id and user_role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # ── 3. Idempotency guard ──────────────────────────────────────────────────
    if rt_request.phase == "ended":
        return  # already ended — 204 with no DB writes

    # ── 4. Update RealtimeTranslationRequest ──────────────────────────────────
    rt_request.phase = "ended"
    rt_request.completed_at = now

    # ── 5. Update parent Session ──────────────────────────────────────────────
    session_result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    session = session_result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Session record missing.")
    session.status = SessionStatus.COMPLETED
    session.completed_at = now

    # ── 6. Phase 3.4 — GCS transcript upload ──────────────────────────────────
    room = conversation_rooms.get(str(session_id))
    if room and room.transcript_logger is not None:
        import asyncio
        import json

        from courtaccess.core import gcs
        from courtaccess.core.config import get_settings
        from courtaccess.speech.session_recorder import SESSIONS_DIR

        session_dir = SESSIONS_DIR / (room.session_name or str(session_id))

        # Finalize audio and transcript locally
        if room.recorder:
            try:
                room.recorder.finalize(session_dir)
            except Exception as e:
                logger.warning("Room %s: recording finalize failed: %s", session_id, e)
        try:
            room.transcript_logger.finalize(session_dir)
        except Exception as e:
            logger.warning("Room %s: transcript finalize failed: %s", session_id, e)

        settings = get_settings()
        bucket = settings.gcs_bucket_transcripts
        blob_name = f"{session_id}/transcript.json"

        payload = room.transcript_logger.serialize(
            session_id=str(session_id),
            start_time=room.session_start_time,
            end_time=now,
        )
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:
            await asyncio.to_thread(
                gcs.upload_bytes,
                bucket,
                blob_name,
                payload_bytes,
                "application/json",
                correlation_id=str(session_id),
            )
            rt_request.transcript_gcs_path = gcs.gcs_uri(bucket, blob_name)

            _7d = 7 * 24 * 3600
            signed_url = await asyncio.to_thread(
                gcs.generate_signed_url,
                bucket,
                blob_name,
                _7d,
                settings.gcp_service_account_json,
                correlation_id=str(session_id),
            )
            rt_request.transcript_signed_url = signed_url
            rt_request.transcript_signed_url_expires_at = now + timedelta(seconds=_7d)
        except Exception as exc:
            logger.warning("Room %s: end_room transcript GCS upload failed: %s", session_id, exc)

        rt_request.total_utterances = room.transcript_logger.entry_count
        if room.session_start_time:
            rt_request.duration_seconds = round((now - room.session_start_time).total_seconds(), 2)

        # Prevent double-upload if WebSocket subsequently disconnects
        room.artifacts_uploaded = True
        room.session_active = False

        # Notify participants
        for p in room.participants:
            if p.ws_open:
                await p.send_json_safe({"type": "session_status", "status": "ended"})

    # ── 7. Audit log + commit ─────────────────────────────────────────────────
    await write_audit(
        db,
        user_id=user.user_id,
        action_type="realtime_room_ended",
        session_id=session_id,
        rt_request_id=rt_request.rt_request_id,
        details={
            "ended_by": str(user.user_id),
            "phase_before": "active",  # can only reach here when phase was 'waiting' or 'active'
        },
    )

    await db.commit()

    logger.info(
        "Room ended: session_id=%s rt_request_id=%s ended_by=%s",
        session_id,
        rt_request.rt_request_id,
        user.user_id,
    )


@router.get(
    "/rooms",
    summary="List active conversation rooms",
)
async def list_rooms(
    _user: Annotated[CurrentUser, Depends(require_role("court_official", "admin"))],
) -> dict:
    """Return all active in-memory ConversationRooms (lobby view)."""
    return {
        "rooms": [
            {
                "room_id": r.room_id,
                "language_a": r.language_a,
                "language_b": r.language_b,
                "participants": [{"name": p.name, "language": p.language, "role": p.role} for p in r.participants],
                "is_full": r.is_full,
                "session_active": r.session_active,
                "created_at": r.created_at.isoformat(),
            }
            for r in conversation_rooms.values()
        ]
    }


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session status",
)
async def get_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> SessionResponse:
    sid = str(session_id)
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    # Resolve role via ROLE_ID_TO_NAME — single source of truth from schemas.
    user_role = ROLE_ID_TO_NAME.get(user.role_id, UserRole.PUBLIC)
    # Admin and court_official may view any session; others may only view their own.
    if session["user_id"] != user.user_id and user_role not in _ROLES_CAN_VIEW_ANY_SESSION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return SessionResponse(
        session_id=session["session_id"],
        websocket_url=f"/sessions/{session_id}/ws",
        status=session["status"],
        created_at=session["created_at"],
        target_language=session["target_language"],
        source_language=session["source_language"],
    )


@router.post(
    "/{session_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End an active session",
)
async def end_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> None:
    sid = str(session_id)
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    # Resolve role via ROLE_ID_TO_NAME — single source of truth from schemas.
    user_role = ROLE_ID_TO_NAME.get(user.role_id, UserRole.PUBLIC)
    if session["user_id"] != user.user_id and user_role != UserRole.ADMIN:  # admin may end any session
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if session["status"] == SessionStatus.ENDED:
        return
    _sessions[sid]["status"] = SessionStatus.ENDED
    logger.info("Session ended: session_id=%s user_id=%s", session_id, user.user_id)


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket endpoint — full speech pipeline
# ══════════════════════════════════════════════════════════════════════════════


@router.websocket("/ws")
async def session_websocket(
    websocket: WebSocket,
) -> None:
    """
    Bidirectional real-time speech interpretation WebSocket.

    Use query params to create or join a conversation room.
    Requires ?token=<Firebase ID token> for authentication.
    """
    # ── Accept first (ASGI requirement) ──────────────────────────────────
    # The ASGI spec does not allow sending websocket.close before
    # websocket.accept — uvicorn maps that to an HTTP 403 Forbidden,
    # which is misleading.  Accept the handshake, then authenticate.
    await websocket.accept()

    # ── Authenticate ─────────────────────────────────────────────────────
    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_json({"type": "error", "message": "Missing authentication token"})
        await websocket.close(code=4001, reason="Missing authentication token")
        return
    try:
        from db.database import AsyncSessionLocal

        async with AsyncSessionLocal() as _auth_db:
            ws_user: WebSocketUser = await get_websocket_user(token, _auth_db)
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "message": str(exc.detail)})
        await websocket.close(code=4001, reason=str(exc.detail))
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # ── Authorise — guests are always public-scoped; only privileged roles may connect ─
    if not ws_user.is_guest and ws_user.role not in _ALLOWED_WS_ROLES:
        reason = "Insufficient role"
        await websocket.send_json({"type": "error", "message": reason})
        await websocket.close(code=4003, reason=reason)
        return

    caller_uid: str = ws_user.firebase_uid or str(ws_user.session_id or "guest")

    # ── Lazy-import services (only available when USE_REAL_SPEECH=true) ───
    try:
        from courtaccess.speech.legal_verifier import get_legal_verifier
        from courtaccess.speech.mt_service import get_mt_service
        from courtaccess.speech.transcribe import get_asr_service
        from courtaccess.speech.tts import get_tts_service

        asr_service = get_asr_service()
        mt_service = get_mt_service()
        tts_service = get_tts_service()
        legal_verifier = get_legal_verifier()
    except Exception as exc:
        logger.warning("Speech services unavailable (%s) — closing WebSocket", exc)
        await websocket.send_json({"type": "error", "message": "Speech pipeline not available"})
        await websocket.close()
        return

    # ── Parse query params ────────────────────────────────────────────────
    room_id_param = (websocket.query_params.get("room_id") or "").strip().upper()
    user_name = websocket.query_params.get("name", "User").strip() or "User"

    # ── Create or join room ───────────────────────────────────────────────
    if room_id_param:
        # Joining an existing room
        room = conversation_rooms.get(room_id_param)
        if room is None:
            await websocket.send_json({"type": "error", "message": f"Room {room_id_param} not found"})
            await websocket.close()
            return
        if room.is_full:
            await websocket.send_json({"type": "error", "message": f"Room {room_id_param} is full"})
            await websocket.close()
            return
        room_id = room_id_param
        user_lang = room.language_b
    else:
        # Creating a new room
        my_lang = (websocket.query_params.get("my_lang") or "en").strip().lower()
        partner_lang = (websocket.query_params.get("partner_lang") or "es").strip().lower()
        if my_lang not in _VALID_LANGS:
            my_lang = "en"
        if partner_lang not in _VALID_LANGS:
            partner_lang = "es"

        room_id = _generate_room_id()
        # Ensure uniqueness against existing rooms
        while room_id in conversation_rooms:
            room_id = _generate_room_id()

        room = ConversationRoom(room_id, language_a=my_lang, language_b=partner_lang)
        room.owner_uid = caller_uid  # record who created this room
        conversation_rooms[room_id] = room
        user_lang = my_lang

    # ── Create participant (only reached after successful auth + role check) ──
    conn_ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    audio_session = AudioSession(conn_ts, language=user_lang)
    role = "a" if len(room.participants) == 0 else "b"
    participant = Participant(websocket, user_name, user_lang, audio_session, role=role)
    room.add_participant(participant)

    # ── Notify participants ───────────────────────────────────────────────
    if len(room.participants) == 1:
        await participant.send_json_safe(
            {
                "type": "room_created",
                "room_id": room_id,
                "user_name": user_name,
                "language": user_lang,
                "partner_language": room.language_b,
            }
        )
        await participant.send_json_safe({"type": "session_status", "status": "waiting"})
        logger.info("Room %s created by %s (%s ↔ %s)", room_id, user_name, room.language_a, room.language_b)
    else:
        partner = room.get_partner(participant)
        await participant.send_json_safe(
            {
                "type": "room_joined",
                "room_id": room_id,
                "user_name": user_name,
                "language": user_lang,
                "partner_name": partner.name if partner else None,
                "partner_language": partner.language if partner else None,
            }
        )
        if partner:
            await partner.send_json_safe({"type": "partner_joined", "name": user_name, "language": user_lang})
        for p in room.participants:
            if p.ws_open:
                await p.send_json_safe({"type": "session_status", "status": "ready"})
        logger.info("Room %s: %s joined as %s", room_id, user_name, user_lang)

    turn = room.turn
    background_tasks: list[asyncio.Task] = []
    partial_task: asyncio.Task | None = None
    utterance_id = 0

    # ── Helpers ───────────────────────────────────────────────────────────

    def _wav_duration_ms(wav_bytes: bytes) -> float:
        try:
            buf = io.BytesIO(wav_bytes)
            with wave.open(buf, "rb") as wf:
                return (wf.getnframes() / wf.getframerate()) * 1000.0
        except Exception:
            return 2000.0

    # ── ASR → MT → Legal → TTS pipeline ──────────────────────────────────

    async def _process_speech(
        pcm: np.ndarray,
        msg_type: str,
        utt_id: int,
        duration: float | None = None,
    ) -> None:
        try:
            text, used_lang = await asyncio.to_thread(asr_service.transcribe, pcm, user_lang)

            # Discard stale partials
            if msg_type == "transcript_partial" and utt_id != utterance_id:
                return
            if not text:
                return

            source_lang = used_lang or user_lang

            # Transcript-log tracking — populated in the pipeline below
            _log_target_lang: str = user_lang
            _log_translated: str | None = None
            _log_legal_verified: bool = False
            _log_legal_correction: bool = False

            self_payload: dict = {
                "type": msg_type,
                "speaker": "self",
                "text": text,
                "language": source_lang,
            }
            if duration is not None:
                self_payload["duration"] = round(duration, 2)

            current_partner = room.get_partner(participant)
            partner_payload: dict | None = None
            tts_wav: bytes = b""

            if current_partner and current_partner.ws_open:
                target_lang = current_partner.language
                _log_target_lang = target_lang

                if source_lang != target_lang and source_lang != "unknown":
                    translated = await asyncio.to_thread(
                        mt_service.translate,
                        text,
                        source_lang,
                        target_lang,
                    )
                    if translated:
                        _log_translated = translated
                        self_payload["translation"] = translated
                        self_payload["target_language"] = target_lang

                        partner_payload = {
                            "type": msg_type,
                            "speaker": "partner",
                            "speaker_name": user_name,
                            "text": text,
                            "language": source_lang,
                            "translation": translated,
                            "target_language": target_lang,
                        }
                        if duration is not None:
                            partner_payload["duration"] = round(duration, 2)

                        # Legal verification (final transcripts only)
                        if (
                            msg_type == "transcript"
                            and legal_verifier is not None
                            and source_lang in _VALID_LANGS
                            and target_lang in _VALID_LANGS
                        ):
                            verification = await asyncio.to_thread(
                                legal_verifier.verify,
                                text,
                                translated,
                                source_lang,
                                target_lang,
                            )
                            for _p in (self_payload, partner_payload):
                                _p["verified_translation"] = verification.verified_translation
                                _p["accuracy_score"] = verification.accuracy_score
                                _p["accuracy_note"] = verification.accuracy_note
                                _p["used_fallback"] = verification.used_fallback
                            _log_legal_verified = not verification.used_fallback
                            _log_legal_correction = verification.verified_translation != translated

                        # TTS (final transcripts only)
                        if msg_type == "transcript":
                            tts_wav = await asyncio.to_thread(
                                tts_service.synthesize,
                                translated,
                                target_lang,
                            )
                            if tts_wav:
                                partner_payload["has_tts"] = True
                else:
                    # Same language — relay untranslated
                    partner_payload = {
                        "type": msg_type,
                        "speaker": "partner",
                        "speaker_name": user_name,
                        "text": text,
                        "language": source_lang,
                    }
                    if duration is not None:
                        partner_payload["duration"] = round(duration, 2)

            # Send to speaker
            await participant.send_json_safe(self_payload)

            # Send to partner + TTS audio
            if current_partner and partner_payload:
                await current_partner.send_json_safe(partner_payload)
                if tts_wav:
                    await current_partner.send_bytes_safe(tts_wav)

                    tts_dur = _wav_duration_ms(tts_wav)
                    turn.lock_user(current_partner.role, tts_dur)
                    await current_partner.send_json_safe(
                        {
                            "type": "mic_locked",
                            "duration_ms": round(tts_dur + turn.lockout_buffer_ms),
                            "reason": "tts_echo",
                        }
                    )
                    logger.info(
                        "Room %s: locked %s mic for %.0f ms",
                        room_id,
                        current_partner.name,
                        tts_dur + turn.lockout_buffer_ms,
                    )

            # Session recording
            if msg_type == "transcript" and room.recorder is not None:
                room.recorder.add_speech_pcm(role, pcm, 16_000)
                if tts_wav and current_partner:
                    room.recorder.add_tts_pcm(current_partner.language, tts_wav)
                if room.transcript_logger is not None:
                    room.transcript_logger.add_entry(
                        speaker_role=role,
                        original_text=text,
                        source_lang=source_lang,
                        target_lang=_log_target_lang,
                        translated_text=_log_translated,
                        legal_verified=_log_legal_verified,
                        legal_correction_applied=_log_legal_correction,
                    )
                logger.info(
                    "Room %s: [%s] '%s' (%s)%s",
                    room_id,
                    user_name,
                    text,
                    source_lang,
                    f" → '{partner_payload.get('translation')}' ({partner_payload.get('target_language')})"
                    if partner_payload and "translation" in partner_payload
                    else "",
                )

        except Exception as exc:
            logger.exception("Room %s: [%s] pipeline error: %s", room_id, user_name, exc)

    # ── Session lifecycle handlers ────────────────────────────────────────

    async def _handle_session_start() -> None:
        if role != "a":
            logger.warning("Room %s: session_start rejected (role=%s)", room_id, role)
            return
        if not room.is_full:
            await participant.send_json_safe(
                {
                    "type": "error",
                    "message": "Cannot start session — partner has not joined yet.",
                }
            )
            return

        room.session_active = True
        room.session_start_time = datetime.now()
        ts = room.session_start_time.strftime("%Y%m%d_%H%M%S")
        room.session_name = f"{ts}_{room_id}_{room.language_a}-{room.language_b}"

        name_a = next((p.name for p in room.participants if p.role == "a"), "User A")
        name_b = next((p.name for p in room.participants if p.role == "b"), "User B")

        room.recorder = SessionRecorder(
            session_name=room.session_name,
            language_a=room.language_a,
            language_b=room.language_b,
            name_a=name_a,
            name_b=name_b,
        )
        room.transcript_logger = TranscriptLogger(
            session_name=room.session_name,
            language_a=room.language_a,
            language_b=room.language_b,
            name_a=name_a,
            name_b=name_b,
        )
        logger.info("Room %s: session recorder initialised: %s", room_id, room.session_name)

        for p in room.participants:
            if p.ws_open:
                await p.send_json_safe({"type": "session_status", "status": "active"})
        logger.info("Room %s: session started by %s", room_id, user_name)

    async def _handle_session_end() -> None:
        if role != "a":
            logger.warning("Room %s: session_end rejected (role=%s)", room_id, role)
            return
        room.session_active = False
        await _finalize_recording()
        for p in room.participants:
            if p.ws_open:
                await p.send_json_safe({"type": "session_status", "status": "ready"})
        logger.info("Room %s: session ended by %s", room_id, user_name)

    async def _handle_mic_mute(muted: bool) -> None:
        nonlocal utterance_id
        if muted:
            if audio_session.segment_detector.is_speaking and audio_session.current_utterance_pcm.size > 0:
                utterance_pcm = audio_session.current_utterance_pcm.copy()
                audio_session.current_utterance_pcm = np.array([], dtype=np.float32)
                dur = round(len(utterance_pcm) / VAD_SAMPLE_RATE, 2)
                utterance_id += 1
                task = asyncio.create_task(_process_speech(utterance_pcm, "transcript", utterance_id, dur))
                background_tasks.append(task)
            turn.release_floor(role)
            audio_session.segment_detector.reset()
        else:
            audio_session.segment_detector.reset()
            audio_session.current_utterance_pcm = np.array([], dtype=np.float32)

        current_partner = room.get_partner(participant)
        if current_partner and current_partner.ws_open:
            await current_partner.send_json_safe(
                {
                    "type": "partner_muted" if muted else "partner_unmuted",
                    "name": user_name,
                }
            )
        logger.info("Room %s: [%s] %s", room_id, user_name, "muted" if muted else "unmuted")

    async def _finalize_recording() -> None:
        if room.recorder is None or room.session_name is None:
            return
        if getattr(room, "artifacts_uploaded", False):
            return
        room.artifacts_uploaded = True
        session_dir = SESSIONS_DIR / room.session_name
        try:
            pending = [t for t in background_tasks if not t.done()]
            if pending:
                logger.info("Room %s: waiting for %d background tasks...", room_id, len(pending))
                await asyncio.gather(*pending, return_exceptions=True)

            end_time = datetime.now(UTC)
            wav_paths = room.recorder.finalize(session_dir)

            if room.transcript_logger is not None:
                room.transcript_logger.finalize(session_dir)

            # ── GCS transcript upload ──────────────────────────────────
            transcript_gcs_path: str | None = None
            transcript_signed_url: str | None = None
            transcript_signed_url_expires_at: datetime | None = None

            if room.transcript_logger is not None and room.db_session_id is not None:
                settings = get_settings()
                bucket = settings.gcs_bucket_transcripts
                blob_name = f"{room.db_session_id}/transcript.json"

                payload = room.transcript_logger.serialize(
                    session_id=str(room.db_session_id),
                    start_time=room.session_start_time,
                    end_time=end_time,
                )
                payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                try:
                    await asyncio.to_thread(
                        gcs.upload_bytes,
                        bucket,
                        blob_name,
                        payload_bytes,
                        "application/json",
                        correlation_id=str(room.db_session_id),
                    )
                    transcript_gcs_path = gcs.gcs_uri(bucket, blob_name)
                except Exception as exc:
                    logger.warning("Room %s: transcript GCS upload failed: %s", room_id, exc)

                # ── Signed URL (7-day expiry) ──────────────────────────
                if transcript_gcs_path:
                    _7d = 7 * 24 * 3600
                    try:
                        transcript_signed_url = await asyncio.to_thread(
                            gcs.generate_signed_url,
                            bucket,
                            blob_name,
                            _7d,
                            settings.gcp_service_account_json,
                            correlation_id=str(room.db_session_id),
                        )
                        transcript_signed_url_expires_at = datetime.now(UTC) + timedelta(seconds=_7d)
                    except Exception as exc:
                        logger.warning("Room %s: signed URL generation failed: %s", room_id, exc)

            # ── WAV upload (gated behind AUDIO_STORAGE_ENABLED) ───────
            if wav_paths:
                await asyncio.to_thread(upload_wav_tracks, room.session_name, wav_paths)

            # ── Single DB write ────────────────────────────────────────
            if room.db_session_id is not None and room.db_rt_request_id is not None:
                try:
                    from db.database import AsyncSessionLocal
                    from db.models import RealtimeTranslationRequest
                    from db.models import Session as SessionModel

                    total_utterances = room.transcript_logger.entry_count if room.transcript_logger else 0
                    duration_s: float | None = None
                    if room.session_start_time is not None:
                        duration_s = round((end_time - room.session_start_time).total_seconds(), 2)

                    async with AsyncSessionLocal() as _db:
                        rt_result = await _db.execute(
                            select(RealtimeTranslationRequest).where(
                                RealtimeTranslationRequest.rt_request_id == room.db_rt_request_id
                            )
                        )
                        rt_row = rt_result.scalar_one_or_none()
                        if rt_row is not None:
                            rt_row.transcript_gcs_path = transcript_gcs_path
                            rt_row.transcript_signed_url = transcript_signed_url
                            rt_row.transcript_signed_url_expires_at = transcript_signed_url_expires_at
                            rt_row.total_utterances = total_utterances
                            rt_row.duration_seconds = duration_s
                            rt_row.phase = "ended"
                            rt_row.completed_at = end_time

                        sess_result = await _db.execute(
                            select(SessionModel).where(SessionModel.session_id == room.db_session_id)
                        )
                        sess_row = sess_result.scalar_one_or_none()
                        if sess_row is not None:
                            sess_row.status = "completed"
                            sess_row.completed_at = end_time

                        await _db.commit()

                    logger.info(
                        "Room %s: DB updated — session_id=%s rt_request_id=%s utterances=%d duration=%.1fs gcs_path=%s",
                        room_id,
                        room.db_session_id,
                        room.db_rt_request_id,
                        total_utterances,
                        duration_s or 0,
                        transcript_gcs_path or "none",
                    )
                except Exception as exc:
                    logger.exception("Room %s: DB write on session end failed: %s", room_id, exc)

            # ── Local manifest ─────────────────────────────────────────
            name_a = next((p.name for p in room.participants if p.role == "a"), "User A")
            name_b = next((p.name for p in room.participants if p.role == "b"), "User B")

            write_manifest(
                session_dir=session_dir,
                session_name=room.session_name,
                start_time=room.session_start_time or end_time,
                end_time=end_time,
                language_a=room.language_a,
                language_b=room.language_b,
                name_a=name_a,
                name_b=name_b,
                room_id=room_id,
                transcript_entries=room.transcript_logger.entry_count if room.transcript_logger else 0,
            )

            for p in room.participants:
                if p.ws_open:
                    await p.send_json_safe(
                        {
                            "type": "session_artifacts",
                            "session_name": room.session_name,
                            "transcript_url": transcript_signed_url,
                        }
                    )
            logger.info("Room %s: session finalised → %s", room_id, session_dir)

        except Exception as exc:
            logger.exception("Room %s: failed to finalise recording: %s", room_id, exc)
        finally:
            room.recorder = None
            room.transcript_logger = None

    # ── Main receive loop ─────────────────────────────────────────────────

    logger.info("Room %s: [%s] connected (role=%s, session_active=%s)", room_id, user_name, role, room.session_active)

    try:
        while True:
            data = await websocket.receive_bytes()

            # Control markers (exactly 4 bytes, matched by value).
            # A 4-byte audio chunk could theoretically collide, but WebM/Opus
            # frames are always larger.  We also check markers BEFORE the
            # session_active gate so they work in every phase.
            if len(data) == 4:
                matched = True
                if data == _MARKER_START:
                    await _handle_session_start()
                elif data == _MARKER_END:
                    await _handle_session_end()
                elif data == _MARKER_MUTE:
                    await _handle_mic_mute(True)
                elif data == _MARKER_UNMUT:
                    await _handle_mic_mute(False)
                else:
                    matched = False
                if matched:
                    continue

            # Skip audio processing until session is active
            if not room.session_active:
                continue

            audio_session.add_chunk(data)
            events = audio_session.process_for_vad(data)

            for event in events:
                if event["type"] == "speech_start":
                    allowed = turn.try_speech_start(role)
                    if not allowed:
                        logger.debug("Room %s: [%s] speech_start REJECTED (%s)", room_id, user_name, turn)
                        continue
                    utterance_id += 1
                    if partial_task and not partial_task.done():
                        partial_task.cancel()
                        partial_task = None

                elif event["type"] == "speech_end":
                    was_active = turn.on_speech_end(role)
                    if not was_active:
                        logger.debug("Room %s: [%s] speech_end IGNORED (not active speaker)", room_id, user_name)
                        continue

                    if partial_task and not partial_task.done():
                        partial_task.cancel()
                        partial_task = None

                    utterance_pcm = event.get("utterance_pcm")
                    dur = event.get("duration")
                    if utterance_pcm is not None and utterance_pcm.size > 0:
                        task = asyncio.create_task(_process_speech(utterance_pcm, "transcript", utterance_id, dur))
                        background_tasks.append(task)

            # Periodic partial transcript while floor is held
            _min_partial = int(VAD_SAMPLE_RATE * 1.0)
            if (
                room.session_active
                and turn.holds_floor(role)
                and audio_session.segment_detector.is_speaking
                and audio_session.current_utterance_pcm.size >= _min_partial
                and (partial_task is None or partial_task.done())
            ):
                partial_task = asyncio.create_task(
                    _process_speech(
                        audio_session.current_utterance_pcm.copy(),
                        "transcript_partial",
                        utterance_id,
                    )
                )
                background_tasks.append(partial_task)

    except WebSocketDisconnect:
        logger.info("Room %s: [%s] disconnected", room_id, user_name)
    except RuntimeError:
        logger.info("Room %s: [%s] disconnected (ws closed)", room_id, user_name)
    except Exception as exc:
        logger.exception("Room %s: [%s] error: %s", room_id, user_name, exc)
    finally:
        participant.ws_open = False
        for t in background_tasks:
            if not t.done():
                t.cancel()

        # Finalize recording if session was active when this participant left
        if room.session_active:
            room.session_active = False
            await _finalize_recording()

        # Notify partner
        departing_partner = room.get_partner(participant)
        if departing_partner and departing_partner.ws_open:
            await departing_partner.send_json_safe({"type": "partner_left", "name": user_name})
            await departing_partner.send_json_safe({"type": "session_status", "status": "ended"})

        room.remove_participant(participant)
        if not room.participants:
            conversation_rooms.pop(room_id, None)
            logger.info("Room %s: closed (empty)", room_id)

        # Save individual WebM recording
        if audio_session.chunks:
            audio_session.save_as_wav()
