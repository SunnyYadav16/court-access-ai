"""
courtaccess/speech/mt_service.py

Machine Translation service using CTranslate2 + NLLB-200.

Provides a singleton MTService that:
  1. Downloads facebook/nllb-200-distilled-1.3B from Hugging Face (first run).
  2. Converts it to an optimised CTranslate2 int8 model (one-time, ~5 min).
  3. Loads the CTranslate2 Translator for fast CPU/GPU inference.
  4. Exposes a simple `translate(text, source_lang, target_lang) -> str` method.

Language codes follow the short ISO 639-1 codes used by the rest of the
speech pipeline ("en", "es", "pt").  Internally these are mapped to the
NLLB Flores-200 BCP-47 codes (e.g. "eng_Latn", "spa_Latn", "por_Latn").

Note: this is the *speech-pipeline* MT service.  The document pipeline uses
courtaccess.core.translation (batch, sync, glossary-injected).  They coexist.

Config (via courtaccess.core.config.Settings):
  NLLB_MODEL        — HuggingFace model name (default: facebook/nllb-200-distilled-1.3B)
  NLLB_MODEL_PATH    — path to pre-converted CTranslate2 directory; if unset,
                       auto-converts from HuggingFace on first run (one-time op).

Model loading is triggered on first instantiation; gate calls behind
USE_REAL_SPEECH=true at the API startup level.
"""

import subprocess
from pathlib import Path
from typing import Optional

import ctranslate2
import transformers

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
#  Language code mapping: short (pipeline) <-> NLLB Flores-200
# ---------------------------------------------------------------------------

LANG_CODE_TO_NLLB: dict[str, str] = {
    "en": "eng_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
}

NLLB_TO_LANG_CODE: dict[str, str] = {v: k for k, v in LANG_CODE_TO_NLLB.items()}

SUPPORTED_LANGUAGES = set(LANG_CODE_TO_NLLB.keys())

# ---------------------------------------------------------------------------
#  Model paths (resolved lazily from Settings)
# ---------------------------------------------------------------------------

_default_ct2_dir = str(Path(__file__).parent.parent.parent / "models" / "nllb-200-distilled-1.3B-ct2")


def _get_hf_model_name() -> str:
    return get_settings().nllb_model


def _get_ct2_model_dir() -> Path:
    s = get_settings()
    return Path(s.nllb_model_path or _default_ct2_dir)


# ---------------------------------------------------------------------------
#  MTService (singleton)
# ---------------------------------------------------------------------------


class MTService:
    """
    Machine Translation service powered by CTranslate2 + NLLB-200.

    The CTranslate2 Translator and the HF tokenizer are loaded once and
    reused across all requests.  The model is automatically converted from
    Hugging Face format on the very first run (requires network access and
    ~5 minutes).  Pre-converted weights via NLLB_MODEL_PATH env var skip this step.
    """

    _instance: Optional["MTService"] = None
    _translator: ctranslate2.Translator | None = None
    _tokenizer: transformers.AutoTokenizer | None = None

    def __new__(cls) -> "MTService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if MTService._translator is None:
            self._load_model()

    # ------------------------------------------------------------------ #
    #  Model loading / conversion                                         #
    # ------------------------------------------------------------------ #

    def _load_model(self) -> None:
        hf_model = _get_hf_model_name()
        ct2_model_dir = _get_ct2_model_dir()
        ct2_dir = str(ct2_model_dir)

        # One-time conversion from Hugging Face -> CTranslate2 (int8)
        if not ct2_model_dir.exists():
            logger.info("Converting %s to CTranslate2 format (one-time, ~2.5 GB download)...", hf_model)
            ct2_model_dir.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    "ct2-transformers-converter",
                    "--model",
                    hf_model,
                    "--output_dir",
                    ct2_dir,
                    "--quantization",
                    "int8",
                    "--force",
                ],
                check=True,
            )
            logger.info("Conversion complete -> %s", ct2_dir)

        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        # float16 on GPU: fast, low VRAM, full quality
        # int8    on CPU: best CPU speed/accuracy balance for NLLB
        compute_type = "float16" if device == "cuda" else "int8"

        logger.info("Loading CTranslate2 translator (%s, %s)...", device, compute_type)
        MTService._translator = ctranslate2.Translator(
            ct2_dir,
            device=device,
            compute_type=compute_type,
        )

        logger.info("Loading tokenizer from %s...", hf_model)
        # Explicitly load tokenizer without attempting mistake-prone token regex fixes
        MTService._tokenizer = transformers.AutoTokenizer.from_pretrained(hf_model, fix_mistral_regex=False)
        logger.info("Translation model ready")

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @property
    def translator(self) -> ctranslate2.Translator:
        assert MTService._translator is not None, "MT translator not loaded"  # noqa: S101
        return MTService._translator

    @property
    def tokenizer(self) -> transformers.AutoTokenizer:
        assert MTService._tokenizer is not None, "MT tokenizer not loaded"  # noqa: S101
        return MTService._tokenizer

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """
        Translate *text* from *source_lang* to *target_lang*.

        Args:
            text: The string to translate.
            source_lang: Short language code ("en", "es", "pt").
            target_lang: Short language code ("en", "es", "pt").

        Returns:
            Translated string.  Returns the original text unchanged if the
            language pair is unsupported or the languages are the same.
        """
        if not text or not text.strip():
            return ""
        if source_lang == target_lang:
            return text

        src_nllb = LANG_CODE_TO_NLLB.get(source_lang)
        tgt_nllb = LANG_CODE_TO_NLLB.get(target_lang)
        if not src_nllb or not tgt_nllb:
            logger.warning("Unsupported language pair: %s -> %s", source_lang, target_lang)
            return text

        tokenizer = self.tokenizer
        translator = self.translator

        tokenizer.src_lang = src_nllb

        source_tokens = tokenizer.convert_ids_to_tokens(tokenizer.encode(text))
        target_prefix = [tgt_nllb]

        results = translator.translate_batch(
            [source_tokens],
            target_prefix=[target_prefix],
            beam_size=4,
            max_decoding_length=256,
        )

        # First hypothesis; skip the leading language token
        target_tokens = results[0].hypotheses[0][1:]

        # Strip special tokens before decoding
        special = {"</s>", "<s>", "<unk>", "<pad>"} | set(LANG_CODE_TO_NLLB.values())
        target_tokens = [t for t in target_tokens if t not in special]

        translated = tokenizer.decode(tokenizer.convert_tokens_to_ids(target_tokens))
        return translated.strip()


# ---------------------------------------------------------------------------
#  Module-level accessor
# ---------------------------------------------------------------------------

_mt_service: MTService | None = None


def get_mt_service() -> MTService:
    """Get or create the global MT service singleton."""
    global _mt_service
    if _mt_service is None:
        _mt_service = MTService()
    return _mt_service
