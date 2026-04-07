"""
Tests for courtaccess/speech/mt_service.py

Tests the language code mappings and translate() edge cases
(empty text, same language, unsupported pairs) — all paths that
return early without loading the real NLLB model.
"""

from unittest.mock import MagicMock, patch

import pytest

from courtaccess.speech.mt_service import (
    LANG_CODE_TO_NLLB,
    NLLB_TO_LANG_CODE,
    SUPPORTED_LANGUAGES,
    MTService,
)


# ══════════════════════════════════════════════════════════════════════════════
# Language code constants
# ══════════════════════════════════════════════════════════════════════════════


def test_lang_code_to_nllb_en():
    assert LANG_CODE_TO_NLLB["en"] == "eng_Latn"


def test_lang_code_to_nllb_es():
    assert LANG_CODE_TO_NLLB["es"] == "spa_Latn"


def test_lang_code_to_nllb_pt():
    assert LANG_CODE_TO_NLLB["pt"] == "por_Latn"


def test_nllb_to_lang_code_reverse_en():
    assert NLLB_TO_LANG_CODE["eng_Latn"] == "en"


def test_nllb_to_lang_code_reverse_es():
    assert NLLB_TO_LANG_CODE["spa_Latn"] == "es"


def test_nllb_to_lang_code_reverse_pt():
    assert NLLB_TO_LANG_CODE["por_Latn"] == "pt"


def test_nllb_to_lang_code_is_inverse_of_lang_code_to_nllb():
    for short, nllb in LANG_CODE_TO_NLLB.items():
        assert NLLB_TO_LANG_CODE[nllb] == short


def test_supported_languages_contains_en():
    assert "en" in SUPPORTED_LANGUAGES


def test_supported_languages_contains_es():
    assert "es" in SUPPORTED_LANGUAGES


def test_supported_languages_contains_pt():
    assert "pt" in SUPPORTED_LANGUAGES


def test_supported_languages_is_set():
    assert isinstance(SUPPORTED_LANGUAGES, set)


def test_supported_languages_matches_mapping_keys():
    assert SUPPORTED_LANGUAGES == set(LANG_CODE_TO_NLLB.keys())


# ══════════════════════════════════════════════════════════════════════════════
# MTService.translate — early-return paths (no model loaded)
# ══════════════════════════════════════════════════════════════════════════════


def _make_mt_service() -> MTService:
    """Build an MTService with a stubbed translator and tokenizer."""
    svc = object.__new__(MTService)
    MTService._translator = MagicMock()
    MTService._tokenizer = MagicMock()
    return svc


def test_translate_empty_string_returns_empty():
    svc = _make_mt_service()
    assert svc.translate("", "en", "es") == ""


def test_translate_whitespace_only_returns_empty():
    svc = _make_mt_service()
    assert svc.translate("   ", "en", "es") == ""


def test_translate_same_language_returns_original():
    svc = _make_mt_service()
    text = "The defendant"
    assert svc.translate(text, "en", "en") == text


def test_translate_same_language_es():
    svc = _make_mt_service()
    text = "el acusado"
    assert svc.translate(text, "es", "es") == text


def test_translate_unsupported_source_returns_original():
    svc = _make_mt_service()
    text = "bonjour"
    result = svc.translate(text, "fr", "en")
    assert result == text


def test_translate_unsupported_target_returns_original():
    svc = _make_mt_service()
    text = "hello"
    result = svc.translate(text, "en", "fr")
    assert result == text


def test_translate_both_unsupported_returns_original():
    svc = _make_mt_service()
    text = "hallo"
    result = svc.translate(text, "de", "ja")
    assert result == text


def test_translate_calls_tokenizer_for_supported_pair():
    """Verify the tokenizer is actually called for a real language pair."""
    svc = object.__new__(MTService)

    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1, 2, 3]
    mock_tokenizer.convert_ids_to_tokens.return_value = ["▁The", "▁defendant"]
    mock_tokenizer.convert_tokens_to_ids.return_value = [4, 5]
    mock_tokenizer.decode.return_value = "el acusado"

    mock_result = MagicMock()
    mock_result.hypotheses = [["spa_Latn", "▁el", "▁acusado"]]

    mock_translator = MagicMock()
    mock_translator.translate_batch.return_value = [mock_result]

    MTService._translator = mock_translator
    MTService._tokenizer = mock_tokenizer

    result = svc.translate("The defendant", "en", "es")
    assert mock_tokenizer.encode.called
    assert mock_translator.translate_batch.called


def test_translate_strips_special_tokens():
    """Special tokens like </s> are excluded from the output."""
    svc = object.__new__(MTService)

    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1]
    mock_tokenizer.convert_ids_to_tokens.return_value = ["▁plea"]

    # Hypotheses with special tokens that should be stripped
    mock_result = MagicMock()
    mock_result.hypotheses = [["spa_Latn", "</s>", "▁declaración", "</s>"]]

    mock_translator = MagicMock()
    mock_translator.translate_batch.return_value = [mock_result]

    # After stripping: ["▁declaración"]
    mock_tokenizer.convert_tokens_to_ids.return_value = [123]
    mock_tokenizer.decode.return_value = "declaración"

    MTService._translator = mock_translator
    MTService._tokenizer = mock_tokenizer

    result = svc.translate("plea", "en", "es")
    # Verify only non-special tokens were passed to decode
    call_args = mock_tokenizer.convert_tokens_to_ids.call_args[0][0]
    assert "spa_Latn" not in call_args
    assert "</s>" not in call_args


# ══════════════════════════════════════════════════════════════════════════════
# MTService singleton
# ══════════════════════════════════════════════════════════════════════════════


def test_mt_service_singleton():
    """Two MTService() calls with mocked _load_model return the same instance."""
    MTService._instance = None
    MTService._translator = None
    MTService._tokenizer = None

    with patch.object(MTService, "_load_model", lambda self: None):
        svc1 = MTService()
        svc2 = MTService()

    assert svc1 is svc2
