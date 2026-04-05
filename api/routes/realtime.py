"""
api/routes/realtime.py

WebSocket and REST endpoints for real-time interpretation sessions.

REST endpoints:
  POST   /sessions/              — Create a session record, get WebSocket URL
  GET    /sessions/rooms         — List active in-memory conversation rooms
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
import uuid
import wave
from datetime import UTC, datetime
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from api.auth import verify_firebase_token
from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import (
    SessionCreateRequest,
    SessionResponse,
    SessionStatus,
)
from courtaccess.core.logger import get_logger
from courtaccess.speech.session import (
    VAD_SAMPLE_RATE,
    AudioSession,
    ConversationRoom,
    Participant,
    _generate_room_id,
)
from courtaccess.speech.session_recorder import SESSIONS_DIR, SessionRecorder, TranscriptLogger, write_manifest

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
    user: Annotated[CurrentUser, Depends(require_role("court_official", "interpreter", "admin"))],
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


@router.get(
    "/rooms",
    summary="List active conversation rooms",
)
async def list_rooms() -> dict:
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
    # Admin (4) and court_official (2) may view any session
    if session["user_id"] != user.user_id and user.role_id not in {4, 2}:
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
    if session["user_id"] != user.user_id and user.role_id != 4:  # admin only
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
        verify_firebase_token(token)
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "message": str(exc.detail)})
        await websocket.close(code=4001, reason=str(exc.detail))
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

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
        conversation_rooms[room_id] = room
        user_lang = my_lang

    # ── Create participant ────────────────────────────────────────────────
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

                if source_lang != target_lang and source_lang != "unknown":
                    translated = await asyncio.to_thread(
                        mt_service.translate,
                        text,
                        source_lang,
                        target_lang,
                    )
                    if translated:
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
                        role=role,
                        text=text,
                        language=source_lang,
                        translation=partner_payload.get("translation") if partner_payload else None,
                        target_language=partner_payload.get("target_language") if partner_payload else None,
                        duration=duration,
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
        session_dir = SESSIONS_DIR / room.session_name
        try:
            pending = [t for t in background_tasks if not t.done()]
            if pending:
                logger.info("Room %s: waiting for %d background tasks...", room_id, len(pending))
                await asyncio.gather(*pending, return_exceptions=True)

            room.recorder.finalize(session_dir)

            if room.transcript_logger is not None:
                room.transcript_logger.finalize(session_dir)

            end_time = datetime.now()
            name_a = next((p.name for p in room.participants if p.role == "a"), "User A")
            name_b = next((p.name for p in room.participants if p.role == "b"), "User B")

            write_manifest(
                session_dir=session_dir,
                session_name=room.session_name,
                start_time=room.session_start_time or datetime.now(),
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
                            "download_url": f"/api/sessions/{room.session_name}/download",
                        }
                    )
            logger.info("Room %s: artifacts saved to %s", room_id, session_dir)

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
