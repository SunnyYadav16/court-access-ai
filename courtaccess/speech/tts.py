"""
courtaccess/speech/tts.py

Text-to-Speech using Piper TTS.
Generates spoken audio from translated text in Spanish or Portuguese.

STUB/REAL HYBRID:
  - Stub: returns silent WAV bytes (44-byte WAV header only).
  - Real: runs Piper TTS subprocess with language-specific voice model.

PRODUCTION NOTES:
  - CPU-only: Piper is fast enough on CPU (~50ms for short phrases).
  - Languages: "spa_Latn" → piper-tts-es, "por_Latn" → piper-tts-pt.
  - Enable with USE_REAL_TTS=true.

OUTPUT CONTRACT:
  {
      "audio_bytes": bytes,   # WAV audio bytes (16kHz, 16-bit, mono)
      "duration_ms": int,
      "language":    str,
  }
"""

import os
import struct

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

_USE_REAL = os.getenv("USE_REAL_TTS", "false").lower() == "true"
_LANGUAGE_TO_MODEL = {
    "spa_Latn": os.getenv("PIPER_TTS_ES_PATH", "/opt/airflow/models/piper-tts-es"),
    "por_Latn": os.getenv("PIPER_TTS_PT_PATH", "/opt/airflow/models/piper-tts-pt"),
}
_SAMPLE_RATE = 16000


def synthesize_speech(text: str, language: str) -> dict:
    """
    Convert translated text to spoken audio.

    Args:
        text:     Translated text to synthesize.
        language: Target language NLLB code ("spa_Latn" or "por_Latn").

    Returns:
        Dict matching OUTPUT CONTRACT above.
    """
    if _USE_REAL:
        return _real_tts(text, language)
    return _stub_tts(text, language)


def _stub_tts(text: str, language: str) -> dict:
    """
    Stub: returns a minimal valid WAV (header-only, 0 audio samples).
    Allows the pipeline to complete without Piper installed.
    """
    wav_header = _make_wav_header(num_samples=0)
    logger.debug("[STUB TTS] lang=%s, text_len=%d → silent WAV.", language, len(text))
    return {"audio_bytes": wav_header, "duration_ms": 0, "language": language}


def _real_tts(text: str, language: str) -> dict:
    """
    Production TTS using Piper subprocess.
    Pipes text to piper binary which writes WAV to stdout.

    REQUIRES:
        - piper binary installed in container
        - Voice model at PIPER_TTS_ES_PATH or PIPER_TTS_PT_PATH
        - USE_REAL_TTS=true
    """
    import subprocess
    import tempfile

    model_path = _LANGUAGE_TO_MODEL.get(language)
    if not model_path:
        logger.warning("[REAL TTS] Unsupported language '%s' — falling back to stub.", language)
        return _stub_tts(text, language)

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        subprocess.run(  # noqa: S603
            ["piper", "--model", model_path, "--output_file", tmp_path],  # noqa: S607
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
            check=True,
        )

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        os.unlink(tmp_path)

        # Estimate duration from WAV file size
        num_samples = max(0, (len(audio_bytes) - 44) // 2)  # 44-byte header, 16-bit
        duration_ms = int(num_samples / _SAMPLE_RATE * 1000)

        logger.info(
            "[REAL TTS] lang=%s, text_len=%d → %d ms audio.",
            language,
            len(text),
            duration_ms,
        )
        return {"audio_bytes": audio_bytes, "duration_ms": duration_ms, "language": language}

    except Exception as exc:
        logger.error("[REAL TTS] Piper failed: %s — falling back to stub.", exc)
        return _stub_tts(text, language)


def _make_wav_header(num_samples: int, channels: int = 1, bits: int = 16) -> bytes:
    """Build a minimal PCM WAV header for num_samples of audio."""
    data_size = num_samples * channels * (bits // 8)
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        channels,
        _SAMPLE_RATE,
        _SAMPLE_RATE * channels * (bits // 8),
        channels * (bits // 8),
        bits,
        b"data",
        data_size,
    )
