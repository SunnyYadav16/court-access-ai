"""
=============================================================================
FILE: dags/src/ocr_printed.py
=============================================================================
Extracts text regions from a PDF.

STUB IMPLEMENTATION — uses PyMuPDF native text extraction (CPU, no install needed).
PyMuPDF is already in requirements.txt.

PRODUCTION UPGRADE:
  Replace _real_ocr() body with PaddleOCR v3 + Qwen2.5-VL for scanned docs.
  The output dict contract must be preserved exactly so downstream tasks
  (translate_text, reconstruct_pdf) work without changes.

OUTPUT CONTRACT:
  {
      "regions": [
          {
              "text":       str,
              "bbox":       [x0, y0, x1, y1],   # PDF points
              "confidence": float,               # 0.0-1.0
              "page":       int,
              "font_size":  float,
              "is_bold":    bool,
          }
      ],
      "full_text": str   # all texts joined by newline
  }
=============================================================================
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str) -> dict:
    """
    Extract text regions from a PDF file.
    NOTE: STUB — uses PyMuPDF native extraction.
    Replace body with PaddleOCR in production.
    """
    return _pymupdf_extract(pdf_path)


def _pymupdf_extract(pdf_path: str) -> dict:
    """
    CPU-friendly extraction using PyMuPDF's built-in text layer.
    Works well for digital PDFs (which all mass.gov forms are).
    For genuinely scanned/handwritten content, PaddleOCR will do better.
    NOTE: STUB — will be replaced with PaddleOCR v3 in production.
    """
    try:
        import fitz  # PyMuPDF — already in requirements.txt
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF (fitz) is required. "
            "It is listed in requirements.txt and should be in the Docker image."
        ) from exc

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc     = fitz.open(pdf_path)
    regions = []

    for page_num, page in enumerate(doc):
        # get_text("dict") returns blocks → lines → spans with bbox + font info
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:   # skip image blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    regions.append({
                        "text":       text,
                        "bbox":       [x0, y0, x1, y1],
                        "confidence": 0.99,   # native PDF text = high confidence
                        "page":       page_num,
                        "font_size":  round(span.get("size", 11.0), 1),
                        "is_bold":    bool(span.get("flags", 0) & 16),
                    })

    doc.close()

    if not regions:
        logger.warning(
            "[STUB OCR] No text extracted from '%s'. "
            "File may be a scanned image or mislabeled non-PDF. "
            "Production PaddleOCR will handle this case.",
            pdf_path,
        )

    full_text = "\n".join(r["text"] for r in regions)
    logger.info(
        "[STUB OCR] Extracted %d region(s) from '%s' using PyMuPDF native.",
        len(regions), pdf_path,
    )
    return {"regions": regions, "full_text": full_text}


