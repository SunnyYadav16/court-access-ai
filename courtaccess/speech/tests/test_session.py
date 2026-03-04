"""
courtaccess/speech/tests/test_session.py

Unit tests for courtaccess.speech.session.
Mocks all pipeline stages (VAD, ASR, translation, TTS, legal review)
to test orchestration logic only — not model inference.
"""

from unittest.mock import patch

import pytest

from courtaccess.speech.session import Participant, ParticipantRole, RealtimeSession


@pytest.fixture
def session():
    return RealtimeSession(session_id="test-session-001", target_language="spa_Latn")


@pytest.fixture
def creator(session):
    p = Participant(participant_id="user-1", role=ParticipantRole.CREATOR)
    session.add_participant(p)
    return p


def test_session_created(session):
    assert session.state.session_id == "test-session-001"
    assert session.state.active is True
    assert session.state.target_language == "spa_Latn"


def test_add_participant(session, creator):
    assert "user-1" in session.state.participants
    assert session.state.participants["user-1"].role == ParticipantRole.CREATOR


def test_participant_priority_ordering():
    p_creator = Participant(role=ParticipantRole.CREATOR)
    p_public = Participant(role=ParticipantRole.PUBLIC)
    assert p_creator.priority < p_public.priority


@pytest.mark.asyncio
async def test_process_audio_chunk_stub(session, creator):
    """Full pipeline runs with all stubs active — no model loading."""
    fake_audio = b"\x00\x01" * 8000  # 0.5s of 16kHz 16-bit audio

    result = await session.process_audio_chunk(fake_audio, "user-1")

    assert "transcript" in result
    assert "translation" in result
    assert "audio_bytes" in result
    assert "confidence" in result
    assert "legal_review" in result


@pytest.mark.asyncio
async def test_process_audio_chunk_no_participant(session):
    """Audio from unknown participant uses session default language."""
    fake_audio = b"\x00\x01" * 8000
    result = await session.process_audio_chunk(fake_audio, "unknown-user")
    assert "transcript" in result


def test_session_close(session):
    session.close()
    assert session.state.active is False


@pytest.mark.asyncio
async def test_silent_audio_returns_empty(session, creator):
    """VAD returning no segments → empty result without ASR call."""
    with patch("courtaccess.speech.session.detect_speech") as mock_vad:
        mock_vad.return_value = {"speech_segments": [], "total_duration_ms": 500, "speech_ratio": 0.0}
        result = await session.process_audio_chunk(b"\x00" * 1000, "user-1")

    assert result["transcript"] == ""
    assert result["audio_bytes"] == b""
