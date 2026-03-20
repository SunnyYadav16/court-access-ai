"""
Tests for courtaccess/core/ingest_document.py

Uses synthetic PyMuPDF pages built in memory — no real PDF files needed
for classification tests. ingest_pdf() tests use a real minimal PDF
created in a temp directory.
"""

import os
import tempfile

import pymupdf
import pytest

from courtaccess.core.ingest_document import (
    ingest_pdf,
    is_content_image,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pdf_with_text(text: str = "Hello world this is a test") -> pymupdf.Document:
    """Create an in-memory PDF with real vector text."""
    doc  = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        pymupdf.Point(50, 100),
        "\n".join([text] * 10),   # enough spans to exceed threshold of 5
        fontsize=12,
    )
    return doc


def _make_blank_pdf() -> pymupdf.Document:
    """Create an in-memory PDF with no content."""
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    return doc


def _save_pdf(doc: pymupdf.Document, path: str):
    """Save an in-memory PDF to disk."""
    doc.save(path)
    doc.close()


# ── classify_page ─────────────────────────────────────────────────────────────

class TestIsContentImageInClassifySection:

    def test_all_zero_high_coverage_is_content_image(self):
        # Only case that returns True — nothing on the page at all
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  0,
            "drawings":    0,
            "images":      0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is True

    def test_has_spans_not_content_image(self):
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  1,
            "drawings":    0,
            "images":      0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_has_drawings_not_content_image(self):
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  0,
            "drawings":    1,
            "images":      0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_has_images_not_content_image(self):
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  0,
            "drawings":    0,
            "images":      1,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_coverage_exactly_95_not_content_image(self):
        # Boundary: > 95, not >= 95
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  0,
            "drawings":    0,
            "images":      0,
            "img_coverage": 95.0,
        }
        assert is_content_image(info) is False

    def test_coverage_just_above_95_is_content_image(self):
        info = {
            "page_type":   "SCANNED",
            "is_scanned":  True,
            "span_count":  0,
            "drawings":    0,
            "images":      0,
            "img_coverage": 95.1,
        }
        assert is_content_image(info) is True

    def test_digital_page_with_no_content_not_skipped(self):
        # Digital pages should never be skipped even at high coverage
        info = {
            "page_type":   "DIGITAL",
            "is_scanned":  False,
            "span_count":  0,
            "drawings":    0,
            "images":      0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is True

# ── is_content_image ──────────────────────────────────────────────────────────

class TestIsContentImage:

    def test_all_zero_high_coverage_is_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     0,
            "images":       0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is True

    def test_has_spans_not_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   1,
            "drawings":     0,
            "images":       0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_has_drawings_not_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     1,
            "images":       0,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_has_images_not_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     0,
            "images":       1,
            "img_coverage": 96.0,
        }
        assert is_content_image(info) is False

    def test_coverage_exactly_95_not_content_image(self):
        # Boundary: > 95, not >= 95
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     0,
            "images":       0,
            "img_coverage": 95.0,
        }
        assert is_content_image(info) is False

    def test_coverage_just_above_95_is_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     0,
            "images":       0,
            "img_coverage": 95.1,
        }
        assert is_content_image(info) is True

    def test_low_coverage_not_content_image(self):
        info = {
            "page_type":    "SCANNED",
            "is_scanned":   True,
            "span_count":   0,
            "drawings":     0,
            "images":       0,
            "img_coverage": 20.0,
        }
        assert is_content_image(info) is False

# ── ingest_pdf ────────────────────────────────────────────────────────────────

class TestIngestPdf:

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest_pdf("/nonexistent/path/doc.pdf")

    def test_raises_value_error_for_invalid_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf",
                                         delete=False) as f:
            f.write(b"not a pdf")
            tmp = f.name
        try:
            with pytest.raises(ValueError):
                ingest_pdf(tmp)
        finally:
            os.unlink(tmp)

    def test_returns_correct_page_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            doc = _make_pdf_with_text()
            _save_pdf(doc, pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            assert result["page_count"] == 1

    def test_output_contract_keys_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            assert "pages"      in result
            assert "page_count" in result
            assert "pdf_path"   in result

    def test_page_entry_has_classification_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            page = result["pages"][0]
            assert "page_type"   in page
            assert "is_scanned"  in page
            assert "span_count"  in page
            assert "img_coverage" in page

    def test_digital_pdf_classified_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            assert result["pages"][0]["page_type"] == "DIGITAL"

    def test_blank_pdf_classified_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "blank.pdf")
            _save_pdf(_make_blank_pdf(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            assert result["pages"][0]["page_type"] == "BLANK"

    def test_images_are_saved_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path  = os.path.join(tmpdir, "test.pdf")
            image_dir = os.path.join(tmpdir, "pages")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, image_dir)
            for page in result["pages"]:
                assert os.path.exists(page["image_path"]), (
                    f"Image not saved: {page['image_path']}"
                )

    def test_image_dimensions_are_positive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            for page in result["pages"]:
                assert page["width_px"]  > 0
                assert page["height_px"] > 0

    def test_pdf_path_in_result_is_absolute(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "test.pdf")
            _save_pdf(_make_pdf_with_text(), pdf_path)
            result = ingest_pdf(pdf_path, tmpdir)
            assert os.path.isabs(result["pdf_path"])
