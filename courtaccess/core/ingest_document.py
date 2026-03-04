"""
courtaccess/core/ingest_document.py

PDF ingestion: splits an uploaded PDF into per-page images for the OCR pipeline.
Uses PyMuPDF (fitz) — CPU-only, already in requirements.txt.

OUTPUT CONTRACT:
  {
      "pages": [
          {
              "page_num":   int,        # 0-indexed
              "image_path": str,        # absolute path to saved PNG
              "width_px":  int,
              "height_px": int,
          }
      ],
      "page_count": int,
      "pdf_path":   str,
  }
"""

import os
from pathlib import Path

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# DPI for page rendering — 150 is sufficient for OCR; 300 for high-quality scans
RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "150"))


def ingest_pdf(pdf_path: str, output_dir: str | None = None) -> dict:
    """
    Split a PDF into per-page PNG images.

    Args:
        pdf_path:   Absolute path to the PDF.
        output_dir: Directory to save page images. Defaults to same dir as PDF.

    Returns:
        Dict matching OUTPUT CONTRACT above.

    Raises:
        FileNotFoundError: if pdf_path does not exist.
        ImportError:       if PyMuPDF is not installed.
    """
    try:
        import fitz
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) is required for PDF ingestion.") from exc

    pdf_path = str(Path(pdf_path).resolve())
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if output_dir is None:
        output_dir = str(Path(pdf_path).parent / "pages")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    pages = []
    matrix = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)  # 72dpi is PDF default

    for page_num in range(len(doc)):
        page = doc[page_num]
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
            }
        )
        logger.debug(
            "Rendered page %d → %s (%dx%d px)",
            page_num,
            image_path,
            pix.width,
            pix.height,
        )

    doc.close()
    logger.info(
        "Ingested '%s': %d page(s) rendered at %d DPI to '%s'.",
        pdf_path,
        len(pages),
        RENDER_DPI,
        output_dir,
    )
    return {
        "pages": pages,
        "page_count": len(pages),
        "pdf_path": pdf_path,
    }
