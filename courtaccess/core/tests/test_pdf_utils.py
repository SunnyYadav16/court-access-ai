"""
Tests for courtaccess/core/pdf_utils.py

No PDF files needed — all tests use synthetic span dicts
and known inputs. Runs instantly with no models loaded.
"""

import pymupdf

from courtaccess.core.pdf_utils import (
    CSS_FONTS,
    FONT_MAP,
    color_to_hex,
    fit_fontsize,
    get_font_code,
    get_font_size,
    safe_color,
)


class TestGetFontCode:
    """Tests for font name/flag → PyMuPDF code mapping."""

    def _span(self, font="", flags=0):
        return {"font": font, "flags": flags}

    # ── Default (Helvetica family) ────────────────────────────
    def test_default_returns_helv(self):
        assert get_font_code(self._span()) == "helv"

    def test_bold_flag_returns_hebo(self):
        assert get_font_code(self._span(flags=16)) == "hebo"

    def test_italic_flag_returns_heit(self):
        assert get_font_code(self._span(flags=2)) == "heit"

    def test_bold_italic_flags_returns_hebi(self):
        assert get_font_code(self._span(flags=16 | 2)) == "hebi"

    # ── Font name detection ───────────────────────────────────
    def test_bold_in_name_returns_hebo(self):
        assert get_font_code(self._span(font="ArialBold")) == "hebo"

    def test_italic_in_name_returns_heit(self):
        assert get_font_code(self._span(font="ArialItalic")) == "heit"

    # ── Serif family ──────────────────────────────────────────
    def test_times_returns_tiro(self):
        assert get_font_code(self._span(font="Times-Roman")) == "tiro"

    def test_times_bold_returns_tibo(self):
        assert get_font_code(self._span(font="Times-Bold")) == "tibo"

    def test_times_italic_returns_tiit(self):
        assert get_font_code(self._span(font="Times-Italic")) == "tiit"

    def test_times_bold_italic_returns_tibi(self):
        assert get_font_code(self._span(font="Times-BoldItalic")) == "tibi"

    def test_serif_flag_returns_tiro(self):
        assert get_font_code(self._span(flags=4)) == "tiro"

    # ── Mono family ───────────────────────────────────────────
    def test_courier_returns_cour(self):
        assert get_font_code(self._span(font="Courier")) == "cour"

    def test_mono_in_name_returns_cour(self):
        assert get_font_code(self._span(font="DejaVuMono")) == "cour"

    def test_courier_bold_returns_cobo(self):
        assert get_font_code(self._span(font="Courier-Bold")) == "cobo"

    def test_mono_flag_returns_cour(self):
        assert get_font_code(self._span(flags=8)) == "cour"

    # ── Mono takes priority over serif ───────────────────────
    def test_mono_beats_serif_when_both_flagged(self):
        # mono flag (8) + serif flag (4) → mono wins
        assert get_font_code(self._span(flags=8 | 4)) == "cour"

    # ── Return values are valid CSS_FONTS keys ────────────────
    def test_all_return_values_are_valid_font_codes(self):
        spans = [
            {"font": "", "flags": 0},
            {"font": "", "flags": 16},
            {"font": "", "flags": 2},
            {"font": "Times-Roman", "flags": 0},
            {"font": "Courier", "flags": 0},
        ]
        for span in spans:
            code = get_font_code(span)
            assert code in CSS_FONTS, f"'{code}' not in CSS_FONTS"


class TestGetFontSize:
    def test_returns_span_size(self):
        assert get_font_size({"size": 12.0}) == 12.0

    def test_rounds_to_one_decimal(self):
        assert get_font_size({"size": 11.987}) == 12.0

    def test_default_when_no_size(self):
        assert get_font_size({}) == 10.0

    def test_enforces_min_size(self):
        assert get_font_size({"size": 2.0}) == 6.0

    def test_custom_min_size(self):
        assert get_font_size({"size": 2.0}, min_size=4.0) == 4.0

    def test_exact_min_size_passes(self):
        assert get_font_size({"size": 6.0}) == 6.0


class TestFitFontsize:
    def test_fits_at_original_size(self):
        # Short text should always fit at original size
        size = fit_fontsize("Hi", 12.0, 200.0)
        assert size == 12.0

    def test_shrinks_for_long_text(self):
        # Very long text in a narrow box must shrink
        long_text = "Este es un texto muy largo que no cabe en el espacio disponible"
        size = fit_fontsize(long_text, 12.0, 50.0)
        assert size < 12.0

    def test_never_below_min_size(self):
        # Even impossibly long text respects the floor
        size = fit_fontsize("A" * 500, 12.0, 10.0, min_size=4.0)
        assert size == 4.0

    def test_custom_min_size_respected(self):
        size = fit_fontsize("A" * 500, 12.0, 10.0, min_size=6.0)
        assert size == 6.0

    def test_original_size_returned_when_fits(self):
        # Exact boundary — text fits, return original unchanged
        size = fit_fontsize("OK", 10.0, 500.0)
        assert size == 10.0

    def test_spanish_longer_than_english(self):
        # Validates the core reason this function exists
        # Spanish text that exceeds the English bbox width gets shrunk
        en = "Defendant"
        es = "El acusado principal"
        font = pymupdf.Font("helv")
        en_width = font.text_length(en, fontsize=12.0)
        es_size = fit_fontsize(es, 12.0, en_width)
        assert es_size < 12.0


class TestSafeColor:
    def test_black_integer(self):
        assert safe_color({"color": 0}) == (0.0, 0.0, 0.0)

    def test_white_integer(self):
        r, g, b = safe_color({"color": 0xFFFFFF})
        assert abs(r - 1.0) < 0.01
        assert abs(g - 1.0) < 0.01
        assert abs(b - 1.0) < 0.01

    def test_red_integer(self):
        r, g, b = safe_color({"color": 0xFF0000})
        assert abs(r - 1.0) < 0.01
        assert g == 0.0
        assert b == 0.0

    def test_float_tuple_passthrough(self):
        result = safe_color({"color": (0.5, 0.25, 0.75)})
        assert abs(result[0] - 0.5) < 0.01
        assert abs(result[1] - 0.25) < 0.01
        assert abs(result[2] - 0.75) < 0.01

    def test_255_tuple_normalized(self):
        # Some PyMuPDF builds return 0-255 integers in tuple
        result = safe_color({"color": (255, 0, 0)})
        assert abs(result[0] - 1.0) < 0.01
        assert result[1] == 0.0
        assert result[2] == 0.0

    def test_missing_color_defaults_to_black(self):
        assert safe_color({}) == (0.0, 0.0, 0.0)

    def test_invalid_color_defaults_to_black(self):
        assert safe_color({"color": None}) == (0.0, 0.0, 0.0)

    def test_raw_integer_input(self):
        # Can also be called with raw int, not just span dict
        r, _g, _b = safe_color(0xFF0000)
        assert abs(r - 1.0) < 0.01

    def test_all_values_in_range(self):
        for color_int in [0x000000, 0xFFFFFF, 0xFF0000, 0x00FF00, 0x0000FF, 0x808080]:
            r, g, b = safe_color({"color": color_int})
            assert 0.0 <= r <= 1.0
            assert 0.0 <= g <= 1.0
            assert 0.0 <= b <= 1.0


class TestColorToHex:
    def test_black(self):
        assert color_to_hex((0.0, 0.0, 0.0)) == "#000000"

    def test_white(self):
        assert color_to_hex((1.0, 1.0, 1.0)) == "#ffffff"

    def test_red(self):
        assert color_to_hex((1.0, 0.0, 0.0)) == "#ff0000"

    def test_invalid_input_returns_black(self):
        assert color_to_hex("not a color") == "#000000"

    def test_clamps_above_one(self):
        # Values slightly above 1.0 due to float math should clamp
        result = color_to_hex((1.001, 0.0, 0.0))
        assert result == "#ff0000"


class TestConstants:
    def test_font_map_has_standard_fonts(self):
        assert "Helvetica" in FONT_MAP
        assert "Times-Roman" in FONT_MAP
        assert "Courier" in FONT_MAP

    def test_css_fonts_covers_all_variants(self):
        expected = [
            "helv",
            "hebo",
            "heit",
            "hebi",
            "tiro",
            "tibo",
            "tiit",
            "tibi",
            "cour",
            "cobo",
            "coit",
            "cobi",
        ]
        for code in expected:
            assert code in CSS_FONTS, f"'{code}' missing from CSS_FONTS"

    def test_css_fonts_tuple_structure(self):
        for code, val in CSS_FONTS.items():
            assert isinstance(val, tuple), f"{code}: expected tuple"
            assert len(val) == 3, f"{code}: expected 3 items"
            assert isinstance(val[0], str), f"{code}: family must be str"
            assert isinstance(val[1], bool), f"{code}: bold must be bool"
            assert isinstance(val[2], bool), f"{code}: italic must be bool"
