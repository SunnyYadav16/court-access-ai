"""
Unit tests for courtaccess/core/pdf_utils.py

Functions under test:
  Font utilities   — get_font_code, get_font_size, fit_fontsize
  Color utilities  — safe_color, color_to_hex
  Block utilities  — _is_blank_fill_line, _should_never_translate,
                     _is_form_field_line, _classify,
                     _lines_are_same_row, _group_lines_into_rows,
                     _detect_alignment, _union_rects,
                     _split_line_by_columns, _find_tightest_cell,
                     _get_available_width

Not tested here (require a real pymupdf page object — integration tests):
  get_background_color, _get_cell_rects, _get_block_units

Design notes:
  - pymupdf is a module-level import in pdf_utils.py, so pymupdf.Rect and
    pymupdf.Font are used directly — no mocking needed for geometry tests.
  - Span / line / block dicts are plain Python dicts that mirror the shape
    PyMuPDF returns from page.get_text("dict").
"""

import pymupdf
import pytest

from courtaccess.core.pdf_utils import (
    _classify,
    _detect_alignment,
    _find_tightest_cell,
    _get_available_width,
    _group_lines_into_rows,
    _is_blank_fill_line,
    _is_form_field_line,
    _lines_are_same_row,
    _should_never_translate,
    _split_line_by_columns,
    _union_rects,
    color_to_hex,
    fit_fontsize,
    get_font_code,
    get_font_size,
    safe_color,
)

# ── Span / line dict builders ─────────────────────────────────────────────────

def _span(text="text", font="", flags=0, size=12.0, color=0,
          x0=0.0, y0=0.0, x1=50.0, y1=12.0) -> dict:
    """Minimal span dict matching PyMuPDF shape."""
    return {
        "text": text,
        "font": font,
        "flags": flags,
        "size": size,
        "color": color,
        "bbox": (x0, y0, x1, y1),
    }


def _line(x0=0.0, y0=0.0, x1=100.0, y1=12.0, spans=None) -> dict:
    """Minimal line dict matching PyMuPDF shape."""
    return {
        "bbox": [x0, y0, x1, y1],
        "spans": spans or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# get_font_code
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFontCode:
    """
    Priority order: mono > serif > sans-serif.
    Within each family: bold+italic > bold > italic > plain.
    Detection via bitflags OR fontname keywords (both paths tested).
    """

    # ── Sans-serif (helv family) via flags ────────────────────────────────────

    def test_no_flags_no_fontname_returns_helv(self):
        assert get_font_code(_span()) == "helv"

    def test_bold_flag_returns_hebo(self):
        assert get_font_code(_span(flags=16)) == "hebo"

    def test_italic_flag_returns_heit(self):
        assert get_font_code(_span(flags=2)) == "heit"

    def test_bold_and_italic_flags_returns_hebi(self):
        assert get_font_code(_span(flags=18)) == "hebi"

    # ── Mono (cour family) via flags ──────────────────────────────────────────

    def test_mono_flag_returns_cour(self):
        assert get_font_code(_span(flags=8)) == "cour"

    def test_mono_plus_bold_returns_cobo(self):
        assert get_font_code(_span(flags=24)) == "cobo"

    def test_mono_plus_italic_returns_coit(self):
        assert get_font_code(_span(flags=10)) == "coit"

    def test_mono_plus_bold_italic_returns_cobi(self):
        assert get_font_code(_span(flags=26)) == "cobi"

    # ── Serif (tiro family) via flags ─────────────────────────────────────────

    def test_serif_flag_returns_tiro(self):
        assert get_font_code(_span(flags=4)) == "tiro"

    def test_serif_plus_bold_returns_tibo(self):
        assert get_font_code(_span(flags=20)) == "tibo"

    def test_serif_plus_italic_returns_tiit(self):
        assert get_font_code(_span(flags=6)) == "tiit"

    def test_serif_plus_bold_italic_returns_tibi(self):
        assert get_font_code(_span(flags=22)) == "tibi"

    # ── Keyword detection in fontname ─────────────────────────────────────────

    def test_fontname_bold_keyword_returns_hebo(self):
        assert get_font_code(_span(font="ArialBold")) == "hebo"

    def test_fontname_italic_keyword_returns_heit(self):
        assert get_font_code(_span(font="Arial-Italic")) == "heit"

    def test_fontname_courier_keyword_returns_cour(self):
        assert get_font_code(_span(font="CourierNew")) == "cour"

    def test_fontname_times_keyword_returns_tiro(self):
        assert get_font_code(_span(font="Times-Roman")) == "tiro"

    def test_fontname_georgia_returns_tiro(self):
        assert get_font_code(_span(font="Georgia")) == "tiro"

    def test_fontname_mono_bold_returns_cobo(self):
        assert get_font_code(_span(font="MonoBold")) == "cobo"

    # ── Priority: mono wins over serif ────────────────────────────────────────

    def test_mono_flag_beats_serif_flag(self):
        # flags = mono(8) | serif(4) = 12
        assert get_font_code(_span(flags=12)) == "cour"


# ─────────────────────────────────────────────────────────────────────────────
# get_font_size
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFontSize:

    def test_normal_size_returned_rounded(self):
        assert get_font_size(_span(size=12.0)) == 12.0

    def test_size_rounded_to_one_decimal(self):
        assert get_font_size(_span(size=11.75)) == 11.8

    def test_size_below_default_min_clamped_to_six(self):
        assert get_font_size(_span(size=3.0)) == 6.0

    def test_size_at_exactly_min_returns_min(self):
        assert get_font_size(_span(size=6.0)) == 6.0

    def test_missing_size_key_defaults_to_ten(self):
        assert get_font_size({}) == 10.0

    def test_custom_min_size_respected(self):
        assert get_font_size(_span(size=2.0), min_size=4.0) == 4.0

    def test_size_above_custom_min_returned_as_is(self):
        assert get_font_size(_span(size=5.0), min_size=4.0) == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# fit_fontsize
# ─────────────────────────────────────────────────────────────────────────────

class TestFitFontsize:
    """fit_fontsize uses real pymupdf.Font — tests are lightweight but real."""

    def test_text_that_fits_returns_original_size(self):
        # A single short character should easily fit in a 200pt bbox
        result = fit_fontsize("A", original_size=12.0, bbox_width=200.0)
        assert result == 12.0

    def test_very_long_text_shrunk_to_at_least_min_size(self):
        # Text that cannot fit even at min_size must return min_size
        long_text = "W" * 200
        result = fit_fontsize(long_text, original_size=24.0, bbox_width=10.0, min_size=4.0)
        assert result == 4.0

    def test_returned_size_never_below_min_size(self):
        long_text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10
        result = fit_fontsize(long_text, original_size=20.0, bbox_width=5.0, min_size=6.0)
        assert result >= 6.0

    def test_result_fits_within_bbox(self):
        text = "Hello Court"
        bbox_width = 80.0
        result = fit_fontsize(text, original_size=18.0, bbox_width=bbox_width)
        font = pymupdf.Font("helv")
        assert font.text_length(text, fontsize=result) <= bbox_width * 0.95


# ─────────────────────────────────────────────────────────────────────────────
# safe_color
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeColor:

    def test_integer_zero_is_black(self):
        assert safe_color(0) == (0.0, 0.0, 0.0)

    def test_integer_white(self):
        r, g, b = safe_color(0xFFFFFF)
        assert r == pytest.approx(1.0) and g == pytest.approx(1.0) and b == pytest.approx(1.0)

    def test_integer_red(self):
        r, g, b = safe_color(0xFF0000)
        assert r == pytest.approx(1.0) and g == pytest.approx(0.0) and b == pytest.approx(0.0)

    def test_integer_blue(self):
        r, g, b = safe_color(0x0000FF)
        assert r == pytest.approx(0.0) and g == pytest.approx(0.0) and b == pytest.approx(1.0)

    def test_float_tuple_values_under_one_kept_as_is(self):
        # Values <= 1.0 treated as already-normalised floats
        result = safe_color((0.5, 0.25, 0.75))
        assert result == pytest.approx((0.5, 0.25, 0.75))

    def test_int_tuple_values_over_one_divided_by_255(self):
        # Values > 1 are treated as 0-255 integers and normalised
        r, g, b = safe_color((255, 128, 0))
        assert r == pytest.approx(1.0)
        assert g == pytest.approx(128 / 255.0)
        assert b == pytest.approx(0.0)

    def test_span_dict_uses_color_key(self):
        result = safe_color({"color": 0xFF0000})
        assert result[0] == pytest.approx(1.0)

    def test_span_dict_missing_color_key_defaults_to_black(self):
        assert safe_color({}) == (0.0, 0.0, 0.0)

    def test_none_returns_black(self):
        # int(None) raises TypeError — caught and returns black
        assert safe_color(None) == (0.0, 0.0, 0.0)

    def test_non_numeric_string_returns_black(self):
        # int("red") raises ValueError — caught and returns black
        assert safe_color("red") == (0.0, 0.0, 0.0)

    def test_tuple_with_fewer_than_three_values_falls_back_to_int_path(self):
        # len < 3 → skips tuple branch → tries int((r, g)) → TypeError → black
        assert safe_color((255, 128)) == (0.0, 0.0, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# color_to_hex
# ─────────────────────────────────────────────────────────────────────────────

class TestColorToHex:

    def test_black(self):
        assert color_to_hex((0.0, 0.0, 0.0)) == "#000000"

    def test_white(self):
        assert color_to_hex((1.0, 1.0, 1.0)) == "#ffffff"

    def test_red(self):
        assert color_to_hex((1.0, 0.0, 0.0)) == "#ff0000"

    def test_midpoint_grey(self):
        # int(0.5 * 255) = 127 = 0x7f
        assert color_to_hex((0.5, 0.5, 0.5)) == "#7f7f7f"

    def test_non_tuple_input_returns_black_default(self):
        assert color_to_hex("red") == "#000000"
        assert color_to_hex(None) == "#000000"
        assert color_to_hex(0xFF0000) == "#000000"

    def test_tuple_wrong_length_returns_black(self):
        # color_to_hex requires len == 3 exactly
        assert color_to_hex((1.0, 0.0)) == "#000000"
        assert color_to_hex((1.0, 0.0, 0.0, 1.0)) == "#000000"

    def test_values_above_one_clamped_to_ff(self):
        # int(2.0 * 255) = 510 → clamped to 255
        assert color_to_hex((2.0, 0.0, 0.0)) == "#ff0000"

    def test_negative_values_clamped_to_zero(self):
        assert color_to_hex((-1.0, 0.0, 0.0)) == "#000000"


# ─────────────────────────────────────────────────────────────────────────────
# _is_blank_fill_line
# ─────────────────────────────────────────────────────────────────────────────

class TestIsBlankFillLine:

    def test_empty_string(self):
        assert _is_blank_fill_line("") is True

    def test_whitespace_only(self):
        assert _is_blank_fill_line("   ") is True

    def test_four_or_more_underscores(self):
        assert _is_blank_fill_line("____") is True
        assert _is_blank_fill_line("__________") is True

    def test_four_or_more_dashes(self):
        assert _is_blank_fill_line("----") is True

    def test_mixed_underscores_dashes_spaces(self):
        assert _is_blank_fill_line("_ - _ -") is True

    def test_dollar_sign_with_filler_chars(self):
        # Matches ^\$[\s_\-\.]{3,}$ — but strip() runs first, so only
        # non-whitespace filler chars (underscores, dashes, dots) survive
        assert _is_blank_fill_line("$___") is True
        assert _is_blank_fill_line("$...") is True

    def test_dollar_sign_with_trailing_spaces_not_blank(self):
        # "$   " → strip() → "$" → dollar regex needs 3+ chars after $ → False
        # Spaces are stripped before the pattern is tested
        assert _is_blank_fill_line("$   ") is False

    def test_single_underscore_caught_by_third_condition(self):
        # re.sub(r"[\s_\-]", "", "_") == "" → len == 0 → True
        # This is a subtle edge case — single underscore is still blank fill
        assert _is_blank_fill_line("_") is True

    def test_normal_text_is_not_blank(self):
        assert _is_blank_fill_line("Defendant Name") is False

    def test_text_with_underscore_in_middle_is_not_blank(self):
        # "word_here" → re.sub removes _ → "wordhere" → len > 0 → False
        assert _is_blank_fill_line("word_here") is False

    def test_two_dollar_filler_chars_below_threshold(self):
        # "$.." only has 2 filler chars after $, needs 3+ → False for $ rule
        # But: re.sub(r"[\s_\-]", "", "$..") → "$.." → len > 0 → False
        assert _is_blank_fill_line("$..") is False


# ─────────────────────────────────────────────────────────────────────────────
# _should_never_translate
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldNeverTranslate:

    def test_print_uppercase(self):
        assert _should_never_translate("PRINT") is True

    def test_print_lowercase(self):
        # t.upper() is used for comparison
        assert _should_never_translate("print") is True

    def test_print_mixed_case(self):
        assert _should_never_translate("Print") is True

    def test_clear(self):
        assert _should_never_translate("CLEAR") is True

    def test_submit(self):
        assert _should_never_translate("SUBMIT") is True

    def test_reset(self):
        assert _should_never_translate("RESET") is True

    def test_save(self):
        assert _should_never_translate("SAVE") is True

    def test_http_url(self):
        assert _should_never_translate("http://mass.gov") is True

    def test_https_url(self):
        assert _should_never_translate("https://mass.gov/forms/abc") is True

    def test_www_url(self):
        assert _should_never_translate("www.mass.gov") is True

    def test_leading_whitespace_stripped(self):
        assert _should_never_translate("  PRINT  ") is True

    def test_normal_text_returns_false(self):
        assert _should_never_translate("Petition for custody") is False

    def test_print_name_is_not_in_set(self):
        # "PRINT NAME".upper() == "PRINT NAME" — not in the exact-match set
        assert _should_never_translate("PRINT NAME") is False

    def test_save_the_date_is_not_in_set(self):
        assert _should_never_translate("SAVE THE DATE") is False


# ─────────────────────────────────────────────────────────────────────────────
# _is_form_field_line
# ─────────────────────────────────────────────────────────────────────────────

class TestIsFormFieldLine:

    def test_x_matches(self):
        assert _is_form_field_line("X") is True

    def test_x_lowercase_matches(self):
        assert _is_form_field_line("x") is True

    def test_date_matches(self):
        assert _is_form_field_line("DATE") is True

    def test_date_lowercase_matches(self):
        assert _is_form_field_line("date") is True

    def test_bbo_no_with_period(self):
        assert _is_form_field_line("BBO NO.") is True

    def test_bbo_no_without_period(self):
        assert _is_form_field_line("BBO NO") is True

    def test_docket_no(self):
        assert _is_form_field_line("DOCKET NO.") is True

    def test_print_name(self):
        assert _is_form_field_line("PRINT NAME") is True

    def test_court_division(self):
        assert _is_form_field_line("COURT DIVISION") is True

    def test_defendant_name(self):
        assert _is_form_field_line("DEFENDANT NAME") is True

    def test_section_with_number(self):
        assert _is_form_field_line("SECTION 1") is True
        assert _is_form_field_line("SECTION 12") is True

    def test_section_with_colon(self):
        assert _is_form_field_line("SECTION 3:") is True

    def test_signature_alone(self):
        assert _is_form_field_line("SIGNATURE") is True

    def test_signature_of_party(self):
        assert _is_form_field_line("SIGNATURE OF ATTORNEY") is True
        assert _is_form_field_line("SIGNATURE OF DEFENDANT JAMES") is True

    def test_leading_trailing_whitespace_stripped(self):
        assert _is_form_field_line("  DATE  ") is True

    def test_arbitrary_sentence_does_not_match(self):
        assert _is_form_field_line("Please complete the following form.") is False

    def test_partial_keyword_does_not_match(self):
        # Anchored regex — partial matches at start/end rejected
        assert _is_form_field_line("DATE OF BIRTH") is False


# ─────────────────────────────────────────────────────────────────────────────
# _classify
# ─────────────────────────────────────────────────────────────────────────────

class TestClassify:

    def test_empty_string_returns_skip(self):
        assert _classify("", 1) == "SKIP"

    def test_digits_only_returns_skip(self):
        assert _classify("12345", 1) == "SKIP"

    def test_no_letters_with_currency_symbol_returns_form_label(self):
        assert _classify("$500", 1) == "FORM_LABEL"
        assert _classify("#12", 1) == "FORM_LABEL"

    def test_numbered_list_item_returns_form_label(self):
        assert _classify("1. Introduction", 1) == "FORM_LABEL"
        assert _classify("12. See attached", 2) == "FORM_LABEL"

    def test_lettered_list_item_returns_form_label(self):
        assert _classify("A. First item", 1) == "FORM_LABEL"

    def test_roman_numeral_list_item_returns_form_label(self):
        assert _classify("iv. Background section", 1) == "FORM_LABEL"

    def test_legal_keyword_with_few_lines_returns_header(self):
        # "G.L." pattern, n_lines <= 2
        assert _classify("G.L. Chapter 208", 1) == "HEADER"

    def test_section_symbol_with_text_returns_header(self):
        # "§ 34" alone returns SKIP — § is not alphabetic and not in the
        # meaningful symbols set, so the early `if not letters` guard fires.
        # The § legal keyword pattern only reaches execution when the text
        # also contains alphabetic characters.
        assert _classify("§ 34", 1) == "SKIP"
        assert _classify("§ INTRODUCTION", 1) == "HEADER"

    def test_certificate_keyword_returns_header(self):
        assert _classify("CERTIFICATE OF DIVORCE", 1) == "HEADER"

    def test_legal_keyword_with_three_or_more_lines_does_not_return_header(self):
        # n_lines > 2 — header check skipped, falls through to all_caps check
        result = _classify("CERTIFICATE", 3)
        # All caps, len < 80, n_lines <= 3 → FORM_LABEL
        assert result == "FORM_LABEL"

    def test_legal_keyword_check_is_case_sensitive(self):
        # "certificate" (lowercase) does NOT match r"CERTIFICATE"
        # Falls through: not all_caps, n_lines=1, len < 60 → FORM_LABEL
        assert _classify("certificate", 1) == "FORM_LABEL"

    def test_all_caps_short_text_returns_form_label(self):
        assert _classify("FULL NAME", 1) == "FORM_LABEL"

    def test_all_caps_long_text_returns_prose(self):
        # len >= 80 AND n_lines > 3 → escapes both all_caps and short checks
        long = "WORD " * 20     # 100 chars, all caps
        assert _classify(long, 4) == "PROSE"

    def test_short_mixed_case_single_line_returns_form_label(self):
        # n_lines == 1, len < 60 → FORM_LABEL regardless of caps
        assert _classify("Petitioner name", 1) == "FORM_LABEL"

    def test_long_mixed_case_multi_line_returns_prose(self):
        long = "This is a longer sentence that exceeds sixty characters in total length."
        assert _classify(long, 3) == "PROSE"


# ─────────────────────────────────────────────────────────────────────────────
# _lines_are_same_row
# ─────────────────────────────────────────────────────────────────────────────

class TestLinesAreSameRow:

    def test_identical_vertical_range_is_same_row(self):
        ln1 = _line(y0=10, y1=20)
        ln2 = _line(y0=10, y1=20)
        assert _lines_are_same_row(ln1, ln2) is True

    def test_non_overlapping_lines_are_different_rows(self):
        ln1 = _line(y0=0, y1=10)
        ln2 = _line(y0=10, y1=20)
        # overlap = 0, min_h = 10 → 0 > 5 → False
        assert _lines_are_same_row(ln1, ln2) is False

    def test_overlap_greater_than_half_height_is_same_row(self):
        ln1 = _line(y0=0, y1=10)
        ln2 = _line(y0=4, y1=14)
        # overlap = min(10,14) - max(0,4) = 10-4 = 6, min_h = 10 → 6 > 5 → True
        assert _lines_are_same_row(ln1, ln2) is True

    def test_overlap_less_than_half_height_is_different_row(self):
        ln1 = _line(y0=0, y1=10)
        ln2 = _line(y0=6, y1=16)
        # overlap = min(10,16) - max(0,6) = 10-6 = 4, min_h = 10 → 4 > 5 → False
        assert _lines_are_same_row(ln1, ln2) is False

    def test_exactly_half_overlap_is_not_same_row(self):
        ln1 = _line(y0=0, y1=10)
        ln2 = _line(y0=5, y1=15)
        # overlap = 5, min_h = 10 → 5 > 5 → False (strict >)
        assert _lines_are_same_row(ln1, ln2) is False


# ─────────────────────────────────────────────────────────────────────────────
# _group_lines_into_rows
# ─────────────────────────────────────────────────────────────────────────────

class TestGroupLinesIntoRows:

    def test_empty_list_returns_empty(self):
        assert _group_lines_into_rows([]) == []

    def test_single_line_returns_one_row(self):
        ln = _line(y0=0, y1=12)
        rows = _group_lines_into_rows([ln])
        assert len(rows) == 1
        assert rows[0] == [ln]

    def test_two_lines_same_row_grouped_together(self):
        left = _line(x0=0, x1=50, y0=0, y1=12)
        right = _line(x0=60, x1=120, y0=0, y1=12)
        rows = _group_lines_into_rows([left, right])
        assert len(rows) == 1
        assert len(rows[0]) == 2

    def test_two_lines_different_rows_produce_two_groups(self):
        top = _line(y0=0, y1=12)
        bottom = _line(y0=20, y1=32)
        rows = _group_lines_into_rows([top, bottom])
        assert len(rows) == 2

    def test_rows_sorted_top_to_bottom(self):
        bottom = _line(x0=0, y0=20, y1=32)
        top = _line(x0=0, y0=0, y1=12)
        rows = _group_lines_into_rows([bottom, top])
        assert rows[0][0]["bbox"][1] < rows[1][0]["bbox"][1]

    def test_lines_within_row_sorted_left_to_right(self):
        right = _line(x0=60, x1=120, y0=0, y1=12)
        left = _line(x0=0, x1=50, y0=0, y1=12)
        rows = _group_lines_into_rows([right, left])
        assert rows[0][0]["bbox"][0] < rows[0][1]["bbox"][0]


# ─────────────────────────────────────────────────────────────────────────────
# _detect_alignment
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectAlignment:

    def test_empty_lines_returns_left(self):
        block = pymupdf.Rect(0, 0, 400, 100)
        assert _detect_alignment([], block) == "left"

    def test_zero_width_block_returns_left(self):
        block = pymupdf.Rect(50, 0, 50, 100)  # width = 0
        line = {"bbox": [50, 0, 100, 12]}
        assert _detect_alignment([line], block) == "left"

    def test_centered_text_detected(self):
        # block x0=0, x1=400. Line bbox x0=150, x1=250.
        # left margin = 150-0 = 150, right margin = 400-250 = 150 → equal → center
        block = pymupdf.Rect(0, 0, 400, 20)
        line = {"bbox": [150, 0, 250, 12]}
        assert _detect_alignment([line], block) == "center"

    def test_right_aligned_text_detected(self):
        # block x0=0, x1=400. Line x0=380, x1=398.
        # left margin = 380, right margin = 2 → ar < 8 and al > 20 → right
        block = pymupdf.Rect(0, 0, 400, 20)
        line = {"bbox": [380, 0, 398, 12]}
        assert _detect_alignment([line], block) == "right"

    def test_left_aligned_text_detected(self):
        # line starts near block left edge → small left margin
        block = pymupdf.Rect(0, 0, 400, 20)
        line = {"bbox": [2, 0, 200, 12]}
        assert _detect_alignment([line], block) == "left"


# ─────────────────────────────────────────────────────────────────────────────
# _union_rects
# ─────────────────────────────────────────────────────────────────────────────

class TestUnionRects:

    def test_empty_list_returns_empty_rect(self):
        result = _union_rects([])
        assert result == pymupdf.Rect()

    def test_single_rect_returned_unchanged(self):
        r = pymupdf.Rect(10, 20, 50, 60)
        result = _union_rects([r])
        assert result.x0 == 10 and result.y0 == 20
        assert result.x1 == 50 and result.y1 == 60

    def test_two_non_overlapping_rects_produce_bounding_box(self):
        r1 = pymupdf.Rect(0, 0, 50, 20)
        r2 = pymupdf.Rect(60, 30, 100, 50)
        result = _union_rects([r1, r2])
        assert result.x0 == 0 and result.y0 == 0
        assert result.x1 == 100 and result.y1 == 50

    def test_three_rects_correct_bounding_box(self):
        rects = [
            pymupdf.Rect(10, 5, 40, 20),
            pymupdf.Rect(0, 15, 60, 30),
            pymupdf.Rect(20, 0, 35, 10),
        ]
        result = _union_rects(rects)
        assert result.x0 == 0 and result.y0 == 0
        assert result.x1 == 60 and result.y1 == 30


# ─────────────────────────────────────────────────────────────────────────────
# _split_line_by_columns
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitLineByColumns:

    def test_empty_spans_returns_empty_list(self):
        line = _line(spans=[_span(text="")])
        assert _split_line_by_columns(line) == []

    def test_whitespace_only_spans_returns_empty_list(self):
        line = _line(spans=[_span(text="   ")])
        assert _split_line_by_columns(line) == []

    def test_single_span_returns_one_column(self):
        line = _line(spans=[_span(text="Name", x0=10, x1=50)])
        result = _split_line_by_columns(line)
        assert len(result) == 1
        assert result[0]["text"] == "Name"

    def test_two_spans_with_large_gap_produce_two_columns(self):
        # gap=15 — spans separated by > 15pt → two columns
        left = _span(text="Name", x0=0, x1=50)
        right = _span(text="Date", x0=70, x1=120)
        line = _line(spans=[left, right])
        result = _split_line_by_columns(line, gap=15.0)
        assert len(result) == 2
        assert result[0]["text"] == "Name"
        assert result[1]["text"] == "Date"

    def test_two_spans_with_small_gap_merged_into_one_column(self):
        # Gap < 15 → treated as one cluster
        left = _span(text="First", x0=0, x1=30)
        right = _span(text="Last", x0=35, x1=70)
        line = _line(spans=[left, right])
        result = _split_line_by_columns(line, gap=15.0)
        assert len(result) == 1
        assert "First" in result[0]["text"]
        assert "Last" in result[0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# _find_tightest_cell
# ─────────────────────────────────────────────────────────────────────────────

class TestFindTightestCell:

    def test_empty_cell_rects_returns_none(self):
        line_rect = pymupdf.Rect(10, 10, 50, 20)
        assert _find_tightest_cell(line_rect, []) is None

    def test_line_not_contained_returns_none(self):
        line_rect = pymupdf.Rect(200, 200, 300, 220)
        cell = pymupdf.Rect(0, 0, 100, 50)
        assert _find_tightest_cell(line_rect, [cell]) is None

    def test_line_inside_one_cell_returns_that_cell(self):
        cell = pymupdf.Rect(0, 0, 200, 50)
        # Line well inside cell (pad=4 by default — cell expanded by 4 on each side)
        line_rect = pymupdf.Rect(10, 5, 100, 20)
        result = _find_tightest_cell(line_rect, [cell])
        assert result == cell

    def test_line_inside_two_cells_returns_smaller_one(self):
        large = pymupdf.Rect(0, 0, 300, 100)
        small = pymupdf.Rect(5, 5, 150, 45)
        line_rect = pymupdf.Rect(10, 10, 100, 30)
        result = _find_tightest_cell(line_rect, [large, small])
        assert result == small


# ─────────────────────────────────────────────────────────────────────────────
# _get_available_width
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAvailableWidth:

    def test_no_cells_falls_back_to_right_margin(self):
        avail = pymupdf.Rect(50, 10, 200, 20)
        # page_width=594, right_margin=36 → (594 - 36) - 50 = 508
        result = _get_available_width(avail, [], page_width=594.0)
        assert result == pytest.approx(558.0 - 50.0)

    def test_matching_cell_returns_cell_width_from_x0(self):
        # Cell covers the x and y range of the avail rect
        avail = pymupdf.Rect(50, 10, 200, 20)
        cell = pymupdf.Rect(40, 5, 250, 25)   # contains y_mid=15, x0=40 <= 52 <= 250
        result = _get_available_width(avail, [cell])
        # cell.x1 - avail.x0 = 250 - 50 = 200
        assert result == pytest.approx(200.0)

    def test_cell_not_covering_y_mid_is_skipped(self):
        avail = pymupdf.Rect(50, 100, 200, 120)   # y_mid = 110
        cell = pymupdf.Rect(0, 0, 300, 50)         # cell y range 0-50, doesn't cover 110
        result = _get_available_width(avail, [cell], page_width=594.0)
        # Falls back to margin calculation
        assert result == pytest.approx(558.0 - 50.0)

    def test_narrowest_matching_cell_used(self):
        avail = pymupdf.Rect(50, 10, 200, 20)
        wide = pymupdf.Rect(40, 5, 400, 25)   # width from x0: 400-50 = 350
        narrow = pymupdf.Rect(40, 5, 200, 25) # width from x0: 200-50 = 150
        result = _get_available_width(avail, [wide, narrow])
        assert result == pytest.approx(150.0)
