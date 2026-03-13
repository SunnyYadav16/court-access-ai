"""
courtaccess/forms/parse_glossary.py

Loads and queries the legal terminology glossaries (data/glossaries/).
Used by legal_review.py to validate that key legal terms are translated
consistently with the approved court glossary.

Glossary format (JSON):
  [
      {
          "term":        str,    # English source term
          "translation": str,    # Approved translation
          "context":     str,    # Usage context / legal area
          "language":    str,    # "es" or "pt"
      }
  ]
"""

import json
from functools import lru_cache
from pathlib import Path

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

_GLOSSARY_DIR = Path(__file__).parent.parent.parent / "data" / "glossaries"

_LANG_FILE = {
    "spa_Latn": "glossary_es.json",
    "es": "glossary_es.json",
    "por_Latn": "glossary_pt.json",
    "pt": "glossary_pt.json",
}


@lru_cache(maxsize=4)
def load_glossary(language: str) -> list[dict]:
    """
    Load the approved legal glossary for a language.
    Cached after first load (glossary files rarely change at runtime).

    Args:
        language: NLLB code ("spa_Latn", "por_Latn") or ISO ("es", "pt").

    Returns:
        List of glossary entry dicts.

    Raises:
        FileNotFoundError: if glossary file does not exist.
        ValueError:        if language is not supported.
    """
    filename = _LANG_FILE.get(language)
    if not filename:
        raise ValueError(f"Unsupported glossary language: {language!r}. Use 'spa_Latn' or 'por_Latn'.")

    glossary_path = _GLOSSARY_DIR / filename
    if not glossary_path.exists():
        raise FileNotFoundError(f"Glossary file not found: {glossary_path}")

    with open(glossary_path, encoding="utf-8") as f:
        entries = json.load(f)

    logger.info("Loaded %d glossary entries for language '%s'.", len(entries), language)
    return entries


def lookup_term(term: str, language: str) -> dict | None:
    """
    Look up a single English term in the glossary.

    Args:
        term:     English source term (case-insensitive).
        language: Target language code.

    Returns:
        Glossary entry dict or None if not found.
    """
    glossary = load_glossary(language)
    term_lower = term.lower().strip()
    for entry in glossary:
        if entry.get("term", "").lower().strip() == term_lower:
            return entry
    return None


def find_inconsistencies(translated_text: str, language: str) -> list[dict]:
    """
    Scan translated text for legal terms that don't match the approved glossary.

    Args:
        translated_text: The translated text to check.
        language:        Language of the translation.

    Returns:
        List of inconsistency dicts:
        [{"term": str, "expected": str, "found_variant": str}]
    """
    glossary = load_glossary(language)
    text_lower = translated_text.lower()
    inconsistencies = []

    for entry in glossary:
        approved = entry.get("translation", "").lower()
        if not approved:
            continue
        # If the approved translation is not found, flag it
        if approved not in text_lower:
            # Check if an English source term appears in the text (not yet translated)
            source = entry.get("term", "").lower()
            if source and source in text_lower:
                inconsistencies.append(
                    {
                        "term": entry["term"],
                        "expected": entry["translation"],
                        "found_variant": "(English term not translated)",
                    }
                )

    return inconsistencies
