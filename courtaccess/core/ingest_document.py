"""
courtaccess/core/ingest_document.py

PDF ingestion and page classification.

Two responsibilities:
  1. ingest_pdf()     — splits PDF into per-page PNG images (existing stub)
  2. classify_page()  — determines page type: DIGITAL | SCANNED | BLANK
  3. is_content_image() — identifies pure image pages (no text to translate)

Page classification drives the pipeline routing in document_pipeline.py:
  DIGITAL  → reconstruct_pdf.py (vector text extraction + layout rebuild)
  SCANNED  → ocr_printed.py + ocr_handwritten.py (OCR pipeline)
  BLANK    → skip entirely

Source: Cell 5 classify_page() and is_content_image() from Colab script,
        cleaned up for module use. No logic changes.

OUTPUT CONTRACT (ingest_pdf):
  {
      "pages": [
          {
              "page_num":    int,     # 0-indexed
              "image_path":  str,     # absolute path to saved PNG
              "width_px":    int,
              "height_px":   int,
              "page_type":   str,     # "DIGITAL" | "SCANNED" | "BLANK"
              "is_scanned":  bool,
              "span_count":  int,     # number of text spans detected
              "img_coverage": float,  # 0.0-100.0 — % of page covered by images
          }
      ],
      "page_count": int,
      "pdf_path":   str,
  }

OUTPUT CONTRACT (classify_page):
  {
      "page_type":   "DIGITAL" | "SCANNED" | "BLANK",
      "is_scanned":  bool,
      "span_count":  int,
      "images":      int,
      "drawings":    int,
      "img_coverage": float,   # 0.0-100.0
  }
"""

import os
from pathlib import Path

import pymupdf

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# DPI for page rendering — 300 for high-quality scans
RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "300"))


# ── Page classification ───────────────────────────────────────────────────────


def classify_page(page) -> dict:
    """
    Classify a PyMuPDF page as DIGITAL, SCANNED, or BLANK.

    Classification logic:
      BLANK   — no text spans and no images
      SCANNED — image coverage > 40% OR has images but no text
                (scanner embedded OCR text on top of a background image)
      DIGITAL — real vector text, span_count > 5, low image coverage
      fallback → SCANNED (very few spans, ambiguous)

    Args:
        page: PyMuPDF page object (fitz.Page)

    Returns:
        Dict matching OUTPUT CONTRACT above.

    Source: Cell 5 classify_page() — no logic changes.
    """
    td = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)

    # Count non-empty text spans
    span_count = 0
    for b in td["blocks"]:
        if b["type"] == 0:
            for line in b["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        span_count += 1

    images = page.get_images(full=True)
    drawings = page.get_drawings()
    page_area = page.rect.width * page.rect.height

    # ── Compute image coverage ────────────────────────────────
    total_img_area = 0.0

    for img in images:
        try:
            for r in page.get_image_rects(img[0]):
                total_img_area += r.width * r.height
        except Exception:
            logger.debug("get_image_rects failed for image — skipping", exc_info=True)

    # Fallback 1: use image block bboxes if get_image_rects fails
    if total_img_area == 0:
        for b in td["blocks"]:
            if b["type"] == 1:
                bb = b["bbox"]
                total_img_area += (bb[2] - bb[0]) * (bb[3] - bb[1])

    # Fallback 2: if images exist but we still can't measure, assume large
    if total_img_area == 0 and images:
        for img in images:
            if img[2] > 500 and img[3] > 500:  # width/height in pixels
                total_img_area = page_area * 0.85
                break

    img_coverage = (total_img_area / page_area * 100) if page_area > 0 else 0.0

    # ── Classification ────────────────────────────────────────

    # BLANK: no text, no images
    if span_count == 0 and not images:
        return {
            "page_type": "BLANK",
            "is_scanned": False,
            "span_count": span_count,
            "images": len(images),
            "drawings": len(drawings),
            "img_coverage": round(img_coverage, 1),
        }

    # SCANNED: large background image (with or without embedded OCR text)
    if img_coverage > 40.0 or (images and span_count == 0):
        return {
            "page_type": "SCANNED",
            "is_scanned": True,
            "span_count": span_count,
            "images": len(images),
            "drawings": len(drawings),
            "img_coverage": round(img_coverage, 1),
        }

    # DIGITAL: real vector text, sufficient span count
    if span_count > 5:
        return {
            "page_type": "DIGITAL",
            "is_scanned": False,
            "span_count": span_count,
            "images": len(images),
            "drawings": len(drawings),
            "img_coverage": round(img_coverage, 1),
        }

    # Fallback: very few spans — treat as scanned
    return {
        "page_type": "SCANNED",
        "is_scanned": True,
        "span_count": span_count,
        "images": len(images),
        "drawings": len(drawings),
        "img_coverage": round(img_coverage, 1),
    }


def is_content_image(info: dict) -> bool:
    """
    Returns True only if a SCANNED page has absolutely no extractable
    content — no spans, no drawings, no images, and coverage > 95%.
    Almost no real page meets this bar — prefer attempting OCR over
    silently skipping.

    DIGITAL pages always return False: they have selectable text by
    definition and must never be skipped regardless of image coverage.

    Source: Cell 5 is_content_image() — updated logic.
    """
    if not info.get("is_scanned", True):
        return False
    return info["img_coverage"] > 95.0 and info["span_count"] == 0 and info["drawings"] == 0 and info["images"] == 0


# ── PDF ingestion ─────────────────────────────────────────────────────────────


def ingest_pdf(pdf_path: str, output_dir: str | None = None) -> dict:
    """
    Split a PDF into per-page PNG images and classify each page.

    Args:
        pdf_path:   Absolute path to the PDF.
        output_dir: Directory to save page images.
                    Defaults to <pdf_dir>/pages/

    Returns:
        Dict matching OUTPUT CONTRACT above.

    Raises:
        FileNotFoundError: if pdf_path does not exist.
        ValueError:        if the file is not a valid PDF.
    """
    pdf_path = str(Path(pdf_path).resolve())
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if output_dir is None:
        output_dir = str(Path(pdf_path).parent / "pages")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {pdf_path}") from exc

    if doc.page_count == 0:
        doc.close()
        raise ValueError(f"PDF has no pages: {pdf_path}")

    matrix = pymupdf.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        # Classify before rendering — uses vector data, no image needed
        info = classify_page(page)

        # Render to PNG
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        image_filename = f"page_{page_num:04d}.png"
        image_path = str(Path(output_dir) / image_filename)
        pix.save(image_path)

        pages.append(
            {
                "page_num": page_num,
                "image_path": image_path,
                "width_px": pix.width,
                "height_px": pix.height,
                "page_type": info["page_type"],
                "is_scanned": info["is_scanned"],
                "span_count": info["span_count"],
                "img_coverage": info["img_coverage"],
            }
        )

        logger.debug(
            "Page %d: %s (spans=%d, img_coverage=%.1f%%) → %s",
            page_num,
            info["page_type"],
            info["span_count"],
            info["img_coverage"],
            image_path,
        )

    doc.close()

    digital = sum(1 for p in pages if p["page_type"] == "DIGITAL")
    scanned = sum(1 for p in pages if p["page_type"] == "SCANNED")
    blank = sum(1 for p in pages if p["page_type"] == "BLANK")

    logger.info(
        "Ingested '%s': %d pages (digital=%d scanned=%d blank=%d) at %d DPI",
        pdf_path,
        len(pages),
        digital,
        scanned,
        blank,
        RENDER_DPI,
    )

    return {
        "pages": pages,
        "page_count": len(pages),
        "pdf_path": pdf_path,
    }
