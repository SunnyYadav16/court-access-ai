"""
courtaccess/core/pdf_utils.py

PDF font utilities, color helpers, and block layout utilities.
Used by OCREngine (ocr_printed.py) and reconstruct_pdf.py.

Sections:
  1. Font utilities    — get_font_code, get_font_size, fit_fontsize (Cell 4)
  2. Color utilities   — safe_color, color_to_hex, get_background_color (Cell 4)
  3. CSS font map      — CSS_FONTS for insert_htmlbox (Cell 9)
  4. Block utilities   — _get_block_units and helpers (Cell 9)

Source: Cell 4 and Cell 9 of the original Colab script.
        All logic is identical — made module-level for reuse across
        digital OCR, scanned OCR, and PDF reconstruction.
"""

import logging
import re

import pymupdf

logger = logging.getLogger(__name__)


# ── Font map (display reference) ─────────────────────────────────────────────
FONT_MAP = {
    "Helvetica": "helv",
    "Helvetica-Bold": "hebo",
    "Helvetica-Oblique": "heit",
    "Helvetica-BoldOblique": "hebi",
    "Times-Roman": "tiro",
    "Times-Bold": "tibo",
    "Times-Italic": "tiit",
    "Times-BoldItalic": "tibi",
    "Courier": "cour",
    "Courier-Bold": "cobo",
    "Courier-Oblique": "coit",
    "Courier-BoldOblique": "cobi",
    "Symbol": "symb",
    "ZapfDingbats": "zadb",
}

# ── CSS font families (used by insert_htmlbox) ────────────────────────────────
CSS_FONTS = {
    "helv": ("Helvetica, Arial, sans-serif", False, False),
    "hebo": ("Helvetica, Arial, sans-serif", True, False),
    "heit": ("Helvetica, Arial, sans-serif", False, True),
    "hebi": ("Helvetica, Arial, sans-serif", True, True),
    "tiro": ("'Times New Roman', serif", False, False),
    "tibo": ("'Times New Roman', serif", True, False),
    "tiit": ("'Times New Roman', serif", False, True),
    "tibi": ("'Times New Roman', serif", True, True),
    "cour": ("'Courier New', monospace", False, False),
    "cobo": ("'Courier New', monospace", True, False),
    "coit": ("'Courier New', monospace", False, True),
    "cobi": ("'Courier New', monospace", True, True),
}


# ══════════════════════════════════════════════════════════════════════════════
# Font utilities — Cell 4
# ══════════════════════════════════════════════════════════════════════════════


def get_font_code(span: dict) -> str:
    """
    Map a PyMuPDF span to the closest built-in font code.
    Source: Cell 4 get_font_code()
    """
    fontname = span.get("font", "")
    flags = span.get("flags", 0)

    is_bold = bool(flags & 16) or any(w in fontname.lower() for w in ["bold", "black", "heavy", "demi"])
    is_italic = bool(flags & 2) or any(w in fontname.lower() for w in ["italic", "oblique", "slant"])
    is_mono = bool(flags & 8) or any(w in fontname.lower() for w in ["courier", "mono", "typewriter", "fixed"])
    is_serif = bool(flags & 4) or any(
        w in fontname.lower() for w in ["times", "serif", "nimbus", "georgia", "garamond", "palatino"]
    )

    if is_mono:
        if is_bold and is_italic:
            return "cobi"
        if is_bold:
            return "cobo"
        if is_italic:
            return "coit"
        return "cour"
    elif is_serif:
        if is_bold and is_italic:
            return "tibi"
        if is_bold:
            return "tibo"
        if is_italic:
            return "tiit"
        return "tiro"
    else:
        if is_bold and is_italic:
            return "hebi"
        if is_bold:
            return "hebo"
        if is_italic:
            return "heit"
        return "helv"


def get_font_size(span: dict, min_size: float = 6.0) -> float:
    """
    Extract font size from span. Source: Cell 4 get_font_size()
    """
    return max(round(span.get("size", 10.0), 1), min_size)


def fit_fontsize(
    text: str,
    original_size: float,
    bbox_width: float,
    fontname: str = "helv",
    min_size: float = 4.0,
) -> float:
    """
    Shrink font size until text fits within bbox_width.
    Source: Cell 4 fit_fontsize()
    """
    font = pymupdf.Font(fontname)
    if font.text_length(text, fontsize=original_size) <= bbox_width * 0.95:
        return original_size
    size = original_size
    while size >= min_size:
        if font.text_length(text, fontsize=size) <= bbox_width * 0.95:
            return size
        size -= 0.5
    return min_size


# ══════════════════════════════════════════════════════════════════════════════
# Color utilities — Cell 4
# ══════════════════════════════════════════════════════════════════════════════


def safe_color(span) -> tuple:
    """
    Convert span color to (r, g, b) 0.0-1.0 tuple.
    Source: Cell 4 _safe_color()
    """
    raw = span.get("color", 0) if isinstance(span, dict) else span

    if isinstance(raw, (tuple, list)) and len(raw) >= 3:
        vals = [v / 255.0 if v > 1 else float(v) for v in raw[:3]]
        return tuple(vals)

    try:
        n = int(raw)
    except (TypeError, ValueError):
        return (0.0, 0.0, 0.0)

    r = ((n >> 16) & 0xFF) / 255.0
    g = ((n >> 8) & 0xFF) / 255.0
    b = (n & 0xFF) / 255.0
    return (r, g, b)


def color_to_hex(color) -> str:
    """
    Convert (r, g, b) float tuple to CSS hex string.
    Source: Cell 9 _color_hex()
    """
    if isinstance(color, (tuple, list)) and len(color) == 3:
        r, g, b = (max(0, min(255, int(c * 255))) for c in color)
        return f"#{r:02x}{g:02x}{b:02x}"
    return "#000000"


def get_background_color(page, bbox: tuple) -> tuple:
    """
    Sample the background color at a given bbox. Falls back to white.
    Source: Cell 4 get_background_color()
    """
    try:
        pix = page.get_pixmap(clip=pymupdf.Rect(bbox), matrix=pymupdf.Matrix(1, 1))
        s = pix.samples
        if len(s) >= 3:
            return (s[0] / 255, s[1] / 255, s[2] / 255)
    except Exception as exc:
        logger.debug("get_background_color failed: %s", exc)
    return (1.0, 1.0, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# Block utilities — Cell 9
# All functions are exact Cell 9 logic, made module-level for reuse.
# ══════════════════════════════════════════════════════════════════════════════

# Source: Cell 9 _FORM_FIELD_RE
_FORM_FIELD_RE = re.compile(
    r"^(X|DATE|BBO\s*NO\.?|DOCKET\s*NO\.?|PRINT\s*NAME"
    r"|COURT\s*DIVISION|DEFENDANT\s*NAME"
    r"|SECTION\s*\d+\s*:?"
    r"|SIGNATURE(\s+OF\s+\w+(\s+\w+)*)?)$",
    re.IGNORECASE,
)


def _is_blank_fill_line(text: str) -> bool:
    """
    Detect blank fill-in lines (underscores/dashes).
    Local copy to avoid circular imports — exact Cell 6 logic.
    Source: Cell 6 _is_blank_fill_line()
    """
    t = text.strip()
    if not t:
        return True
    if re.match(r"^[\s_\-]{4,}$", t):
        return True
    if re.match(r"^\$[\s_\-\.]{3,}$", t):
        return True
    return len(re.sub(r"[\s_\-]", "", t)) == 0


def _should_never_translate(text: str) -> bool:
    """
    Returns True for text that must never be sent to NLLB.
    Source: Cell 9 _should_never_translate()
    """
    t = text.strip()
    if t.upper() in {"PRINT", "CLEAR", "SUBMIT", "RESET", "SAVE"}:
        return True
    return bool(re.search(r"https?://|www\.", t, re.IGNORECASE))


def _is_form_field_line(text: str) -> bool:
    """
    Returns True if text matches known form field label patterns.
    Source: Cell 9 _is_form_field_line()
    """
    return bool(_FORM_FIELD_RE.match(text.strip()))


def _classify(text: str, n_lines: int) -> str:
    """
    Classify a text unit as SKIP, FORM_LABEL, HEADER, or PROSE.
    Source: Cell 9 _classify()
    """
    if not text:
        return "SKIP"
    letters = [c for c in text if c.isalpha()]
    if not letters:
        meaningful = [c for c in text if c in "$#%@£€"]
        if meaningful:
            return "FORM_LABEL"
        return "SKIP"
    # Numbered/lettered list items → FORM_LABEL
    if re.match(r"^([A-Za-z]|\d+|[ivxlcdmIVXLCDM]+)[\.\)]\s+\w", text):
        return "FORM_LABEL"
    all_caps = all(c.isupper() for c in letters)
    if n_lines <= 2 and any(
        re.search(p, text) for p in [r"G\.L\.", r"§", r"CERTIFICATE", r"WAIVER", r"REQUIRED BY", r"OPTIONAL"]
    ):
        return "HEADER"
    if all_caps and len(text) < 80 and n_lines <= 3:
        return "FORM_LABEL"
    if n_lines == 1 and len(text) < 60:
        return "FORM_LABEL"
    return "PROSE"


def _detect_alignment(lines_data: list, block_rect) -> str:
    """
    Detect text alignment from a list of line dicts and block rect.
    Source: Cell 9 _detect_alignment()
    """
    if not lines_data or block_rect.width <= 0:
        return "left"
    lm = [ln["bbox"][0] - block_rect.x0 for ln in lines_data]
    rm = [block_rect.x1 - ln["bbox"][2] for ln in lines_data]
    al = sum(lm) / len(lm)
    ar = sum(rm) / len(rm)
    if al > 5 and ar > 5 and abs(al - ar) < 15:
        return "center"
    if ar < 8 and al > 20:
        return "right"
    return "left"


def _lines_are_same_row(ln1: dict, ln2: dict, tolerance: float = 3.0) -> bool:
    """
    Returns True if two lines overlap vertically enough to be on the same row.
    Source: Cell 9 _lines_are_same_row() (inner function, made module-level)
    """
    y0_1, y1_1 = ln1["bbox"][1], ln1["bbox"][3]
    y0_2, y1_2 = ln2["bbox"][1], ln2["bbox"][3]
    overlap = min(y1_1, y1_2) - max(y0_1, y0_2)
    min_height = min(y1_1 - y0_1, y1_2 - y0_2)
    return overlap > min_height * 0.5


def _group_lines_into_rows(lines: list, tolerance: float = 3.0) -> list:
    """
    Group lines into rows by vertical overlap.
    Returns rows sorted top-to-bottom, each row sorted left-to-right.
    Source: Cell 9 _group_lines_into_rows() (inner function, made module-level)
    """
    rows = []
    used = set()
    for i, ln in enumerate(lines):
        if i in used:
            continue
        row = [ln]
        used.add(i)
        for j, ln2 in enumerate(lines):
            if j in used:
                continue
            if _lines_are_same_row(ln, ln2, tolerance):
                row.append(ln2)
                used.add(j)
        row.sort(key=lambda r: r["bbox"][0])
        rows.append(row)
    rows.sort(key=lambda r: r[0]["bbox"][1])
    return rows


def _split_line_by_columns(line: dict, block_x1: float | None = None, gap: float = 15.0) -> list:
    """
    Split a line into column clusters based on horizontal gaps between spans.
    Returns list of column dicts with text, orig_rect, avail_rect, first_span.
    Source: Cell 9 _split_line_by_columns()
    """
    spans = [s for s in line["spans"] if s["text"].strip()]
    if not spans:
        return []

    clusters, cur = [], [spans[0]]
    for s in spans[1:]:
        if s["bbox"][0] - cur[-1]["bbox"][2] > gap:
            clusters.append(cur)
            cur = [s]
        else:
            cur.append(s)
    clusters.append(cur)

    right = block_x1 if block_x1 else clusters[-1][-1]["bbox"][2]
    result = []
    for i, cl in enumerate(clusters):
        text = " ".join(s["text"] for s in cl).strip()
        if not text:
            continue
        x0 = cl[0]["bbox"][0]
        x1 = clusters[i + 1][0]["bbox"][0] - 2.0 if i + 1 < len(clusters) else right
        y0, y1 = line["bbox"][1], line["bbox"][3]
        result.append(
            {
                "text": text,
                "orig_rect": pymupdf.Rect(x0, y0, cl[-1]["bbox"][2], y1),
                "avail_rect": pymupdf.Rect(x0, y0, max(x1, x0 + 10), y1),
                "first_span": cl[0],
            }
        )
    return result


def _union_rects(rects: list):
    """
    Return the bounding rect of all rects.
    Source: Cell 9 _union_rects()
    """
    if not rects:
        return pymupdf.Rect()
    return pymupdf.Rect(
        min(r.x0 for r in rects),
        min(r.y0 for r in rects),
        max(r.x1 for r in rects),
        max(r.y1 for r in rects),
    )


def _get_cell_rects(page, min_w: float = 15.0, min_h: float = 4.0) -> list:
    """
    Extract rectangle paths from page drawings (form table cell boundaries).
    Returns list of Rects sorted smallest-area first.
    Source: Cell 9 _get_cell_rects()
    """
    rects = []
    for d in page.get_drawings():
        r = d.get("rect")
        if r and r.width >= min_w and r.height >= min_h:
            rects.append(pymupdf.Rect(r))
    rects.sort(key=lambda r: r.width * r.height)
    return rects


def _find_tightest_cell(line_rect, cell_rects: list, pad: float = 4.0):
    """
    Return the smallest cell rect that contains line_rect (with padding).
    Used for grid-aware width calculation only — not for placement.
    Source: Cell 9 _find_tightest_cell()
    """
    best = None
    best_area = float("inf")
    for cell in cell_rects:
        expanded = pymupdf.Rect(
            cell.x0 - pad,
            cell.y0 - pad,
            cell.x1 + pad,
            cell.y1 + pad,
        )
        if expanded.contains(line_rect):
            area = cell.width * cell.height
            if area < best_area:
                best_area = area
                best = cell
    return best


def _get_available_width(avail_rect, cell_rects: list, page_width: float = 594.0) -> float:
    """
    Compute available text width considering form table cell boundaries.
    Falls back to distance-to-right-margin for free-floating text.
    Source: Cell 9 _get_available_width()
    """
    x0 = avail_rect.x0
    y_mid = (avail_rect.y0 + avail_rect.y1) / 2

    best_width = None
    for cell in cell_rects:
        if not (cell.y0 <= y_mid <= cell.y1):
            continue
        if not (cell.x0 <= x0 + 2 <= cell.x1):
            continue
        cell_width = cell.x1 - x0
        if best_width is None or cell_width < best_width:
            best_width = cell_width

    if best_width is not None:
        return best_width

    return (page_width - 36) - x0  # 36pt right margin


def _get_block_units(blk: dict) -> list:
    """
    Extract logical text units from a PyMuPDF block dict.

    Groups spans into:
      - Multi-column rows → one unit per column
      - Prose lines       → merged into a single prose unit
      - Form labels       → one unit each (no merging)

    Each unit dict contains:
      text, orig_rect, avail_rect, unit_type, first_span,
      is_caps, is_centered, is_right, preserve

    Source: Cell 9 _get_block_units() — exact logic, inner closures preserved.
    """
    all_spans = [s for ln in blk["lines"] for s in ln["spans"] if s["text"].strip()]
    if not all_spans:
        return []

    block_first = all_spans[0]
    block_rect = pymupdf.Rect(blk["bbox"])

    # Detect alignment from non-trivial lines
    tls = [ln for ln in blk["lines"] if " ".join(s["text"] for s in ln["spans"]).strip() not in ("", "X")]
    alignment = _detect_alignment(tls, block_rect) if tls else "left"
    is_centered = alignment == "center"
    is_right = alignment == "right"

    prose_texts: list = []
    prose_orig: list = []
    prose_avail: list = []
    prose_spans: list = []
    units: list = []

    def _flush():
        if not prose_texts:
            return
        text = " ".join(" ".join(prose_texts).split())
        if _is_blank_fill_line(text) or not text.strip():
            prose_texts.clear()
            prose_orig.clear()
            prose_avail.clear()
            prose_spans.clear()
            return
        ou = _union_rects(prose_orig)
        av = pymupdf.Rect(block_rect.x0, ou.y0, block_rect.x1, ou.y1)
        fs = prose_spans[0] if prose_spans else block_first
        ut = _classify(text, len(prose_texts))
        lets = [c for c in text if c.isalpha()]
        units.append(
            {
                "text": text,
                "orig_rect": ou,
                "avail_rect": av,
                "unit_type": ut,
                "first_span": fs,
                "is_caps": bool(lets) and all(c.isupper() for c in lets),
                "is_centered": is_centered,
                "is_right": is_right,
                "preserve": False,
            }
        )
        prose_texts.clear()
        prose_orig.clear()
        prose_avail.clear()
        prose_spans.clear()

    def _emit(text, orig_r, avail_r, fs, preserve=False):
        lets = [c for c in text if c.isalpha()]
        units.append(
            {
                "text": text.strip(),
                "orig_rect": orig_r,
                "avail_rect": avail_r,
                "unit_type": "FORM_LABEL",
                "first_span": fs,
                "is_caps": bool(lets) and all(c.isupper() for c in lets),
                "is_centered": False,
                "is_right": False,
                "preserve": preserve,
            }
        )

    for row in _group_lines_into_rows(blk["lines"]):
        if len(row) > 1:
            # Side-by-side columns — emit each as its own unit
            _flush()
            for k, ln in enumerate(row):
                t = " ".join(s["text"] for s in ln["spans"] if s["text"].strip()).strip()
                if not t or t.strip() == "X":
                    continue
                x0 = ln["bbox"][0]
                x1 = row[k + 1]["bbox"][0] - 2.0 if k + 1 < len(row) else block_rect.x1
                y0, y1 = ln["bbox"][1], ln["bbox"][3]
                orig_r = pymupdf.Rect(ln["bbox"])
                avail_r = pymupdf.Rect(x0, y0, x1, y1)
                fs = ln["spans"][0] if ln["spans"] else block_first
                if _is_blank_fill_line(t) or _should_never_translate(t):
                    _emit(t, orig_r, avail_r, fs, preserve=True)
                else:
                    _emit(t, orig_r, avail_r, fs, preserve=False)
            continue

        # Single line
        ln = row[0]
        cols = _split_line_by_columns(ln, block_rect.x1)

        if len(cols) > 1:
            _flush()
            for cl in cols:
                t = cl["text"]
                if not t or t.strip() == "X" or _is_blank_fill_line(t):
                    continue
                _emit(
                    t,
                    cl["orig_rect"],
                    cl["avail_rect"],
                    cl["first_span"],
                    preserve=_should_never_translate(t),
                )
        elif len(cols) == 1:
            cl, text = cols[0], cols[0]["text"]
            if not text or text.strip() == "X":
                _flush()
                continue
            if _is_blank_fill_line(text):
                _flush()
                _emit(text, cl["orig_rect"], cl["avail_rect"], cl["first_span"], preserve=True)
                continue
            if _should_never_translate(text):
                _flush()
                _emit(text, cl["orig_rect"], cl["avail_rect"], cl["first_span"], preserve=True)
                continue
            if _is_form_field_line(text):
                _flush()
                _emit(text, cl["orig_rect"], cl["avail_rect"], cl["first_span"])
                continue
            if _classify(text, 1) in ("FORM_LABEL", "HEADER"):
                _flush()
                _emit(text, cl["orig_rect"], cl["avail_rect"], cl["first_span"])
                continue
            prose_texts.append(text)
            prose_orig.append(cl["orig_rect"])
            prose_avail.append(cl["avail_rect"])
            prose_spans.append(cl["first_span"])

    _flush()
    return units
