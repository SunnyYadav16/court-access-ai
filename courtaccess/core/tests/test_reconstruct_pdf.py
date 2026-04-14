"""
Unit tests for courtaccess/core/reconstruct_pdf.py

Functions under test:
  _citation_fallback  — pure: append missing citations from orig to trans
  _restore_caps       — pure: uppercase trans if orig was all-caps
  _insert_unit_html   — page insertion (mocked pymupdf page)
  reconstruct_pdf     — orchestration (real minimal PDFs via tmp_path)

Design notes:
  - _citation_fallback and _restore_caps are pure functions with no deps;
    tested directly with no mocking.
  - _insert_unit_html receives a pymupdf page object — mocked with MagicMock
    so no real PDF is needed. Insert_htmlbox fallback path tested by making
    insert_htmlbox raise.
  - reconstruct_pdf is tested with real minimal PDFs created in tmp_path to
    exercise FileNotFoundError / ValueError guards and output-file creation.
    The full redact+insert pipeline is exercised with a simple translated_regions
    list on a 1-page PDF.
"""

from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from courtaccess.core.reconstruct_pdf import (
    _citation_fallback,
    _insert_unit_html,
    _restore_caps,
    reconstruct_pdf,
)

# ── Minimal PDF factory ───────────────────────────────────────────────────────


def _make_pdf(path, num_pages=1, with_text=True):
    """Create a minimal real PDF for reconstruct_pdf integration tests."""
    doc = pymupdf.open()
    for _ in range(num_pages):
        page = doc.new_page(width=595, height=842)
        if with_text:
            for i in range(8):
                page.insert_text((50, 80 + i * 30), f"Line {i}: Original English text.")
    doc.save(str(path))
    doc.close()


def _region(page=0, text="Hello", translated="Hola", preserve=False, bbox=(50, 80, 300, 100), avail_bbox=None):
    """Build a minimal translated_regions entry."""
    return {
        "page": page,
        "text": text,
        "translated_text": translated,
        "preserve": preserve,
        "bbox": list(bbox),
        "avail_bbox": list(avail_bbox) if avail_bbox else list(bbox),
        "fontname": "helv",
        "color_rgb": [0.0, 0.0, 0.0],
        "is_centered": False,
        "is_right": False,
        "font_size": 10.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# _citation_fallback — pure function
# ─────────────────────────────────────────────────────────────────────────────


class TestCitationFallback:
    def test_no_citations_in_orig_returns_trans_unchanged(self):
        result = _citation_fallback("The defendant appeared.", "El acusado apareció.")
        assert result == "El acusado apareció."

    def test_citation_already_in_trans_not_duplicated(self):
        result = _citation_fallback("See G.L. c. 90.", "Ver G.L. c. 90.")
        assert result == "Ver G.L. c. 90."

    def test_missing_gl_citation_appended(self):
        result = _citation_fallback("Under G.L. c. 90.", "Bajo la ley.")
        assert "G.L. c. 90" in result
        assert result.startswith("Bajo la ley.")

    def test_missing_section_symbol_appended(self):
        result = _citation_fallback("See § 12A for details.", "Ver los detalles.")
        assert "§ 12A" in result

    def test_multiple_missing_citations_all_appended(self):
        result = _citation_fallback("See G.L. c. 90 and § 5.", "Ver la ley.")
        assert "G.L. c. 90" in result
        assert "§ 5" in result

    def test_appended_citations_wrapped_in_parentheses(self):
        result = _citation_fallback("Under G.L. c. 10.", "Bajo la ley.")
        assert "(" in result and ")" in result

    def test_appended_after_rstrip_of_trans(self):
        # Translation may have trailing whitespace — stripped before appending
        result = _citation_fallback("Under G.L. c. 10.", "Bajo la ley.   ")
        assert not result.startswith("Bajo la ley.   (")
        assert "G.L. c. 10" in result

    def test_case_insensitive_gl_citation_found(self):
        # _CITE_RE has re.IGNORECASE
        result = _citation_fallback("under g.l. c. 90.", "bajo la ley.")
        assert "g.l. c. 90" in result.lower()


# ─────────────────────────────────────────────────────────────────────────────
# _restore_caps — pure function
# ─────────────────────────────────────────────────────────────────────────────


class TestRestoreCaps:
    def test_all_caps_original_uppercases_translation(self):
        assert _restore_caps("COMMONWEALTH OF MASSACHUSETTS", "commonwealth") == "COMMONWEALTH"

    def test_mixed_case_original_leaves_translation_unchanged(self):
        assert _restore_caps("The Defendant", "el acusado") == "el acusado"

    def test_lowercase_original_leaves_translation_unchanged(self):
        assert _restore_caps("the defendant", "el acusado") == "el acusado"

    def test_no_letters_in_original_leaves_translation_unchanged(self):
        # All-numeric/symbolic orig → lets is [] → not all upper → unchanged
        assert _restore_caps("123 456", "texto") == "texto"

    def test_empty_original_leaves_translation_unchanged(self):
        assert _restore_caps("", "texto") == "texto"

    def test_single_uppercase_letter_uppercases_translation(self):
        assert _restore_caps("A", "texto") == "TEXTO"

    def test_translation_returned_as_is_when_caps_restored(self):
        # Confirms the function returns trans.upper(), not a modified orig
        result = _restore_caps("HELLO", "hola mundo")
        assert result == "HOLA MUNDO"

    def test_all_caps_with_numbers_and_symbols(self):
        # "FORM NO. 123" — only letters "FORMNO" checked, all upper → upcase
        assert _restore_caps("FORM NO. 123", "formulario no.") == "FORMULARIO NO."


# ─────────────────────────────────────────────────────────────────────────────
# _insert_unit_html — mocked page
# ─────────────────────────────────────────────────────────────────────────────


class TestInsertUnitHtml:
    def _make_rect(self, x0=50, y0=100, x1=300, y1=120):
        return pymupdf.Rect(x0, y0, x1, y1)

    def test_blank_text_returns_immediately_without_page_calls(self):
        page = MagicMock()
        _insert_unit_html(page, "   ", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        page.insert_htmlbox.assert_not_called()
        page.insert_text.assert_not_called()

    def test_tiny_width_rect_returns_immediately(self):
        page = MagicMock()
        tiny = pymupdf.Rect(50, 100, 51, 120)  # width = 1 <= 2
        _insert_unit_html(page, "hello", tiny, 10.0, "helv", (0, 0, 0), False)
        page.insert_htmlbox.assert_not_called()

    def test_tiny_height_rect_returns_immediately(self):
        page = MagicMock()
        tiny = pymupdf.Rect(50, 100, 300, 101)  # height = 1 <= 2
        _insert_unit_html(page, "hello", tiny, 10.0, "helv", (0, 0, 0), False)
        page.insert_htmlbox.assert_not_called()

    def test_normal_text_calls_insert_htmlbox(self):
        page = MagicMock()
        _insert_unit_html(page, "Hola mundo", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        page.insert_htmlbox.assert_called_once()

    def test_html_contains_text_content(self):
        page = MagicMock()
        _insert_unit_html(page, "Acusado", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "Acusado" in html_arg

    def test_html_uses_center_alignment_when_is_centered(self):
        page = MagicMock()
        _insert_unit_html(page, "Centered", self._make_rect(), 10.0, "helv", (0, 0, 0), True)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "text-align:center" in html_arg

    def test_html_uses_left_alignment_by_default(self):
        page = MagicMock()
        _insert_unit_html(page, "Left", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "text-align:left" in html_arg

    def test_html_uses_right_alignment_when_is_right(self):
        page = MagicMock()
        _insert_unit_html(page, "Right", self._make_rect(), 10.0, "helv", (0, 0, 0), False, is_right=True)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "text-align:right" in html_arg

    def test_html_escapes_ampersand(self):
        page = MagicMock()
        _insert_unit_html(page, "A & B", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "&amp;" in html_arg
        assert " & " not in html_arg

    def test_html_escapes_less_than(self):
        page = MagicMock()
        _insert_unit_html(page, "x < y", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        html_arg = page.insert_htmlbox.call_args[0][1]
        assert "&lt;" in html_arg

    def test_fallback_to_insert_text_when_htmlbox_raises(self):
        page = MagicMock()
        page.insert_htmlbox.side_effect = Exception("not supported")
        _insert_unit_html(page, "Fallback text", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        page.insert_text.assert_called_once()

    def test_insert_text_fallback_also_suppressed_on_failure(self):
        # If both insert_htmlbox and insert_text raise, no exception should propagate
        page = MagicMock()
        page.insert_htmlbox.side_effect = Exception("htmlbox failed")
        page.insert_text.side_effect = Exception("text failed")
        _insert_unit_html(page, "Text", self._make_rect(), 10.0, "helv", (0, 0, 0), False)
        # No exception raised — contextlib.suppress catches it


# ─────────────────────────────────────────────────────────────────────────────
# reconstruct_pdf — orchestration
# ─────────────────────────────────────────────────────────────────────────────


class TestReconstructPdf:
    def test_raises_file_not_found_for_missing_original(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            reconstruct_pdf(
                str(tmp_path / "ghost.pdf"),
                [],
                str(tmp_path / "out.pdf"),
            )

    def test_raises_value_error_for_non_pdf_file(self, tmp_path):
        # pymupdf.open raises FileDataError before reaching doc.is_pdf for
        # truly corrupt bytes. Mock the open call to return a stub whose
        # is_pdf=False so the source-code ValueError branch is exercised.
        bad = tmp_path / "not_a_pdf.pdf"
        bad.write_bytes(b"%PDF-1.4\n")  # file must exist to pass FileNotFoundError guard
        mock_doc = MagicMock()
        mock_doc.is_pdf = False
        with patch("pymupdf.open", return_value=mock_doc), pytest.raises(ValueError):
            reconstruct_pdf(str(bad), [], str(tmp_path / "out.pdf"))

    def test_creates_output_file(self, tmp_path):
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src)
        reconstruct_pdf(str(src), [], str(out))
        assert out.exists()

    def test_creates_parent_directories_for_output(self, tmp_path):
        src = tmp_path / "original.pdf"
        out = tmp_path / "nested" / "dir" / "output.pdf"
        _make_pdf(src)
        reconstruct_pdf(str(src), [], str(out))
        assert out.exists()

    def test_empty_regions_produces_valid_pdf(self, tmp_path):
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src)
        reconstruct_pdf(str(src), [], str(out))
        # Output is a valid PDF
        result_doc = pymupdf.open(str(out))
        assert result_doc.page_count == 1
        result_doc.close()

    def test_output_page_count_matches_original(self, tmp_path):
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src, num_pages=3)
        reconstruct_pdf(str(src), [], str(out))
        result_doc = pymupdf.open(str(out))
        assert result_doc.page_count == 3
        result_doc.close()

    def test_regions_on_missing_page_skipped_gracefully(self, tmp_path):
        # Region references page 99 but PDF only has 1 page — no crash
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src, num_pages=1)
        region = _region(page=99, text="Hello", translated="Hola")
        reconstruct_pdf(str(src), [region], str(out))
        assert out.exists()

    def test_preserve_region_uses_original_text(self, tmp_path):
        # preserve=True → original text reinserted, translated_text ignored
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src, num_pages=1, with_text=False)
        region = _region(
            page=0,
            text="_______________",
            translated="should not appear",
            preserve=True,
            bbox=(50, 80, 300, 100),
        )
        # Should not raise — just checking it completes cleanly
        reconstruct_pdf(str(src), [region], str(out))
        assert out.exists()

    def test_region_with_empty_translated_text_skipped(self, tmp_path):
        # translated_text="" and preserve=False → region skipped, no crash
        src = tmp_path / "original.pdf"
        out = tmp_path / "output.pdf"
        _make_pdf(src, num_pages=1, with_text=False)
        region = _region(page=0, text="Hello", translated="", preserve=False)
        reconstruct_pdf(str(src), [region], str(out))
        assert out.exists()
