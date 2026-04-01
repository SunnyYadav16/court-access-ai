"""
courtaccess/core/ocr_printed.py

OCREngine — extracts text regions from PDF pages.

Two modes controlled by USE_REAL_OCR env var:
  false (default) — PyMuPDF native text extraction (CPU, no extra install)
  true            — PaddleOCR for scanned pages, PyMuPDF for digital pages
                    Falls back to Tesseract if PaddleOCR unavailable.
                    Falls back to PyMuPDF if neither OCR engine is available.

Page routing (real mode):
  DIGITAL → _extract_digital  (Cell 9 _get_block_units logic)
  SCANNED → _extract_scanned_paddle → _extract_scanned_tesseract → PyMuPDF
  BLANK   → skipped

Extended region contract (all fields):
  {
      # Base fields
      "text":        str,
      "bbox":        [x0, y0, x1, y1],   # orig_rect — PDF points
      "confidence":  float,               # 0.0-1.0
      "page":        int,                 # 0-indexed
      "font_size":   float,
      "is_bold":     bool,
      # Layout fields (from _get_block_units for digital; defaults for scanned)
      "avail_bbox":  [x0, y0, x1, y1],   # available rect for insert_htmlbox
      "fontname":    str,                 # "helv", "hebo" etc
      "color_rgb":   [r, g, b],           # 0.0-1.0 each, JSON-serializable
      "is_centered": bool,
      "is_right":    bool,
      "unit_type":   str,                 # "PROSE"|"FORM_LABEL"|"HEADER"
      "is_caps":     bool,                # original was all-caps
      "preserve":    bool,                # skip translation, insert original
  }

Source: Cell 9 of the original Colab script.
  _extract_digital uses _get_block_units from pdf_utils.py (Cell 9 logic)
  _extract_scanned_paddle ← Cell 9 reconstruct_scanned_page_paddle()
  _extract_scanned_tesseract ← Cell 9 reconstruct_scanned_page_tesseract()
"""

import contextlib
import logging
import os
import tempfile
from pathlib import Path

import pymupdf

from courtaccess.core.ingest_document import classify_page, is_content_image
from courtaccess.core.pdf_utils import (
    _get_block_units,
    _is_blank_fill_line,
    get_font_code,
    get_font_size,
    safe_color,
)

logger = logging.getLogger(__name__)


class OCREngine:
    """
    Extracts text regions from PDF pages, routing each page through
    the appropriate extraction method based on page classification.

    Usage:
        engine  = OCREngine().load()
        result  = engine.extract_text_from_pdf("/path/to/doc.pdf")
        regions = result["regions"]

    Models are loaded once in load() and reused for all calls.
    """

    # Source: Cell 9 — 300 DPI render for PaddleOCR
    RENDER_DPI: int = 300

    # ── Initialisation ────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self.OCR_CONFIDENCE_THRESHOLD = float(os.getenv("OCR_CONFIDENCE_THRESHOLD"))
        self._use_real = str(os.getenv("USE_REAL_OCR")).lower() == "true"
        self._paddle = None
        self._tesseract_available = False

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self) -> "OCREngine":
        """
        Load OCR engines. Falls back gracefully — never crashes pipeline.
        Returns self for chaining: OCREngine().load()
        """
        if self._use_real:
            try:
                from paddleocr import PaddleOCR

                self._paddle = PaddleOCR(use_textline_orientation=True, lang="en")
                logger.info("PaddleOCR loaded successfully")
            except Exception as exc:
                logger.warning(
                    "PaddleOCR unavailable (%s) — scanned pages will use PyMuPDF fallback",
                    exc,
                )
                self._paddle = None

            try:
                import pytesseract  # noqa: F401

                self._tesseract_available = True
                logger.info("Tesseract available as secondary fallback")
            except ImportError:
                self._tesseract_available = False

        return self

    def extract_text_from_pdf(self, pdf_path: str) -> dict:
        """
        Extract text regions from all pages of a PDF.

        Routes each page through the appropriate extractor:
          DIGITAL → _extract_digital (Cell 9 _get_block_units logic)
          SCANNED → PaddleOCR → Tesseract → PyMuPDF (fallback chain)
          BLANK   → skipped

        Returns dict with 'regions' (list) and 'full_text' (str).
        Raises FileNotFoundError if pdf_path does not exist.
        """
        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = pymupdf.open(pdf_path)
        all_regions = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            info = classify_page(page)

            if info["page_type"] == "BLANK":
                logger.debug("Page %d: BLANK — skipping", page_num)
                continue

            if is_content_image(info):
                logger.debug("Page %d: IMAGE-ONLY — skipping", page_num)
                continue

            if info["page_type"] == "DIGITAL" or not self._use_real:
                regions = self._extract_digital(page, page_num)
                logger.debug(
                    "Page %d: DIGITAL — %d units via PyMuPDF",
                    page_num,
                    len(regions),
                )
            elif self._paddle is not None:
                regions = self._extract_scanned_paddle(page, page_num)
                logger.debug(
                    "Page %d: SCANNED — %d regions via PaddleOCR",
                    page_num,
                    len(regions),
                )
            elif self._tesseract_available:
                regions = self._extract_scanned_tesseract(page, page_num)
                logger.debug(
                    "Page %d: SCANNED — %d regions via Tesseract",
                    page_num,
                    len(regions),
                )
            else:
                logger.warning(
                    "Page %d: SCANNED but no OCR engine — falling back to PyMuPDF",
                    page_num,
                )
                regions = self._extract_digital(page, page_num)

            all_regions.extend(regions)

        doc.close()

        full_text = "\n".join(r["text"] for r in all_regions)
        logger.info(
            "Extracted %d region(s) from '%s'",
            len(all_regions),
            pdf_path,
        )
        return {"regions": all_regions, "full_text": full_text}

    # ── Private extractors ────────────────────────────────────────────────────

    def _extract_digital(self, page, page_num: int) -> list:
        """
        Extract text units from a digital PDF page using Cell 9
        _get_block_units() logic. Returns extended region contract
        with full layout metadata for faithful reconstruction.

        Source: Cell 9 Phase 1 (inventory) + _get_block_units()
        """
        td = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        regions = []

        for block in td.get("blocks", []):
            if block.get("type") != 0:
                continue

            for unit in _get_block_units(block):
                if unit["unit_type"] == "SKIP":
                    # Cell 9 keeps SKIP units (pure numbers, punctuation) —
                    # they get redacted in Phase 4 and reinserted unchanged.
                    unit["preserve"] = True

                text = unit["text"]
                if not text or not text.strip():
                    continue

                orig_rect = unit["orig_rect"]
                avail_rect = unit["avail_rect"]
                fs = unit["first_span"]

                fontname = get_font_code(fs)
                font_size = get_font_size(fs)
                color = safe_color(fs)

                regions.append(
                    {
                        # Base fields
                        "text": text,
                        "bbox": [orig_rect.x0, orig_rect.y0, orig_rect.x1, orig_rect.y1],
                        "confidence": 0.99,
                        "page": page_num,
                        "font_size": font_size,
                        "is_bold": bool(fs.get("flags", 0) & 16),
                        # Layout fields
                        "avail_bbox": [avail_rect.x0, avail_rect.y0, avail_rect.x1, avail_rect.y1],
                        "fontname": fontname,
                        "color_rgb": list(color),
                        "is_centered": unit["is_centered"],
                        "is_right": unit.get("is_right", False),
                        "unit_type": unit["unit_type"],
                        "is_caps": unit.get("is_caps", False),
                        "preserve": unit["preserve"],
                    }
                )

        return regions

    def _extract_scanned_paddle(self, page, page_num: int) -> list:
        """
        Extract text from a scanned page using PaddleOCR.
        Scanned regions use default layout metadata (helv, black, left-aligned).

        Source: Cell 9 reconstruct_scanned_page_paddle() — extraction only.
        """
        mat = pymupdf.Matrix(self.RENDER_DPI / 72, self.RENDER_DPI / 72)
        pix = page.get_pixmap(matrix=mat)

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(tmp_fd)

        try:
            pix.save(tmp_path)
            result = self._paddle.ocr(tmp_path, cls=True)
        except Exception as exc:
            logger.warning("PaddleOCR failed on page %d: %s", page_num, exc)
            return []
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

        if not result or not result[0]:
            return []

        sx = page.rect.width / pix.width
        sy = page.rect.height / pix.height

        regions = []
        for line in result[0]:
            box, (text, conf) = line[0], line[1]

            if conf < self.OCR_CONFIDENCE_THRESHOLD:
                continue
            if not text.strip() or text.strip() == "X":
                continue
            if _is_blank_fill_line(text):
                continue

            xs = [p[0] * sx for p in box]
            ys = [p[1] * sy for p in box]
            x0, y0 = min(xs), min(ys)
            x1, y1 = max(xs), max(ys)

            regions.append(
                self._scanned_region(
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    float(conf),
                    page_num,
                    font_size=round((y1 - y0) * 0.72, 1),
                )
            )

        return regions

    def _extract_scanned_tesseract(self, page, page_num: int) -> list:
        """
        Extract text from a scanned page using Tesseract (fallback).
        Source: Cell 9 reconstruct_scanned_page_tesseract() — extraction only.
        """
        try:
            import pytesseract
            from PIL import Image as PILImage
        except ImportError:
            logger.warning("Tesseract (pytesseract/Pillow) not available")
            return []

        mat = pymupdf.Matrix(self.RENDER_DPI / 72, self.RENDER_DPI / 72)
        pix = page.get_pixmap(matrix=mat)
        img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)

        sx = page.rect.width / pix.width
        sy = page.rect.height / pix.height

        data = pytesseract.image_to_data(
            img,
            lang="eng",
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

        line_map: dict = {}
        for i, word in enumerate(data["text"]):
            if not word.strip() or int(data["conf"][i]) < 30:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            line_map.setdefault(key, []).append(i)

        regions = []
        for key in sorted(
            line_map,
            key=lambda k: (
                min(data["top"][i] for i in line_map[k]),
                min(data["left"][i] for i in line_map[k]),
            ),
        ):
            idx = line_map[key]
            text = " ".join(data["text"][i] for i in idx).strip()
            if not text or text == "X":
                continue
            if _is_blank_fill_line(text):
                continue

            x0 = min(data["left"][i] for i in idx) * sx
            y0 = min(data["top"][i] for i in idx) * sy
            x1 = max(data["left"][i] + data["width"][i] for i in idx) * sx
            y1 = max(data["top"][i] + data["height"][i] for i in idx) * sy

            avg_conf = sum(int(data["conf"][i]) for i in idx) / len(idx) / 100.0

            regions.append(
                self._scanned_region(
                    text,
                    x0,
                    y0,
                    x1,
                    y1,
                    min(max(avg_conf, 0.0), 1.0),
                    page_num,
                    font_size=round((y1 - y0) * 0.65, 1),
                )
            )

        return regions

    @staticmethod
    def _scanned_region(
        text: str,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        confidence: float,
        page_num: int,
        font_size: float = 10.0,
    ) -> dict:
        """
        Build a region dict with scanned-page defaults for layout fields.
        avail_bbox equals bbox for scanned pages (no avail_rect inference).
        """
        return {
            "text": text,
            "bbox": [x0, y0, x1, y1],
            "avail_bbox": [x0, y0, x1, y1],
            "confidence": confidence,
            "page": page_num,
            "font_size": font_size,
            "is_bold": False,
            "fontname": "helv",
            "color_rgb": [0.0, 0.0, 0.0],
            "is_centered": False,
            "is_right": False,
            "unit_type": "PROSE",
            "is_caps": False,
            "preserve": False,
        }
