"""
Tests for language configs.
No external dependencies — runs instantly with no models loaded.
"""

import pytest

from courtaccess.languages import get_language_config, supported_languages
from courtaccess.languages.base import LanguageConfig


class TestRegistry:
    def test_supported_languages_returns_both(self):
        langs = supported_languages()
        assert "spanish" in langs
        assert "portuguese" in langs

    def test_get_spanish_returns_config(self):
        config = get_language_config("spanish")
        assert isinstance(config, LanguageConfig)

    def test_get_portuguese_returns_config(self):
        config = get_language_config("portuguese")
        assert isinstance(config, LanguageConfig)

    def test_case_insensitive_lookup(self):
        assert get_language_config("Spanish").code == "spanish"
        assert get_language_config("PORTUGUESE").code == "portuguese"

    def test_unsupported_language_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported language"):
            get_language_config("klingon")

    def test_error_message_lists_supported_languages(self):
        with pytest.raises(ValueError, match="spanish"):
            get_language_config("french")


class TestSpanishConfig:
    def setup_method(self):
        self.config = get_language_config("spanish")

    def test_nllb_codes(self):
        assert self.config.nllb_source == "eng_Latn"
        assert self.config.nllb_target == "spa_Latn"

    def test_display_name(self):
        assert "Spanish" in self.config.display_name

    def test_court_names_longest_first_when_sorted(self):
        # The translation module sorts at runtime — verify that
        # sorting by length produces correct longest-first order
        keys = list(self.config.court_name_translations.keys())
        sorted_keys = sorted(keys, key=len, reverse=True)
        # "Massachusetts Trial Court" must come before "Trial Court"
        assert sorted_keys.index("Massachusetts Trial Court") < sorted_keys.index("Trial Court")
        # "Land Court Department" must come before "Land Court"
        assert sorted_keys.index("Land Court Department") < sorted_keys.index("Land Court")

    def test_critical_court_translations(self):
        ct = self.config.court_name_translations
        assert ct["Massachusetts Trial Court"] == "Tribunal de Justicia de Massachusetts"
        assert ct["Land Court"] == "Tribunal de Tierras"
        assert ct["Superior Court"] == "Tribunal Superior"

    def test_critical_legal_overrides(self):
        lo = self.config.legal_overrides
        assert lo["defendant"] == "acusado"
        assert lo["plaintiff"] == "demandante"
        assert lo["beyond a reasonable doubt"] == "más allá de una duda razonable"

    def test_glossary_path_is_set(self):
        assert self.config.glossary_path.endswith(".json")
        assert "es" in self.config.glossary_path

    def test_form_token_translations(self):
        ft = self.config.form_token_translations
        assert ft["DATE"] == "FECHA"
        assert ft["SIGNATURE"] == "FIRMA"
        assert ft["SIGN"] == "FIRMAR"
        assert len(ft) == 7

    def test_glossary_skip_lines_is_set(self):
        assert isinstance(self.config.glossary_skip_lines, set)

    def test_glossary_skip_lines_not_empty(self):
        assert len(self.config.glossary_skip_lines) > 0

    def test_glossary_skip_lines_contains_key_strings(self):
        assert "glossary of legal" in self.config.glossary_skip_lines
        assert "revised" in self.config.glossary_skip_lines
        assert "introduction" in self.config.glossary_skip_lines


class TestPortugueseConfig:
    """
    Portuguese is a stub — tests verify structure only,
    not translation values. Full tests added when Portuguese
    Colab script is provided.
    """

    def setup_method(self):
        self.config = get_language_config("portuguese")

    def test_nllb_codes(self):
        assert self.config.nllb_source == "eng_Latn"
        assert self.config.nllb_target == "por_Latn"

    def test_display_name(self):
        assert "Portuguese" in self.config.display_name

    def test_glossary_path_is_set(self):
        assert self.config.glossary_path.endswith(".json")
        assert "pt" in self.config.glossary_path

    def test_stub_keys_match_spanish_keys(self):
        # Portuguese must have the same English keys as Spanish
        # so the pipeline can look up any court name regardless of language
        es = get_language_config("spanish").court_name_translations
        pt = self.config.court_name_translations
        assert set(es.keys()) == set(pt.keys()), "Portuguese court name keys must match Spanish. Missing: " + str(
            set(es.keys()) - set(pt.keys())
        )

    def test_form_tokens_keys_match_spanish(self):
        es = get_language_config("spanish").form_token_translations
        pt = self.config.form_token_translations
        assert set(es.keys()) == set(pt.keys()), "Portuguese form token keys must match Spanish. Missing: " + str(
            set(es.keys()) - set(pt.keys())
        )

    def test_is_stub(self):
        # Confirms Portuguese is still a stub —
        # remove this test when real values are added
        assert "[PT STUB]" in list(self.config.court_name_translations.values()), (
            "Portuguese stub marker missing — did you add real values?"
        )
        assert self.config.ready_for_production is False, (
            "Portuguese should be marked ready_for_production=False until real translation values are provided."
        )

    def test_glossary_skip_lines_is_set(self):
        # Portuguese stub — empty set is correct until PT script provided
        assert isinstance(self.config.glossary_skip_lines, set)


class TestBaseConfig:
    def test_llama_lang_label_defaults_to_display_name(self):
        from courtaccess.languages.base import LanguageConfig

        config = LanguageConfig(
            code="test",
            display_name="Test Language",
            nllb_source="eng_Latn",
            nllb_target="test_Latn",
            glossary_path="data/glossaries/glossary_test.json",
        )
        assert config.llama_lang_label == "Test Language"

    def test_empty_dicts_are_independent(self):
        from courtaccess.languages.base import LanguageConfig

        c1 = LanguageConfig(
            code="a",
            display_name="A",
            nllb_source="eng_Latn",
            nllb_target="a_Latn",
            glossary_path="data/glossaries/a.json",
        )
        c2 = LanguageConfig(
            code="b",
            display_name="B",
            nllb_source="eng_Latn",
            nllb_target="b_Latn",
            glossary_path="data/glossaries/b.json",
        )
        c1.court_name_translations["test"] = "value"
        assert "test" not in c2.court_name_translations

    def test_glossary_skip_lines_independent(self):
        from courtaccess.languages.base import LanguageConfig

        c1 = LanguageConfig(
            code="a",
            display_name="A",
            nllb_source="eng_Latn",
            nllb_target="a_Latn",
            glossary_path="data/glossaries/a.json",
        )
        c2 = LanguageConfig(
            code="b",
            display_name="B",
            nllb_source="eng_Latn",
            nllb_target="b_Latn",
            glossary_path="data/glossaries/b.json",
        )
        c1.glossary_skip_lines.add("test_string")
        assert "test_string" not in c2.glossary_skip_lines
