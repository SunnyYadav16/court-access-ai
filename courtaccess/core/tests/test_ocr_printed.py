"""
Unit tests for courtaccess/core/ocr_printed.py

Class under test: OCREngine — extracts text regions from PDF pages.

Methods tested:
  _scanned_region        — static: build region dict with scanned defaults
  __init__ / load        — env-driven mode selection, graceful model loading
  extract_text_from_pdf  — FileNotFoundError guard, output contract, page routing
  _extract_digital       — integration via real minimal PDF (no OCR engine needed)
  _extract_scanned_paddle — mocked PaddleOCR, confidence/text filtering
  _extract_scanned_tesseract — ImportError graceful fallback

Design notes:
  - OCR_CONFIDENCE_THRESHOLD is read as float(os.getenv(...)) at __init__ time.
    An autouse fixture ensures it is set before any OCREngine() construction.
  - USE_REAL_OCR="false" → stub mode: all pages routed through _extract_digital
    (PyMuPDF native extraction — no GPU / external model required).
  - PaddleOCR / pytesseract tested by injecting None into sys.modules so that
    `from paddleocr import PaddleOCR` / `import pytesseract` raises ImportError.
  - _extract_scanned_paddle is exercised with a mocked page (MagicMock) and a
    mock self._paddle whose .ocr() returns controlled PaddleOCR-format output.
"""

from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from courtaccess.core.ocr_printed import OCREngine

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pdf(path, num_pages=1, with_text=True):
    """Create a minimal real PDF for integration tests."""
    doc = pymupdf.open()
    for _ in range(num_pages):
        page = doc.new_page(width=595, height=842)
        if with_text:
            for i in range(8):
                page.insert_text((50, 80 + i * 30), f"Line {i}: Original English text.")
    doc.save(str(path))
    doc.close()


def _paddle_result(text="Hello world", conf=0.99, box=None):
    """Build a minimal PaddleOCR result list."""
    if box is None:
        box = [[10, 10], [200, 10], [200, 30], [10, 30]]
    return [[[box, (text, conf)]]]


def _mock_page(width=595.0, height=842.0, pix_width=595, pix_height=842):
    """Build a MagicMock pymupdf page with controllable geometry."""
    mock_pix = MagicMock()
    mock_pix.width = pix_width
    mock_pix.height = pix_height
    page = MagicMock()
    page.rect.width = width
    page.rect.height = height
    page.get_pixmap.return_value = mock_pix
    return page, mock_pix


# ── Autouse env fixture ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _ocr_env(monkeypatch):
    """Ensure OCR env vars are set before every test in this module."""
    monkeypatch.setenv("OCR_CONFIDENCE_THRESHOLD", "0.6")
    monkeypatch.setenv("USE_REAL_OCR", "false")


@pytest.fixture()
def engine():
    """Stub-mode OCREngine, already loaded."""
    return OCREngine().load()


# ─────────────────────────────────────────────────────────────────────────────
# _scanned_region — pure static method
# ─────────────────────────────────────────────────────────────────────────────


class TestScannedRegion:

    def test_returns_dict_with_all_contract_keys(self):
        r = OCREngine._scanned_region("Hello", 0, 0, 100, 20, 0.9, 0)
        required = {
            "text", "bbox", "avail_bbox", "confidence", "page",
            "font_size", "is_bold", "fontname", "color_rgb",
            "is_centered", "is_right", "unit_type", "is_caps", "preserve",
        }
        assert required.issubset(r.keys())

    def test_bbox_and_avail_bbox_are_equal_for_scanned(self):
        r = OCREngine._scanned_region("Text", 10, 20, 110, 40, 0.95, 0)
        assert r["bbox"] == r["avail_bbox"]

    def test_coordinates_stored_correctly(self):
        r = OCREngine._scanned_region("T", 5, 10, 50, 30, 0.8, 2)
        assert r["bbox"] == [5, 10, 50, 30]

    def test_confidence_passed_through(self):
        r = OCREngine._scanned_region("T", 0, 0, 100, 20, 0.75, 0)
        assert r["confidence"] == pytest.approx(0.75)

    def test_page_num_stored(self):
        r = OCREngine._scanned_region("T", 0, 0, 100, 20, 0.9, 3)
        assert r["page"] == 3

    def test_default_font_size_is_ten(self):
        r = OCREngine._scanned_region("T", 0, 0, 100, 20, 0.9, 0)
        assert r["font_size"] == 10.0

    def test_custom_font_size_stored(self):
        r = OCREngine._scanned_region("T", 0, 0, 100, 20, 0.9, 0, font_size=12.5)
        assert r["font_size"] == pytest.approx(12.5)

    def test_defaults_are_helv_black_left_not_bold(self):
        r = OCREngine._scanned_region("T", 0, 0, 100, 20, 0.9, 0)
        assert r["fontname"] == "helv"
        assert r["color_rgb"] == [0.0, 0.0, 0.0]
        assert r["is_bold"] is False
        assert r["is_centered"] is False
        assert r["preserve"] is False


# ─────────────────────────────────────────────────────────────────────────────
# __init__ — env-driven mode flag
# ─────────────────────────────────────────────────────────────────────────────


class TestOCREngineInit:

    def test_use_real_false_when_env_is_false(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "false")
        eng = OCREngine()
        assert eng._use_real is False

    def test_use_real_true_when_env_is_true(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "true")
        eng = OCREngine()
        assert eng._use_real is True

    def test_confidence_threshold_read_from_env(self, monkeypatch):
        monkeypatch.setenv("OCR_CONFIDENCE_THRESHOLD", "0.75")
        eng = OCREngine()
        assert pytest.approx(0.75) == eng.OCR_CONFIDENCE_THRESHOLD

    def test_paddle_and_tesseract_start_unloaded(self):
        eng = OCREngine()
        assert eng._paddle is None
        assert eng._tesseract_available is False


# ─────────────────────────────────────────────────────────────────────────────
# load() — model loading with graceful fallbacks
# ─────────────────────────────────────────────────────────────────────────────


class TestLoad:

    def test_returns_self_for_chaining(self):
        eng = OCREngine()
        result = eng.load()
        assert result is eng

    def test_stub_mode_does_not_touch_paddle(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "false")
        eng = OCREngine().load()
        assert eng._paddle is None
        assert eng._tesseract_available is False

    def test_real_mode_paddle_unavailable_paddle_stays_none(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "true")
        with patch.dict("sys.modules", {"paddleocr": None, "pytesseract": None}):
            eng = OCREngine().load()
        assert eng._paddle is None

    def test_real_mode_tesseract_unavailable_flag_false(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "true")
        with patch.dict("sys.modules", {"paddleocr": None, "pytesseract": None}):
            eng = OCREngine().load()
        assert eng._tesseract_available is False

    def test_real_mode_tesseract_available_sets_flag(self, monkeypatch):
        monkeypatch.setenv("USE_REAL_OCR", "true")
        mock_tess = MagicMock()
        # paddleocr unavailable so we skip paddle; tesseract is present
        with patch.dict("sys.modules", {"paddleocr": None, "pytesseract": mock_tess}):
            eng = OCREngine().load()
        assert eng._tesseract_available is True


# ─────────────────────────────────────────────────────────────────────────────
# extract_text_from_pdf — output contract and page routing
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractTextFromPdf:

    def test_raises_file_not_found_for_missing_pdf(self, engine, tmp_path):
        with pytest.raises(FileNotFoundError):
            engine.extract_text_from_pdf(str(tmp_path / "ghost.pdf"))

    def test_output_has_regions_key(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src)
        result = engine.extract_text_from_pdf(str(src))
        assert "regions" in result

    def test_output_has_full_text_key(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src)
        result = engine.extract_text_from_pdf(str(src))
        assert "full_text" in result

    def test_full_text_is_join_of_region_texts(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src)
        result = engine.extract_text_from_pdf(str(src))
        expected = "\n".join(r["text"] for r in result["regions"])
        assert result["full_text"] == expected

    def test_pdf_with_text_returns_non_empty_regions(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src, with_text=True)
        result = engine.extract_text_from_pdf(str(src))
        assert len(result["regions"]) > 0

    def test_empty_pdf_returns_empty_regions(self, engine, tmp_path):
        src = tmp_path / "empty.pdf"
        _make_pdf(src, with_text=False)
        result = engine.extract_text_from_pdf(str(src))
        assert result["regions"] == []

    def test_each_region_has_required_fields(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src, with_text=True)
        result = engine.extract_text_from_pdf(str(src))
        required = {"text", "bbox", "confidence", "page", "font_size", "fontname"}
        for region in result["regions"]:
            assert required.issubset(region.keys()), f"Region missing keys: {region.keys()}"

    def test_region_page_field_matches_page_index(self, engine, tmp_path):
        src = tmp_path / "doc.pdf"
        _make_pdf(src, num_pages=2, with_text=True)
        result = engine.extract_text_from_pdf(str(src))
        pages_seen = {r["page"] for r in result["regions"]}
        # Both pages should have regions
        assert 0 in pages_seen
        assert 1 in pages_seen


# ─────────────────────────────────────────────────────────────────────────────
# _extract_scanned_paddle — mocked PaddleOCR
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractScannedPaddle:

    @pytest.fixture()
    def paddle_engine(self):
        eng = OCREngine()
        eng._paddle = MagicMock()
        return eng

    def test_none_result_returns_empty_list(self, paddle_engine):
        page, _ = _mock_page()
        paddle_engine._paddle.ocr.return_value = None
        assert paddle_engine._extract_scanned_paddle(page, 0) == []

    def test_empty_first_element_returns_empty_list(self, paddle_engine):
        page, _ = _mock_page()
        paddle_engine._paddle.ocr.return_value = [[]]
        assert paddle_engine._extract_scanned_paddle(page, 0) == []

    def test_confidence_below_threshold_filtered(self, paddle_engine):
        page, _ = _mock_page()
        # threshold=0.6, confidence=0.5 → should be filtered
        paddle_engine._paddle.ocr.return_value = _paddle_result("Hello", conf=0.5)
        result = paddle_engine._extract_scanned_paddle(page, 0)
        assert result == []

    def test_confidence_above_threshold_included(self, paddle_engine):
        page, _ = _mock_page()
        paddle_engine._paddle.ocr.return_value = _paddle_result("Hello", conf=0.9)
        result = paddle_engine._extract_scanned_paddle(page, 0)
        assert len(result) == 1

    def test_text_x_only_filtered(self, paddle_engine):
        page, _ = _mock_page()
        paddle_engine._paddle.ocr.return_value = _paddle_result("X", conf=0.99)
        result = paddle_engine._extract_scanned_paddle(page, 0)
        assert result == []

    def test_blank_fill_line_filtered(self, paddle_engine):
        page, _ = _mock_page()
        # Underscores = blank fill line
        paddle_engine._paddle.ocr.return_value = _paddle_result("__________", conf=0.99)
        result = paddle_engine._extract_scanned_paddle(page, 0)
        assert result == []

    def test_valid_result_has_scanned_region_contract(self, paddle_engine):
        page, _ = _mock_page()
        paddle_engine._paddle.ocr.return_value = _paddle_result("Court order", conf=0.95)
        result = paddle_engine._extract_scanned_paddle(page, 0)
        assert len(result) == 1
        r = result[0]
        assert r["text"] == "Court order"
        assert r["confidence"] == pytest.approx(0.95)
        assert r["fontname"] == "helv"
        assert r["preserve"] is False


# ─────────────────────────────────────────────────────────────────────────────
# _extract_scanned_tesseract — ImportError fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractScannedTesseract:

    def test_pytesseract_unavailable_returns_empty_list(self):
        eng = OCREngine()
        page, _ = _mock_page()
        with patch.dict("sys.modules", {"pytesseract": None, "PIL": None}):
            result = eng._extract_scanned_tesseract(page, 0)
        assert result == []

    def test_pil_unavailable_returns_empty_list(self):
        eng = OCREngine()
        page, _ = _mock_page()
        # pytesseract present but PIL not → ImportError on PIL import
        with patch.dict("sys.modules", {"PIL": None}):
            result = eng._extract_scanned_tesseract(page, 0)
        assert result == []
