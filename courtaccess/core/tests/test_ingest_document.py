"""
Unit tests for courtaccess/core/ingest_document.py

Functions under test:
  is_content_image  — pure dict predicate, no deps
  classify_page     — page classification logic (mocked pymupdf page)
  ingest_pdf        — orchestration (real minimal PDFs via pymupdf)

Design notes:
  - classify_page receives a pymupdf page object. We mock it with MagicMock so
    no real PDF is needed — the classification logic is pure once the page API
    is stubbed.
  - ingest_pdf is tested with real minimal PDFs constructed via pymupdf in
    tmp_path. This exercises the FileNotFoundError / ValueError guards and
    the output contract without needing pre-existing fixture files.
  - RENDER_DPI has a source-level default (300) — no conftest patch needed.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from courtaccess.core.ingest_document import classify_page, ingest_pdf, is_content_image

# ── Page mock builder ─────────────────────────────────────────────────────────

def _make_page(
    span_texts: list[str] | None = None,
    images: list | None = None,
    drawings: list | None = None,
    page_width: float = 595.0,
    page_height: float = 842.0,
    image_rects: list | None = None,
    image_rects_raises: bool = False,
    image_blocks: list | None = None,
) -> MagicMock:
    """
    Build a MagicMock that satisfies the pymupdf page interface used by
    classify_page:
      page.get_text("dict", flags=...) → {"blocks": [...]}
      page.get_images(full=True)       → list of image tuples
      page.get_drawings()              → list
      page.rect.width / .height        → floats
      page.get_image_rects(xref)       → list[pymupdf.Rect] or raises

    Args:
        span_texts:        flat list of non-empty span text strings.
        images:            list of image tuples (xref, smask, w, h, ...).
        drawings:          list of drawing dicts.
        image_rects:       list of pymupdf.Rect returned by get_image_rects().
        image_rects_raises: if True, get_image_rects raises Exception.
        image_blocks:      list of (x0,y0,x1,y1) tuples for type=1 image blocks.
    """
    # Build text-dict blocks from flat span list
    blocks: list = []
    if span_texts:
        text_block: dict = {
            "type": 0,
            "lines": [
                {"spans": [{"text": t}]}
                for t in span_texts
            ],
        }
        blocks.append(text_block)

    # Add type=1 image blocks for coverage fallback-1 testing
    for bbox in (image_blocks or []):
        blocks.append({"type": 1, "bbox": bbox})

    td = {"blocks": blocks}

    page = MagicMock()
    page.get_text.return_value = td
    page.get_images.return_value = images or []
    page.get_drawings.return_value = drawings or []
    page.rect.width = page_width
    page.rect.height = page_height

    if image_rects_raises:
        page.get_image_rects.side_effect = Exception("xref lookup failed")
    else:
        page.get_image_rects.return_value = [
            pymupdf.Rect(r) if isinstance(r, (tuple, list)) else r
            for r in (image_rects or [])
        ]

    return page


def _make_pdf(path: Path, num_pages: int = 1, with_text: bool = True) -> None:
    """Create a minimal real PDF using pymupdf for ingest_pdf tests.

    Each insert_text() call creates a separate text block (one span each).
    We insert 8 lines so span_count=8 > 5 → DIGITAL classification.
    """
    doc = pymupdf.open()
    for _ in range(num_pages):
        page = doc.new_page(width=595, height=842)
        if with_text:
            for i in range(8):
                page.insert_text((50, 80 + i * 30), f"Line {i}: Legal document text content.")
    doc.save(str(path))
    doc.close()


# ─────────────────────────────────────────────────────────────────────────────
# is_content_image
# ─────────────────────────────────────────────────────────────────────────────

class TestIsContentImage:

    def test_digital_page_always_returns_false(self):
        # is_scanned=False short-circuits immediately
        info = {
            "is_scanned": False,
            "img_coverage": 99.0,
            "span_count": 0,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is False

    def test_scanned_page_meeting_all_conditions_returns_true(self):
        info = {
            "is_scanned": True,
            "img_coverage": 96.0,
            "span_count": 0,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is True

    def test_img_coverage_exactly_95_returns_false(self):
        # Condition is > 95.0 (strict), not >= 95.0
        info = {
            "is_scanned": True,
            "img_coverage": 95.0,
            "span_count": 0,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is False

    def test_any_span_count_returns_false(self):
        info = {
            "is_scanned": True,
            "img_coverage": 99.0,
            "span_count": 1,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is False

    def test_any_drawings_returns_false(self):
        info = {
            "is_scanned": True,
            "img_coverage": 99.0,
            "span_count": 0,
            "drawings": 1,
            "images": 0,
        }
        assert is_content_image(info) is False

    def test_any_images_returns_false(self):
        info = {
            "is_scanned": True,
            "img_coverage": 99.0,
            "span_count": 0,
            "drawings": 0,
            "images": 1,
        }
        assert is_content_image(info) is False

    def test_missing_is_scanned_defaults_to_true_and_evaluates_rest(self):
        # Default is True → proceeds to check other conditions
        info = {
            "img_coverage": 99.0,
            "span_count": 0,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is True

    def test_low_coverage_scanned_returns_false(self):
        info = {
            "is_scanned": True,
            "img_coverage": 50.0,
            "span_count": 0,
            "drawings": 0,
            "images": 0,
        }
        assert is_content_image(info) is False


# ─────────────────────────────────────────────────────────────────────────────
# classify_page — output contract
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPageContract:

    def test_output_has_all_required_keys(self):
        page = _make_page()  # blank page
        result = classify_page(page)
        required = {"page_type", "is_scanned", "span_count", "images", "drawings", "img_coverage"}
        assert required == set(result.keys())

    def test_img_coverage_rounded_to_one_decimal(self):
        # A page with no images → img_coverage should be 0.0 (already clean)
        page = _make_page()
        result = classify_page(page)
        assert result["img_coverage"] == round(result["img_coverage"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# classify_page — BLANK classification
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPageBlank:

    def test_no_spans_no_images_is_blank(self):
        page = _make_page(span_texts=[], images=[], drawings=[])
        result = classify_page(page)
        assert result["page_type"] == "BLANK"
        assert result["is_scanned"] is False

    def test_blank_page_has_zero_span_count(self):
        page = _make_page()
        result = classify_page(page)
        assert result["span_count"] == 0

    def test_drawings_alone_do_not_prevent_blank(self):
        # Drawings are counted but not used in BLANK check — only spans and images
        page = _make_page(drawings=[{"type": "l"}])
        result = classify_page(page)
        assert result["page_type"] == "BLANK"
        assert result["drawings"] == 1

    def test_whitespace_only_spans_treated_as_no_spans(self):
        # span["text"].strip() must be truthy — whitespace-only counts as 0
        page = _make_page(span_texts=["   ", "\t", ""])
        result = classify_page(page)
        assert result["page_type"] == "BLANK"


# ─────────────────────────────────────────────────────────────────────────────
# classify_page — SCANNED classification
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPageScanned:

    def test_image_with_no_text_is_scanned(self):
        # images exist, span_count == 0 → SCANNED even with low coverage
        img = (1, 0, 100, 100, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            span_texts=[],
            images=[img],
            image_rects=[pymupdf.Rect(0, 0, 100, 100)],  # small coverage
        )
        result = classify_page(page)
        assert result["page_type"] == "SCANNED"
        assert result["is_scanned"] is True

    def test_high_image_coverage_is_scanned_even_with_text(self):
        # img_coverage > 40% overrides span count
        large_rect = pymupdf.Rect(0, 0, 595, 450)  # covers > 50% of page

        img = (1, 0, 595, 450, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            span_texts=["word"] * 10,  # plenty of spans
            images=[img],
            image_rects=[large_rect],
        )
        result = classify_page(page)
        assert result["page_type"] == "SCANNED"
        assert result["img_coverage"] > 40.0

    def test_few_spans_no_images_falls_back_to_scanned(self):
        # 1-5 spans, no images, coverage 0 -> doesn't reach DIGITAL branch
        page = _make_page(span_texts=["word1", "word2", "word3"])
        result = classify_page(page)
        assert result["page_type"] == "SCANNED"
        assert result["span_count"] == 3

    def test_exactly_five_spans_is_scanned(self):
        # DIGITAL requires span_count > 5 (strict), so 5 → fallback SCANNED
        page = _make_page(span_texts=["w"] * 5)
        result = classify_page(page)
        assert result["page_type"] == "SCANNED"

    def test_img_coverage_boundary_at_40_percent(self):
        # Exactly 40.0% → condition is > 40.0 (strict), so not SCANNED by that rule
        # With 6+ spans → should be DIGITAL
        page_area = 595.0 * 842.0
        target_area = page_area * 0.40
        # 595 * height = target_area → height = target_area / 595
        h = target_area / 595.0
        rect = pymupdf.Rect(0, 0, 595, h)
        img = (1, 0, 595, int(h), 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            span_texts=["word"] * 6,
            images=[img],
            image_rects=[rect],
        )
        result = classify_page(page)
        assert result["img_coverage"] == pytest.approx(40.0, abs=0.5)
        assert result["page_type"] == "DIGITAL"


# ─────────────────────────────────────────────────────────────────────────────
# classify_page — DIGITAL classification
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPageDigital:

    def test_many_spans_low_coverage_is_digital(self):
        page = _make_page(span_texts=["word"] * 10, images=[], drawings=[])
        result = classify_page(page)
        assert result["page_type"] == "DIGITAL"
        assert result["is_scanned"] is False

    def test_exactly_six_spans_is_digital(self):
        # span_count > 5 → DIGITAL (6 is the minimum)
        page = _make_page(span_texts=["w"] * 6)
        result = classify_page(page)
        assert result["page_type"] == "DIGITAL"

    def test_span_count_reported_correctly(self):
        page = _make_page(span_texts=["a", "b", "c", "d", "e", "f", "g"])
        result = classify_page(page)
        assert result["span_count"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# classify_page — image coverage fallback paths
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPageImageCoverage:

    def test_primary_path_uses_get_image_rects(self):
        # Large rect returned by get_image_rects → high coverage → SCANNED
        large_rect = pymupdf.Rect(0, 0, 595, 600)
        img = (1, 0, 595, 600, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(images=[img], image_rects=[large_rect])
        result = classify_page(page)
        assert result["img_coverage"] > 40.0

    def test_fallback1_uses_image_block_bboxes_when_rects_empty(self):
        # get_image_rects returns [] → fallback 1: type=1 block bbox used
        # Block covers (0,0,595,600) → high coverage → SCANNED
        img = (1, 0, 595, 600, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            images=[img],
            image_rects=[],               # primary returns nothing
            image_blocks=[(0, 0, 595, 600)],  # fallback-1 block
        )
        result = classify_page(page)
        assert result["img_coverage"] > 40.0

    def test_fallback2_assumes_85_percent_for_large_image(self):
        # get_image_rects raises, no image blocks → fallback 2:
        # image with w>500 and h>500 → total_img_area = page_area * 0.85
        img = (1, 0, 600, 800, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            images=[img],
            image_rects_raises=True,   # primary raises
            image_blocks=[],           # no fallback-1 blocks
        )
        result = classify_page(page)
        assert result["img_coverage"] == pytest.approx(85.0, abs=0.1)

    def test_fallback2_skipped_for_small_image(self):
        # Image dimensions <= 500 → fallback 2 condition not met → coverage stays 0
        img = (1, 0, 400, 400, 8, "DeviceRGB", "", "", "jpeg", 0, 0)
        page = _make_page(
            span_texts=["w"] * 6,  # enough for DIGITAL if coverage stays low
            images=[img],
            image_rects_raises=True,
        )
        result = classify_page(page)
        assert result["img_coverage"] == 0.0

    def test_zero_page_area_gives_zero_coverage(self):
        page = _make_page(page_width=0.0, page_height=0.0)
        result = classify_page(page)
        assert result["img_coverage"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ingest_pdf
# ─────────────────────────────────────────────────────────────────────────────

class TestIngestPdf:

    def test_raises_file_not_found_for_missing_pdf(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ingest_pdf(str(tmp_path / "ghost.pdf"))

    def test_raises_value_error_for_non_pdf_file(self, tmp_path):
        bad = tmp_path / "not_a_pdf.pdf"
        bad.write_bytes(b"this is not a pdf at all")
        with pytest.raises(ValueError):
            ingest_pdf(str(bad))

    def test_raises_value_error_for_empty_pdf(self, tmp_path):
        # pymupdf refuses to save a zero-page document (raises on doc.save),
        # so we mock pymupdf.open to return a stub with page_count=0. The file
        # must exist on disk so the FileNotFoundError guard passes first.
        pdf = tmp_path / "empty.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        mock_doc = MagicMock()
        mock_doc.page_count = 0
        with patch("pymupdf.open", return_value=mock_doc), pytest.raises(ValueError):
            ingest_pdf(str(pdf))

    def test_single_page_pdf_returns_correct_contract(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf, num_pages=1)
        result = ingest_pdf(str(pdf))
        assert result["page_count"] == 1
        assert result["pdf_path"] == str(pdf.resolve())
        assert len(result["pages"]) == 1

    def test_multi_page_pdf_returns_all_pages(self, tmp_path):
        pdf = tmp_path / "multi.pdf"
        _make_pdf(pdf, num_pages=3)
        result = ingest_pdf(str(pdf))
        assert result["page_count"] == 3
        assert len(result["pages"]) == 3

    def test_page_entry_has_all_required_fields(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf, num_pages=1)
        result = ingest_pdf(str(pdf))
        page = result["pages"][0]
        required = {"page_num", "image_path", "width_px", "height_px",
                    "page_type", "is_scanned", "span_count", "img_coverage"}
        assert required == set(page.keys())

    def test_page_num_is_zero_indexed(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf, num_pages=2)
        result = ingest_pdf(str(pdf))
        assert result["pages"][0]["page_num"] == 0
        assert result["pages"][1]["page_num"] == 1

    def test_png_images_written_to_default_output_dir(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        _make_pdf(pdf, num_pages=1)
        result = ingest_pdf(str(pdf))
        image_path = Path(result["pages"][0]["image_path"])
        assert image_path.exists()
        assert image_path.suffix == ".png"
        # Default output dir is <pdf_dir>/pages/
        assert image_path.parent.name == "pages"

    def test_custom_output_dir_respected(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        out = tmp_path / "custom_output"
        _make_pdf(pdf, num_pages=1)
        result = ingest_pdf(str(pdf), output_dir=str(out))
        image_path = Path(result["pages"][0]["image_path"])
        assert image_path.parent == out

    def test_text_pdf_classified_as_digital(self, tmp_path):
        # A PDF with real vector text should classify as DIGITAL
        pdf = tmp_path / "digital.pdf"
        _make_pdf(pdf, num_pages=1, with_text=True)
        result = ingest_pdf(str(pdf))
        assert result["pages"][0]["page_type"] == "DIGITAL"
