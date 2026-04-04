"""
Silero VAD Service for real-time voice activity detection.
Processes audio chunks and returns speech probability.
"""

import threading

import numpy as np

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)


class VADService:
    """
    Voice Activity Detection service backed by the Silero VAD model.

    This class wraps model loading and inference, exposing a simple
    `process_chunk` API that takes a 16 kHz mono float32 numpy array and
    returns both the speech probability and a boolean is_speech flag.

    The service is effectively a singleton: the underlying model is loaded
    once and reused across all sessions, but transient recurrent state should
    be reset via `reset_states()` for each new audio stream.
    """

    _instance = None
    _model = None
    _lock = threading.Lock()  # Serializes inference to protect recurrent state

    def __new__(cls):
        """Singleton pattern to reuse loaded model."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if VADService._model is None:
            self._load_model()

    def _load_model(self):
        """Load Silero VAD model from local path (materialized by dvc pull).

        Reads SILERO_VAD_MODEL_PATH from the environment — must point to the
        silero_vad.jit.pt file downloaded by scripts/setup_models.sh and
        pulled from gs://courtaccess-ai-models via dvc pull.

        Fails fast with a clear error if the path is unset or the file is
        missing, rather than hitting the internet via torch.hub.
        """
        import os

        model_path = os.getenv("SILERO_VAD_MODEL_PATH")

        if not model_path:
            raise RuntimeError(
                "SILERO_VAD_MODEL_PATH is not set. "
                "Run 'dvc pull' to download the model from GCS, then ensure "
                "SILERO_VAD_MODEL_PATH points to models/silero-vad-v4/silero_vad.jit.pt"
            )

        from pathlib import Path

        if not Path(model_path).is_file():
            raise RuntimeError(
                f"Silero VAD model not found at: {model_path}\nRun 'dvc pull' to download the model from GCS."
            )

        import torch

        logger.info("Loading Silero VAD model from %s ...", model_path)
        model = torch.jit.load(model_path, map_location="cpu")  # nosec B614
        model.eval()
        VADService._model = model
        logger.info("Silero VAD model loaded successfully")

    @property
    def model(self):
        return VADService._model

    def reset_states(self):
        """Reset model states for new audio stream."""
        self.model.reset_states()

    def process_chunk(self, audio_chunk: np.ndarray, sample_rate: int = 16000) -> tuple[float, bool]:
        """
        Process an audio chunk and return speech probability and decision.

        Args:
            audio_chunk: 1D float32 numpy array of audio samples normalized
                to [-1, 1]. Can also be a torch.Tensor.
            sample_rate: Sample rate in Hz (typically 16000).

        Returns:
            (speech_probability, is_speech) where:
                - speech_probability is a float in [0, 1]
                - is_speech is True when probability >= 0.5
        """
        import torch

        # Convert numpy to torch tensor
        audio_tensor = torch.from_numpy(audio_chunk).float() if isinstance(audio_chunk, np.ndarray) else audio_chunk

        # Ensure 1D tensor
        if audio_tensor.dim() > 1:
            audio_tensor = audio_tensor.squeeze()

        # Get speech probability — lock protects the model's recurrent state
        # so concurrent sessions don't corrupt each other.
        with self._lock, torch.no_grad():
            speech_prob = self.model(audio_tensor, sample_rate).item()

        # Threshold for speech detection
        threshold = get_settings().vad_speech_threshold
        is_speech = speech_prob >= threshold

        return speech_prob, is_speech


class SpeechSegmentDetector:
    """
    Detects speech segments with silence-based boundary detection.
    Tracks when speech starts and ends based on VAD output.
    """

    def __init__(self, silence_threshold_ms: int = 500, sample_rate: int = 16000, chunk_size: int = 512):
        """
        Args:
            silence_threshold_ms: Silence duration (ms) to mark end of utterance
            sample_rate: Audio sample rate
            chunk_size: Number of samples per chunk
        """
        self.silence_threshold_ms = silence_threshold_ms
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size

        # Calculate number of silent chunks needed
        chunk_duration_ms = (chunk_size / sample_rate) * 1000
        self.silence_chunks_threshold = int(silence_threshold_ms / chunk_duration_ms)

        # State tracking
        self.is_speaking = False
        self.silent_chunks = 0
        self.speech_start_time = None
        self.total_speech_chunks = 0

    def update(self, is_speech: bool) -> dict:
        """
        Update state with new VAD result.

        Args:
            is_speech: Whether current chunk contains speech

        Returns:
            Event dict with 'type' key: 'speech_start', 'speech_end', or None
        """
        event = {"type": None}

        if is_speech:
            self.silent_chunks = 0

            if not self.is_speaking:
                # Speech just started
                self.is_speaking = True
                self.speech_start_time = self.total_speech_chunks
                event = {
                    "type": "speech_start",
                }

            self.total_speech_chunks += 1

        else:
            if self.is_speaking:
                self.silent_chunks += 1

                if self.silent_chunks >= self.silence_chunks_threshold:
                    # Speech ended (silence threshold reached)
                    speech_duration = (self.total_speech_chunks - self.speech_start_time) * (
                        self.chunk_size / self.sample_rate
                    )

                    event = {"type": "speech_end", "duration": round(speech_duration, 2)}

                    self.is_speaking = False
                    self.silent_chunks = 0

        return event

    def reset(self):
        """Reset detector state for new session."""
        self.is_speaking = False
        self.silent_chunks = 0
        self.speech_start_time = None
        self.total_speech_chunks = 0


# Global VAD service instance
_vad_service: VADService | None = None


def get_vad_service() -> VADService:
    """Get or create the global VAD service instance."""
    global _vad_service
    if _vad_service is None:
        _vad_service = VADService()
    return _vad_service
