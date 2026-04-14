"""
Tests for courtaccess/speech/vad.py

SpeechSegmentDetector is fully testable without any ML model.
VADService requires torch + a real model file, so it is only tested
at the singleton/interface level via mocks.
"""

from courtaccess.speech.vad import SpeechSegmentDetector

# ══════════════════════════════════════════════════════════════════════════════
# SpeechSegmentDetector — __init__
# ══════════════════════════════════════════════════════════════════════════════


def test_init_calculates_silence_chunks_threshold():
    # 500 ms silence / (512/16000 * 1000 ms) = 500 / 32 = ~15 chunks
    detector = SpeechSegmentDetector(silence_threshold_ms=500, sample_rate=16000, chunk_size=512)
    expected = int(500 / (512 / 16000 * 1000))
    assert detector.silence_chunks_threshold == expected


def test_init_default_state_not_speaking():
    detector = SpeechSegmentDetector()
    assert detector.is_speaking is False


def test_init_silent_chunks_zero():
    detector = SpeechSegmentDetector()
    assert detector.silent_chunks == 0


def test_init_total_speech_chunks_zero():
    detector = SpeechSegmentDetector()
    assert detector.total_speech_chunks == 0


def test_init_speech_start_time_none():
    detector = SpeechSegmentDetector()
    assert detector.speech_start_time is None


def test_init_custom_sample_rate():
    detector = SpeechSegmentDetector(silence_threshold_ms=1000, sample_rate=8000, chunk_size=256)
    chunk_ms = (256 / 8000) * 1000  # 32 ms
    expected = int(1000 / chunk_ms)
    assert detector.silence_chunks_threshold == expected


# ══════════════════════════════════════════════════════════════════════════════
# SpeechSegmentDetector — update() state machine
# ══════════════════════════════════════════════════════════════════════════════


def test_update_speech_start_event():
    detector = SpeechSegmentDetector()
    event = detector.update(is_speech=True)
    assert event["type"] == "speech_start"


def test_update_speech_start_sets_is_speaking():
    detector = SpeechSegmentDetector()
    detector.update(is_speech=True)
    assert detector.is_speaking is True


def test_update_speech_start_increments_total_chunks():
    detector = SpeechSegmentDetector()
    detector.update(is_speech=True)
    assert detector.total_speech_chunks == 1


def test_update_continuing_speech_returns_no_event():
    detector = SpeechSegmentDetector()
    detector.update(is_speech=True)  # start
    event = detector.update(is_speech=True)  # continue
    assert event["type"] is None


def test_update_continuing_speech_increments_chunks():
    detector = SpeechSegmentDetector()
    for _ in range(5):
        detector.update(is_speech=True)
    assert detector.total_speech_chunks == 5


def test_update_silence_before_speaking_returns_no_event():
    detector = SpeechSegmentDetector()
    event = detector.update(is_speech=False)
    assert event["type"] is None
    assert detector.is_speaking is False


def test_update_silence_resets_silent_chunks_count_when_not_speaking():
    detector = SpeechSegmentDetector()
    # No speaking yet — silence does nothing to silent_chunks counter
    detector.update(is_speech=False)
    assert detector.silent_chunks == 0


def test_update_silence_increments_silent_chunks_while_speaking():
    detector = SpeechSegmentDetector(silence_threshold_ms=1000, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # start
    detector.update(is_speech=False)  # first silent chunk
    assert detector.silent_chunks == 1


def test_update_speech_end_event_after_silence_threshold():
    # Use very short silence threshold (1 chunk)
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # start (1 chunk = 32 ms)
    event = detector.update(is_speech=False)  # 1 silent chunk = threshold
    assert event["type"] == "speech_end"


def test_update_speech_end_event_contains_duration():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)
    event = detector.update(is_speech=False)
    assert "duration" in event
    assert isinstance(event["duration"], float)


def test_update_speech_end_resets_is_speaking():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)
    detector.update(is_speech=False)
    assert detector.is_speaking is False


def test_update_speech_end_resets_silent_chunks():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)
    detector.update(is_speech=False)
    assert detector.silent_chunks == 0


def test_update_silence_before_threshold_no_end_event():
    # threshold = 2 chunks; only 1 silent chunk → no end event
    detector = SpeechSegmentDetector(silence_threshold_ms=64, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # start
    event = detector.update(is_speech=False)  # 1 silent chunk — threshold is 2
    assert event["type"] is None


def test_update_speech_resumes_after_brief_silence():
    detector = SpeechSegmentDetector(silence_threshold_ms=64, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # start
    detector.update(is_speech=False)  # 1 silent chunk (< threshold of 2)
    event = detector.update(is_speech=True)  # resume speaking
    # Should NOT re-fire speech_start (already speaking)
    assert event["type"] is None


def test_update_speech_start_resets_silent_chunks():
    detector = SpeechSegmentDetector(silence_threshold_ms=64, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # start
    detector.update(is_speech=False)  # 1 silent chunk
    detector.update(is_speech=True)  # resume — should reset silent_chunks
    assert detector.silent_chunks == 0


def test_full_cycle_start_then_end():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    events = []
    events.append(detector.update(is_speech=True))  # speech_start
    events.append(detector.update(is_speech=True))  # continuing
    events.append(detector.update(is_speech=False))  # speech_end (1 chunk = threshold)

    types = [e["type"] for e in events]
    assert types[0] == "speech_start"
    assert types[1] is None
    assert types[2] == "speech_end"


def test_second_utterance_fires_speech_start_again():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)  # 1st utterance starts
    detector.update(is_speech=False)  # 1st utterance ends
    event = detector.update(is_speech=True)  # 2nd utterance
    assert event["type"] == "speech_start"


# ══════════════════════════════════════════════════════════════════════════════
# SpeechSegmentDetector — reset()
# ══════════════════════════════════════════════════════════════════════════════


def test_reset_clears_is_speaking():
    detector = SpeechSegmentDetector()
    detector.update(is_speech=True)
    detector.reset()
    assert detector.is_speaking is False


def test_reset_clears_silent_chunks():
    detector = SpeechSegmentDetector(silence_threshold_ms=64, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)
    detector.update(is_speech=False)
    detector.reset()
    assert detector.silent_chunks == 0


def test_reset_clears_speech_start_time():
    detector = SpeechSegmentDetector()
    detector.update(is_speech=True)
    detector.reset()
    assert detector.speech_start_time is None


def test_reset_clears_total_speech_chunks():
    detector = SpeechSegmentDetector()
    for _ in range(10):
        detector.update(is_speech=True)
    detector.reset()
    assert detector.total_speech_chunks == 0


def test_reset_allows_new_cycle():
    detector = SpeechSegmentDetector(silence_threshold_ms=32, sample_rate=16000, chunk_size=512)
    detector.update(is_speech=True)
    detector.update(is_speech=False)
    detector.reset()
    event = detector.update(is_speech=True)
    assert event["type"] == "speech_start"


# ══════════════════════════════════════════════════════════════════════════════
# VADService — singleton pattern (no model required)
# ══════════════════════════════════════════════════════════════════════════════


def test_vad_service_singleton():
    """Two VADService() calls with a mocked model return the same instance."""
    from unittest.mock import MagicMock, patch

    from courtaccess.speech.vad import VADService

    mock_model = MagicMock()
    with patch.object(VADService, "_load_model", lambda self: setattr(VADService, "_model", mock_model)):
        svc1 = VADService()
        svc2 = VADService()
    assert svc1 is svc2


def test_get_vad_service_returns_vad_service():
    from unittest.mock import MagicMock, patch

    import courtaccess.speech.vad as vad_mod
    from courtaccess.speech.vad import VADService, get_vad_service

    mock_model = MagicMock()
    original = vad_mod._vad_service
    try:
        vad_mod._vad_service = None
        VADService._instance = None
        VADService._model = None
        with patch.object(VADService, "_load_model", lambda self: setattr(VADService, "_model", mock_model)):
            svc = get_vad_service()
        assert isinstance(svc, VADService)
    finally:
        vad_mod._vad_service = original
