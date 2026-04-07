"""
courtaccess/core/translation.py

NLLB-200 translation pipeline with full text protection.

Two modes controlled by USE_REAL_TRANSLATION env var:
  false (default) — stub mode, prefixes text with language tag
  true            — real NLLB-200 via CTranslate2 (requires GPU)

Protection pipeline (real mode, steps applied in translate_one):
  Step 0:   Blank line detection    — underscore/dash fill-ins preserved as-is
  Step 0.5: Form token translation  — DATE→FECHA etc from LanguageConfig
  Step 1:   Citation extraction     — §, G.L. c., URLs → RFCT{n}RF placeholders
  Step 1.5: Court name protection   — court names → RFCN{n}RF (restores to
                                      verified target-language translation)
  Step 2:   Proper noun protection  — spaCy NER → RFPN{n}RF placeholders
  Step 3:   Preserve-only check     — skip NLLB if nothing real left to translate
  Step 4:   NLLB translation        — clean protected text translated via CTranslate2
  Step 5:   Placeholder restoration — all protected text restored
  Step 6:   Court name safety net   — catch any court names that slipped through
  Step 7:   Hallucination guard     — reject outputs with extreme length ratios

Source: Cell 6 of the original Colab script, converted to OOP.
        All logic is identical to Cell 6 — made language-aware via
        LanguageConfig instead of hardcoded Spanish values.

DESIGN NOTES:
  - spaCy (en_core_web_lg) is ALWAYS loaded in load(), regardless of
    _use_real. It is needed for proper noun protection in step 2.
  - CTranslate2 tokenizer and translator are loaded ONCE in load()
    and reused for all subsequent calls. Never reloaded per-call.
  - The four pure-function methods (_is_blank_fill_line,
    _extract_citations, _restore_placeholders, _is_preserve_only)
    are @staticmethod — they need no instance state. This allows
    direct calls as Translator._method() in tests and external code.

OUTPUT CONTRACT (translate_text):
  {
      "original":   str,
      "translated": str,
      "confidence": float
  }
"""

import ctypes
import logging
import os
import re
import time

from courtaccess.languages.base import LanguageConfig

logger = logging.getLogger(__name__)

# Language tag labels used in stub mode output
_LANG_LABELS: dict = {
    "spa_Latn": "ES",
    "por_Latn": "PT",
}

# ── Citation patterns — module-level so @staticmethod can reference directly ──
# Source: Cell 6 CITATION_PATTERNS — identical, zero changes.
CITATION_PATTERNS: list = [
    r"G\.L\.\s+c\.\s+[\d]+[A-Za-z]?",
    r"M\.G\.L\.\s+c\.\s+\d+",
    r"§\s*\d+[A-Za-z]*",
    r"Mass\.\s+R\.\s+\w+\.\s*P\.\s*\d+",
    r"\d+\s+U\.S\.C\.\s+§?\s*\d+",
    r"P\.\s*\d+\.\d+",
    r"(?<!\w)\d{4}-\w+-\d+(?!\w)",
    r"TC\d+\s*\(\d+\.\d+\)",
    r"TC\d+",
    r"LC-[A-Z\-]+",
    r"https?://\S+",
    r"www\.\S+",
    r"\b[A-Z]{2,}-\d+\b",
    r"\b(BMC|DC|TMC|HC|JC|PC|SC|RMC)\b",
]


def _cuda_available() -> bool:
    """Check CUDA availability via CTranslate2 (no torch dependency)."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class Translator:
    """
    NLLB-200 translation pipeline for court documents.

    All protection logic is language-aware via LanguageConfig.
    Court names and form tokens come from config instead of
    being hardcoded for Spanish.

    Usage:
        translator = Translator(config).load()
        translated = translator.translate_one("The defendant...", "spa_Latn")
        result     = translator.translate_text("The defendant...", "spa_Latn")
        batch      = translator.batch_translate(["text1", "text2"], "spa_Latn")
    """

    # Class-level alias so callers can use either Translator.CITATION_PATTERNS
    # or the module-level CITATION_PATTERNS — both refer to the same list.
    CITATION_PATTERNS = CITATION_PATTERNS

    # ── Initialisation ────────────────────────────────────────────────────────

    def __init__(self, config: LanguageConfig) -> None:
        from courtaccess.core.config import settings

        self.config = config
        self._use_real = str(os.getenv("USE_REAL_TRANSLATION")).lower() == "true"
        self._hallucination_max = settings.translation_hallucination_ratio_max
        self._hallucination_min = settings.translation_hallucination_ratio_min
        self._nlp = None  # spaCy — always loaded in load()
        self._tokenizer = None  # CTranslate2 tokenizer — real mode only
        self._ct2_translator = None  # CTranslate2 model — real mode only

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> "Translator":
        """
        Load all models into memory.

        spaCy (en_core_web_lg) is loaded ONLY in real mode — it is needed for
        step 2 (proper noun protection) but that step is never reached in stub
        mode (translate_one returns early at step 0.5/stub check).

        Skipping spaCy in stub mode saves 619 MB per task, which is critical
        when many DAG runs fire in parallel (e.g. 22 forms x 2 languages).

        CTranslate2 tokenizer and translator are loaded only when
        _use_real=True. They are loaded once here and reused for all
        subsequent translate_one() calls — never reloaded per-call.

        Returns self for chaining: Translator(config).load()
        """
        if self._use_real:
            t0 = time.time()
            import spacy

            self._nlp = spacy.load("en_core_web_lg")
            logger.info("spaCy en_core_web_lg loaded in %.2fs", time.time() - t0)

            model_path = os.getenv("NLLB_MODEL_PATH")
            if not model_path:
                raise RuntimeError("NLLB_MODEL_PATH is not set — cannot load AutoTokenizer or ctranslate2.Translator.")

            t1 = time.time()
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(model_path, fix_mistral_regex=False)
            logger.info("NLLB tokenizer loaded in %.2fs", time.time() - t1)

            t2 = time.time()
            import ctranslate2

            device = "cuda" if _cuda_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            self._ct2_translator = ctranslate2.Translator(
                model_path,
                device=device,
                compute_type=compute_type,
            )
            logger.info(
                "CTranslate2 NLLB model loaded in %.2fs on %s",
                time.time() - t2,
                device,
            )
        else:
            logger.debug("Stub mode — skipping spaCy/NLLB model load.")

        return self

    def unload(self) -> None:
        """
        Explicitly release memory held by the models.
        Crucial for Airflow worker processes to avoid OOM from compounding models.
        """
        import gc

        if self._ct2_translator is not None:
            try:
                self._ct2_translator.unload_model()
            except Exception as e:
                logger.debug("Error unloading ct2_translator: %s", e)
            self._ct2_translator = None

        if self._nlp is not None:
            del self._nlp
            self._nlp = None

        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None

        gc.collect()

        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception as e:
            logger.debug("malloc_trim unavailable: %s", e)

    def _ensure_loaded(self) -> None:
        """Raise RuntimeError if real-speech mode is on but models are unloaded."""
        if self._use_real and (self._nlp is None or self._tokenizer is None or self._ct2_translator is None):
            raise RuntimeError("Translator models have been unloaded. Call load() before translating.")

    def translate_one(self, text: str, target_lang: str) -> str:
        """
        Translate a single string through the full 8-step protection pipeline.
        Returns the translated string directly (not a dict).

        Used by reconstruct_pdf.py which needs strings, not dicts.

        Args:
            text:        English text to translate
            target_lang: NLLB target code e.g. "spa_Latn"

        Returns:
            Translated string, or original if preserved / guard triggered

        Source: Cell 6 translate_one() — logic identical, zero changes.
                self.config replaces hardcoded Spanish dicts.
                self._nlp replaces module-level global.
        """
        self._ensure_loaded()
        if not text or not text.strip():
            return text

        # Step 0 — preserve blank fill-in lines exactly as-is
        if self._is_blank_fill_line(text):
            return text

        # Step 0.5 — form token translation (DATE→FECHA etc)
        # Source: Cell 6 _FORM_TOKENS hardcoded dict → now from LanguageConfig
        if text.strip().upper() in self.config.form_token_translations:
            return self.config.form_token_translations[text.strip().upper()]

        if not self._use_real:
            return self._stub_translate(text, target_lang)["translated"]

        # Step 1 — protect citations with RFCT{n}RF placeholders
        protected, cite_map = self._extract_citations(text)

        # Step 1.5 — protect court names → RFCN{n}RF restores as
        #            verified target-language translation, not English
        protected, court_map = self._extract_court_names(protected)

        # Step 2 — protect proper nouns with spaCy NER → RFPN{n}RF
        protected, prop_map = self._extract_proper_nouns(protected)

        # Step 3 — if nothing real left to translate, restore and return.
        # Must pass `protected` (which contains the RFCT/RFCN/RFPN placeholders),
        # not the original `text` (which has none), so _restore_placeholders
        # can find and replace all the placeholder tokens.
        if self._is_preserve_only(protected):
            return self._restore_placeholders(protected, cite_map, court_map, prop_map)

        # Step 4 — NLLB translation via CTranslate2
        try:
            translated_raw = self._raw_nllb_translate([protected], target_lang)[0]
        except Exception as exc:
            logger.warning("NLLB error: %s — keeping original", exc)
            return text

        # Step 5 — restore all placeholders
        translated = self._restore_placeholders(translated_raw, cite_map, court_map, prop_map)

        # Step 6 — court name safety net for any that slipped through
        translated = self._apply_court_name_safety_net(translated)

        # Step 7 — hallucination guard
        ratio = len(translated) / max(len(text), 1)
        if ratio > self._hallucination_max or ratio < self._hallucination_min:
            logger.warning(
                "Hallucination guard (ratio=%.1f): '%s' — keeping original",
                ratio,
                text[:50],
            )
            return text

        return translated

    def batch_translate(self, texts: list, target_lang: str) -> list:
        """
        Translate a list of strings through the full pipeline.
        Returns list of translated strings in the same order.

        Source: Cell 6 batch_translate()
        """
        return [self.translate_one(t, target_lang) for t in texts]

    def translate_text(self, text: str, target_lang: str) -> dict:
        """
        Translate text and return the full output contract dict.
        Used by the DAG and API routes.

        Returns:
            {"original": str, "translated": str, "confidence": float}
        """
        self._ensure_loaded()
        if not self._use_real:
            return self._stub_translate(text, target_lang)

        translated = self.translate_one(text, target_lang)
        return {
            "original": text,
            "translated": translated,
            "confidence": 0.91,
        }

    # ── Private static methods — pure functions, no instance state ────────────
    # Declared @staticmethod so tests can call Translator._method(text)
    # without needing an instance. Instance calls (self._method()) still work.

    @staticmethod
    def _is_blank_fill_line(text: str) -> bool:
        """
        Detect blank fill-in lines — sequences of underscores or
        dashes used as form fill-in fields. Preserved exactly as-is.
        Examples: '_______________', '- - - - - - -'
        Does NOT match mixed lines like '___ (street address)'.

        Source: Cell 6 _is_blank_fill_line() — identical logic.
        """
        t = text.strip()
        if not t:
            return True
        if re.match(r"^[\s_\-]{4,}$", t):
            return True
        if re.match(r"^\$[\s_\-\.]{3,}$", t):
            return True
        non_blank = re.sub(r"[\s_\-]", "", t)
        return len(non_blank) == 0

    @staticmethod
    def _extract_citations(text: str) -> tuple:
        """
        Find citation patterns and replace with RFCT{n}RF placeholders.
        Returns (protected_text, {placeholder: original}).
        Iterates CITATION_PATTERNS in order; reverses matches within
        each pattern to preserve string positions.

        Source: Cell 6 _extract_citations() — identical logic.
        """
        placeholders = {}
        protected = text
        counter = 0

        for pattern in CITATION_PATTERNS:  # module-level constant
            matches = list(re.finditer(pattern, protected))
            for m in reversed(matches):
                key = f"RFCT{counter}RF"
                placeholders[key] = m.group(0)
                protected = protected[: m.start()] + key + protected[m.end() :]
                counter += 1

        return protected, placeholders

    @staticmethod
    def _restore_placeholders(text: str, *dicts) -> str:
        """
        Restore all placeholders. Uses regex fallback to handle cases
        where NLLB inserts spaces inside tokens (e.g. RFCT 0 RF).

        Source: Cell 6 _restore_placeholders() — identical logic.
        """
        result = text
        for d in dicts:
            for key, original in d.items():
                if key in result:
                    result = result.replace(key, original)
                    continue
                num = re.search(r"\d+", key)
                if num:
                    prefix = key[: key.index(num.group())]
                    suffix = key[key.index(num.group()) + len(num.group()) :]
                    pattern = re.escape(prefix) + r"\s*" + num.group() + r"\s*" + re.escape(suffix)
                    result = re.sub(
                        pattern,
                        lambda m, o=original: o,
                        result,
                        flags=re.IGNORECASE,
                    )
        return result

    @staticmethod
    def _is_preserve_only(text: str) -> bool:
        """
        Returns True if text contains only placeholders/numbers/
        punctuation with no real words left to translate.

        Strips RFCT and RFPN tokens only — NOT RFCN.
        This matches Cell 6 exactly (RFCN not included here).

        Source: Cell 6 _is_preserve_only() — identical regex.
        """
        stripped = text.strip()
        if not stripped:
            return True
        cleaned = re.sub(r"RFCT\d+RF|RFPN\d+RF", "", stripped)
        cleaned = re.sub(r"[\d\s\.\-\/\(\)\,\;\:\#\@\!\?]+", "", cleaned)
        return len(cleaned.strip()) == 0

    # ── Private instance methods — require instance state ─────────────────────

    def _extract_court_names(self, text: str) -> tuple:
        """
        Find court names and replace with RFCN{n}RF placeholders.
        Placeholders restore directly to verified target-language
        translations — NLLB never sees court names.
        Sorted longest-first to prevent partial matches.

        Uses self.config.court_name_translations.

        Source: Cell 6 _extract_court_names() — made language-aware.
        """
        placeholders = {}
        protected = text
        counter = 0

        for en_name in sorted(
            self.config.court_name_translations.keys(),
            key=lambda x: -len(x),
        ):
            matches = list(re.finditer(re.escape(en_name), protected, re.IGNORECASE))
            for m in reversed(matches):
                key = f"RFCN{counter}RF"
                placeholders[key] = self.config.court_name_translations[en_name]
                protected = protected[: m.start()] + key + protected[m.end() :]
                counter += 1

        return protected, placeholders

    def _extract_proper_nouns(self, text: str) -> tuple:
        """
        Use spaCy NER to protect proper nouns from mistranslation.
        Replaces PERSON, GPE, LOC, ORG, PRODUCT, NORP entities
        with RFPN{n}RF placeholders (restores as original English).
        Entities with function words are skipped. Min length: 3 chars.
        Processes entities in reverse order to preserve positions.

        Uses self._nlp (loaded by load()).

        Source: Cell 6 _extract_proper_nouns() — identical logic.
        """
        doc = self._nlp(text)
        placeholders = {}
        protected = text
        counter = 0

        entities = sorted(doc.ents, key=lambda e: e.start_char, reverse=True)

        for ent in entities:
            if ent.label_ not in ("PERSON", "GPE", "LOC", "ORG", "PRODUCT", "NORP"):
                continue

            ent_text = ent.text.strip()
            if len(ent_text) < 3:
                continue

            if re.match(r"^RF[A-Z]+\d+RF$", ent_text):
                continue

            words = ent_text.split()
            has_function = any(
                w.lower()
                in {
                    "the",
                    "of",
                    "in",
                    "at",
                    "for",
                    "and",
                    "or",
                    "a",
                    "an",
                    "by",
                    "to",
                    "from",
                }
                for w in words
                if not w[0].isupper()
            )
            if has_function:
                continue

            key = f"RFPN{counter}RF"
            placeholders[key] = ent_text
            protected = protected[: ent.start_char] + key + protected[ent.end_char :]
            counter += 1

        return protected, placeholders

    def _apply_court_name_safety_net(self, text: str) -> str:
        """
        Post-translation pass: replace any English court names that
        slipped through with verified target-language translations.
        Sorted longest-first to prevent partial matches.

        Uses self.config.court_name_translations.

        Source: Cell 6 _translate_court_names() — made language-aware.
        """
        result = text
        for en, translated in sorted(
            self.config.court_name_translations.items(),
            key=lambda x: -len(x[0]),
        ):
            result = re.sub(re.escape(en), translated, result, flags=re.IGNORECASE)
        return result

    def _raw_nllb_translate(self, texts: list, target_lang: str) -> list:
        self._tokenizer.src_lang = self.config.nllb_source
        tgt_id = self._tokenizer.convert_tokens_to_ids(target_lang)
        tgt_token = self._tokenizer.convert_ids_to_tokens([tgt_id])[0]

        results = []
        for text in texts:
            inputs = self._tokenizer(
                text,
                truncation=True,
                max_length=512,
            )
            token_ids = inputs["input_ids"]
            tokens = self._tokenizer.convert_ids_to_tokens(token_ids)

            out = self._ct2_translator.translate_batch(
                [tokens],
                target_prefix=[[tgt_token]],
                max_decoding_length=min(512, len(tokens) + 60),
                beam_size=2,
            )
            output_tokens = out[0].hypotheses[0][1:]
            output_ids = self._tokenizer.convert_tokens_to_ids(output_tokens)
            results.append(self._tokenizer.decode(output_ids, skip_special_tokens=True))

        return results

    def _stub_translate(self, text: str, target_lang: str) -> dict:
        """
        Stub mode — prefixes text with language tag.
        Returns full output contract dict.
        """
        tag = _LANG_LABELS.get(target_lang, target_lang)
        translated = f"[{tag}] {text}"
        logger.debug("[STUB TRANSLATE] %s → '%s'", target_lang, text[:40])
        return {
            "original": text,
            "translated": translated,
            "confidence": 0.50,
        }


# Public alias for the static method — used by reconstruct_pdf.py
is_blank_fill_line = Translator._is_blank_fill_line
