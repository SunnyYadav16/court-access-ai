"""
courtaccess/languages/__init__.py

Single import point for language configs.
Usage:
    from courtaccess.languages import get_language_config
    config = get_language_config("spanish")
"""

import logging

from courtaccess.languages.base import LanguageConfig
from courtaccess.languages.portuguese import PORTUGUESE_CONFIG
from courtaccess.languages.spanish import SPANISH_CONFIG

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, LanguageConfig] = {
    "spanish": SPANISH_CONFIG,
    "portuguese": PORTUGUESE_CONFIG,
}


def get_language_config(language: str) -> LanguageConfig:
    """
    Return LanguageConfig for the given language code.
    Raises ValueError for unsupported languages.

    Args:
        language: "spanish" | "portuguese"

    Returns:
        LanguageConfig instance

    Raises:
        ValueError: if language is not supported
    """
    key = language.lower().strip()
    if key not in _REGISTRY:
        supported = ", ".join(_REGISTRY.keys())
        raise ValueError(f"Unsupported language: '{language}'. Supported: {supported}")
    config = _REGISTRY[key]
    if not config.ready_for_production:
        logger.warning(
            "Language '%s' is not ready for production (stub config). "
            "Set USE_REAL_TRANSLATION=false or switch to a supported language.",
            key,
        )
    return config


def supported_languages() -> list[str]:
    """Return list of supported language codes."""
    return list(_REGISTRY.keys())
