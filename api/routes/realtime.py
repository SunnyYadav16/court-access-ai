"""
api/routes/realtime.py

WebSocket and REST endpoints for real-time interpretation sessions.

Endpoints:
  POST   /sessions/              — Create a new session, get WebSocket URL
  GET    /sessions/{session_id}  — Get session metadata and status
  POST   /sessions/{session_id}/end  — End an active session
  WS     /sessions/{session_id}/ws  — Live audio stream (VAD → ASR → NLLB → TTS)

WebSocket message protocol:
  Client → Server:
    { "type": "audio_chunk", "payload": { "data": "<base64>" } }
    { "type": "ping" }
  Server → Client:
    { "type": "transcript", "payload": TranscriptSegment }
    { "type": "error",      "payload": { "code": "...", "message": "..." } }
    { "type": "pong" }
    { "type": "session_ended" }
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import (
    SessionCreateRequest,
    SessionResponse,
    SessionStatus,
    TranscriptSegment,
    WebSocketMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["realtime"])


# ── In-memory session registry (replace with Redis in production) ─────────────
_sessions: dict[str, dict] = {}


# ══════════════════════════════════════════════════════════════════════════════
# REST endpoints
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a real-time interpretation session",
    description=(
        "Creates a new interpretation session and returns a WebSocket URL. "
        "The caller should immediately open the WebSocket connection and "
        "begin streaming audio chunks."
    ),
)
async def create_session(
    body: SessionCreateRequest,
    user: Annotated[
        CurrentUser, Depends(require_role("court_official", "interpreter", "admin"))
    ],  # Elevated roles only
    db: DBSession,
) -> SessionResponse:
    """
    Create a new active session for the authenticated user.

    TODO (production):
      - Persist session to db via db/models.py Session model
      - Register session in Redis for WebSocket worker fan-out
      - Return real WebSocket URL based on current host
    """
    session_id = uuid.uuid4()
    now = datetime.now(tz=UTC)

    _sessions[str(session_id)] = {
        "session_id": session_id,
        "user_id": user.user_id,
        "status": SessionStatus.ACTIVE,
        "created_at": now,
        "target_language": body.target_language,
        "source_language": body.source_language,
        "participants": [{"user_id": user.user_id, "role": "creator"}],
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
    """
    Return metadata for an existing session.
    Users can only retrieve their own sessions unless they are admin/court_official.

    TODO (production): Query db/models.py Session for persistent state.
    """
    sid = str(session_id)
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session["user_id"] != user.user_id and user.role_id not in (4, 2):  # admin, court_official
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
    """
    End an active session. Triggers transcript finalization and cleanup.

    TODO (production):
      - Mark session ENDED in database
      - Flush transcript to GCS
      - Notify connected WebSocket clients via Redis pub/sub
    """
    sid = str(session_id)
    session = _sessions.get(sid)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session["user_id"] != user.user_id and user.role_id != 4:  # admin
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    if session["status"] == SessionStatus.ENDED:
        return  # Idempotent

    _sessions[sid]["status"] = SessionStatus.ENDED
    logger.info("Session ended: session_id=%s user_id=%s", session_id, user.user_id)


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket endpoint
# ══════════════════════════════════════════════════════════════════════════════


@router.websocket("/{session_id}/ws")
async def session_websocket(
    websocket: WebSocket,
    session_id: uuid.UUID,
) -> None:
    """
    WebSocket endpoint for a live interpretation session.

    Protocol:
      - Client sends audio_chunk messages (base64-encoded PCM frames)
      - Server responds with interim/final transcript segments
      - Server echoes pong for any ping message
      - On session end or disconnect, server sends session_ended

    Authentication:
      The Bearer token is passed as a query parameter:
        ws://host/sessions/{id}/ws?token=<access_token>
      This is a WebSocket limitation — Authorization headers are not
      supported in browser WebSocket APIs.

    TODO (production):
      - Validate token from query param
      - Pipe audio to courtaccess.speech.vad → transcribe → translate → tts
      - Fan-out transcripts to all session participants via Redis
      - Buffer and store final transcripts to GCS
    """
    sid = str(session_id)
    session = _sessions.get(sid)
    if not session or session["status"] == SessionStatus.ENDED:
        await websocket.close(code=4004, reason="Session not found or ended")
        return

    await websocket.accept()
    logger.info("WebSocket connected: session_id=%s", session_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = WebSocketMessage.model_validate_json(raw)
            except Exception:
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "payload": {"code": "invalid_message", "message": "Could not parse message"},
                        }
                    )
                )
                continue

            if msg.type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif msg.type == "audio_chunk":
                # STUB — echo a fake transcript segment back.
                # Production: decode base64 PCM → VAD → Whisper → NLLB → push segment.
                segment = TranscriptSegment(
                    speaker_id=session["user_id"],
                    original_text="[STUB] Audio received",
                    translated_text=None,
                    language=session["source_language"],
                    timestamp_ms=msg.timestamp_ms or 0,
                    is_final=False,
                )
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "transcript",
                            "payload": segment.model_dump(mode="json"),
                        }
                    )
                )

            else:
                logger.debug("Unknown message type: %s", msg.type)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session_id=%s", session_id)
    except Exception as exc:
        logger.exception("WebSocket error for session %s: %s", session_id, exc)
        import contextlib

        with contextlib.suppress(Exception):
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "payload": {"code": "server_error", "message": "Unexpected error"},
                    }
                )
            )
    finally:
        logger.info("WebSocket closed: session_id=%s", session_id)
