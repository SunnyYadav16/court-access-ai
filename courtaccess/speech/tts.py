"""
Text-to-Speech service using Piper TTS.

This module provides a singleton TTSService that:
 1. Resolves Piper ONNX voice model paths from GCS-pulled local directories.
 2. Loads a PiperVoice instance per language (en, es, pt).
 3. Exposes a `synthesize(text, language) -> bytes` method that returns
    complete WAV audio bytes ready to send over WebSocket.

Voice models are NOT downloaded at runtime. They are downloaded once by
scripts/setup_models.sh, pushed to gs://courtaccess-ai-models via DVC,
and pulled to local disk via `dvc pull` before container startup.

Voice models used:
 - en: en_US-lessac-medium  (22 050 Hz, ~40 MB)  → PIPER_TTS_EN_PATH
 - es: es_ES-davefx-medium  (22 050 Hz, ~40 MB)  → PIPER_TTS_ES_PATH
 - pt: pt_BR-faber-medium   (22 050 Hz, ~40 MB)  → PIPER_TTS_PT_PATH
"""

import io
import wave
from pathlib import Path
from typing import Optional

from piper import PiperVoice
from piper.config import SynthesisConfig

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
#  Voice model registry
# ---------------------------------------------------------------------------

# Mapping: short lang code -> expected voice name (used to find the .onnx file
# when the directory contains exactly the voice setup_models.sh placed there).
# The name is a hint for logging — actual resolution globs for any .onnx file
# so a different-named voice still works as long as there is exactly one.
VOICE_MAP: dict[str, dict] = {
    "en": {"name": "en_US-lessac-medium"},
    "es": {"name": "es_ES-davefx-medium"},
    "pt": {"name": "pt_BR-faber-medium"},
}

SUPPORTED_LANGUAGES = set(VOICE_MAP.keys())


def _get_lang_path_overrides() -> dict[str, str | None]:
    """Resolve per-language path overrides from settings."""
    s = get_settings()
    return {
        "en": s.piper_tts_en_path,
        "es": s.piper_tts_es_path,
        "pt": s.piper_tts_pt_path,
    }


# ---------------------------------------------------------------------------
#  Path resolver  (replaces the old _download_voice downloader)
# ---------------------------------------------------------------------------


def _resolve_voice_path(lang: str) -> Path:
    """Resolve the local .onnx path for *lang* from GCS-pulled model directory.

    Reads PIPER_TTS_{EN,ES,PT}_PATH from settings (set via env vars in
    docker-compose / GCP VM).  The directory must already exist on disk —
    populated by `dvc pull` before container startup.

    Resolution order:
      1. Check <override_dir>/<expected_name>.onnx  (exact name match)
      2. Glob <override_dir>/*.onnx                 (any .onnx in the dir)
      3. Fail fast with a clear RuntimeError

    No network calls are made. No fallback downloads. If the file is
    missing, the container should not start — the caller will surface the
    error at TTSService init time so the problem is visible immediately.

    Args:
        lang: Short language code — "en", "es", or "pt".

    Returns:
        Path to the resolved .onnx file.

    Raises:
        RuntimeError: If the env var is unset, the directory is missing,
                      or no .onnx file is found inside it.
    """
    override = _get_lang_path_overrides().get(lang)
    expected_name = VOICE_MAP[lang]["name"]

    if not override:
        raise RuntimeError(
            f"PIPER_TTS_{lang.upper()}_PATH is not set. "
            f"Run 'dvc pull' to download the model from GCS, then set "
            f"PIPER_TTS_{lang.upper()}_PATH to the models/piper-tts-{lang}/ directory."
        )

    override_dir = Path(override)

    if not override_dir.is_dir():
        raise RuntimeError(
            f"Piper TTS directory for '{lang}' not found at: {override_dir}\n"
            "Run 'dvc pull' to download the model from GCS."
        )

    # 1. Exact name match (the normal case after setup_models.sh)
    exact = override_dir / f"{expected_name}.onnx"
    if exact.is_file():
        return exact

    # 2. Any .onnx in the directory (supports alternate voice names)
    onnx_files = sorted(override_dir.glob("*.onnx"))
    if onnx_files:
        if len(onnx_files) > 1:
            logger.warning(
                "Multiple .onnx files found in %s — using %s. Remove unused voices to avoid ambiguity.",
                override_dir,
                onnx_files[0].name,
            )
        return onnx_files[0]

    raise RuntimeError(
        f"No .onnx voice file found in {override_dir}.\n"
        f"Expected: {expected_name}.onnx\n"
        "Run 'dvc pull' to restore the model from GCS."
    )


# ---------------------------------------------------------------------------
#  TTSService (singleton)
# ---------------------------------------------------------------------------


class TTSService:
    """
    Text-to-Speech service powered by Piper TTS.

    One PiperVoice is loaded per language and reused across requests.
    Voice models are resolved from GCS-pulled local directories — never
    downloaded at runtime.
    """

    _instance: Optional["TTSService"] = None
    _voices: dict | None = None  # Initialized in __init__, not at class level

    def __new__(cls) -> "TTSService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if TTSService._voices is None:
            TTSService._voices = {}
            self._load_voices()

    # ------------------------------------------------------------------ #
    #  Voice loading                                                      #
    # ------------------------------------------------------------------ #

    def _load_voices(self) -> None:
        """Resolve paths and load all voice models from local disk."""
        import torch

        use_cuda = torch.cuda.is_available()

        for lang in VOICE_MAP:
            onnx_path = _resolve_voice_path(lang)
            config_path = onnx_path.with_suffix(".onnx.json")

            if not config_path.is_file():
                raise RuntimeError(
                    f"Piper config JSON not found alongside {onnx_path.name}.\n"
                    f"Expected: {config_path}\n"
                    "Run 'dvc pull' to restore the model from GCS."
                )

            logger.info("Loading voice for '%s' from %s (CUDA=%s) ...", lang, onnx_path.name, use_cuda)
            voice = PiperVoice.load(
                str(onnx_path),
                config_path=str(config_path),
                use_cuda=use_cuda,
            )
            TTSService._voices[lang] = voice
            logger.info("Voice '%s' ready", lang)

        logger.info("All %d voices loaded", len(TTSService._voices))

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def synthesize(
        self,
        text: str,
        language: str,
        length_scale: float = 1.0,
    ) -> bytes:
        """
        Synthesize *text* into WAV audio bytes using the voice for *language*.

        Args:
            text: The text to speak.
            language: Short language code ("en", "es", "pt").
            length_scale: Speaking rate (1.0 = normal, <1 = faster, >1 = slower).

        Returns:
            Complete WAV file as bytes (16-bit PCM mono, sample rate
            depends on the voice model — typically 22 050 Hz).
            Returns empty bytes if language unsupported or text is empty.
        """
        if not text or not text.strip():
            return b""

        voice = TTSService._voices.get(language)
        if voice is None:
            logger.warning("No voice loaded for language '%s'", language)
            return b""

        syn_config = SynthesisConfig(
            length_scale=length_scale,
        )

        # Synthesize into an in-memory WAV buffer.
        # synthesize_wav() sets channels/sample_rate/sample_width on the
        # wave.Wave_write before writing audio data.
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file, syn_config=syn_config)

        return buf.getvalue()


# ---------------------------------------------------------------------------
#  Module-level accessor
# ---------------------------------------------------------------------------

_tts_service: TTSService | None = None


def get_tts_service() -> TTSService:
    """Get or create the global TTS service singleton."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
