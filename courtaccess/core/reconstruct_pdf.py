"""
courtaccess/core/reconstruct_pdf.py

Rebuilds a PDF with translated text overlaid, preserving original layout.

Pipeline per page (Cell 9 phases):
  Phase 4 — Redact original text:
              DIGITAL pages: span-level redact with fill=None (transparent)
              SCANNED pages: region-level redact with fill=(1,1,1) (white)
  Phase 5 — Insert translated text via insert_htmlbox:
              preserve=True  → insert original text unchanged (blank lines,
                               URLs, checkboxes — redacted then reinserted)
              preserve=False → apply post-processing then insert

Post-processing (Phase 3, Cell 9):
  _citation_fallback  — append missing citations if NLLB dropped them
  _restore_caps       — uppercase all-caps text if original was all-caps

Rendering:
  insert_htmlbox with CSS styling — handles wrapping, alignment, font
  avail_rect from region["avail_bbox"] — set by OCREngine for digital pages
  cell_rects from page drawings — computed here for available-width calc

Source: Cell 9 of the original Colab script.
        reconstruct_digital_page() and reconstruct_scanned_page_paddle()
        refactored into a single reconstruct_pdf() function that consumes
        pre-translated regions from OCREngine + Translator.
"""

import contextlib
import logging
import re
from collections import defaultdict
from pathlib import Path

import pymupdf

from courtaccess.core.ingest_document import classify_page
from courtaccess.core.pdf_utils import (
    CSS_FONTS,
    _get_available_width,
    _get_cell_rects,
    color_to_hex,
    fit_fontsize,
)

logger = logging.getLogger(__name__)


# ── Citation regex for post-processing ───────────────────────────────────────
# Source: Cell 9 _citation_fallback regex
_CITE_RE = re.compile(
    r"G\.L\.\s+c\.\s+[\d]+[A-Za-z]?(?:[,\s]+§\s*\d+[A-Za-z]*)?"
    r"|§\s*\d+[A-Za-z]*",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
# Post-processing helpers — Cell 9 Phase 3
# ══════════════════════════════════════════════════════════════════════════════


def _citation_fallback(orig: str, trans: str) -> str:
    """
    Append any citations present in orig but missing from trans.
    Handles RFCT0RF restoration failures caught by Llama but missed by NLLB.
    Source: Cell 9 _citation_fallback()
    """
    missing = [m.group(0) for m in _CITE_RE.finditer(orig) if m.group(0) not in trans]
    if missing:
        trans = trans.rstrip() + " (" + ", ".join(missing) + ")"
    return trans


def _restore_caps(orig: str, trans: str) -> str:
    """
    If original text was all-caps, uppercase the translation.
    Preserves FORM LABELS like 'COMMONWEALTH OF MASSACHUSETTS'.
    Source: Cell 9 _restore_caps()
    """
    lets = [c for c in orig if c.isalpha()]
    if lets and all(c.isupper() for c in lets):
        return trans.upper()
    return trans


# ══════════════════════════════════════════════════════════════════════════════
# HTML insertion — Cell 9 _insert_unit_html
# ══════════════════════════════════════════════════════════════════════════════


def _insert_unit_html(
    page,
    text: str,
    avail_rect,
    orig_size: float,
    fontname: str,
    color: tuple,
    is_centered: bool,
    is_right: bool = False,
    cell_rects: list | None = None,
    page_width: float = 594.0,
) -> None:
    """
    Insert text into avail_rect using insert_htmlbox.
    Handles wrapping, alignment, and font scaling automatically.
    Falls back to insert_text if insert_htmlbox fails.
    Source: Cell 9 _insert_unit_html()
    """
    if not text.strip():
        return
    if avail_rect.width <= 2 or avail_rect.height <= 2:
        return

    # Available width from cell boundaries or margin
    if cell_rects:
        avail_width = _get_available_width(avail_rect, cell_rects, page_width)
    else:
        avail_width = page_width - 36 - avail_rect.x0

    # Single-line units: shrink to fit; prose: wrap naturally
    single_line = avail_rect.height < orig_size * 2.5

    if single_line:
        fitted_size = fit_fontsize(text, orig_size, avail_width, fontname)
        white_space = "nowrap"
    else:
        fitted_size = orig_size
        white_space = "normal"

    css_family, is_bold, is_italic = CSS_FONTS.get(fontname, ("Helvetica, Arial, sans-serif", False, False))
    align = "center" if is_centered else ("right" if is_right else "left")
    weight = "bold" if is_bold else "normal"
    style = "italic" if is_italic else "normal"
    col = color_to_hex(color)

    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = (
        f'<p style="'
        f"font-family:{css_family};"
        f"font-size:{fitted_size:.1f}pt;"
        f"font-weight:{weight};"
        f"font-style:{style};"
        f"color:{col};"
        f"text-align:{align};"
        f"white-space:{white_space};"
        f"margin:0;padding:0;line-height:1.15;"
        f'">{safe}</p>'
    )

    try:
        page.insert_htmlbox(avail_rect, html)
    except Exception as exc:
        logger.debug("insert_htmlbox failed (%s) — falling back to insert_text", exc)
        with contextlib.suppress(Exception):
            page.insert_text(
                pymupdf.Point(avail_rect.x0, avail_rect.y0 + fitted_size),
                text,
                fontsize=fitted_size,
                fontname=fontname,
                color=color,
            )


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════


def reconstruct_pdf(
    original_path: str,
    translated_regions: list,
    output_path: str,
) -> None:
    """
    Rebuild a PDF with translated text inserted into original bounding boxes.

    Consumes pre-translated regions from OCREngine + Translator pipeline.
    Implements Cell 9 reconstruction phases:
      Phase 4: redact original text
      Phase 5: insert translated text via insert_htmlbox

    For preserve=True regions (blank lines, URLs, checkboxes):
      - Original text is reinserted unchanged after redaction.
      - This matches Cell 9 behavior exactly.

    Args:
        original_path:      Absolute path to the original English PDF.
        translated_regions: List of region dicts from OCREngine, each
                            enriched with "translated_text" by the pipeline.
                            Must include bbox, page, and layout fields.
        output_path:        Where to write the reconstructed PDF.

    Raises:
        FileNotFoundError: if original_path does not exist.
        ValueError:        if the file is not a valid PDF.
    """
    if not Path(original_path).exists():
        raise FileNotFoundError(f"Original PDF not found: {original_path}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(original_path)

    if not doc.is_pdf:
        doc.close()
        raise ValueError(
            f"File is not a valid PDF: '{original_path}'. "
            "The scraper may have downloaded an HTML error page. "
            "Check preprocessing flags — mark as 'mislabeled'."
        )

    # Group regions by page number
    regions_by_page: dict = defaultdict(list)
    for region in translated_regions:
        regions_by_page[region.get("page", 0)].append(region)

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_regions = regions_by_page.get(page_num, [])

        if not page_regions:
            continue

        # ── Cell rects for avail_width calculation ────────────────────────
        cell_rects = _get_cell_rects(page)
        page_width = page.rect.width

        # ── Phase 4: Redact original text ─────────────────────────────────
        # Detect whether page has vector text (DIGITAL) or not (SCANNED).
        # DIGITAL: redact at span level with fill=None (transparent bg kept).
        # SCANNED: redact at region bbox level with fill=(1,1,1) (white box).
        # Source: Cell 9 Phase 4 — span-level redaction, y1 - 1pt.
        info = classify_page(page)

        if info["page_type"] == "DIGITAL":
            # Redact every non-empty span in the page
            td = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
            for blk in td["blocks"]:
                if blk["type"] != 0:
                    continue
                for ln in blk["lines"]:
                    for span in ln["spans"]:
                        if span["text"].strip():
                            sb = span["bbox"]
                            page.add_redact_annot(
                                pymupdf.Rect(sb[0], sb[1], sb[2], sb[3] - 1),
                                fill=None,
                            )
        else:
            # Scanned: redact at region bbox level with white fill
            for region in page_regions:
                bbox = region.get("bbox")
                if bbox:
                    x0, y0, x1, y1 = bbox
                    page.add_redact_annot(
                        pymupdf.Rect(x0, y0, x1, y1 - 1),
                        fill=(1, 1, 1),
                    )

        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

        # ── Phase 5: Insert translated text ───────────────────────────────
        count = 0
        for region in page_regions:
            orig_text = region.get("text", "")

            # Determine text to insert
            if region.get("preserve", False):
                # preserve=True → reinsert original text unchanged
                # (Cell 9: blank fill lines, URLs, X checkboxes)
                text_to_insert = orig_text
            else:
                text_to_insert = region.get("translated_text", "").strip()
                if not text_to_insert:
                    continue
                # Phase 3 post-processing (Cell 9)
                text_to_insert = _citation_fallback(orig_text, text_to_insert)
                text_to_insert = _restore_caps(orig_text, text_to_insert)

            if not text_to_insert:
                continue

            # Rendering params from extended region contract
            fontname = region.get("fontname", "helv")
            color = tuple(region.get("color_rgb", [0.0, 0.0, 0.0]))
            is_centered = region.get("is_centered", False)
            is_right = region.get("is_right", False)
            font_size = max(region.get("font_size", 10.0), 6.0)

            # avail_bbox preferred; fall back to bbox
            avail_raw = region.get("avail_bbox") or region.get("bbox")
            if not avail_raw:
                continue
            avail_rect = pymupdf.Rect(*avail_raw)

            _insert_unit_html(
                page,
                text_to_insert,
                avail_rect,
                font_size,
                fontname,
                color,
                is_centered,
                is_right,
                cell_rects=cell_rects,
                page_width=page_width,
            )
            count += 1

        logger.debug("Page %d: inserted %d unit(s)", page_num, count)

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    logger.info("PDF reconstructed → '%s'", output_path)
