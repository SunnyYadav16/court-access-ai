"""
courtaccess/speech/session.py

Real-time session manager: orchestrates the full speech pipeline for a
WebSocket connection.

Pipeline per audio chunk:
    audio_bytes → VAD → ASR → Translation → Legal Review (async) → TTS → client

Key responsibilities:
  - Receive raw PCM audio chunks from the WebSocket
  - Run VAD then ASR to get transcript
  - Translate EN → target language
  - Fire legal review async (non-blocking for real-time)
  - Synthesize TTS audio
  - Stream translated audio back to client
  - Manage session state (active, language, participant role)

DEFERRED EXTRACTIONS (see implementation_plan.md):
  - Priority queue logic stays in this file until it exceeds ~200 lines
    AND the logic is cleanly separable. Extract to priority_queue.py then.

NOTE: This is a skeleton. WebSocket wiring lives in api/routes/realtime.py.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from courtaccess.core.legal_review import review_legal_terms
from courtaccess.core.logger import get_logger
from courtaccess.core.translation import translate_text
from courtaccess.speech.transcribe import transcribe_audio
from courtaccess.speech.tts import synthesize_speech
from courtaccess.speech.vad import detect_speech

logger = get_logger(__name__)


class ParticipantRole(StrEnum):
    CREATOR = "creator"  # Court official who started the session (highest priority)
    INTERPRETER = "interpreter"
    PUBLIC = "public"


@dataclass
class Participant:
    participant_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    role: ParticipantRole = ParticipantRole.PUBLIC
    language: str = "eng_Latn"  # NLLB language code of the speaker
    target_language: str = "spa_Latn"  # Language to translate INTO

    @property
    def priority(self) -> int:
        """Lower number = higher priority. Creator always wins."""
        return {
            ParticipantRole.CREATOR: 0,
            ParticipantRole.INTERPRETER: 1,
            ParticipantRole.PUBLIC: 2,
        }[self.role]


@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    participants: dict[str, Participant] = field(default_factory=dict)
    active: bool = True
    target_language: str = "spa_Latn"


class RealtimeSession:
    """
    Manages the lifecycle of one real-time translation session.

    One session = one WebSocket connection from a court official.
    Multiple participants can be added (future multi-party support).
    """

    def __init__(self, session_id: str, target_language: str = "spa_Latn") -> None:
        self.state = SessionState(
            session_id=session_id,
            target_language=target_language,
        )
        logger.info("Session %s created (target_language=%s).", session_id, target_language)

    def add_participant(self, participant: Participant) -> None:
        self.state.participants[participant.participant_id] = participant
        logger.info(
            "Session %s: participant %s added (role=%s).",
            self.state.session_id,
            participant.participant_id,
            participant.role,
        )

    async def process_audio_chunk(
        self,
        audio_bytes: bytes,
        participant_id: str,
    ) -> dict:
        """
        Run the full pipeline on one audio chunk from a participant.

        Args:
            audio_bytes:    Raw 16-bit PCM audio (16kHz mono).
            participant_id: ID of the speaking participant (for priority).

        Returns:
            {
                "transcript":    str,
                "translation":   str,
                "audio_bytes":   bytes,   # TTS WAV
                "confidence":    float,
                "legal_review":  dict | None,  # None until async review completes
            }
        """
        participant = self.state.participants.get(participant_id)
        target_lang = participant.target_language if participant else self.state.target_language

        # Step 1: VAD — filter silence
        vad_result = detect_speech(audio_bytes)
        if not vad_result["speech_segments"]:
            logger.debug("Session %s: no speech detected in chunk — skipping.", self.state.session_id)
            return {"transcript": "", "translation": "", "audio_bytes": b"", "confidence": 0.0, "legal_review": None}

        # Step 2: ASR
        asr_result = transcribe_audio(audio_bytes)
        transcript = asr_result["text"]
        if not transcript.strip():
            return {"transcript": "", "translation": "", "audio_bytes": b"", "confidence": 0.0, "legal_review": None}

        # Step 3: Translation
        translation_result = translate_text(
            text=transcript,
            source_lang="eng_Latn",
            target_lang=target_lang,
        )
        translated_text = translation_result["translated"]

        # Step 4: Legal review — fire async, don't block TTS
        legal_task = asyncio.create_task(asyncio.to_thread(review_legal_terms, translated_text, target_lang))

        # Step 5: TTS — synthesize translated audio immediately
        tts_result = synthesize_speech(translated_text, target_lang)

        # Step 6: Await legal review (best-effort — doesn't block audio delivery)
        try:
            legal_review = await asyncio.wait_for(legal_task, timeout=2.0)
        except TimeoutError:
            legal_review = None
            logger.warning("Session %s: legal review timed out — proceeding without.", self.state.session_id)

        logger.info(
            "Session %s: chunk processed | transcript=%r | translation=%r | tts_ms=%d",
            self.state.session_id,
            transcript[:50],
            translated_text[:50],
            tts_result["duration_ms"],
        )

        return {
            "transcript": transcript,
            "translation": translated_text,
            "audio_bytes": tts_result["audio_bytes"],
            "confidence": asr_result["confidence"],
            "legal_review": legal_review,
        }

    def close(self) -> None:
        self.state.active = False
        logger.info("Session %s closed.", self.state.session_id)
