"""
Tests for courtaccess/speech/session_recorder.py

SessionRecorder and TranscriptLogger are pure numpy/wave operations —
fully testable without any ML model or network access.
write_manifest and _sha256_file are also pure filesystem operations.
"""

import hashlib
import io
import json
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from courtaccess.speech.session_recorder import (
    SessionRecorder,
    TranscriptLogger,
    _sha256_file,
    write_manifest,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_wav_bytes(
    sample_rate: int = 16000,
    n_samples: int = 1600,
    sample_width: int = 2,
) -> bytes:
    """Create a minimal valid WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        samples = np.zeros(n_samples, dtype=np.int16).tobytes()
        wf.writeframes(samples)
    return buf.getvalue()


def _make_pcm(n_samples: int = 1600, value: float = 0.5) -> np.ndarray:
    """Create a float32 PCM array at *value*."""
    return np.full(n_samples, value, dtype=np.float32)


# ══════════════════════════════════════════════════════════════════════════════
# SessionRecorder._resample_if_needed
# ══════════════════════════════════════════════════════════════════════════════


def test_resample_passthrough_same_rate():
    pcm = _make_pcm(100)
    result = SessionRecorder._resample_if_needed(pcm, source_sr=16000)
    assert len(result) == 100
    np.testing.assert_array_equal(result, pcm)


def test_resample_downsample_48k_to_16k():
    pcm = _make_pcm(4800)  # 0.1 s at 48 kHz
    result = SessionRecorder._resample_if_needed(pcm, source_sr=48000)
    expected_len = int(4800 * 16000 / 48000)  # 1600
    assert len(result) == expected_len


def test_resample_upsample():
    pcm = _make_pcm(800)  # 0.1 s at 8 kHz
    result = SessionRecorder._resample_if_needed(pcm, source_sr=8000)
    expected_len = int(800 * 16000 / 8000)  # 1600
    assert len(result) == expected_len


def test_resample_empty_array_returns_empty():
    pcm = np.array([], dtype=np.float32)
    result = SessionRecorder._resample_if_needed(pcm, source_sr=48000)
    assert len(result) == 0


def test_resample_output_dtype_float32():
    pcm = _make_pcm(4800)
    result = SessionRecorder._resample_if_needed(pcm, source_sr=48000)
    assert result.dtype == np.float32


# ══════════════════════════════════════════════════════════════════════════════
# SessionRecorder._float32_to_int16_bytes
# ══════════════════════════════════════════════════════════════════════════════


def test_float32_to_int16_zero():
    pcm = np.zeros(4, dtype=np.float32)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    assert result == b"\x00\x00" * 4


def test_float32_to_int16_max_value():
    pcm = np.array([1.0], dtype=np.float32)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    value = int.from_bytes(result, byteorder="little", signed=True)
    assert value == 32767


def test_float32_to_int16_min_value():
    pcm = np.array([-1.0], dtype=np.float32)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    value = int.from_bytes(result, byteorder="little", signed=True)
    assert value == -32767


def test_float32_to_int16_clipping_above():
    pcm = np.array([2.0], dtype=np.float32)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    value = int.from_bytes(result, byteorder="little", signed=True)
    assert value == 32767


def test_float32_to_int16_clipping_below():
    pcm = np.array([-2.0], dtype=np.float32)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    value = int.from_bytes(result, byteorder="little", signed=True)
    assert value == -32767


def test_float32_to_int16_bytes_length():
    pcm = _make_pcm(100)
    result = SessionRecorder._float32_to_int16_bytes(pcm)
    assert len(result) == 100 * 2  # 2 bytes per int16 sample


# ══════════════════════════════════════════════════════════════════════════════
# SessionRecorder.add_speech_pcm
# ══════════════════════════════════════════════════════════════════════════════


def test_add_speech_pcm_appends_to_role_track():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(1600)
    rec.add_speech_pcm("a", pcm)
    assert len(rec._tracks["a"]) == 1


def test_add_speech_pcm_pads_other_track():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(1600)
    rec.add_speech_pcm("a", pcm)
    assert len(rec._tracks["b"]) == 1  # silence padding added


def test_add_speech_pcm_silence_bytes_equal_in_length():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(1600)
    rec.add_speech_pcm("a", pcm)
    speech_len = len(b"".join(rec._tracks["a"]))
    silence_len = len(b"".join(rec._tracks["b"]))
    assert speech_len == silence_len


def test_add_speech_pcm_updates_sample_count():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(1600)
    rec.add_speech_pcm("a", pcm)
    assert rec._sample_counts["a"] == 1600
    assert rec._sample_counts["b"] == 1600


def test_add_speech_pcm_role_b():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(800)
    rec.add_speech_pcm("b", pcm)
    assert len(rec._tracks["b"]) == 1
    assert len(rec._tracks["a"]) == 1


def test_add_speech_pcm_resamples_48k():
    rec = SessionRecorder("s1", "en", "es")
    pcm = _make_pcm(4800)  # 48 kHz
    rec.add_speech_pcm("a", pcm, source_sample_rate=48000)
    # After resampling to 16 kHz: 4800 * (16000/48000) = 1600 samples
    assert rec._sample_counts["a"] == 1600


# ══════════════════════════════════════════════════════════════════════════════
# SessionRecorder.add_tts_pcm
# ══════════════════════════════════════════════════════════════════════════════


def test_add_tts_pcm_parses_wav():
    rec = SessionRecorder("s1", "en", "es")
    wav = _make_wav_bytes(sample_rate=16000, n_samples=1600)
    rec.add_tts_pcm("b", wav)
    assert len(rec._tracks["b"]) == 1


def test_add_tts_pcm_pads_other_track():
    rec = SessionRecorder("s1", "en", "es")
    wav = _make_wav_bytes(sample_rate=16000, n_samples=1600)
    rec.add_tts_pcm("b", wav)
    assert len(rec._tracks["a"]) == 1


def test_add_tts_pcm_empty_bytes_noop():
    rec = SessionRecorder("s1", "en", "es")
    rec.add_tts_pcm("b", b"")
    assert len(rec._tracks["b"]) == 0


def test_add_tts_pcm_invalid_wav_graceful():
    rec = SessionRecorder("s1", "en", "es")
    rec.add_tts_pcm("b", b"not a wav")  # should not raise
    assert len(rec._tracks["b"]) == 0


# ══════════════════════════════════════════════════════════════════════════════
# SessionRecorder.finalize
# ══════════════════════════════════════════════════════════════════════════════


def test_finalize_creates_wav_files(tmp_path):
    rec = SessionRecorder("session1", "en", "es")
    pcm = _make_pcm(1600)
    rec.add_speech_pcm("a", pcm)
    paths = rec.finalize(output_dir=tmp_path)
    assert "a" in paths
    assert "b" in paths
    assert paths["a"].exists()
    assert paths["b"].exists()


def test_finalize_wav_filenames(tmp_path):
    rec = SessionRecorder("mysession", "en", "es")
    rec.add_speech_pcm("a", _make_pcm(160))
    paths = rec.finalize(output_dir=tmp_path)
    assert paths["a"].name == "mysession_a_en.wav"
    assert paths["b"].name == "mysession_b_es.wav"


def test_finalize_wav_is_valid(tmp_path):
    rec = SessionRecorder("s1", "en", "es")
    rec.add_speech_pcm("a", _make_pcm(1600))
    paths = rec.finalize(output_dir=tmp_path)
    with wave.open(str(paths["a"]), "rb") as wf:
        assert wf.getsampwidth() == 2
        assert wf.getnchannels() == 1


def test_finalize_empty_tracks_still_creates_files(tmp_path):
    rec = SessionRecorder("empty", "en", "es")
    paths = rec.finalize(output_dir=tmp_path)
    assert paths["a"].exists()
    assert paths["b"].exists()


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptLogger — add_entry / accessors
# ══════════════════════════════════════════════════════════════════════════════


def test_add_entry_increments_count():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="a", original_text="Hello", source_lang="en", target_lang="es")
    assert log.entry_count == 1


def test_add_entry_turn_index_increments():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="a", original_text="Hi", source_lang="en", target_lang="es")
    log.add_entry(speaker_role="b", original_text="Hola", source_lang="es", target_lang="en")
    assert log.utterances[0]["turn_index"] == 0
    assert log.utterances[1]["turn_index"] == 1


def test_add_entry_stores_all_fields():
    log = TranscriptLogger("s1", "en", "es")
    ts = datetime.now(tz=UTC)
    log.add_entry(
        speaker_role="a",
        original_text="Objection",
        source_lang="en",
        target_lang="es",
        translated_text="Objeción",
        spoken_at=ts,
        asr_confidence=0.95,
        nllb_confidence=0.88,
        legal_verified=True,
        legal_correction_applied=False,
    )
    utt = log.utterances[0]
    assert utt["speaker_role"] == "a"
    assert utt["original_text"] == "Objection"
    assert utt["translated_text"] == "Objeción"
    assert utt["spoken_at"] == ts
    assert utt["asr_confidence"] == 0.95
    assert utt["nllb_confidence"] == 0.88
    assert utt["legal_verified"] is True
    assert utt["legal_correction_applied"] is False


def test_add_entry_defaults_optional_fields():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="b", original_text="No", source_lang="es", target_lang="en")
    utt = log.utterances[0]
    assert utt["translated_text"] is None
    assert utt["asr_confidence"] is None
    assert utt["nllb_confidence"] is None
    assert utt["legal_verified"] is False
    assert utt["legal_correction_applied"] is False


def test_entry_count_starts_at_zero():
    log = TranscriptLogger("s1", "en", "es")
    assert log.entry_count == 0


def test_utterances_returns_list():
    log = TranscriptLogger("s1", "en", "es")
    assert isinstance(log.utterances, list)


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptLogger.format_text
# ══════════════════════════════════════════════════════════════════════════════


def test_format_text_contains_session_header():
    log = TranscriptLogger("mysession", "en", "es", name_a="Alice", name_b="Bob")
    text = log.format_text()
    assert "SESSION TRANSCRIPT" in text
    assert "mysession" in text


def test_format_text_contains_participant_names():
    log = TranscriptLogger("s1", "en", "es", name_a="Alice", name_b="Bob")
    text = log.format_text()
    assert "Alice" in text
    assert "Bob" in text


def test_format_text_contains_entry():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="a", original_text="Hello court", source_lang="en", target_lang="es")
    text = log.format_text()
    assert "Hello court" in text


def test_format_text_contains_translation():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(
        speaker_role="a",
        original_text="Hello",
        source_lang="en",
        target_lang="es",
        translated_text="Hola",
    )
    text = log.format_text()
    assert "Hola" in text


def test_format_text_empty_log_no_crash():
    log = TranscriptLogger("s1", "en", "es")
    text = log.format_text()
    assert "SESSION TRANSCRIPT" in text
    assert "0" in text  # zero entries


def test_format_text_shows_asr_confidence():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(
        speaker_role="a", original_text="Test", source_lang="en", target_lang="es",
        asr_confidence=0.92,
    )
    text = log.format_text()
    assert "ASR=0.92" in text


def test_format_text_shows_legal_verified_flag():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(
        speaker_role="a", original_text="Test", source_lang="en", target_lang="es",
        legal_verified=True,
    )
    text = log.format_text()
    assert "verified" in text


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptLogger.serialize
# ══════════════════════════════════════════════════════════════════════════════


def test_serialize_returns_dict():
    log = TranscriptLogger("s1", "en", "es")
    result = log.serialize(session_id="uuid-1")
    assert isinstance(result, dict)


def test_serialize_contains_session_metadata():
    log = TranscriptLogger("s1", "en", "es", name_a="Alice", name_b="Bob")
    result = log.serialize(session_id="uuid-1")
    assert result["session_id"] == "uuid-1"
    assert result["session_name"] == "s1"
    assert result["language_a"] == "en"
    assert result["language_b"] == "es"
    assert result["name_a"] == "Alice"
    assert result["name_b"] == "Bob"


def test_serialize_total_utterances():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="a", original_text="Hi", source_lang="en", target_lang="es")
    log.add_entry(speaker_role="b", original_text="Hola", source_lang="es", target_lang="en")
    result = log.serialize(session_id="uuid-2")
    assert result["total_utterances"] == 2


def test_serialize_duration_seconds():
    log = TranscriptLogger("s1", "en", "es")
    start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)
    result = log.serialize(session_id="u1", start_time=start, end_time=end)
    assert result["duration_seconds"] == 300.0


def test_serialize_spoken_at_is_iso_string():
    log = TranscriptLogger("s1", "en", "es")
    ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)
    log.add_entry(
        speaker_role="a", original_text="Test", source_lang="en", target_lang="es",
        spoken_at=ts,
    )
    result = log.serialize(session_id="u1")
    spoken_at = result["utterances"][0]["spoken_at"]
    assert isinstance(spoken_at, str)
    # Should parse back without error
    datetime.fromisoformat(spoken_at)


def test_serialize_json_serializable():
    log = TranscriptLogger("s1", "en", "es")
    log.add_entry(speaker_role="a", original_text="Test", source_lang="en", target_lang="es")
    result = log.serialize(session_id="u1")
    # Should not raise
    json.dumps(result)


# ══════════════════════════════════════════════════════════════════════════════
# TranscriptLogger.finalize
# ══════════════════════════════════════════════════════════════════════════════


def test_finalize_writes_text_file(tmp_path):
    log = TranscriptLogger("mysession", "en", "es")
    log.add_entry(speaker_role="a", original_text="Hello", source_lang="en", target_lang="es")
    path = log.finalize(output_dir=tmp_path)
    assert path.exists()
    assert path.suffix == ".txt"


def test_finalize_filename_convention(tmp_path):
    log = TranscriptLogger("mysession", "en", "es")
    path = log.finalize(output_dir=tmp_path)
    assert path.name == "mysession_transcript.txt"


def test_finalize_file_contains_session_header(tmp_path):
    log = TranscriptLogger("mysession", "en", "es")
    path = log.finalize(output_dir=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert "SESSION TRANSCRIPT" in content


# ══════════════════════════════════════════════════════════════════════════════
# _sha256_file
# ══════════════════════════════════════════════════════════════════════════════


def test_sha256_file_matches_hashlib(tmp_path):
    data = b"test data for hashing"
    f = tmp_path / "file.bin"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert _sha256_file(f) == expected


def test_sha256_file_empty_file(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    result = _sha256_file(f)
    assert len(result) == 64


def test_sha256_file_different_contents_differ(tmp_path):
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"aaa")
    f2.write_bytes(b"bbb")
    assert _sha256_file(f1) != _sha256_file(f2)


# ══════════════════════════════════════════════════════════════════════════════
# write_manifest
# ══════════════════════════════════════════════════════════════════════════════


def test_write_manifest_creates_json_file(tmp_path):
    start = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 5, 0, tzinfo=UTC)
    path = write_manifest(
        tmp_path, "sess1",
        start_time=start, end_time=end,
        language_a="en", language_b="es",
        name_a="Alice", name_b="Bob",
        room_id="ABCDEF",
    )
    assert path.exists()
    assert path.suffix == ".json"


def test_write_manifest_valid_json(tmp_path):
    start = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 12, 1, tzinfo=UTC)
    path = write_manifest(
        tmp_path, "sess1",
        start_time=start, end_time=end,
        language_a="en", language_b="es",
        name_a="A", name_b="B",
        room_id="ABCDEF",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["session_name"] == "sess1"
    assert data["room_id"] == "ABCDEF"
    assert data["duration_seconds"] == 60.0


def test_write_manifest_includes_file_hashes(tmp_path):
    # Create a dummy artifact file
    artifact = tmp_path / "sess1_a_en.wav"
    artifact.write_bytes(b"fake wav data")

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 1, tzinfo=UTC)
    path = write_manifest(
        tmp_path, "sess1",
        start_time=start, end_time=end,
        language_a="en", language_b="es",
        name_a="A", name_b="B",
        room_id="XYZ",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["files"]) >= 1
    assert "sha256" in data["files"][0]
    assert "size_bytes" in data["files"][0]


def test_write_manifest_participants_metadata(tmp_path):
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 1, tzinfo=UTC)
    path = write_manifest(
        tmp_path, "sess1",
        start_time=start, end_time=end,
        language_a="en", language_b="pt",
        name_a="Judge", name_b="Respondent",
        room_id="ROOM1",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["participants"]["a"]["name"] == "Judge"
    assert data["participants"]["b"]["language"] == "pt"
