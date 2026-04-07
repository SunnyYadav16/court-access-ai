"""
Tests for courtaccess/speech/tts.py

Tests VOICE_MAP constants, _resolve_voice_path() error paths, and
TTSService.synthesize() early-return paths — all without loading
real Piper voice models.
"""

from unittest.mock import MagicMock, patch

import pytest

from courtaccess.speech.tts import (
    SUPPORTED_LANGUAGES,
    VOICE_MAP,
    TTSService,
    _resolve_voice_path,
)

# ══════════════════════════════════════════════════════════════════════════════
# VOICE_MAP
# ══════════════════════════════════════════════════════════════════════════════


def test_voice_map_contains_en():
    assert "en" in VOICE_MAP


def test_voice_map_contains_es():
    assert "es" in VOICE_MAP


def test_voice_map_contains_pt():
    assert "pt" in VOICE_MAP


def test_voice_map_entries_have_name():
    for lang, cfg in VOICE_MAP.items():
        assert "name" in cfg, f"Missing 'name' in VOICE_MAP['{lang}']"


def test_voice_map_en_voice_name():
    assert "en_US" in VOICE_MAP["en"]["name"]


def test_voice_map_es_voice_name():
    assert "es_ES" in VOICE_MAP["es"]["name"]


def test_voice_map_pt_voice_name():
    assert "pt_BR" in VOICE_MAP["pt"]["name"]


# ══════════════════════════════════════════════════════════════════════════════
# SUPPORTED_LANGUAGES
# ══════════════════════════════════════════════════════════════════════════════


def test_supported_languages_is_set():
    assert isinstance(SUPPORTED_LANGUAGES, set)


def test_supported_languages_contains_en():
    assert "en" in SUPPORTED_LANGUAGES


def test_supported_languages_contains_es():
    assert "es" in SUPPORTED_LANGUAGES


def test_supported_languages_contains_pt():
    assert "pt" in SUPPORTED_LANGUAGES


def test_supported_languages_matches_voice_map():
    assert set(VOICE_MAP.keys()) == SUPPORTED_LANGUAGES


# ══════════════════════════════════════════════════════════════════════════════
# _resolve_voice_path — error paths
# ══════════════════════════════════════════════════════════════════════════════


def test_resolve_voice_path_raises_when_env_not_set():
    mock_settings = MagicMock()
    mock_settings.piper_tts_en_path = None
    mock_settings.piper_tts_es_path = None
    mock_settings.piper_tts_pt_path = None

    with patch("courtaccess.speech.tts._get_lang_path_overrides", return_value={"en": None, "es": None, "pt": None}), pytest.raises(RuntimeError, match="PIPER_TTS_EN_PATH"):
        _resolve_voice_path("en")


def test_resolve_voice_path_raises_when_dir_missing(tmp_path):
    missing_dir = tmp_path / "nonexistent"
    with patch("courtaccess.speech.tts._get_lang_path_overrides", return_value={"en": str(missing_dir), "es": "", "pt": ""}), pytest.raises(RuntimeError, match="not found"):
        _resolve_voice_path("en")


def test_resolve_voice_path_raises_when_no_onnx_in_dir(tmp_path):
    # Directory exists but has no .onnx files
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()

    with patch("courtaccess.speech.tts._get_lang_path_overrides", return_value={"en": str(voice_dir), "es": "", "pt": ""}), pytest.raises(RuntimeError, match=r"No \.onnx"):
        _resolve_voice_path("en")


def test_resolve_voice_path_exact_name_match(tmp_path):
    voice_dir = tmp_path / "en"
    voice_dir.mkdir()
    expected_name = VOICE_MAP["en"]["name"]
    onnx_file = voice_dir / f"{expected_name}.onnx"
    onnx_file.write_bytes(b"fake onnx")

    with patch("courtaccess.speech.tts._get_lang_path_overrides", return_value={"en": str(voice_dir), "es": "", "pt": ""}):
        result = _resolve_voice_path("en")

    assert result == onnx_file


def test_resolve_voice_path_glob_fallback(tmp_path):
    voice_dir = tmp_path / "en"
    voice_dir.mkdir()
    # File with non-standard name (not the exact expected name)
    onnx_file = voice_dir / "alternate_voice.onnx"
    onnx_file.write_bytes(b"fake onnx")

    with patch("courtaccess.speech.tts._get_lang_path_overrides", return_value={"en": str(voice_dir), "es": "", "pt": ""}):
        result = _resolve_voice_path("en")

    assert result == onnx_file


# ══════════════════════════════════════════════════════════════════════════════
# TTSService.synthesize — early-return paths (no real voices loaded)
# ══════════════════════════════════════════════════════════════════════════════


def _make_tts_service() -> TTSService:
    """Build a TTSService with a pre-populated voices dict (no real loading)."""
    svc = object.__new__(TTSService)
    TTSService._voices = {}  # empty — simulates "no voice for this lang"
    return svc


def test_synthesize_empty_text_returns_empty_bytes():
    svc = _make_tts_service()
    assert svc.synthesize("", "en") == b""


def test_synthesize_whitespace_only_returns_empty_bytes():
    svc = _make_tts_service()
    assert svc.synthesize("   \t\n", "en") == b""


def test_synthesize_unsupported_language_returns_empty_bytes():
    svc = _make_tts_service()
    assert svc.synthesize("Hello", "fr") == b""


def test_synthesize_unknown_language_returns_empty_bytes():
    svc = _make_tts_service()
    assert svc.synthesize("Hello", "xx") == b""


def test_synthesize_calls_voice_synthesize_wav():
    """When a voice IS loaded, synthesize_wav should be called."""
    import io
    import wave

    svc = object.__new__(TTSService)

    # Build a real WAV bytes as return value
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(b"\x00\x00" * 100)

    # Mock voice that writes wav bytes when synthesize_wav is called
    def fake_synthesize(text, wav_file, syn_config=None):
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)

    mock_voice = MagicMock()
    mock_voice.synthesize_wav.side_effect = fake_synthesize

    TTSService._voices = {"en": mock_voice}

    result = svc.synthesize("Hello court", "en")
    assert mock_voice.synthesize_wav.called
    assert len(result) > 0


# ══════════════════════════════════════════════════════════════════════════════
# TTSService singleton
# ══════════════════════════════════════════════════════════════════════════════


def test_tts_service_singleton():
    """Two TTSService() calls with mocked _load_voices return the same instance."""
    TTSService._instance = None
    TTSService._voices = None

    with patch.object(TTSService, "_load_voices", lambda self: setattr(TTSService, "_voices", {})):
        svc1 = TTSService()
        svc2 = TTSService()

    assert svc1 is svc2
