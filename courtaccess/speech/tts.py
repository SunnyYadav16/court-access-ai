"""
Text-to-Speech service using Piper TTS.

This module provides a singleton TTSService that:
 1. Downloads Piper ONNX voice models from Hugging Face (first run).
 2. Loads a PiperVoice instance per language (en, es, pt).
 3. Exposes a `synthesize(text, language) -> bytes` method that returns
    complete WAV audio bytes ready to send over WebSocket.

Voice models used:
 - en: en_US-lessac-medium  (22 050 Hz, ~40 MB)
 - es: es_ES-davefx-medium  (22 050 Hz, ~40 MB)
 - pt: pt_BR-faber-medium   (22 050 Hz, ~40 MB)
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

_DEFAULT_VOICES_DIR = str(Path(__file__).parent.parent.parent / "models" / "piper-voices")


def _get_voices_dir() -> Path:
    """Resolve voice directory from settings (lazy, not at import time)."""
    s = get_settings()
    return Path(s.piper_voices_dir or _DEFAULT_VOICES_DIR)


def _get_lang_path_overrides() -> dict[str, str | None]:
    """Resolve per-language path overrides from settings."""
    s = get_settings()
    return {
        "en": s.piper_tts_en_path,
        "es": s.piper_tts_es_path,
        "pt": s.piper_tts_pt_path,
    }


# HuggingFace repo and base URL for voice downloads
_HF_REPO = "rhasspy/piper-voices"
_HF_BRANCH = "v1.0.0"

# Mapping: short lang code -> (onnx_relative_path, config_relative_path)
# Paths are relative to the HF repo root.
VOICE_MAP: dict[str, dict] = {
    "en": {
        "name": "en_US-lessac-medium",
        "onnx_path": "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json_path": "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "es": {
        "name": "es_ES-davefx-medium",
        "onnx_path": "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        "json_path": "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json",
    },
    "pt": {
        "name": "pt_BR-faber-medium",
        "onnx_path": "pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        "json_path": "pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx.json",
    },
}

SUPPORTED_LANGUAGES = set(VOICE_MAP.keys())


# ---------------------------------------------------------------------------
#  Download helper
# ---------------------------------------------------------------------------


def _download_voice(lang: str) -> Path:
    """Download the ONNX model + config JSON for *lang* from Hugging Face.

    If a per-language path override is set via PIPER_TTS_{EN,ES,PT}_PATH,
    the model is loaded from that directory instead of downloading.
    """
    info = VOICE_MAP[lang]
    name = info["name"]

    # Check per-language env var override (matches docker-compose convention)
    override = _get_lang_path_overrides().get(lang)
    if override:
        override_dir = Path(override)
        override_onnx = override_dir / f"{name}.onnx"
        if override_onnx.exists():
            return override_onnx
        # Also check if the .onnx file lives directly in the override dir
        # under a different name (glob for any .onnx file)
        onnx_files = list(override_dir.glob("*.onnx"))
        if onnx_files:
            return onnx_files[0]
        logger.warning("Override path %s set but no .onnx found; falling back to download", override)

    from huggingface_hub import hf_hub_download

    dest_dir = _get_voices_dir() / name
    dest_dir.mkdir(parents=True, exist_ok=True)

    onnx_local = dest_dir / f"{name}.onnx"
    json_local = dest_dir / f"{name}.onnx.json"

    if onnx_local.exists() and json_local.exists():
        return onnx_local

    logger.info("Downloading voice model '%s' ...", name)

    # Download ONNX model
    downloaded_onnx = hf_hub_download(
        repo_id=_HF_REPO,
        filename=info["onnx_path"],
        revision=_HF_BRANCH,
        local_dir=str(dest_dir),
    )
    # Move to expected location if huggingface_hub nested it
    dl_onnx = Path(downloaded_onnx)
    if dl_onnx != onnx_local:
        onnx_local.parent.mkdir(parents=True, exist_ok=True)
        dl_onnx.rename(onnx_local)

    # Download config JSON
    downloaded_json = hf_hub_download(
        repo_id=_HF_REPO,
        filename=info["json_path"],
        revision=_HF_BRANCH,
        local_dir=str(dest_dir),
    )
    dl_json = Path(downloaded_json)
    if dl_json != json_local:
        json_local.parent.mkdir(parents=True, exist_ok=True)
        dl_json.rename(json_local)

    logger.info("Voice '%s' downloaded -> %s", name, dest_dir)
    return onnx_local


# ---------------------------------------------------------------------------
#  TTSService (singleton)
# ---------------------------------------------------------------------------


class TTSService:
    """
    Text-to-Speech service powered by Piper TTS.

    One PiperVoice is loaded per language and reused across requests.
    Voice models are downloaded automatically on first use.
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
        """Download (if needed) and load all voice models."""
        _get_voices_dir().mkdir(parents=True, exist_ok=True)

        for lang in VOICE_MAP:
            onnx_path = _download_voice(lang)
            config_path = onnx_path.with_suffix(".onnx.json")

            logger.info("Loading voice for '%s' from %s ...", lang, onnx_path.name)
            voice = PiperVoice.load(
                str(onnx_path),
                config_path=str(config_path),
                use_cuda=False,
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
        sentence_silence: float = 0.2,
    ) -> bytes:
        """
        Synthesize *text* into WAV audio bytes using the voice for *language*.

        Args:
            text: The text to speak.
            language: Short language code ("en", "es", "pt").
            length_scale: Speaking rate (1.0 = normal, <1 = faster, >1 = slower).
            sentence_silence: Seconds of silence between sentences.

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
            sentence_silence=sentence_silence,
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
