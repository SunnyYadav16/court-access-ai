"""
Tests for courtaccess/speech/legal_verifier.py

LegalVerifierService._parse_response() and _fallback() are pure functions —
testable without any network or Vertex AI credentials.
get_legal_verifier() is tested via feature-flag paths.
"""


from courtaccess.speech.legal_verifier import (
    LANG_LABELS,
    LegalVerifierService,
    VerificationResult,
    get_legal_verifier,
)

# ══════════════════════════════════════════════════════════════════════════════
# LANG_LABELS
# ══════════════════════════════════════════════════════════════════════════════


def test_lang_labels_en():
    assert LANG_LABELS["en"] == "English"


def test_lang_labels_es():
    assert LANG_LABELS["es"] == "Spanish"


def test_lang_labels_pt():
    assert LANG_LABELS["pt"] == "Portuguese"


def test_lang_labels_is_dict():
    assert isinstance(LANG_LABELS, dict)


# ══════════════════════════════════════════════════════════════════════════════
# VerificationResult dataclass
# ══════════════════════════════════════════════════════════════════════════════


def test_verification_result_fields():
    result = VerificationResult(
        verified_translation="acusado",
        accuracy_score=0.95,
        accuracy_note="Minor rephrasing.",
        raw_translation="acusado",
        used_fallback=False,
    )
    assert result.verified_translation == "acusado"
    assert result.accuracy_score == 0.95
    assert result.accuracy_note == "Minor rephrasing."
    assert result.raw_translation == "acusado"
    assert result.used_fallback is False


def test_verification_result_used_fallback_true():
    result = VerificationResult(
        verified_translation="x", accuracy_score=1.0,
        accuracy_note="n/a", raw_translation="x", used_fallback=True,
    )
    assert result.used_fallback is True


# ══════════════════════════════════════════════════════════════════════════════
# LegalVerifierService._fallback (static — no client needed)
# ══════════════════════════════════════════════════════════════════════════════


def test_fallback_returns_raw_translation():
    result = LegalVerifierService._fallback("el acusado")
    assert result.verified_translation == "el acusado"
    assert result.raw_translation == "el acusado"


def test_fallback_sets_used_fallback_true():
    result = LegalVerifierService._fallback("some text")
    assert result.used_fallback is True


def test_fallback_accuracy_score_is_1():
    result = LegalVerifierService._fallback("any")
    assert result.accuracy_score == 1.0


def test_fallback_note_mentions_unavailable():
    result = LegalVerifierService._fallback("text")
    assert "unavailable" in result.accuracy_note.lower() or "machine translation" in result.accuracy_note.lower()


def test_fallback_empty_string():
    result = LegalVerifierService._fallback("")
    assert result.verified_translation == ""
    assert result.used_fallback is True


# ══════════════════════════════════════════════════════════════════════════════
# LegalVerifierService._parse_response (pure JSON parsing — no client needed)
# ══════════════════════════════════════════════════════════════════════════════


def _make_service() -> LegalVerifierService:
    """Return a LegalVerifierService without loading the real client."""
    svc = object.__new__(LegalVerifierService)
    return svc


def test_parse_response_valid_json():
    svc = _make_service()
    raw = '{"verified_translation": "el acusado", "accuracy_score": 0.95, "accuracy_note": "Good."}'
    result = svc._parse_response(raw, "el acusado")
    assert result.verified_translation == "el acusado"
    assert result.accuracy_score == 0.95
    assert result.accuracy_note == "Good."
    assert result.used_fallback is False


def test_parse_response_strips_markdown_fences():
    svc = _make_service()
    raw = '```json\n{"verified_translation": "réu", "accuracy_score": 1.0, "accuracy_note": "Perfect."}\n```'
    result = svc._parse_response(raw, "réu")
    assert result.verified_translation == "réu"


def test_parse_response_missing_verified_translation_uses_raw():
    svc = _make_service()
    raw = '{"accuracy_score": 0.9, "accuracy_note": "OK"}'
    result = svc._parse_response(raw, "fallback text")
    assert result.verified_translation == "fallback text"


def test_parse_response_missing_accuracy_score_defaults_to_1():
    svc = _make_service()
    raw = '{"verified_translation": "x", "accuracy_note": "note"}'
    result = svc._parse_response(raw, "x")
    assert result.accuracy_score == 1.0


def test_parse_response_missing_accuracy_note_gets_default():
    svc = _make_service()
    raw = '{"verified_translation": "x", "accuracy_score": 0.8}'
    result = svc._parse_response(raw, "x")
    assert result.accuracy_note != ""


def test_parse_response_score_clamped_above_1():
    svc = _make_service()
    raw = '{"verified_translation": "x", "accuracy_score": 1.5, "accuracy_note": "n/a"}'
    result = svc._parse_response(raw, "x")
    assert result.accuracy_score == 1.0


def test_parse_response_score_clamped_below_0():
    svc = _make_service()
    raw = '{"verified_translation": "x", "accuracy_score": -0.3, "accuracy_note": "n/a"}'
    result = svc._parse_response(raw, "x")
    assert result.accuracy_score == 0.0


def test_parse_response_score_rounded_to_3_decimals():
    svc = _make_service()
    raw = '{"verified_translation": "x", "accuracy_score": 0.123456, "accuracy_note": "n/a"}'
    result = svc._parse_response(raw, "x")
    assert result.accuracy_score == 0.123


def test_parse_response_empty_verified_translation_falls_back_to_raw():
    svc = _make_service()
    raw = '{"verified_translation": "", "accuracy_score": 1.0, "accuracy_note": "n/a"}'
    result = svc._parse_response(raw, "raw fallback")
    assert result.verified_translation == "raw fallback"


def test_parse_response_raw_translation_preserved():
    svc = _make_service()
    raw = '{"verified_translation": "refined", "accuracy_score": 0.9, "accuracy_note": "ok"}'
    result = svc._parse_response(raw, "original nllb")
    assert result.raw_translation == "original nllb"


def test_parse_response_invalid_json_falls_back():
    svc = _make_service()
    result = svc._parse_response("not json at all", "raw text")
    assert result.used_fallback is True
    assert result.verified_translation == "raw text"


def test_parse_response_empty_string_falls_back():
    svc = _make_service()
    result = svc._parse_response("", "raw")
    assert result.used_fallback is True


def test_parse_response_whitespace_verified_falls_back_to_raw():
    svc = _make_service()
    raw = '{"verified_translation": "   ", "accuracy_score": 1.0, "accuracy_note": "n/a"}'
    result = svc._parse_response(raw, "raw fallback")
    assert result.verified_translation == "raw fallback"


# ══════════════════════════════════════════════════════════════════════════════
# get_legal_verifier — feature flag disabled
# ══════════════════════════════════════════════════════════════════════════════


def test_get_legal_verifier_returns_none_when_disabled(monkeypatch):
    """When USE_VERTEX_LEGAL_REVIEW=false, get_legal_verifier() returns None."""
    from unittest.mock import MagicMock

    import courtaccess.speech.legal_verifier as lv_mod

    mock_settings = MagicMock()
    mock_settings.use_vertex_legal_review = False
    mock_settings.vertex_project_id = ""

    monkeypatch.setattr(lv_mod, "_legal_verifier", None)
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "courtaccess.speech.legal_verifier.get_settings", return_value=mock_settings
    ):
        result = get_legal_verifier()
    assert result is None


def test_get_legal_verifier_returns_none_when_no_project_id(monkeypatch):
    """When VERTEX_PROJECT_ID is empty, returns None regardless of feature flag."""
    from unittest.mock import MagicMock, patch

    import courtaccess.speech.legal_verifier as lv_mod

    mock_settings = MagicMock()
    mock_settings.use_vertex_legal_review = True
    mock_settings.vertex_project_id = ""

    monkeypatch.setattr(lv_mod, "_legal_verifier", None)
    with patch("courtaccess.speech.legal_verifier.get_settings", return_value=mock_settings):
        result = get_legal_verifier()
    assert result is None
