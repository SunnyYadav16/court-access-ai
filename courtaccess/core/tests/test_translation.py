"""
Unit tests for courtaccess/core/translation.py

Classes/functions under test:
  Translator._is_blank_fill_line  — static, pure function
  Translator._extract_citations   — static, pure function
  Translator._restore_placeholders — static, pure function
  Translator._is_preserve_only    — static, pure function
  Translator (stub mode)          — load/translate/batch/unload lifecycle
  Translator._extract_court_names — instance method, language-aware
  Translator._apply_court_name_safety_net — instance method

Design notes:
  - All tests run in stub mode (USE_REAL_TRANSLATION not set in os.environ →
    str(None).lower() != "true"). This means load() skips spaCy/CTranslate2 —
    no GPU or model files are needed.
  - Static method tests call Translator.<method>() directly without a Translator
    instance; instance tests use the `translator` fixture (stub mode).
  - LanguageConfig is constructed with minimal inline values — no language
    module files are imported. Tests remain isolated from the languages package.
  - Translator.__init__ imports config.py at call time. The five env vars
    missing from .env are supplied here so the singleton loads successfully.
"""

import os

# Supply defaults for the five fields missing from .env — must precede config import.
_MISSING = {
    "GCS_BUCKET_TRANSCRIPTS": "test-transcripts",
    "USE_REAL_SPEECH": "false",
    "ROOM_JWT_SECRET": "test-jwt-secret",
    "ROOM_JWT_EXPIRY_HOURS": "24",
    "ROOM_CODE_EXPIRY_MINUTES": "10",
}
for _k, _v in _MISSING.items():
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402

from courtaccess.core.translation import Translator  # noqa: E402
from courtaccess.languages.base import LanguageConfig  # noqa: E402

# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def lang_config():
    """Minimal LanguageConfig for Spanish — inline, no file I/O."""
    return LanguageConfig(
        code="spanish",
        display_name="Spanish (Español)",
        nllb_source="eng_Latn",
        nllb_target="spa_Latn",
        glossary_path="/dev/null",
        court_name_translations={
            "Boston Municipal Court": "Tribunal Municipal de Boston",
            "District Court": "Tribunal de Distrito",
            "Housing Court": "Tribunal de Vivienda",
        },
        form_token_translations={
            "DATE": "FECHA",
            "SIGNATURE": "FIRMA",
            "SIGN": "FIRMAR",
        },
    )


@pytest.fixture()
def translator(lang_config, monkeypatch):
    """
    Stub-mode Translator, loaded.

    pytest-dotenv loads .env into os.environ at session start, including
    USE_REAL_TRANSLATION=true. We force-override to 'false' here so that
    Translator.__init__ (which reads os.getenv directly) stays in stub mode
    — no GPU or model files are needed.
    """
    monkeypatch.setenv("USE_REAL_TRANSLATION", "false")
    return Translator(lang_config).load()


# ─────────────────────────────────────────────────────────────────────────────
# _is_blank_fill_line — @staticmethod, pure predicate
# ─────────────────────────────────────────────────────────────────────────────


class TestIsBlankFillLine:
    def test_empty_string_is_blank(self):
        assert Translator._is_blank_fill_line("") is True

    def test_whitespace_only_is_blank(self):
        assert Translator._is_blank_fill_line("   ") is True

    def test_long_underscores_is_blank(self):
        assert Translator._is_blank_fill_line("_______________") is True

    def test_long_dashes_is_blank(self):
        assert Translator._is_blank_fill_line("-----------") is True

    def test_spaced_dashes_is_blank(self):
        assert Translator._is_blank_fill_line("- - - - - -") is True

    def test_dollar_with_underscores_is_blank(self):
        # Step 3: ^\$[\s_\-\.]{3,}$
        assert Translator._is_blank_fill_line("$___") is True

    def test_dollar_with_dots_is_blank(self):
        assert Translator._is_blank_fill_line("$...") is True

    def test_mixed_underscores_spaces_is_blank(self):
        # non_blank = re.sub([\s_\-], "", t) → ""
        assert Translator._is_blank_fill_line("_ _ _") is True

    def test_real_word_is_not_blank(self):
        assert Translator._is_blank_fill_line("Name") is False

    def test_mixed_underscore_and_text_is_not_blank(self):
        # "_____ (street address)" — has letters
        assert Translator._is_blank_fill_line("_____ (street address)") is False

    def test_number_is_not_blank(self):
        assert Translator._is_blank_fill_line("123") is False

    def test_module_alias_matches_static_method(self):
        # The module-level `is_blank_fill_line` alias should be the same function
        from courtaccess.core.translation import is_blank_fill_line

        assert is_blank_fill_line is Translator._is_blank_fill_line


# ─────────────────────────────────────────────────────────────────────────────
# _extract_citations — @staticmethod
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractCitations:
    def test_no_citations_returns_text_unchanged(self):
        text = "The defendant failed to appear."
        protected, cite_map = Translator._extract_citations(text)
        assert protected == text
        assert cite_map == {}

    def test_gl_citation_replaced_with_placeholder(self):
        text = "See G.L. c. 123 for details."
        protected, cite_map = Translator._extract_citations(text)
        assert "G.L. c. 123" not in protected
        assert len(cite_map) == 1
        assert "G.L. c. 123" in cite_map.values()

    def test_url_replaced_with_placeholder(self):
        text = "Visit https://www.courts.ma.gov for more."
        protected, cite_map = Translator._extract_citations(text)
        assert "https://www.courts.ma.gov" not in protected
        assert len(cite_map) == 1

    def test_section_symbol_replaced(self):
        text = "See § 12A for the rule."
        protected, cite_map = Translator._extract_citations(text)
        assert "§ 12A" not in protected
        assert "§ 12A" in cite_map.values()

    def test_multiple_citations_get_distinct_placeholders(self):
        text = "See G.L. c. 90 and G.L. c. 45."
        _, cite_map = Translator._extract_citations(text)
        # Two different G.L. citations → two entries
        assert len(cite_map) == 2
        keys = list(cite_map.keys())
        assert keys[0] != keys[1]

    def test_placeholder_key_format_is_rfct_number_rf(self):
        text = "Under G.L. c. 10."
        _, cite_map = Translator._extract_citations(text)
        for key in cite_map:
            assert key.startswith("RFCT")
            assert key.endswith("RF")

    def test_placeholder_present_in_protected_text(self):
        text = "Under § 5 of the act."
        protected, cite_map = Translator._extract_citations(text)
        for key in cite_map:
            assert key in protected

    def test_court_code_replaced(self):
        # Pattern: \b(BMC|DC|TMC|HC|JC|PC|SC|RMC)\b
        text = "Filed at BMC on record."
        protected, cite_map = Translator._extract_citations(text)
        assert "BMC" not in protected
        assert "BMC" in cite_map.values()


# ─────────────────────────────────────────────────────────────────────────────
# _restore_placeholders — @staticmethod
# ─────────────────────────────────────────────────────────────────────────────


class TestRestorePlaceholders:
    def test_exact_placeholder_replaced(self):
        result = Translator._restore_placeholders(
            "Call RFCT0RF for info.",
            {"RFCT0RF": "G.L. c. 90"},
        )
        assert result == "Call G.L. c. 90 for info."

    def test_multiple_placeholders_all_restored(self):
        result = Translator._restore_placeholders(
            "See RFCT0RF and RFCT1RF.",
            {"RFCT0RF": "G.L. c. 10", "RFCT1RF": "§ 4"},
        )
        assert "RFCT0RF" not in result
        assert "RFCT1RF" not in result
        assert "G.L. c. 10" in result
        assert "§ 4" in result

    def test_multiple_dicts_all_restored(self):
        result = Translator._restore_placeholders(
            "RFCT0RF RFCN0RF",
            {"RFCT0RF": "§ 10"},
            {"RFCN0RF": "Tribunal Municipal"},
        )
        assert "§ 10" in result
        assert "Tribunal Municipal" in result

    def test_empty_dicts_leave_text_unchanged(self):
        result = Translator._restore_placeholders("hello world", {}, {})
        assert result == "hello world"

    def test_space_corrupted_token_restored_via_regex(self):
        # NLLB sometimes inserts spaces: "RFCT 0 RF" → should still restore
        result = Translator._restore_placeholders(
            "Call RFCT 0 RF for info.",
            {"RFCT0RF": "G.L. c. 90"},
        )
        assert "G.L. c. 90" in result

    def test_no_match_leaves_placeholder_intact(self):
        # A placeholder not in any dict stays as-is
        result = Translator._restore_placeholders(
            "See RFCT99RF here.",
            {"RFCT0RF": "§ 10"},  # different number
        )
        assert "RFCT99RF" in result


# ─────────────────────────────────────────────────────────────────────────────
# _is_preserve_only — @staticmethod
# ─────────────────────────────────────────────────────────────────────────────


class TestIsPreserveOnly:
    def test_empty_string_is_preserve_only(self):
        assert Translator._is_preserve_only("") is True

    def test_whitespace_only_is_preserve_only(self):
        assert Translator._is_preserve_only("   ") is True

    def test_rfct_placeholder_only_is_preserve_only(self):
        assert Translator._is_preserve_only("RFCT0RF") is True

    def test_rfpn_placeholder_only_is_preserve_only(self):
        assert Translator._is_preserve_only("RFPN2RF") is True

    def test_numbers_only_is_preserve_only(self):
        assert Translator._is_preserve_only("123 456") is True

    def test_punctuation_only_is_preserve_only(self):
        assert Translator._is_preserve_only("... --- !!") is True

    def test_real_word_not_preserve_only(self):
        assert Translator._is_preserve_only("The defendant") is False

    def test_placeholder_with_real_word_not_preserve_only(self):
        assert Translator._is_preserve_only("RFCT0RF defendant") is False

    def test_rfcn_not_stripped_leaves_non_preserve(self):
        # _is_preserve_only strips RFCT/RFPN but NOT RFCN — RFCN letters
        # remain after stripping → len > 0 → False
        assert Translator._is_preserve_only("RFCN0RF") is False

    def test_multiple_rfct_and_rfpn_together_is_preserve_only(self):
        assert Translator._is_preserve_only("RFCT0RF RFPN1RF RFCT2RF") is True


# ─────────────────────────────────────────────────────────────────────────────
# Translator — stub mode lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslatorStubMode:
    def test_load_returns_self(self, translator):
        # Chaining: Translator(config).load() returns the same instance
        assert isinstance(translator, Translator)

    def test_stub_mode_does_not_load_nlp(self, translator):
        assert translator._nlp is None

    def test_stub_mode_does_not_load_tokenizer(self, translator):
        assert translator._tokenizer is None

    def test_stub_mode_does_not_load_ct2_translator(self, translator):
        assert translator._ct2_translator is None


# ─────────────────────────────────────────────────────────────────────────────
# translate_text — output contract (stub mode)
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslateTextContract:
    def test_returns_dict_with_three_keys(self, translator):
        result = translator.translate_text("Hello court.", "spa_Latn")
        assert set(result.keys()) == {"original", "translated", "confidence"}

    def test_original_field_matches_input(self, translator):
        result = translator.translate_text("Court order.", "spa_Latn")
        assert result["original"] == "Court order."

    def test_confidence_is_float(self, translator):
        result = translator.translate_text("Some text.", "spa_Latn")
        assert isinstance(result["confidence"], float)

    def test_stub_confidence_is_0_5(self, translator):
        result = translator.translate_text("Some text.", "spa_Latn")
        assert result["confidence"] == 0.50

    def test_translated_prefixed_with_es_for_spanish(self, translator):
        result = translator.translate_text("Hello.", "spa_Latn")
        assert result["translated"].startswith("[ES]")

    def test_translated_prefixed_with_pt_for_portuguese(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_REAL_TRANSLATION", "false")
        pt_config = LanguageConfig(
            code="portuguese",
            display_name="Portuguese",
            nllb_source="eng_Latn",
            nllb_target="por_Latn",
            glossary_path="/dev/null",
        )
        t = Translator(pt_config).load()
        result = t.translate_text("Hello.", "por_Latn")
        assert result["translated"].startswith("[PT]")

    def test_unknown_lang_tag_uses_code_as_prefix(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_REAL_TRANSLATION", "false")
        t = Translator(lang_config).load()
        result = t.translate_text("Hello.", "zho_Hans")
        assert result["translated"].startswith("[zho_Hans]")


# ─────────────────────────────────────────────────────────────────────────────
# translate_one — step 0 and step 0.5 (stub mode)
# ─────────────────────────────────────────────────────────────────────────────


class TestTranslateOneProtectionSteps:
    def test_empty_text_returned_unchanged(self, translator):
        assert translator.translate_one("", "spa_Latn") == ""

    def test_whitespace_only_returned_unchanged(self, translator):
        assert translator.translate_one("   ", "spa_Latn") == "   "

    def test_blank_fill_line_preserved_step0(self, translator):
        # Step 0: underscore line is returned as-is, no stub prefix added
        fill = "_______________________"
        assert translator.translate_one(fill, "spa_Latn") == fill

    def test_dash_fill_line_preserved_step0(self, translator):
        fill = "- - - - - - -"
        assert translator.translate_one(fill, "spa_Latn") == fill

    def test_form_token_date_translated_step05(self, translator):
        # Step 0.5: "DATE" → "FECHA" (from form_token_translations fixture)
        assert translator.translate_one("DATE", "spa_Latn") == "FECHA"

    def test_form_token_signature_translated_step05(self, translator):
        assert translator.translate_one("SIGNATURE", "spa_Latn") == "FIRMA"

    def test_form_token_case_insensitive_step05(self, translator):
        # text.strip().upper() is compared — uppercase match on "date"
        assert translator.translate_one("date", "spa_Latn") == "FECHA"

    def test_non_token_text_reaches_stub_path(self, translator):
        # "Defendant name" is not a form token or fill line → stub prefix added
        result = translator.translate_one("Defendant name", "spa_Latn")
        assert result.startswith("[ES]")


# ─────────────────────────────────────────────────────────────────────────────
# batch_translate
# ─────────────────────────────────────────────────────────────────────────────


class TestBatchTranslate:
    def test_returns_list_of_same_length(self, translator):
        texts = ["Hello.", "Court order.", "Sign here."]
        results = translator.batch_translate(texts, "spa_Latn")
        assert len(results) == 3

    def test_each_item_translated(self, translator):
        texts = ["Hello.", "World."]
        results = translator.batch_translate(texts, "spa_Latn")
        assert all(isinstance(r, str) for r in results)

    def test_empty_list_returns_empty_list(self, translator):
        assert translator.batch_translate([], "spa_Latn") == []

    def test_preserves_order(self, translator):
        texts = ["first", "second", "third"]
        results = translator.batch_translate(texts, "spa_Latn")
        # All should be prefixed with [ES] since none are form tokens or fill lines
        assert results[0].endswith("first")
        assert results[2].endswith("third")


# ─────────────────────────────────────────────────────────────────────────────
# _extract_court_names — instance method
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractCourtNames:
    def test_known_court_name_replaced_with_rfcn_placeholder(self, translator):
        text = "File at Boston Municipal Court next week."
        protected, court_map = translator._extract_court_names(text)
        assert "Boston Municipal Court" not in protected
        assert len(court_map) == 1

    def test_placeholder_restores_to_target_language_translation(self, translator):
        text = "File at Boston Municipal Court."
        _, court_map = translator._extract_court_names(text)
        key = next(iter(court_map.keys()))
        assert court_map[key] == "Tribunal Municipal de Boston"

    def test_unknown_court_name_leaves_text_unchanged(self, translator):
        text = "File at Superior Court of Appeals."
        protected, court_map = translator._extract_court_names(text)
        assert protected == text
        assert court_map == {}

    def test_placeholder_key_format_is_rfcn_number_rf(self, translator):
        text = "Heard at District Court."
        _, court_map = translator._extract_court_names(text)
        for key in court_map:
            assert key.startswith("RFCN")
            assert key.endswith("RF")

    def test_multiple_court_names_get_distinct_placeholders(self, translator):
        text = "Cases in Boston Municipal Court and Housing Court."
        _, court_map = translator._extract_court_names(text)
        assert len(court_map) == 2


# ─────────────────────────────────────────────────────────────────────────────
# _apply_court_name_safety_net — instance method
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyCourtNameSafetyNet:
    def test_english_court_name_replaced(self, translator):
        text = "Resolved by District Court yesterday."
        result = translator._apply_court_name_safety_net(text)
        assert "District Court" not in result
        assert "Tribunal de Distrito" in result

    def test_case_insensitive_match(self, translator):
        text = "Filed at BOSTON MUNICIPAL COURT."
        result = translator._apply_court_name_safety_net(text)
        assert "Tribunal Municipal de Boston" in result

    def test_unknown_court_not_replaced(self, translator):
        text = "Filed at Supreme Court."
        result = translator._apply_court_name_safety_net(text)
        assert result == text


# ─────────────────────────────────────────────────────────────────────────────
# unload — memory cleanup
# ─────────────────────────────────────────────────────────────────────────────


class TestUnload:
    def test_unload_clears_nlp(self, translator):
        translator.unload()
        assert translator._nlp is None

    def test_unload_clears_tokenizer(self, translator):
        translator.unload()
        assert translator._tokenizer is None

    def test_unload_clears_ct2_translator(self, translator):
        translator.unload()
        assert translator._ct2_translator is None

    def test_unload_when_already_none_does_not_raise(self, translator):
        # Calling unload() on a stub-mode instance (models are already None)
        # must not raise any exception
        translator.unload()
        translator.unload()  # second call should be safe too


# ─────────────────────────────────────────────────────────────────────────────
# _ensure_loaded — real mode guard
# ─────────────────────────────────────────────────────────────────────────────


class TestEnsureLoaded:
    def test_stub_mode_ensure_loaded_does_not_raise(self, translator):
        # _use_real is False — models being None is expected and fine
        translator._ensure_loaded()  # must not raise

    def test_real_mode_with_unloaded_models_raises_runtime_error(self, translator):
        # Simulate real mode with models still None (never loaded)
        translator._use_real = True
        with pytest.raises(RuntimeError, match="Call load\\(\\) before translating"):
            translator._ensure_loaded()
