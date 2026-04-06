"""
courtaccess/speech/tests/test_turn_taking.py

Unit tests for TurnStateMachine.

Tests cover:
  1. Initial idle state
  2. Role A can claim floor on speech_start
  3. Role B is rejected while A holds floor
  4. Floor is released after grace period expires
  5. Same user can reclaim floor during grace (multi-part question)
  6. Asymmetric grace periods (A=2000ms, B=1000ms)
  7. lock_user() blocks speech_start
  8. lock_user() is a no-op if locked user holds the floor
  9. release_floor() immediately frees the floor
  10. get_status() returns correct state dict
"""

from unittest.mock import patch

from courtaccess.speech.turn_taking import FloorState, TurnStateMachine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tsm(grace_a_ms: float = 2000, grace_b_ms: float = 1000, lockout_buffer_ms: float = 200) -> TurnStateMachine:
    return TurnStateMachine(
        lockout_buffer_ms=lockout_buffer_ms,
        grace_a_ms=grace_a_ms,
        grace_b_ms=grace_b_ms,
    )


# ---------------------------------------------------------------------------
# 1. Initial idle state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_state_is_idle(self):
        tsm = make_tsm()
        assert tsm.state == FloorState.IDLE

    def test_no_floor_holder(self):
        tsm = make_tsm()
        assert tsm._floor_holder is None

    def test_nobody_holds_floor(self):
        tsm = make_tsm()
        assert not tsm.holds_floor("a")
        assert not tsm.holds_floor("b")

    def test_nobody_is_locked(self):
        tsm = make_tsm()
        assert not tsm.is_locked("a")
        assert not tsm.is_locked("b")


# ---------------------------------------------------------------------------
# 2. Role A claims floor on speech_start
# ---------------------------------------------------------------------------


class TestRoleAClaims:
    def test_a_can_start_speech(self):
        tsm = make_tsm()
        result = tsm.try_speech_start("a")
        assert result is True

    def test_state_becomes_a_speaking(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        assert tsm.state == FloorState.A_SPEAKING

    def test_a_holds_floor_after_claim(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        assert tsm.holds_floor("a")

    def test_b_does_not_hold_floor_after_a_claims(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        assert not tsm.holds_floor("b")


# ---------------------------------------------------------------------------
# 3. Role B rejected while A holds floor
# ---------------------------------------------------------------------------


class TestRoleBRejectedWhileAHoldsFloor:
    def test_b_rejected_while_a_speaking(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        result = tsm.try_speech_start("b")
        assert result is False

    def test_state_stays_a_speaking(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        tsm.try_speech_start("b")
        assert tsm.state == FloorState.A_SPEAKING

    def test_b_rejected_during_a_processing(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        # Still within grace period
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            result = tsm.try_speech_start("b")
        assert result is False

    def test_state_stays_a_processing_after_b_rejected(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            tsm.try_speech_start("b")
            assert tsm.state == FloorState.A_PROCESSING


# ---------------------------------------------------------------------------
# 4. Floor released after grace period expires
# ---------------------------------------------------------------------------


class TestGracePeriodExpiry:
    def test_floor_released_after_a_grace_expires(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        # Advance past grace
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 2.1):
            assert not tsm.holds_floor("a")
            assert tsm.state == FloorState.IDLE

    def test_b_can_claim_after_a_grace_expires(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 2.1):
            result = tsm.try_speech_start("b")
        assert result is True

    def test_floor_released_after_b_grace_expires(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_b_ms=1000)
            tsm.try_speech_start("b")
            tsm.on_speech_end("b")
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 1.1):
            assert not tsm.holds_floor("b")
            assert tsm.state == FloorState.IDLE

    def test_state_idle_after_grace_expires(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
            assert tsm.state == FloorState.A_PROCESSING
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 2.1):
            tsm._check_grace()
            assert tsm.state == FloorState.IDLE


# ---------------------------------------------------------------------------
# 5. Same user reclaims floor during grace (multi-part question)
# ---------------------------------------------------------------------------


class TestSameUserReclaimsDuringGrace:
    def test_a_reclaims_during_grace(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
            assert tsm.state == FloorState.A_PROCESSING

        # Still within grace — A resumes speaking
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 1.0):
            result = tsm.try_speech_start("a")
        assert result is True
        assert tsm.state == FloorState.A_SPEAKING

    def test_grace_cancelled_on_reclaim(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            tsm.try_speech_start("a")
            assert tsm._grace_expiry == 0.0

    def test_b_reclaims_during_grace(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_b_ms=1000)
            tsm.try_speech_start("b")
            tsm.on_speech_end("b")

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.4):
            result = tsm.try_speech_start("b")
        assert result is True
        assert tsm.state == FloorState.B_SPEAKING


# ---------------------------------------------------------------------------
# 6. Asymmetric grace periods
# ---------------------------------------------------------------------------


class TestAsymmetricGrace:
    def test_a_grace_is_longer(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000, grace_b_ms=1000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")

        # At 1.5s: still within A's 2000ms grace, B still blocked
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 1.5):
            assert tsm.holds_floor("a")
            assert not tsm.try_speech_start("b")

        # At 2.1s: A's grace expired, B can now speak
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 2.1):
            assert not tsm.holds_floor("a")
            assert tsm.try_speech_start("b")

    def test_b_grace_is_shorter(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000, grace_b_ms=1000)
            tsm.try_speech_start("b")
            tsm.on_speech_end("b")

        # At 0.5s: still within B's 1000ms grace
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            assert tsm.holds_floor("b")

        # At 1.1s: B's grace expired, A can now speak
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 1.1):
            assert not tsm.holds_floor("b")
            assert tsm.try_speech_start("a")

    def test_grace_values_stored(self):
        tsm = make_tsm(grace_a_ms=2000, grace_b_ms=1000)
        assert tsm.grace_ms["a"] == 2000
        assert tsm.grace_ms["b"] == 1000


# ---------------------------------------------------------------------------
# 7. lock_user() blocks speech_start
# ---------------------------------------------------------------------------


class TestLockUserBlocksSpeech:
    def test_locked_user_cannot_start(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.lock_user("a", duration_ms=500)

        # Still within lock window
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.4):
            result = tsm.try_speech_start("a")
        assert result is False

    def test_lock_expires_and_user_can_speak(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.lock_user("b", duration_ms=500)  # total lock = 700ms

        # After lock + buffer expires
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.8):
            result = tsm.try_speech_start("b")
        assert result is True

    def test_lock_extends_on_queued_tts(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.lock_user("a", duration_ms=500)  # expiry = now + 0.7
            tsm.lock_user("a", duration_ms=1000)  # expiry = now + 1.2 — should win

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.9):
            assert tsm.is_locked("a")  # still locked by the longer segment

    def test_shorter_lock_does_not_shorten_existing(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.lock_user("b", duration_ms=1000)  # expiry = now + 1.2
            tsm.lock_user("b", duration_ms=100)  # expiry = now + 0.3 — should NOT win

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            assert tsm.is_locked("b")


# ---------------------------------------------------------------------------
# 8. lock_user() is a no-op if the locked user holds the floor
# ---------------------------------------------------------------------------


class TestLockUserNoOpForFloorHolder:
    def test_lock_skipped_for_active_speaker(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.try_speech_start("a")  # A holds floor
            tsm.lock_user("a", duration_ms=1000)

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.1):
            assert not tsm.is_locked("a")  # lock was ignored

    def test_lock_applied_to_non_floor_holder(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.try_speech_start("a")  # A holds floor
            tsm.lock_user("b", duration_ms=1000)  # lock B — B does NOT hold floor

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.5):
            assert tsm.is_locked("b")


# ---------------------------------------------------------------------------
# 9. release_floor() immediately frees the floor
# ---------------------------------------------------------------------------


class TestReleaseFloor:
    def test_release_resets_state(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        tsm.release_floor("a")
        assert tsm.state == FloorState.IDLE

    def test_release_clears_holder(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        tsm.release_floor("a")
        assert tsm._floor_holder is None

    def test_release_clears_grace_expiry(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm()
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        tsm.release_floor("a")
        assert tsm._grace_expiry == 0.0

    def test_release_noop_for_non_holder(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        tsm.release_floor("b")  # B does not hold floor — should be no-op
        assert tsm._floor_holder == "a"
        assert tsm.state == FloorState.A_SPEAKING

    def test_b_can_speak_after_a_releases(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        tsm.release_floor("a")
        result = tsm.try_speech_start("b")
        assert result is True
        assert tsm.state == FloorState.B_SPEAKING


# ---------------------------------------------------------------------------
# 10. get_status() returns correct state dict
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_idle_status(self):
        tsm = make_tsm(grace_a_ms=2000, grace_b_ms=1000)
        status = tsm.get_status()
        assert status["state"] == "idle"
        assert status["floor_holder"] is None
        assert status["a_locked"] is False
        assert status["b_locked"] is False
        assert status["a_lock_remaining_ms"] == 0
        assert status["b_lock_remaining_ms"] == 0

    def test_status_while_a_speaking(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        status = tsm.get_status()
        assert status["state"] == "a_speaking"
        assert status["floor_holder"] == "a"

    def test_status_while_a_processing(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
            status = tsm.get_status()
        assert status["state"] == "a_processing"
        assert status["floor_holder"] == "a"

    def test_status_after_grace_expires(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(grace_a_ms=2000)
            tsm.try_speech_start("a")
            tsm.on_speech_end("a")
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 2.1):
            status = tsm.get_status()
        assert status["state"] == "idle"
        assert status["floor_holder"] is None

    def test_status_shows_lock_remaining(self):
        now = 1000.0
        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now):
            tsm = make_tsm(lockout_buffer_ms=200)
            tsm.lock_user("b", duration_ms=800)  # total = 1000ms

        with patch("courtaccess.speech.turn_taking.time.monotonic", return_value=now + 0.3):
            status = tsm.get_status()
        assert status["b_locked"] is True
        assert status["b_lock_remaining_ms"] > 0

    def test_status_grace_values(self):
        tsm = make_tsm(grace_a_ms=2000, grace_b_ms=1000)
        status = tsm.get_status()
        assert status["grace_ms"] == {"a": 2000, "b": 1000}

    def test_repr_contains_state(self):
        tsm = make_tsm()
        tsm.try_speech_start("a")
        r = repr(tsm)
        assert "state=a_speaking" in r
        assert "floor=a" in r
