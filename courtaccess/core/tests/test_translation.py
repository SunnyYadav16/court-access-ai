"""
courtaccess/core/tests/test_translation.py

Unit tests for courtaccess.core.translation.
Tests stub mode only — real NLLB model tests run on GPU CI only.
"""

from courtaccess.core.translation import _stub_translate, translate_text


def test_translate_text_returns_contract():
    result = translate_text("The defendant pleads not guilty.", "eng_Latn", "spa_Latn")
    assert "original" in result
    assert "translated" in result
    assert "confidence" in result
    assert isinstance(result["confidence"], float)


def test_stub_translate_prefix_es():
    result = _stub_translate("Motion to suppress.", "eng_Latn", "spa_Latn")
    assert result["translated"].startswith("[ES]")
    assert result["original"] == "Motion to suppress."


def test_stub_translate_prefix_pt():
    result = _stub_translate("Motion to suppress.", "eng_Latn", "por_Latn")
    assert result["translated"].startswith("[PT]")


def test_translate_text_unknown_language():
    """Unknown target language falls back to raw NLLB code prefix."""
    result = translate_text("Test.", "eng_Latn", "fra_Latn")
    assert "translated" in result


def test_translate_text_empty_string():
    result = translate_text("", "eng_Latn", "spa_Latn")
    assert result["original"] == ""
