"""
courtaccess/core/tests/test_translation.py

Tests for courtaccess.core.translation.Translator

Stub mode tests only — real NLLB tests require model weights
and are marked integration.
"""

import pytest

from courtaccess.core.translation import Translator
from courtaccess.languages import get_language_config


def _make_translator(load_spacy: bool = False) -> Translator:
    """
    Create a Translator in stub mode.
    load_spacy=True loads the real spaCy model for NER tests.
    """
    t = Translator(get_language_config("spanish"))
    if load_spacy or t._use_real:
        t.load()
    return t


# ── translate_text output contract ───────────────────────────────────────────


class TestTranslateTextContract:
    def test_returns_required_keys(self):
        t = _make_translator()
        result = t.translate_text("The defendant pleads not guilty.", "spa_Latn")
        assert "original" in result
        assert "translated" in result
        assert "confidence" in result

    def test_confidence_is_float(self):
        t = _make_translator()
        assert isinstance(t.translate_text("Test.", "spa_Latn")["confidence"], float)

    def test_original_preserved_in_result(self):
        t = _make_translator()
        text = "The defendant pleads not guilty."
        assert t.translate_text(text, "spa_Latn")["original"] == text

    def test_empty_string_contract(self):
        t = _make_translator()
        result = t.translate_text("", "spa_Latn")
        assert result["original"] == ""

    def test_stub_confidence_is_0_5(self):
        t = _make_translator()
        if t._use_real:
            pytest.skip("Test specifically for stub confidence")
        assert t.translate_text("Test.", "spa_Latn")["confidence"] == 0.50

    def test_stub_es_prefix(self):
        t = _make_translator()
        if t._use_real:
            pytest.skip("Test specifically for stub prefix")
        assert t.translate_text("Motion to suppress.", "spa_Latn")["translated"].startswith("[ES]")

    def test_stub_pt_prefix(self):
        t = _make_translator()
        if t._use_real:
            pytest.skip("Test specifically for stub prefix")
        assert t.translate_text("Motion to suppress.", "por_Latn")["translated"].startswith("[PT]")

    def test_unknown_language_uses_code_as_label(self):
        t = _make_translator()
        assert "translated" in t.translate_text("Test.", "fra_Latn")


# ── _is_blank_fill_line ───────────────────────────────────────────────────────


class TestIsBlankFillLine:
    def setup_method(self):
        self.t = _make_translator()

    def test_underscores(self):
        assert self.t._is_blank_fill_line("_______________")

    def test_dashes(self):
        assert self.t._is_blank_fill_line("- - - - - - -")

    def test_empty_string(self):
        assert self.t._is_blank_fill_line("")

    def test_spaces_only(self):
        assert self.t._is_blank_fill_line("   ")

    def test_dollar_dash(self):
        assert self.t._is_blank_fill_line("$___")

    def test_real_text_not_blank(self):
        assert not self.t._is_blank_fill_line("The defendant")

    def test_mixed_text_and_underscores_not_blank(self):
        assert not self.t._is_blank_fill_line("___ street address")


# ── translate_one — stub mode ─────────────────────────────────────────────────


class TestTranslateOne:
    def setup_method(self):
        self.t = _make_translator()

    def test_blank_fill_line_preserved(self):
        assert self.t.translate_one("_______________", "spa_Latn") == "_______________"

    def test_empty_string_preserved(self):
        assert self.t.translate_one("", "spa_Latn") == ""

    def test_form_token_date(self):
        assert self.t.translate_one("DATE", "spa_Latn") == "FECHA"

    def test_form_token_case_insensitive(self):
        assert self.t.translate_one("date", "spa_Latn") == "FECHA"

    def test_form_token_signature(self):
        assert self.t.translate_one("SIGNATURE", "spa_Latn") == "FIRMA"

    def test_form_token_sign(self):
        assert self.t.translate_one("SIGN", "spa_Latn") == "FIRMAR"

    def test_stub_es_prefix(self):
        if self.t._use_real:
            pytest.skip("Test specifically for stub prefix")
        assert self.t.translate_one("The defendant", "spa_Latn").startswith("[ES]")

    def test_stub_pt_prefix(self):
        if self.t._use_real:
            pytest.skip("Test specifically for stub prefix")
        assert self.t.translate_one("The defendant", "por_Latn").startswith("[PT]")


# ── batch_translate ───────────────────────────────────────────────────────────


class TestBatchTranslate:
    def setup_method(self):
        self.t = _make_translator()

    def test_returns_same_length(self):
        texts = ["Hello", "World", "Test"]
        assert len(self.t.batch_translate(texts, "spa_Latn")) == 3

    def test_preserves_blank_lines(self):
        texts = ["Hello", "_______________", "World"]
        result = self.t.batch_translate(texts, "spa_Latn")
        assert result[1] == "_______________"

    def test_empty_list_returns_empty(self):
        assert self.t.batch_translate([], "spa_Latn") == []

    def test_form_tokens_translated(self):
        result = self.t.batch_translate(["DATE", "SIGNATURE"], "spa_Latn")
        assert result[0] == "FECHA"
        assert result[1] == "FIRMA"


# ── _extract_citations ────────────────────────────────────────────────────────


class TestExtractCitations:
    def setup_method(self):
        self.t = _make_translator()

    def test_extracts_gl_citation(self):
        _, placeholders = self.t._extract_citations("Under G.L. c. 263, the defendant has rights.")
        assert len(placeholders) == 1
        assert "G.L. c. 263" in next(iter(placeholders.values()))

    def test_extracts_section_symbol(self):
        _, placeholders = self.t._extract_citations("See § 6 for details.")
        assert len(placeholders) >= 1

    def test_extracts_url(self):
        _, placeholders = self.t._extract_citations("Visit https://www.mass.gov/courts for more info.")
        assert any(v == "https://www.mass.gov/courts" for v in placeholders.values())

    def test_placeholder_format(self):
        _, placeholders = self.t._extract_citations("Under G.L. c. 263.")
        for key in placeholders:
            assert key.startswith("RFCT") and key.endswith("RF")

    def test_no_citations_empty_dict(self):
        _, placeholders = self.t._extract_citations("The defendant pleads not guilty.")
        assert placeholders == {}

    def test_citation_removed_from_protected(self):
        protected, _ = self.t._extract_citations("Under G.L. c. 263, see § 6.")
        assert "G.L." not in protected
        assert "§" not in protected


# ── _extract_court_names ──────────────────────────────────────────────────────


class TestExtractCourtNames:
    def setup_method(self):
        self.t = _make_translator()

    def test_extracts_known_court_name(self):
        _, placeholders = self.t._extract_court_names("Filed in the Massachusetts Trial Court today.")
        assert len(placeholders) == 1

    def test_placeholder_restores_to_spanish(self):
        _, placeholders = self.t._extract_court_names("Filed in the Massachusetts Trial Court.")
        assert next(iter(placeholders.values())) == "Tribunal de Justicia de Massachusetts"

    def test_longer_name_before_shorter(self):
        _, placeholders = self.t._extract_court_names("Massachusetts Trial Court filing.")
        assert "Tribunal de Justicia de Massachusetts" in list(placeholders.values())
        assert "Tribunal de Justicia" not in list(placeholders.values())

    def test_case_insensitive(self):
        _, placeholders = self.t._extract_court_names("filed in the LAND COURT today.")
        assert len(placeholders) >= 1

    def test_no_court_names_empty_dict(self):
        protected, placeholders = self.t._extract_court_names("The defendant pleads not guilty.")
        assert placeholders == {}
        assert protected == "The defendant pleads not guilty."


# ── _restore_placeholders ─────────────────────────────────────────────────────


class TestRestorePlaceholders:
    def setup_method(self):
        self.t = _make_translator()

    def test_restores_single(self):
        assert (
            self.t._restore_placeholders("Hello RFCT0RF world", {"RFCT0RF": "G.L. c. 263"}) == "Hello G.L. c. 263 world"
        )

    def test_restores_multiple_dicts(self):
        result = self.t._restore_placeholders(
            "RFCT0RF and RFCN0RF",
            {"RFCT0RF": "§ 6"},
            {"RFCN0RF": "Tribunal Superior"},
        )
        assert "§ 6" in result
        assert "Tribunal Superior" in result

    def test_handles_spaced_placeholder(self):
        result = self.t._restore_placeholders("Hello RFCT 0 RF world", {"RFCT0RF": "G.L. c. 263"})
        assert "G.L. c. 263" in result

    def test_no_placeholders_unchanged(self):
        text = "No placeholders here."
        assert self.t._restore_placeholders(text, {}) == text


# ── _is_preserve_only ────────────────────────────────────────────────────────


class TestIsPreserveOnly:
    def setup_method(self):
        self.t = _make_translator()

    def test_empty_string(self):
        assert self.t._is_preserve_only("")

    def test_rfct_placeholder_only(self):
        assert self.t._is_preserve_only("RFCT0RF")

    def test_rfpn_placeholder_only(self):
        assert self.t._is_preserve_only("RFPN0RF")

    def test_rfcn_not_preserve_only(self):
        # RFCN is NOT stripped — matches Cell 6 exactly
        assert not self.t._is_preserve_only("RFCN0RF")

    def test_numbers_only(self):
        assert self.t._is_preserve_only("123 456")

    def test_real_text_not_preserve(self):
        assert not self.t._is_preserve_only("The defendant")

    def test_mixed_placeholder_and_text(self):
        assert not self.t._is_preserve_only("RFCT0RF defendant")


# ── _apply_court_name_safety_net ─────────────────────────────────────────────


class TestApplyCourtNameSafetyNet:
    def setup_method(self):
        self.t = _make_translator()

    def test_replaces_english_court_name(self):
        result = self.t._apply_court_name_safety_net("El caso fue presentado en Superior Court hoy.")
        assert "Tribunal Superior" in result
        assert "Superior Court" not in result

    def test_case_insensitive(self):
        result = self.t._apply_court_name_safety_net("En el LAND COURT se presentó.")
        assert "Tribunal de Tierras" in result

    def test_no_court_names_unchanged(self):
        text = "El acusado se declaró inocente."
        assert self.t._apply_court_name_safety_net(text) == text
