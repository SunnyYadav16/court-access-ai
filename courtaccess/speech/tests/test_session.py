"""
Tests for courtaccess/speech/session.py

Tests AudioStreamDecoder buffer logic, ConversationRoom state,
Participant helpers, and _generate_room_id — all without loading
real VAD/ASR models.  AudioSession is tested with a mocked VAD service.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from courtaccess.speech.session import (
    AudioSession,
    AudioStreamDecoder,
    ConversationRoom,
    Participant,
    _generate_room_id,
)

# ── Room code charset (copied from session.py) ────────────────────────────────
_ROOM_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


# ══════════════════════════════════════════════════════════════════════════════
# _generate_room_id
# ══════════════════════════════════════════════════════════════════════════════


def test_generate_room_id_length():
    room_id = _generate_room_id()
    assert len(room_id) == 6


def test_generate_room_id_only_valid_chars():
    for _ in range(20):
        room_id = _generate_room_id()
        for ch in room_id:
            assert ch in _ROOM_CHARS, f"Invalid char '{ch}' in room_id '{room_id}'"


def test_generate_room_id_no_ambiguous_chars():
    for _ in range(50):
        room_id = _generate_room_id()
        for ch in ("O", "0", "I", "1", "L"):
            assert ch not in room_id


def test_generate_room_id_unique():
    ids = {_generate_room_id() for _ in range(100)}
    # With 31^6 = ~887M possibilities, 100 draws should all be unique
    assert len(ids) == 100


def test_generate_room_id_uppercase():
    for _ in range(10):
        room_id = _generate_room_id()
        assert room_id == room_id.upper()


# ══════════════════════════════════════════════════════════════════════════════
# AudioStreamDecoder — initialization & buffer logic
# ══════════════════════════════════════════════════════════════════════════════


def test_decoder_initial_buffer_empty():
    dec = AudioStreamDecoder()
    assert dec.buffer == b""


def test_decoder_initial_not_initialized():
    dec = AudioStreamDecoder()
    assert dec.initialized is False


def test_decoder_initial_samples_returned_zero():
    dec = AudioStreamDecoder()
    assert dec._samples_returned == 0


def test_decoder_target_sample_rate_stored():
    dec = AudioStreamDecoder(target_sample_rate=16000)
    assert dec.target_sample_rate == 16000


def test_decoder_add_chunk_accumulates_buffer_on_invalid_data():
    dec = AudioStreamDecoder()
    dec.add_chunk(b"garbage data")
    # Buffer grows even when decode fails
    assert len(dec.buffer) > 0


def test_decoder_add_chunk_returns_empty_array_on_invalid_data():
    dec = AudioStreamDecoder()
    result = dec.add_chunk(b"not webm data")
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    assert len(result) == 0


def test_decoder_ebml_signature_detection_resets_buffer():
    """When a fresh EBML header arrives and decoder is initialized, buffer resets."""
    _ebml_signature = bytes([0x1A, 0x45, 0xDF, 0xA3])
    dec = AudioStreamDecoder()
    dec.buffer = b"old accumulated data"
    dec.initialized = True
    dec._samples_returned = 999

    dec.add_chunk(_ebml_signature + b"\x00" * 20)

    # Buffer should now only contain the new chunk (EBML data)
    assert b"old accumulated data" not in dec.buffer
    assert dec._samples_returned == 0


def test_decoder_ebml_no_reset_when_not_initialized():
    """EBML header does NOT reset if decoder hasn't initialized yet."""
    _ebml_signature = bytes([0x1A, 0x45, 0xDF, 0xA3])
    dec = AudioStreamDecoder()
    dec.buffer = b"prefix"
    dec.initialized = False

    dec.add_chunk(_ebml_signature + b"\x00" * 20)

    # Buffer should have grown (prefix + new chunk)
    assert b"prefix" in dec.buffer


# ══════════════════════════════════════════════════════════════════════════════
# AudioSession — attributes and basic behaviour (VAD mocked)
# ══════════════════════════════════════════════════════════════════════════════


def _make_audio_session(session_id="test-session", language="en") -> AudioSession:
    """Create an AudioSession with VAD service mocked out.

    get_vad_service and SpeechSegmentDetector are imported locally inside
    AudioSession.__init__, so we patch them at the source module (vad.py).
    """
    mock_vad = MagicMock()
    mock_detector = MagicMock()
    mock_detector.is_speaking = False

    with patch("courtaccess.speech.vad.get_vad_service", return_value=mock_vad), \
         patch("courtaccess.speech.vad.SpeechSegmentDetector", return_value=mock_detector):
        session = AudioSession(session_id, language)
    return session


def test_audio_session_id_stored():
    s = _make_audio_session("sess-001")
    assert s.session_id == "sess-001"


def test_audio_session_language_stored():
    s = _make_audio_session(language="es")
    assert s.language == "es"


def test_audio_session_chunks_start_empty():
    s = _make_audio_session()
    assert s.chunks == []


def test_audio_session_pcm_buffer_empty():
    s = _make_audio_session()
    assert len(s.pcm_buffer) == 0


def test_audio_session_add_chunk_appends():
    s = _make_audio_session()
    s.add_chunk(b"data1")
    s.add_chunk(b"data2")
    assert len(s.chunks) == 2
    assert s.chunks[0] == b"data1"


def test_audio_session_get_webm_data_joins_chunks():
    s = _make_audio_session()
    s.add_chunk(b"part1")
    s.add_chunk(b"part2")
    assert s.get_webm_data() == b"part1part2"


def test_audio_session_get_webm_data_empty_when_no_chunks():
    s = _make_audio_session()
    assert s.get_webm_data() == b""


# ══════════════════════════════════════════════════════════════════════════════
# ConversationRoom
# ══════════════════════════════════════════════════════════════════════════════


def _make_room(room_id="ROOM01", lang_a="en", lang_b="es") -> ConversationRoom:
    return ConversationRoom(room_id, lang_a, lang_b)


def test_room_id_stored():
    room = _make_room("ABCDEF")
    assert room.room_id == "ABCDEF"


def test_room_language_a_stored():
    room = _make_room(lang_a="en")
    assert room.language_a == "en"


def test_room_language_b_stored():
    room = _make_room(lang_b="es")
    assert room.language_b == "es"


def test_room_initially_not_full():
    room = _make_room()
    assert room.is_full is False


def test_room_full_after_two_participants():
    room = _make_room()
    mock_ws = MagicMock()
    mock_session = MagicMock()
    p1 = Participant(mock_ws, "Alice", "en", mock_session, role="a")
    p2 = Participant(mock_ws, "Bob", "es", mock_session, role="b")
    room.add_participant(p1)
    room.add_participant(p2)
    assert room.is_full is True


def test_room_full_after_one_participant_is_false():
    room = _make_room()
    mock_ws = MagicMock()
    p1 = Participant(mock_ws, "Alice", "en", MagicMock(), role="a")
    room.add_participant(p1)
    assert room.is_full is False


def test_room_add_and_remove_participant():
    room = _make_room()
    mock_ws = MagicMock()
    p = Participant(mock_ws, "Alice", "en", MagicMock(), role="a")
    room.add_participant(p)
    assert len(room.participants) == 1
    room.remove_participant(p)
    assert len(room.participants) == 0


def test_room_remove_nonexistent_participant_noop():
    room = _make_room()
    p = Participant(MagicMock(), "Ghost", "en", MagicMock(), role="a")
    room.remove_participant(p)  # should not raise
    assert len(room.participants) == 0


def test_room_get_partner_returns_other():
    room = _make_room()
    mock_ws = MagicMock()
    p1 = Participant(mock_ws, "Alice", "en", MagicMock(), role="a")
    p2 = Participant(mock_ws, "Bob", "es", MagicMock(), role="b")
    room.add_participant(p1)
    room.add_participant(p2)
    assert room.get_partner(p1) is p2
    assert room.get_partner(p2) is p1


def test_room_get_partner_returns_none_when_alone():
    room = _make_room()
    p1 = Participant(MagicMock(), "Alice", "en", MagicMock(), role="a")
    room.add_participant(p1)
    assert room.get_partner(p1) is None


def test_room_initial_participants_empty():
    room = _make_room()
    assert room.participants == []


def test_room_session_not_active_initially():
    room = _make_room()
    assert room.session_active is False


def test_room_db_session_id_none_initially():
    room = _make_room()
    assert room.db_session_id is None


# ══════════════════════════════════════════════════════════════════════════════
# Participant
# ══════════════════════════════════════════════════════════════════════════════


def test_participant_stores_name():
    p = Participant(MagicMock(), "Alice", "en", MagicMock(), role="a")
    assert p.name == "Alice"


def test_participant_stores_language():
    p = Participant(MagicMock(), "Bob", "es", MagicMock(), role="b")
    assert p.language == "es"


def test_participant_stores_role():
    p = Participant(MagicMock(), "Alice", "en", MagicMock(), role="a")
    assert p.role == "a"


def test_participant_ws_open_initially_true():
    p = Participant(MagicMock(), "Alice", "en", MagicMock())
    assert p.ws_open is True


def test_participant_default_role_is_a():
    p = Participant(MagicMock(), "Alice", "en", MagicMock())
    assert p.role == "a"


@pytest.mark.asyncio
async def test_participant_send_json_safe_closes_on_error():
    mock_ws = MagicMock()
    mock_ws.send_json.side_effect = Exception("socket closed")
    p = Participant(mock_ws, "Alice", "en", MagicMock())
    await p.send_json_safe({"type": "test"})
    assert p.ws_open is False


@pytest.mark.asyncio
async def test_participant_send_bytes_safe_closes_on_error():
    mock_ws = MagicMock()
    mock_ws.send_bytes.side_effect = Exception("socket closed")
    p = Participant(mock_ws, "Alice", "en", MagicMock())
    await p.send_bytes_safe(b"audio data")
    assert p.ws_open is False


@pytest.mark.asyncio
async def test_participant_send_json_noop_when_closed():
    mock_ws = MagicMock()
    p = Participant(mock_ws, "Alice", "en", MagicMock())
    p.ws_open = False
    await p.send_json_safe({"msg": "hello"})
    mock_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_participant_send_bytes_noop_when_closed():
    mock_ws = MagicMock()
    p = Participant(mock_ws, "Alice", "en", MagicMock())
    p.ws_open = False
    await p.send_bytes_safe(b"data")
    mock_ws.send_bytes.assert_not_called()
