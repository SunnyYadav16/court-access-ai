"""
=============================================================================
FILE: dags/src/translate_text.py
=============================================================================
Translates a single text string between languages.

STUB IMPLEMENTATION — prefixes text with a language tag so the pipeline
runs end-to-end and output PDFs visually confirm the stub ran.

PRODUCTION UPGRADE:
  Replace _stub_translate() with NLLB-200 via CTranslate2 (INT8 quantised).
  The output dict contract must be preserved exactly.

OUTPUT CONTRACT:
  {
      "original":   str,
      "translated": str,
      "confidence": float   # 0.0-1.0
  }
=============================================================================
"""

import logging
import os

logger = logging.getLogger(__name__)

# Set USE_REAL_TRANSLATION=true to enable the production model.
# NOTE: Production model requires GPU + significant RAM — do not enable locally.
_USE_REAL = os.getenv("USE_REAL_TRANSLATION", "false").lower() == "true"

# Human-readable labels for the stub prefix
_LANG_LABELS = {
    "spa_Latn": "ES",
    "por_Latn": "PT",
}


def translate_text(text: str, source_lang: str, target_lang: str) -> dict:
    """
    Translate text from source_lang to target_lang.
    NOTE: STUB — prefixes text with language tag.
    Replace with NLLB-200 in production.
    """
    if _USE_REAL:
        return _real_translate(text, source_lang, target_lang)
    return _stub_translate(text, source_lang, target_lang)


def _stub_translate(text: str, source_lang: str, target_lang: str) -> dict:
    """
    Stub: prefix text with language tag so translated PDFs are visually
    distinguishable from the original.
    NOTE: NOT a real translation — for pipeline testing only.
    """
    tag = _LANG_LABELS.get(target_lang, target_lang)
    translated = f"[{tag}] {text}"
    logger.debug("[STUB TRANSLATE] %s→%s: '%s…'", source_lang, target_lang, text[:30])
    return {"original": text, "translated": translated, "confidence": 0.50}


def _real_translate(text: str, source_lang: str, target_lang: str) -> dict:
    """
    Production translation via NLLB-200 + CTranslate2.
    NOTE: NOT active in stub mode. Requires GPU, ~3GB VRAM.
    Enable by setting USE_REAL_TRANSLATION=true in the container environment.
    """
    try:
        import ctranslate2
        from transformers import AutoTokenizer

        model_path = os.getenv(
            "NLLB_MODEL_PATH",
            "/opt/models/nllb-200-distilled-1.3B-ct2",
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        translator = ctranslate2.Translator(model_path, device="cpu")

        tokenizer.src_lang = source_lang
        inputs = tokenizer(text, return_tensors="pt")
        tgt_id = tokenizer.convert_tokens_to_ids(target_lang)
        results = translator.translate_batch(
            [inputs["input_ids"][0].tolist()],
            target_prefix=[[tgt_id]],
        )
        ids = results[0].hypotheses[0][1:]
        translated = tokenizer.decode(ids, skip_special_tokens=True)
        return {"original": text, "translated": translated, "confidence": 0.91}

    except Exception as exc:
        logger.error("[REAL TRANSLATE] Failed: %s — falling back to stub.", exc)
        return _stub_translate(text, source_lang, target_lang)
