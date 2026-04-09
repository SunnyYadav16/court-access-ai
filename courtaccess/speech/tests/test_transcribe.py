"""
Tests for courtaccess/speech/transcribe.py — ASRService and get_asr_service.

Coverage:
  - Singleton (__new__ / _instance)
  - __init__ gating on _model
  - _load_model: device/compute_type selection, model path vs size, side-effects
  - model property (returns model / AssertionError when None)
  - transcribe: empty input, input normalisation, model call params,
                segment joining, language resolution
  - get_asr_service factory + caching
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_segment(text: str) -> MagicMock:
    seg = MagicMock()
    seg.text = text
    return seg


def _info_with_language(language: str | None) -> MagicMock:
    info = MagicMock()
    info.language = language
    return info


def _info_without_language_attr() -> MagicMock:
    """MagicMock with no 'language' attribute (spec=[])."""
    return MagicMock(spec=[])


# ── autouse fixture: clean singleton state between every test ─────────────────


@pytest.fixture(autouse=True)
def reset_asr_singleton():
    """Restore ASRService singleton and module-level _asr_service after each test."""
    from courtaccess.speech import transcribe as transcribe_mod
    from courtaccess.speech.transcribe import ASRService

    orig_instance = ASRService._instance
    orig_model = ASRService._model
    orig_global = transcribe_mod._asr_service

    ASRService._instance = None
    ASRService._model = None
    transcribe_mod._asr_service = None

    yield

    ASRService._instance = orig_instance
    ASRService._model = orig_model
    transcribe_mod._asr_service = orig_global


# ── helper: bare ASRService instance without calling __init__ ─────────────────


def _bare_svc():
    from courtaccess.speech.transcribe import ASRService

    svc = object.__new__(ASRService)
    fake_model = MagicMock()
    ASRService._model = fake_model
    return svc


# ══════════════════════════════════════════════════════════════════════════════
# Singleton — __new__ / __init__
# ══════════════════════════════════════════════════════════════════════════════


class TestASRServiceSingleton:
    def test_same_instance_returned_on_repeated_construction(self):
        from courtaccess.speech.transcribe import ASRService

        with patch.object(ASRService, "_load_model"):
            a = ASRService()
            b = ASRService()

        assert a is b

    def test_instance_stored_on_class(self):
        from courtaccess.speech.transcribe import ASRService

        with patch.object(ASRService, "_load_model"):
            svc = ASRService()

        assert ASRService._instance is svc

    def test_init_calls_load_model_when_model_none(self):
        from courtaccess.speech.transcribe import ASRService

        with patch.object(ASRService, "_load_model") as mock_load:
            ASRService()

        mock_load.assert_called_once()

    def test_init_skips_load_model_when_model_already_set(self):
        from courtaccess.speech.transcribe import ASRService

        ASRService._model = MagicMock()
        with patch.object(ASRService, "_load_model") as mock_load:
            ASRService()

        mock_load.assert_not_called()

    def test_new_instance_not_created_when_instance_exists(self):
        from courtaccess.speech.transcribe import ASRService

        with patch.object(ASRService, "_load_model"):
            first = ASRService()
            ASRService._model = MagicMock()  # simulate already-loaded model
            second = ASRService()

        assert first is second


# ══════════════════════════════════════════════════════════════════════════════
# model property
# ══════════════════════════════════════════════════════════════════════════════


class TestModelProperty:
    def test_returns_model_when_set(self):
        from courtaccess.speech.transcribe import ASRService

        fake_model = MagicMock()
        ASRService._model = fake_model
        svc = object.__new__(ASRService)

        assert svc.model is fake_model

    def test_raises_assertion_error_when_model_none(self):
        from courtaccess.speech.transcribe import ASRService

        ASRService._model = None
        svc = object.__new__(ASRService)

        with pytest.raises(AssertionError, match="not loaded"):
            _ = svc.model


# ══════════════════════════════════════════════════════════════════════════════
# _load_model
# ══════════════════════════════════════════════════════════════════════════════


def _mock_settings(model_path: str | None = "", model: str = "small") -> MagicMock:
    s = MagicMock()
    s.whisper_model_path = model_path
    s.whisper_model = model
    return s


def _patched_load_model(svc, *, cuda: bool, model_path=None, model_size="small"):
    """Run _load_model with torch and faster_whisper stubbed out."""

    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = cuda

    mock_whisper_cls = MagicMock()
    mock_whisper_instance = MagicMock()
    mock_whisper_cls.return_value = mock_whisper_instance

    mock_fw_module = MagicMock()
    mock_fw_module.WhisperModel = mock_whisper_cls

    settings = _mock_settings(model_path=model_path, model=model_size)

    with (
        patch.dict("sys.modules", {"torch": mock_torch, "faster_whisper": mock_fw_module}),
        patch("courtaccess.speech.transcribe.get_settings", return_value=settings),
    ):
        svc._load_model()

    return mock_whisper_cls, mock_whisper_instance


class TestLoadModel:
    def test_uses_cpu_and_int8_when_no_cuda(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        mock_cls, _ = _patched_load_model(svc, cuda=False, model_size="small")

        mock_cls.assert_called_once_with("small", device="cpu", compute_type="int8")

    def test_uses_cuda_and_int8_float16_when_cuda_available(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        mock_cls, _ = _patched_load_model(svc, cuda=True, model_size="small")

        mock_cls.assert_called_once_with("small", device="cuda", compute_type="int8_float16")

    def test_uses_model_path_when_set(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        mock_cls, _ = _patched_load_model(svc, cuda=False, model_path="/weights/whisper.bin", model_size="small")

        mock_cls.assert_called_once_with("/weights/whisper.bin", device="cpu", compute_type="int8")

    def test_falls_back_to_model_size_when_path_empty_string(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        mock_cls, _ = _patched_load_model(svc, cuda=False, model_path="", model_size="medium")

        mock_cls.assert_called_once_with("medium", device="cpu", compute_type="int8")

    def test_falls_back_to_model_size_when_path_is_none(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        mock_cls, _ = _patched_load_model(svc, cuda=False, model_path=None, model_size="large-v3-turbo")

        mock_cls.assert_called_once_with("large-v3-turbo", device="cpu", compute_type="int8")

    def test_sets_class_model_after_loading(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        _, mock_instance = _patched_load_model(svc, cuda=False)

        assert ASRService._model is mock_instance

    def test_model_none_before_load_set_after(self):
        from courtaccess.speech.transcribe import ASRService

        svc = object.__new__(ASRService)
        assert ASRService._model is None

        _patched_load_model(svc, cuda=False)

        assert ASRService._model is not None


# ══════════════════════════════════════════════════════════════════════════════
# transcribe — empty / trivial input
# ══════════════════════════════════════════════════════════════════════════════


class TestTranscribeEmptyInput:
    def test_empty_array_returns_empty_string_preserving_language(self):
        svc = _bare_svc()
        text, lang = svc.transcribe(np.array([]), language="en")
        assert text == ""
        assert lang == "en"

    def test_empty_array_with_none_language_returns_none(self):
        svc = _bare_svc()
        text, lang = svc.transcribe(np.array([]), language=None)
        assert text == ""
        assert lang is None

    def test_empty_array_does_not_call_model(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        svc.transcribe(np.array([]))
        ASRService._model.transcribe.assert_not_called()

    def test_size_zero_2d_array_returns_early(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        svc.transcribe(np.zeros((0, 1), dtype=np.float32))
        ASRService._model.transcribe.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# transcribe — input normalisation
# ══════════════════════════════════════════════════════════════════════════════


class TestTranscribeInputNormalisation:
    def _setup_model_return(self, language="en"):
        from courtaccess.speech.transcribe import ASRService

        info = _info_with_language(language)
        ASRService._model.transcribe.return_value = (iter([]), info)

    def test_non_float32_ndarray_converted_to_float32(self):
        """The isinstance guard runs only for ndarray inputs (lists fail at .size)."""
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        self._setup_model_return()
        # Pass a boolean array — isinstance check passes, then astype kicks in
        svc.transcribe(np.ones(3, dtype=bool), language="en")

        passed = ASRService._model.transcribe.call_args[0][0]
        assert isinstance(passed, np.ndarray)
        assert passed.dtype == np.float32

    def test_int16_array_cast_to_float32(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        self._setup_model_return()
        svc.transcribe(np.array([100, 200, 300], dtype=np.int16), language="en")

        passed = ASRService._model.transcribe.call_args[0][0]
        assert passed.dtype == np.float32

    def test_float64_array_cast_to_float32(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        self._setup_model_return()
        svc.transcribe(np.array([0.1, 0.2], dtype=np.float64), language="en")

        passed = ASRService._model.transcribe.call_args[0][0]
        assert passed.dtype == np.float32

    def test_2d_array_flattened_to_1d(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        self._setup_model_return()
        svc.transcribe(np.zeros((2, 80), dtype=np.float32), language="en")

        passed = ASRService._model.transcribe.call_args[0][0]
        assert passed.ndim == 1
        assert passed.size == 160

    def test_already_float32_1d_passed_unchanged_dtype(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        self._setup_model_return()
        pcm = np.linspace(-1.0, 1.0, 160, dtype=np.float32)
        svc.transcribe(pcm, language="en")

        passed = ASRService._model.transcribe.call_args[0][0]
        assert passed.dtype == np.float32
        assert passed.ndim == 1


# ══════════════════════════════════════════════════════════════════════════════
# transcribe — model call parameters
# ══════════════════════════════════════════════════════════════════════════════


class TestTranscribeModelCallParams:
    def _run(self, language="en"):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        info = _info_with_language(language)
        ASRService._model.transcribe.return_value = (iter([]), info)
        pcm = np.zeros(160, dtype=np.float32)
        svc.transcribe(pcm, language=language)
        return ASRService._model.transcribe.call_args

    def test_task_is_transcribe(self):
        _, kwargs = self._run()
        assert kwargs["task"] == "transcribe"

    def test_beam_size_is_3(self):
        _, kwargs = self._run()
        assert kwargs["beam_size"] == 3

    def test_language_forwarded_to_model(self):
        _, kwargs = self._run(language="pt")
        assert kwargs["language"] == "pt"

    def test_none_language_forwarded_to_model(self):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        info = _info_without_language_attr()
        ASRService._model.transcribe.return_value = (iter([]), info)
        svc.transcribe(np.zeros(160, dtype=np.float32), language=None)

        _, kwargs = ASRService._model.transcribe.call_args
        assert kwargs["language"] is None


# ══════════════════════════════════════════════════════════════════════════════
# transcribe — segment joining
# ══════════════════════════════════════════════════════════════════════════════


class TestTranscribeSegmentJoining:
    def _transcribe(self, segments, language="en"):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        info = _info_with_language(language)
        ASRService._model.transcribe.return_value = (iter(segments), info)
        text, _ = svc.transcribe(np.zeros(160, dtype=np.float32), language=language)
        return text

    def test_no_segments_returns_empty_string(self):
        assert self._transcribe([]) == ""

    def test_single_segment_returned_as_is(self):
        assert self._transcribe([_make_segment("Hello world")]) == "Hello world"

    def test_multiple_segments_joined_with_space(self):
        segs = [_make_segment("The defendant"), _make_segment("entered a plea")]
        assert self._transcribe(segs) == "The defendant entered a plea"

    def test_three_segments_joined(self):
        segs = [_make_segment("Objection"), _make_segment("your"), _make_segment("Honor")]
        assert self._transcribe(segs) == "Objection your Honor"

    def test_segment_whitespace_stripped_before_joining(self):
        segs = [_make_segment("  Hello  "), _make_segment("  world  ")]
        assert self._transcribe(segs) == "Hello world"

    def test_empty_segment_texts_filtered_out(self):
        segs = [_make_segment(""), _make_segment("Hello"), _make_segment("")]
        assert self._transcribe(segs) == "Hello"

    def test_whitespace_only_segments_filtered_out(self):
        segs = [_make_segment("   "), _make_segment("Plea"), _make_segment("\t\n")]
        assert self._transcribe(segs) == "Plea"

    def test_all_empty_segments_returns_empty_string(self):
        segs = [_make_segment(""), _make_segment("  "), _make_segment("\n")]
        assert self._transcribe(segs) == ""

    def test_final_text_has_no_leading_or_trailing_whitespace(self):
        # Even if join produces a string with surrounding spaces somehow
        segs = [_make_segment("  Hello  ")]
        text = self._transcribe(segs)
        assert text == text.strip()

    def test_mixed_empty_and_nonempty_segments(self):
        segs = [
            _make_segment(""),
            _make_segment("The"),
            _make_segment("   "),
            _make_segment("court"),
            _make_segment(""),
        ]
        assert self._transcribe(segs) == "The court"


# ══════════════════════════════════════════════════════════════════════════════
# transcribe — language resolution
# ══════════════════════════════════════════════════════════════════════════════


class TestTranscribeLanguageResolution:
    def _transcribe_lang(self, info, *, language="en"):
        from courtaccess.speech.transcribe import ASRService

        svc = _bare_svc()
        ASRService._model.transcribe.return_value = (iter([]), info)
        _, used_lang = svc.transcribe(np.zeros(160, dtype=np.float32), language=language)
        return used_lang

    def test_uses_info_language_when_available(self):
        info = _info_with_language("es")
        assert self._transcribe_lang(info, language="en") == "es"

    def test_info_language_overrides_passed_language(self):
        info = _info_with_language("pt")
        assert self._transcribe_lang(info, language="en") == "pt"

    def test_falls_back_to_passed_language_when_info_language_none(self):
        info = _info_with_language(None)  # info.language is None (falsy)
        assert self._transcribe_lang(info, language="pt") == "pt"

    def test_falls_back_to_passed_language_when_info_has_no_language_attr(self):
        info = _info_without_language_attr()
        assert self._transcribe_lang(info, language="pt") == "pt"

    def test_falls_back_to_passed_language_when_info_language_empty_string(self):
        info = _info_with_language("")  # empty string is falsy
        assert self._transcribe_lang(info, language="en") == "en"

    def test_returns_none_when_language_none_and_no_info_language(self):
        info = _info_without_language_attr()
        assert self._transcribe_lang(info, language=None) is None

    def test_returns_detected_language_when_language_none_and_info_has_language(self):
        info = _info_with_language("en")
        assert self._transcribe_lang(info, language=None) == "en"

    def test_language_detection_works_for_spanish(self):
        info = _info_with_language("es")
        assert self._transcribe_lang(info, language=None) == "es"

    def test_language_detection_works_for_portuguese(self):
        info = _info_with_language("pt")
        assert self._transcribe_lang(info, language=None) == "pt"


# ══════════════════════════════════════════════════════════════════════════════
# get_asr_service factory
# ══════════════════════════════════════════════════════════════════════════════


class TestGetAsrService:
    def test_returns_asr_service_instance(self):
        from courtaccess.speech.transcribe import ASRService, get_asr_service

        with patch.object(ASRService, "_load_model"):
            svc = get_asr_service()

        assert isinstance(svc, ASRService)

    def test_caches_instance_in_module_global(self):
        from courtaccess.speech import transcribe as transcribe_mod
        from courtaccess.speech.transcribe import ASRService, get_asr_service

        with patch.object(ASRService, "_load_model"):
            svc = get_asr_service()

        assert transcribe_mod._asr_service is svc

    def test_returns_same_instance_on_repeated_calls(self):
        from courtaccess.speech.transcribe import ASRService, get_asr_service

        with patch.object(ASRService, "_load_model"):
            first = get_asr_service()
            # model is now loaded (mocked), subsequent calls won't re-load
            ASRService._model = MagicMock()
            second = get_asr_service()
            third = get_asr_service()

        assert first is second
        assert second is third

    def test_load_model_called_only_once_across_repeated_gets(self):
        from courtaccess.speech.transcribe import ASRService, get_asr_service

        with patch.object(ASRService, "_load_model") as mock_load:
            get_asr_service()
            # Simulate model being set so second call doesn't re-trigger
            ASRService._model = MagicMock()
            get_asr_service()
            get_asr_service()

        assert mock_load.call_count == 1

    def test_new_instance_after_global_cleared(self):
        from courtaccess.speech import transcribe as transcribe_mod
        from courtaccess.speech.transcribe import ASRService, get_asr_service

        with patch.object(ASRService, "_load_model"):
            first = get_asr_service()

        # Manually reset everything (simulating process restart or test isolation)
        transcribe_mod._asr_service = None
        ASRService._instance = None
        ASRService._model = None

        with patch.object(ASRService, "_load_model"):
            second = get_asr_service()

        assert second is not first
        assert isinstance(second, ASRService)
