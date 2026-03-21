"""
courtaccess/forms/parse_glossary.py

Glossary class for loading and querying legal terminology glossaries.

Glossary JSON format (flat dict):
    {"english_term_lower": "target_language_translation", ...}

Usage:
    glossary = Glossary(config).load()
    matches  = glossary.get_matching_terms("The defendant pleads not guilty.")

One-time parse from PDF:
    glossary = Glossary(config).parse_pdf("/path/to/glossary.pdf")
"""

import json
import logging
from pathlib import Path

import pymupdf

from courtaccess.languages.base import LanguageConfig

logger = logging.getLogger(__name__)

_GLOSSARY_DIR = Path(__file__).parent.parent.parent / "data" / "glossaries"


class Glossary:
    """
    Loads, parses, and queries a legal terminology glossary
    for a specific target language.

    The glossary is a flat dict mapping lowercase English terms
    to their verified target-language translations. It is built
    once from a PDF source and committed to the repo as JSON.

    Source: Cell 7a of the original Colab script.
    All parsing logic carried over exactly — made language-aware
    via LanguageConfig instead of hardcoded Spanish values.
    """

    def __init__(self, config: LanguageConfig) -> None:
        self.config = config
        self.json_path = _GLOSSARY_DIR / Path(config.glossary_path).name
        self.glossary: dict = {}

    # ── Public API ────────────────────────────────────────────

    def load(self) -> "Glossary":
        """
        Load glossary from committed JSON file.

        Raises:
            FileNotFoundError: if the JSON file does not exist,
                with instructions for generating it.
        """
        if not self.json_path.exists():
            raise FileNotFoundError(
                f"Glossary not found: {self.json_path}\n"
                f"Generate it by running:\n"
                f"  python scripts/parse_glossary.py "
                f"--pdf /path/to/glossary.pdf "
                f"--lang {self.config.code}"
            )

        with open(self.json_path, encoding="utf-8") as f:
            self.glossary = json.load(f)

        logger.info(
            "Glossary loaded: %d terms for '%s'",
            len(self.glossary),
            self.config.code,
        )
        return self

    def parse_pdf(self, pdf_path: str) -> "Glossary":
        """
        Parse a glossary PDF and save the result as JSON.

        Applies config.legal_overrides as the final authoritative
        override layer on top of PDF-parsed terms — exactly as
        MA_OVERRIDES_ES was applied in Cell 7a.

        Args:
            pdf_path: absolute path to the glossary PDF

        Returns:
            self, with self.glossary populated and saved to disk

        Source: Cell 7a parse_spanish_glossary() + load_glossary_es()
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Glossary PDF not found: {pdf_path}")

        self.glossary = self._parse_blocks(str(pdf_path))

        # Apply language-specific overrides as authoritative final layer
        # This matches Cell 7a: glossary.update({k.lower(): v for k, v in MA_OVERRIDES_ES.items()})
        self.glossary.update({k.lower(): v for k, v in self.config.legal_overrides.items()})

        logger.info(
            "Glossary parsed: %d terms for '%s'",
            len(self.glossary),
            self.config.code,
        )

        _GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self.glossary, f, ensure_ascii=False, indent=2)

        logger.info("Glossary saved: %s", self.json_path)
        return self

    def get_matching_terms(self, text: str, max_terms: int = 8) -> dict:
        """
        Find glossary terms appearing in text.
        Longer terms matched first to prevent partial overlaps.
        Returns {english_term: translation} for matches only.

        Source: Cell 7a get_matching_glossary_terms()
        """
        text_lower = text.lower()
        matches = {}

        for term in sorted(self.glossary, key=len, reverse=True):
            if term in text_lower:
                matches[term] = self.glossary[term]
            if len(matches) >= max_terms:
                break

        return matches

    # ── Private parsing methods ───────────────────────────────

    def _should_skip(self, text: str, y0: float) -> bool:
        """
        Source: Cell 7a _should_skip()
        Uses config.glossary_skip_lines instead of hardcoded set.
        """
        if y0 < 55 or y0 > 725:
            return True
        t = text.lower().strip()
        if not t:
            return True
        if len(t) <= 2 and t.isalpha():
            return True
        return any(t.startswith(skip) for skip in self.config.glossary_skip_lines)

    def _parse_blocks(self, pdf_path: str) -> dict:
        """
        Parse NJ Courts glossary PDF block by block.

        Structure: each entry is one block with two lines.
          Line 1 = English term
          Line 2 = target-language translation

        Multi-column blocks (3+ lines) are split by x-coordinate.

        Source: Cell 7a parse_spanish_glossary()
        """
        doc = pymupdf.open(pdf_path)
        glossary = {}

        for pg_num in range(2, len(doc)):
            page = doc[pg_num]
            td = page.get_text("dict")

            for b in td["blocks"]:
                if b["type"] != 0:
                    continue

                b_y0 = round(b["bbox"][1], 1)
                if b_y0 < 55 or b_y0 > 725:
                    continue

                lines = [" ".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]]
                lines = [ln for ln in lines if ln]

                if not lines or self._should_skip(lines[0], b_y0):
                    continue

                if len(lines) == 1:
                    continue

                if len(lines) == 2:
                    en, tl = lines[0].strip(), lines[1].strip()
                    if en and tl:
                        glossary[en.strip(" ,;").lower()] = tl
                    continue

                # 3+ lines — split by x-coordinate into left/right columns
                non_empty = [ln for ln in b["lines"] if " ".join(s["text"] for s in ln["spans"]).strip()]
                x0s = [round(ln["bbox"][0], 1) for ln in non_empty]

                left, right = [], []
                for ln, x0 in zip(non_empty, x0s, strict=False):
                    text = " ".join(s["text"] for s in ln["spans"]).strip()
                    (left if x0 < 200 else right).append(text)

                if left and right:
                    en = " ".join(left).strip()
                    tl = " ".join(right).strip()
                else:
                    en = left[0] if left else lines[0]
                    tl = " ".join(left[1:] if left else lines[1:]).strip()

                if en and tl:
                    glossary[en.strip(" ,;").lower()] = tl

        doc.close()
        return glossary
