"""
courtaccess/speech/vad.py

Voice Activity Detection using Silero VAD v4.
Filters silence and noise from raw audio before passing to ASR.

STUB/REAL HYBRID:
  - Stub: marks entire audio as speech (passthrough).
  - Real: runs Silero VAD v4 via PyTorch.

PRODUCTION NOTES:
  - Prevents Faster-Whisper hallucinations on silence.
  - Segments are returned as (start_ms, end_ms) tuples — ASR slices on these.

OUTPUT CONTRACT:
  {
      "speech_segments": [[start_ms, end_ms], ...],
      "total_duration_ms": int,
      "speech_ratio":      float,   # proportion of audio that is speech
  }
"""

import os

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

_USE_REAL = os.getenv("USE_REAL_VAD", "false").lower() == "true"
_SAMPLE_RATE = 16000  # Silero VAD requires 16kHz mono
_THRESHOLD = 0.5  # Confidence threshold for speech detection


def detect_speech(audio_bytes: bytes, sample_rate: int = _SAMPLE_RATE) -> dict:
    """
    Detect speech segments in raw PCM audio bytes.

    Args:
        audio_bytes: Raw 16-bit PCM audio (mono, 16kHz).
        sample_rate: Sample rate of the audio (default 16000).

    Returns:
        Dict matching OUTPUT CONTRACT above.
    """
    if _USE_REAL:
        return _real_vad(audio_bytes, sample_rate)
    return _stub_vad(audio_bytes, sample_rate)


def _stub_vad(audio_bytes: bytes, sample_rate: int) -> dict:
    """
    Stub: treats entire audio chunk as speech.
    Safe passthrough that keeps the pipeline moving without GPU.
    """
    total_ms = int(len(audio_bytes) / 2 / sample_rate * 1000)  # 16-bit = 2 bytes/sample
    logger.debug("[STUB VAD] %d ms audio → marked as 100%% speech.", total_ms)
    return {
        "speech_segments": [[0, total_ms]],
        "total_duration_ms": total_ms,
        "speech_ratio": 1.0,
    }


def _real_vad(audio_bytes: bytes, sample_rate: int) -> dict:
    """
    Production VAD using Silero VAD v4.
    Requires: torch, torchaudio, silero-vad model weights.
    Enable with USE_REAL_VAD=true.
    """
    try:
        import numpy as np
        import torch

        model_path = os.getenv("SILERO_VAD_PATH", "/opt/models/silero-vad-v4")
        model, utils = torch.hub.load(  # nosec B614
            repo_or_dir=model_path,
            model="silero_vad",
            source="local",
            force_reload=False,
        )
        get_speech_timestamps = utils[0]

        # Convert bytes → float32 tensor
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio_tensor = torch.from_numpy(audio_array)

        timestamps = get_speech_timestamps(
            audio_tensor,
            model,
            threshold=_THRESHOLD,
            sampling_rate=sample_rate,
            return_seconds=False,
        )

        total_samples = len(audio_array)
        total_ms = int(total_samples / sample_rate * 1000)
        segments = [[int(t["start"] / sample_rate * 1000), int(t["end"] / sample_rate * 1000)] for t in timestamps]
        speech_samples = sum(t["end"] - t["start"] for t in timestamps)
        speech_ratio = round(speech_samples / total_samples, 3) if total_samples else 0.0

        logger.info(
            "[REAL VAD] %d ms audio → %d speech segment(s), speech ratio=%.2f",
            total_ms,
            len(segments),
            speech_ratio,
        )
        return {
            "speech_segments": segments,
            "total_duration_ms": total_ms,
            "speech_ratio": speech_ratio,
        }

    except Exception as exc:
        logger.error("[REAL VAD] Failed: %s — falling back to stub.", exc)
        return _stub_vad(audio_bytes, sample_rate)
