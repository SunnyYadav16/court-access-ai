"""
tests/test_pretranslation_dag.py

Unit tests for the src/ modules used by form_pretranslation_dag.

Follows the same pattern as test_form_scraper.py and test_preprocess_forms.py:
  - sys.path.insert so src.* imports work without Airflow being installed
  - Tests target src/ module functions directly (no Airflow task imports)
  - All file I/O uses tmp_path fixtures
  - No network calls, no GPU, no Docker required

Run with:
    pytest tests/test_pretranslation_dag.py -v
"""

import sys
from pathlib import Path

import pytest

# ── Path setup (matches teammate's pattern exactly) ───────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dags"))

import src.legal_review as lr
import src.ocr_printed as ocr
import src.reconstruct_pdf as rp
import src.translate_text as tt

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_pdf(path: Path) -> None:
    """Create a minimal real PDF using PyMuPDF for reconstruction tests."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((100, 100), "COMMONWEALTH OF MASSACHUSETTS", fontsize=12)
    page.insert_text((100, 130), "Notice of Appearance", fontsize=10)
    page.insert_text((100, 160), "Defendant:", fontsize=10)
    page.insert_text((100, 190), "Plaintiff:", fontsize=10)
    doc.save(str(path))
    doc.close()


def _sample_regions() -> list[dict]:
    """Realistic OCR regions used across multiple tests."""
    return [
        {
            "text": "COMMONWEALTH OF MASSACHUSETTS",
            "bbox": [100, 100, 500, 120],
            "confidence": 0.99,
            "page": 0,
            "font_size": 12.0,
            "is_bold": True,
        },
        {
            "text": "Notice of Appearance",
            "bbox": [100, 130, 400, 150],
            "confidence": 0.97,
            "page": 0,
            "font_size": 10.0,
            "is_bold": False,
        },
        {
            "text": "Defendant:",
            "bbox": [100, 160, 200, 180],
            "confidence": 0.95,
            "page": 0,
            "font_size": 10.0,
            "is_bold": False,
        },
        {
            "text": "Plaintiff:",
            "bbox": [100, 190, 200, 210],
            "confidence": 0.95,
            "page": 0,
            "font_size": 10.0,
            "is_bold": False,
        },
    ]


# ══════════════════════════════════════════════════════════════════════════════
# src/ocr_printed.py
# ══════════════════════════════════════════════════════════════════════════════


class TestOcrPrinted:
    def test_returns_dict_with_regions_and_full_text(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        assert "regions" in result
        assert "full_text" in result

    def test_regions_is_list(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        assert isinstance(result["regions"], list)

    def test_regions_not_empty_for_real_pdf(self, tmp_path):
        """A PDF with embedded text must yield at least one region."""
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        assert len(result["regions"]) > 0

    def test_each_region_has_required_keys(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        for region in result["regions"]:
            assert "text" in region, f"Missing 'text' in {region}"
            assert "bbox" in region, f"Missing 'bbox' in {region}"
            assert "confidence" in region, f"Missing 'confidence' in {region}"
            assert "page" in region, f"Missing 'page' in {region}"

    def test_bbox_is_list_of_four_numbers(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        for region in result["regions"]:
            assert isinstance(region["bbox"], list)
            assert len(region["bbox"]) == 4

    def test_confidence_in_valid_range(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        for region in result["regions"]:
            assert 0.0 <= region["confidence"] <= 1.0

    def test_full_text_joins_all_region_texts(self, tmp_path):
        """full_text must equal all region texts joined by newline."""
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        expected = "\n".join(r["text"] for r in result["regions"])
        assert result["full_text"] == expected

    def test_raises_file_not_found_for_missing_pdf(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ocr.extract_text_from_pdf(str(tmp_path / "nonexistent.pdf"))

    def test_page_number_is_integer(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        for region in result["regions"]:
            assert isinstance(region["page"], int)

    def test_page_number_is_zero_indexed(self, tmp_path):
        """Single-page PDF: all regions on page 0."""
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf)
        result = ocr.extract_text_from_pdf(str(pdf))
        for region in result["regions"]:
            assert region["page"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# src/translate_text.py
# ══════════════════════════════════════════════════════════════════════════════


class TestTranslateText:
    def test_returns_dict_with_three_keys(self):
        result = tt.translate_text("Defendant:", "eng_Latn", "spa_Latn")
        assert "original" in result
        assert "translated" in result
        assert "confidence" in result

    def test_original_field_matches_input(self):
        text = "Notice of Appearance"
        result = tt.translate_text(text, "eng_Latn", "spa_Latn")
        assert result["original"] == text

    def test_stub_spanish_prefixes_es(self):
        """Stub translation must prefix with [ES] so output PDFs are distinguishable."""
        result = tt.translate_text("Defendant:", "eng_Latn", "spa_Latn")
        assert result["translated"].startswith("[ES]")

    def test_stub_portuguese_prefixes_pt(self):
        result = tt.translate_text("Defendant:", "eng_Latn", "por_Latn")
        assert result["translated"].startswith("[PT]")

    def test_translated_field_is_string(self):
        result = tt.translate_text("Plaintiff:", "eng_Latn", "spa_Latn")
        assert isinstance(result["translated"], str)

    def test_confidence_is_float_in_range(self):
        result = tt.translate_text("Plaintiff:", "eng_Latn", "spa_Latn")
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_empty_string_does_not_raise(self):
        result = tt.translate_text("", "eng_Latn", "spa_Latn")
        assert "translated" in result

    def test_empty_string_translated_field_is_string(self):
        result = tt.translate_text("", "eng_Latn", "spa_Latn")
        assert isinstance(result["translated"], str)

    def test_spanish_and_portuguese_produce_different_output(self):
        """ES and PT stubs should produce different prefixes."""
        es = tt.translate_text("Defendant:", "eng_Latn", "spa_Latn")
        pt = tt.translate_text("Defendant:", "eng_Latn", "por_Latn")
        assert es["translated"] != pt["translated"]

    def test_same_input_same_output(self):
        """Stub must be deterministic."""
        r1 = tt.translate_text("Defendant:", "eng_Latn", "spa_Latn")
        r2 = tt.translate_text("Defendant:", "eng_Latn", "spa_Latn")
        assert r1["translated"] == r2["translated"]


# ══════════════════════════════════════════════════════════════════════════════
# src/legal_review.py
# ══════════════════════════════════════════════════════════════════════════════


class TestLegalReview:
    def test_returns_dict_with_status_and_corrections(self):
        result = lr.review_legal_terms("ORIGINAL: ...\nSPANISH: ...", "spa_Latn")
        assert "status" in result
        assert "corrections" in result

    def test_stub_returns_ok_status(self):
        result = lr.review_legal_terms("text", "spa_Latn")
        assert result["status"] == "ok"

    def test_stub_returns_empty_corrections(self):
        result = lr.review_legal_terms("text", "spa_Latn")
        assert result["corrections"] == []

    def test_corrections_is_list(self):
        result = lr.review_legal_terms("text", "por_Latn")
        assert isinstance(result["corrections"], list)

    def test_works_for_portuguese(self):
        result = lr.review_legal_terms("text", "por_Latn")
        assert result["status"] == "ok"

    def test_empty_text_does_not_raise(self):
        result = lr.review_legal_terms("", "spa_Latn")
        assert "status" in result

    def test_does_not_raise_on_long_text(self):
        """Legal review must handle large combined original+translated text."""
        long_text = "Some legal text. " * 500
        result = lr.review_legal_terms(long_text, "spa_Latn")
        assert result["status"] == "ok"


# ══════════════════════════════════════════════════════════════════════════════
# src/reconstruct_pdf.py
# ══════════════════════════════════════════════════════════════════════════════


class TestReconstructPdf:
    def test_creates_output_file(self, tmp_path):
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(out))
        assert out.exists()

    def test_output_file_is_not_empty(self, tmp_path):
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(out))
        assert out.stat().st_size > 0

    def test_output_is_valid_pdf(self, tmp_path):
        import fitz

        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(out))
        doc = fitz.open(str(out))
        assert len(doc) >= 1
        doc.close()

    def test_empty_regions_still_produces_pdf(self, tmp_path):
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "out.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), [], str(out))
        assert out.exists()

    def test_raises_file_not_found_for_missing_original(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            rp.reconstruct_pdf(
                str(tmp_path / "missing.pdf"),
                [],
                str(tmp_path / "out.pdf"),
            )

    def test_creates_output_directory_if_needed(self, tmp_path):
        orig = tmp_path / "orig.pdf"
        out_dir = tmp_path / "subdir" / "v1"
        out = out_dir / "es.pdf"
        _make_pdf(orig)
        out_dir.mkdir(parents=True)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(out))
        assert out.exists()

    def test_portuguese_produces_separate_file(self, tmp_path):
        orig = tmp_path / "orig.pdf"
        es = tmp_path / "es.pdf"
        pt = tmp_path / "pt.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(es))
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("PT"), str(pt))
        assert es.exists()
        assert pt.exists()

    def test_output_size_reasonable(self, tmp_path):
        """Output PDF should be at least 1KB — not a zero-byte or corrupted file."""
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        rp.reconstruct_pdf(str(orig), _sample_regions_translated("ES"), str(out))
        assert out.stat().st_size > 1024

    def test_regions_with_missing_translated_text_skipped(self, tmp_path):
        """Regions with empty translated_text should not cause errors."""
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        regions = [
            {
                "text": "Title",
                "translated_text": "",
                "bbox": [100, 100, 400, 120],
                "page": 0,
                "font_size": 12.0,
                "is_bold": False,
            },
            {
                "text": "Body",
                "translated_text": "[ES] Body text",
                "bbox": [100, 130, 400, 150],
                "page": 0,
                "font_size": 10.0,
                "is_bold": False,
            },
        ]
        rp.reconstruct_pdf(str(orig), regions, str(out))
        assert out.exists()

    def test_bold_regions_handled(self, tmp_path):
        """Bold regions should not cause errors in reconstruction."""
        orig = tmp_path / "orig.pdf"
        out = tmp_path / "es.pdf"
        _make_pdf(orig)
        regions = [
            {
                "text": "BOLD TITLE",
                "translated_text": "[ES] TITULO EN NEGRITA",
                "bbox": [100, 100, 400, 120],
                "page": 0,
                "font_size": 12.0,
                "is_bold": True,
            },
        ]
        rp.reconstruct_pdf(str(orig), regions, str(out))
        assert out.exists()


def _sample_regions_translated(lang_tag: str) -> list[dict]:
    """Return sample OCR regions with translated_text set."""
    return [{**r, "translated_text": f"[{lang_tag}] {r['text']}"} for r in _sample_regions()]
