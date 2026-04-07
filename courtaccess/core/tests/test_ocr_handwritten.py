"""
Unit tests for courtaccess/core/ocr_handwritten.py

Functions under test:
  extract_handwritten  — routes to stub or real based on _USE_REAL flag
  _stub_extract        — always returns []
  _real_extract        — catches all exceptions, returns [] on failure

Design notes:
  - _USE_REAL is a module-level constant evaluated at import time.
    .env has USE_REAL_HANDWRITING_OCR=true, so _USE_REAL=True in the test
    process. We patch it directly via patch.object for stub-path tests.
  - _real_extract wraps everything in try/except and returns [] on any
    failure. Tests exercise this by patching the lazy torch/transformers
    imports to raise, confirming graceful degradation.
  - Output contract shape is verified on a mocked real-extract result.
"""

from unittest.mock import MagicMock, patch

import courtaccess.core.ocr_handwritten as ocr_hw_mod
from courtaccess.core.ocr_handwritten import _stub_extract, extract_handwritten

# ── Region factory ────────────────────────────────────────────────────────────

def _region(bbox=(10, 20, 100, 40), confidence=0.3, page=0):
    return {"bbox": list(bbox), "confidence": confidence, "page": page}


# ─────────────────────────────────────────────────────────────────────────────
# extract_handwritten — empty input guard
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractHandwrittenEmptyInput:

    def test_empty_regions_returns_empty_list(self):
        result = extract_handwritten("any/path.png", [], page_num=0)
        assert result == []

    def test_empty_regions_does_not_call_stub_or_real(self):
        with (
            patch.object(ocr_hw_mod, "_USE_REAL", False),
            patch("courtaccess.core.ocr_handwritten._stub_extract") as mock_stub,
            patch("courtaccess.core.ocr_handwritten._real_extract") as mock_real,
        ):
            extract_handwritten("path.png", [], page_num=0)
        mock_stub.assert_not_called()
        mock_real.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# extract_handwritten — stub mode routing
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractHandwrittenStubMode:

    def test_stub_mode_returns_empty_list(self):
        with patch.object(ocr_hw_mod, "_USE_REAL", False):
            result = extract_handwritten("path.png", [_region()], page_num=0)
        assert result == []

    def test_stub_mode_returns_empty_list_for_multiple_regions(self):
        regions = [_region(), _region(bbox=(50, 60, 200, 80))]
        with patch.object(ocr_hw_mod, "_USE_REAL", False):
            result = extract_handwritten("path.png", regions, page_num=2)
        assert result == []

    def test_stub_mode_calls_stub_extract_not_real_extract(self):
        with (
            patch.object(ocr_hw_mod, "_USE_REAL", False),
            patch("courtaccess.core.ocr_handwritten._stub_extract", return_value=[]) as mock_stub,
            patch("courtaccess.core.ocr_handwritten._real_extract") as mock_real,
        ):
            extract_handwritten("path.png", [_region()], page_num=0)
        mock_stub.assert_called_once()
        mock_real.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# extract_handwritten — real mode routing
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractHandwrittenRealMode:

    def test_real_mode_calls_real_extract(self):
        fake_result = [{"text": "John", "bbox": [0, 0, 100, 20], "confidence": 0.85, "page": 0, "source": "qwen2.5-vl"}]
        with (
            patch.object(ocr_hw_mod, "_USE_REAL", True),
            patch("courtaccess.core.ocr_handwritten._real_extract", return_value=fake_result) as mock_real,
        ):
            result = extract_handwritten("path.png", [_region()], page_num=0)
        mock_real.assert_called_once()
        assert result == fake_result

    def test_real_mode_does_not_call_stub_extract(self):
        with (
            patch.object(ocr_hw_mod, "_USE_REAL", True),
            patch("courtaccess.core.ocr_handwritten._real_extract", return_value=[]),
            patch("courtaccess.core.ocr_handwritten._stub_extract") as mock_stub,
        ):
            extract_handwritten("path.png", [_region()], page_num=0)
        mock_stub.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# _stub_extract — always returns []
# ─────────────────────────────────────────────────────────────────────────────

class TestStubExtract:

    def test_returns_empty_list_for_single_region(self):
        assert _stub_extract([_region()], page_num=0) == []

    def test_returns_empty_list_for_multiple_regions(self):
        assert _stub_extract([_region(), _region()], page_num=1) == []

    def test_returns_empty_list_for_empty_input(self):
        assert _stub_extract([], page_num=0) == []

    def test_page_num_does_not_affect_output(self):
        assert _stub_extract([_region()], page_num=99) == []


# ─────────────────────────────────────────────────────────────────────────────
# _real_extract — exception handling (no GPU/model in CI)
# ─────────────────────────────────────────────────────────────────────────────

class TestRealExtractExceptionHandling:

    def test_returns_empty_list_when_torch_import_fails(self):
        # Simulate environment without torch installed
        from courtaccess.core.ocr_handwritten import _real_extract
        with patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")):
            result = _real_extract("path.png", [_region()], page_num=0)
        assert result == []

    def test_returns_empty_list_when_model_path_missing(self):
        # QWEN_VL_MODEL_PATH not set → from_pretrained(None) raises
        from courtaccess.core.ocr_handwritten import _real_extract
        with (
            patch.dict("os.environ", {"QWEN_VL_MODEL_PATH": ""}),
            patch("torch.no_grad", MagicMock()),
        ):
            # from_pretrained("") will raise — exception caught → []
            result = _real_extract("path.png", [_region()], page_num=0)
        assert result == []
