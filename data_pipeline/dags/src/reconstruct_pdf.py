
"""
=============================================================================
FILE: dags/src/reconstruct_pdf.py
=============================================================================
Rebuilds a PDF with translated text inserted into original bounding boxes,
preserving layout, images, and signatures.

PRODUCTION-READY IMPLEMENTATION — uses PyMuPDF (fitz), which is already
in requirements.txt and works on CPU with no GPU required.

This file does NOT need to be swapped for production — it is the final
implementation. The OCR and translation stubs feed into this function.
When those are upgraded to real models, the region format they produce
must match the output contract of src/ocr_printed.py and src/translate_text.py.
=============================================================================
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def reconstruct_pdf(
    original_path: str,
    translated_regions: list[dict],
    output_path: str,
) -> None:
    """
    Rebuild a PDF with translated text.

    For each region in translated_regions:
      1. Draw a white rectangle over the original text area (redact)
      2. Insert translated text into the same bounding box
      3. Dynamically shrink font if text is too long to fit
      4. Preserve all non-text elements (images, signatures, form lines)

    Args:
        original_path:       Absolute path to the original English PDF.
        translated_regions:  List of region dicts. Each must have:
                               - "translated_text": str
                               - "bbox":            [x0, y0, x1, y1]
                               - "page":            int  (0-indexed)
                               - "font_size":       float (optional)
                               - "is_bold":         bool  (optional)
        output_path:         Where to write the output PDF.
    """
    try:
        import fitz
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF reconstruction. "
            "It is in requirements.txt and should be in the Docker image."
        ) from exc

    if not Path(original_path).exists():
        raise FileNotFoundError(f"Original PDF not found: {original_path}")

    doc = fitz.open(original_path)

    for region in translated_regions:
        translated = region.get("translated_text", "").strip()
        bbox       = region.get("bbox")
        page_num   = region.get("page", 0)

        # Skip empty regions or missing bbox
        if not translated or not bbox:
            continue
        if page_num >= len(doc):
            logger.warning(
                "Region references page %d but doc has %d page(s). Skipping.",
                page_num, len(doc),
            )
            continue

        page = doc[page_num]
        x0, y0, x1, y1 = bbox
        rect = fitz.Rect(x0, y0, x1, y1)

        # Step 1: Redact (white box over original text)
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))

        # Step 2: Choose font (bold if original was bold)
        fontname = "times-bold" if region.get("is_bold") else "times-roman"

        # Step 3: Insert translated text with dynamic font shrinking
        font_size = max(region.get("font_size", 10.0), 6.0)
        inserted  = False
        while font_size >= 5.0:
            rc = page.insert_textbox(
                rect, translated,
                fontname=fontname, fontsize=font_size,
                color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT,
            )
            if rc >= 0:    # rc >= 0 means text fitted
                inserted = True
                break
            font_size -= 0.5

        if not inserted:
            # Last resort: insert truncated text at minimum size
            truncated = translated[:60] + "…"
            page.insert_textbox(
                rect, truncated,
                fontname=fontname, fontsize=5.0,
                color=(0, 0, 0), align=fitz.TEXT_ALIGN_LEFT,
            )
            logger.warning(
                "Text too long for bbox %s on page %d — truncated to 60 chars.",
                bbox, page_num,
            )

    # Save with garbage collection and compression
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    logger.info("PDF reconstructed and saved to '%s'.", output_path)