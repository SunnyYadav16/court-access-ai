import io
import secrets
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

# Heavy imports deferred to methods so the module can be imported
# without torch/av/etc. when USE_REAL_SPEECH=false.

logger = get_logger(__name__)


def _get_recordings_dir() -> Path:
    """Resolve recordings directory from settings (lazy, creates on first call)."""
    d = Path(get_settings().session_recordings_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


# VAD configuration
VAD_SAMPLE_RATE = 16000
VAD_CHUNK_SIZE = 512  # ~32ms at 16kHz


class AudioStreamDecoder:
    """
    Incrementally decodes a WebM/Opus audio byte stream into PCM samples.

    The browser sends small WebM/Opus chunks over the WebSocket.  This
    class buffers those bytes and uses PyAV to decode whatever complete
    frames are available, returning 16 kHz mono float32 PCM suitable for
    VAD.

    To prevent **O(N²) degradation** (re-decoding the entire session on
    every chunk), the client periodically restarts its MediaRecorder,
    which sends a new WebM EBML header.  When we detect that header we
    reset the buffer so the decode window stays bounded.
    """

    # First 4 bytes of the EBML header that starts every WebM file.
    _EBML_SIGNATURE = bytes([0x1A, 0x45, 0xDF, 0xA3])

    def __init__(self, target_sample_rate: int = 16000):
        self.target_sample_rate = target_sample_rate
        self.buffer = b""
        self.initialized = False
        # Track how many resampled samples have already been returned so
        # that each call only yields the *new* portion of the audio.
        self._samples_returned = 0

    def add_chunk(self, data: bytes) -> np.ndarray:
        """
        Add a WebM/Opus chunk and return only the **newly decoded** PCM
        samples since the last successful call.

        If *data* starts with a fresh EBML header (new MediaRecorder
        segment), the accumulated buffer is reset so the decode window
        stays small.
        """
        # ── Detect fresh WebM header → reset decoder ──
        if len(data) >= 4 and data[:4] == self._EBML_SIGNATURE and self.initialized:
            self.buffer = b""
            self._samples_returned = 0

        self.buffer += data

        try:
            import av

            # Decode the accumulated buffer
            input_buffer = io.BytesIO(self.buffer)
            container = av.open(input_buffer, format="webm")

            samples = []
            for stream in container.streams:
                if stream.type == "audio":
                    for frame in container.decode(stream):
                        audio = frame.to_ndarray()
                        # Convert stereo to mono if needed
                        audio = audio.mean(axis=0) if audio.shape[0] > 1 else audio[0]
                        samples.append(audio)

            container.close()

            if samples:
                self.initialized = True
                audio_data = np.concatenate(samples).astype(np.float32)

                # Resample to target_sample_rate.  Browser Opus streams are
                # typically 48 kHz; we need 16 kHz for VAD/ASR.  Use
                # np.interp for proper interpolation (avoids aliasing from
                # naive decimation).
                source_rate = 48000  # Opus default
                if source_rate != self.target_sample_rate:
                    duration_s = len(audio_data) / source_rate
                    target_len = int(duration_s * self.target_sample_rate)
                    if target_len > 0:
                        audio_data = np.interp(
                            np.linspace(0, len(audio_data) - 1, target_len),
                            np.arange(len(audio_data)),
                            audio_data,
                        ).astype(np.float32)

                # Return only the new samples
                new_samples = audio_data[self._samples_returned :]
                self._samples_returned = len(audio_data)
                return new_samples

        except Exception:  # noqa: S110
            # Not enough data yet to decode, or error
            pass

        return np.array([], dtype=np.float32)


class AudioSession:
    """
    Manages the lifetime of a single browser audio session.

    Responsibilities:
    - Collect raw WebM chunks so the full session can be saved as a WAV file.
    - Decode incoming chunks to 16 kHz mono PCM via AudioStreamDecoder.
    - Run Silero VAD on fixed-size PCM windows.
    - Use SpeechSegmentDetector to turn per-chunk VAD decisions into
      higher-level "speech_start"/"speech_end" events.
    """

    def __init__(self, session_id: str, language: str | None = None):
        self.session_id = session_id
        self.chunks: list[bytes] = []
        self.started_at = datetime.now()
        self.language = language

        # VAD components — import lazily so session.py can be imported
        # without torch/av when USE_REAL_SPEECH=false.
        from courtaccess.speech.vad import SpeechSegmentDetector, get_vad_service

        self.vad_service = get_vad_service()
        # NOTE: We intentionally do NOT call vad_service.reset_states() here.
        # The singleton model's recurrent state is shared across concurrent
        # sessions.  A threading.Lock in VADService.process_chunk serializes
        # access so sessions don't corrupt each other's state.
        self.segment_detector = SpeechSegmentDetector(
            silence_threshold_ms=500, sample_rate=VAD_SAMPLE_RATE, chunk_size=VAD_CHUNK_SIZE
        )

        # Audio processing
        self.decoder = AudioStreamDecoder(target_sample_rate=VAD_SAMPLE_RATE)
        self.pcm_buffer = np.array([], dtype=np.float32)
        # Buffer for the current utterance (between speech_start and speech_end)
        self.current_utterance_pcm = np.array([], dtype=np.float32)

    def add_chunk(self, data: bytes):
        """Add an audio chunk to the session."""
        self.chunks.append(data)

    def process_for_vad(self, data: bytes) -> list[dict]:
        """
        Decode an incoming WebM chunk, run VAD over complete PCM windows,
        and return speech boundary events.

        This method is intentionally fast (no ASR). ASR is run separately
        in background threads by the WebSocket handler so the receive loop
        is never blocked.
        """
        events = []

        # Decode WebM chunk to PCM
        pcm_samples = self.decoder.add_chunk(data)

        if len(pcm_samples) == 0:
            return events

        # Add to PCM buffer
        self.pcm_buffer = np.concatenate([self.pcm_buffer, pcm_samples])

        # Process complete VAD chunks
        while len(self.pcm_buffer) >= VAD_CHUNK_SIZE:
            chunk = self.pcm_buffer[:VAD_CHUNK_SIZE]
            self.pcm_buffer = self.pcm_buffer[VAD_CHUNK_SIZE:]

            # Run VAD via per-session process_chunk (each session gets
            # its own SpeechSegmentDetector; the model itself is stateless
            # for single-chunk inference without reset_states).
            _speech_prob, is_speech = self.vad_service.process_chunk(chunk, sample_rate=VAD_SAMPLE_RATE)

            # Check for speech boundary events
            event = self.segment_detector.update(is_speech)

            # Accumulate PCM for the current utterance while speaking
            if self.segment_detector.is_speaking:
                if self.current_utterance_pcm.size == 0:
                    self.current_utterance_pcm = chunk.copy()
                else:
                    self.current_utterance_pcm = np.concatenate([self.current_utterance_pcm, chunk])

            # Reset utterance buffer at speech_start
            if event["type"] == "speech_start":
                self.current_utterance_pcm = chunk.copy()

            # On speech_end, attach the accumulated utterance PCM so the
            # WebSocket handler can transcribe it in a background thread.
            if event["type"] == "speech_end":
                event["utterance_pcm"] = self.current_utterance_pcm.copy()
                self.current_utterance_pcm = np.array([], dtype=np.float32)

            if event["type"]:
                events.append(event)

        return events

    def get_webm_data(self) -> bytes:
        """Combine all chunks into a single WebM blob."""
        return b"".join(self.chunks)

    def save_as_wav(self) -> Path | None:
        """Convert WebM audio to WAV and save to disk."""
        if not self.chunks:
            return None

        webm_data = self.get_webm_data()
        output_path = _get_recordings_dir() / f"{self.session_id}.wav"

        try:
            import av

            input_buffer = io.BytesIO(webm_data)
            container = av.open(input_buffer, format="webm")

            audio_stream = next(s for s in container.streams if s.type == "audio")

            samples = []
            for frame in container.decode(audio_stream):
                frame = frame.to_ndarray()
                samples.append(frame)

            container.close()

            if not samples:
                return None

            audio_data = np.concatenate(samples, axis=1)

            audio_data = audio_data.mean(axis=0) if audio_data.shape[0] > 1 else audio_data[0]

            audio_data = (audio_data * 32767).astype(np.int16)

            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(48000)
                wav_file.writeframes(audio_data.tobytes())

            return output_path

        except Exception as e:
            logger.warning("Error converting audio for session %s: %s", self.session_id, e)
            debug_path = _get_recordings_dir() / f"{self.session_id}.webm"
            debug_path.write_bytes(webm_data)
            logger.info("Saved raw WebM to %s", debug_path)
            return None


class Participant:
    """
    Represents one user inside a ConversationRoom.

    Wraps the WebSocket, display name, spoken language, and the
    per-connection AudioSession used for VAD / decoding.
    """

    def __init__(
        self,
        ws,  # fastapi.WebSocket (imported at runtime by callers)
        name: str,
        language: str,
        session: AudioSession,
        role: str = "a",
    ):
        self.ws = ws
        self.name = name
        self.language = language  # language this user speaks
        self.session = session
        self.role = role  # 'a' (creator) or 'b' (joiner)
        self.ws_open = True

    async def send_json_safe(self, payload: dict):
        """Send a JSON text frame, swallowing errors if the socket closed."""
        if not self.ws_open:
            return
        try:
            await self.ws.send_json(payload)
        except Exception:
            self.ws_open = False

    async def send_bytes_safe(self, data: bytes):
        """Send a binary frame, swallowing errors if the socket closed."""
        if not self.ws_open:
            return
        try:
            await self.ws.send_bytes(data)
        except Exception:
            self.ws_open = False


class ConversationRoom:
    """
    A conversation session between two participants.

    The room creator defines both languages up-front (e.g. English <-> Spanish).
    The creator is assigned ``language_a``; whoever joins is automatically
    assigned ``language_b``.  This keeps the join flow dead-simple for the
    LEP user — they only need the room code and a name.
    """

    def __init__(self, room_id: str, language_a: str, language_b: str):
        self.room_id = room_id
        self.language_a = language_a  # creator's language
        self.language_b = language_b  # joiner's language
        self.participants: list[Participant] = []
        self.created_at = datetime.now()
        from courtaccess.speech.session_recorder import SessionRecorder, TranscriptLogger
        from courtaccess.speech.turn_taking import TurnStateMachine

        self.turn = TurnStateMachine()  # Phase 7: turn-taking & echo suppression
        # Phase 10: session recording & transcript
        self.recorder: SessionRecorder | None = None
        self.transcript_logger: TranscriptLogger | None = None
        self.session_start_time: datetime | None = None
        self.session_name: str | None = None
        self.session_active = False  # U.4: controlled by creator's session_start

    @property
    def is_full(self) -> bool:
        return len(self.participants) >= 2

    def add_participant(self, participant: Participant):
        self.participants.append(participant)

    def remove_participant(self, participant: Participant):
        if participant in self.participants:
            self.participants.remove(participant)

    def get_partner(self, participant: Participant) -> Participant | None:
        for p in self.participants:
            if p is not participant:
                return p
        return None


# Characters for room codes (excluding ambiguous: O/0, I/1/L)
_ROOM_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_room_id() -> str:
    """Generate a short, human-friendly 6-character room code."""
    return "".join(secrets.choice(_ROOM_CHARS) for _ in range(6))
