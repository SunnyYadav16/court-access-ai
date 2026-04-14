"""
Tests for courtaccess/speech/turn_taking.py

TurnStateMachine is a pure state machine with no I/O — fully testable.
All tests pass explicit lockout/grace values so Settings fields are not
required to be non-None.
"""

import time

from courtaccess.speech.turn_taking import FloorState, TurnStateMachine


# ── Constructor shortcut ───────────────────────────────────────────────────────
def _machine(lockout=300.0, grace_a=2000.0, grace_b=1000.0) -> TurnStateMachine:
    return TurnStateMachine(lockout_buffer_ms=lockout, grace_a_ms=grace_a, grace_b_ms=grace_b)


# ══════════════════════════════════════════════════════════════════════════════
# FloorState enum
# ══════════════════════════════════════════════════════════════════════════════


def test_floor_state_idle_value():
    assert FloorState.IDLE == "idle"


def test_floor_state_a_speaking():
    assert FloorState.A_SPEAKING == "a_speaking"


def test_floor_state_a_processing():
    assert FloorState.A_PROCESSING == "a_processing"


def test_floor_state_b_speaking():
    assert FloorState.B_SPEAKING == "b_speaking"


def test_floor_state_b_processing():
    assert FloorState.B_PROCESSING == "b_processing"


# ══════════════════════════════════════════════════════════════════════════════
# Initialization
# ══════════════════════════════════════════════════════════════════════════════


def test_initial_state_is_idle():
    m = _machine()
    assert m.state == FloorState.IDLE


def test_initial_floor_holder_is_none():
    m = _machine()
    assert m._floor_holder is None


def test_initial_no_locks():
    m = _machine()
    assert not m.is_locked("a")
    assert not m.is_locked("b")


def test_grace_ms_stored():
    m = _machine(grace_a=3000.0, grace_b=500.0)
    assert m.grace_ms["a"] == 3000.0
    assert m.grace_ms["b"] == 500.0


def test_lockout_buffer_stored():
    m = _machine(lockout=150.0)
    assert m.lockout_buffer_ms == 150.0


# ══════════════════════════════════════════════════════════════════════════════
# try_speech_start
# ══════════════════════════════════════════════════════════════════════════════


def test_a_can_claim_idle_floor():
    m = _machine()
    assert m.try_speech_start("a") is True


def test_b_can_claim_idle_floor():
    m = _machine()
    assert m.try_speech_start("b") is True


def test_claiming_floor_sets_a_speaking_state():
    m = _machine()
    m.try_speech_start("a")
    assert m.state == FloorState.A_SPEAKING


def test_claiming_floor_sets_b_speaking_state():
    m = _machine()
    m.try_speech_start("b")
    assert m.state == FloorState.B_SPEAKING


def test_a_cannot_speak_when_b_holds_floor():
    m = _machine()
    m.try_speech_start("b")
    assert m.try_speech_start("a") is False


def test_b_cannot_speak_when_a_holds_floor():
    m = _machine()
    m.try_speech_start("a")
    assert m.try_speech_start("b") is False


def test_same_role_can_continue_holding_floor():
    m = _machine()
    m.try_speech_start("a")
    assert m.try_speech_start("a") is True


def test_locked_user_cannot_speak():
    m = _machine(lockout=300.0)
    m.lock_user("a", duration_ms=5000.0)
    assert m.try_speech_start("a") is False


def test_holds_floor_true_for_active_speaker():
    m = _machine()
    m.try_speech_start("a")
    assert m.holds_floor("a") is True


def test_holds_floor_false_for_other_role():
    m = _machine()
    m.try_speech_start("a")
    assert m.holds_floor("b") is False


def test_holds_floor_false_when_idle():
    m = _machine()
    assert m.holds_floor("a") is False
    assert m.holds_floor("b") is False


# ══════════════════════════════════════════════════════════════════════════════
# on_speech_end
# ══════════════════════════════════════════════════════════════════════════════


def test_on_speech_end_returns_true_for_floor_holder():
    m = _machine()
    m.try_speech_start("a")
    assert m.on_speech_end("a") is True


def test_on_speech_end_returns_false_for_non_holder():
    m = _machine()
    m.try_speech_start("a")
    assert m.on_speech_end("b") is False


def test_on_speech_end_transitions_a_to_processing():
    m = _machine()
    m.try_speech_start("a")
    m.on_speech_end("a")
    assert m.state == FloorState.A_PROCESSING


def test_on_speech_end_transitions_b_to_processing():
    m = _machine()
    m.try_speech_start("b")
    m.on_speech_end("b")
    assert m.state == FloorState.B_PROCESSING


def test_on_speech_end_sets_grace_expiry():
    m = _machine(grace_a=500.0)
    m.try_speech_start("a")
    before = time.monotonic()
    m.on_speech_end("a")
    after = time.monotonic()
    # grace_expiry should be roughly now + 0.5s
    assert before + 0.4 <= m._grace_expiry <= after + 0.6


# ══════════════════════════════════════════════════════════════════════════════
# release_floor
# ══════════════════════════════════════════════════════════════════════════════


def test_release_floor_resets_to_idle():
    m = _machine()
    m.try_speech_start("a")
    m.release_floor("a")
    assert m.state == FloorState.IDLE


def test_release_floor_clears_floor_holder():
    m = _machine()
    m.try_speech_start("a")
    m.release_floor("a")
    assert m._floor_holder is None


def test_release_floor_noop_for_non_holder():
    m = _machine()
    m.try_speech_start("a")
    m.release_floor("b")  # b doesn't hold floor
    assert m._floor_holder == "a"


def test_release_floor_allows_other_to_claim():
    m = _machine()
    m.try_speech_start("a")
    m.release_floor("a")
    assert m.try_speech_start("b") is True


# ══════════════════════════════════════════════════════════════════════════════
# lock_user / is_locked
# ══════════════════════════════════════════════════════════════════════════════


def test_lock_user_makes_user_locked():
    m = _machine(lockout=0.0)
    m.lock_user("b", duration_ms=5000.0)
    assert m.is_locked("b") is True


def test_lock_user_does_not_lock_floor_holder():
    m = _machine(lockout=0.0)
    m.try_speech_start("a")
    m.lock_user("a", duration_ms=5000.0)
    assert m.is_locked("a") is False


def test_lock_user_extends_existing_lock():
    m = _machine(lockout=0.0)
    m.lock_user("b", duration_ms=1000.0)
    first_expiry = m._lockout["b"]
    m.lock_user("b", duration_ms=5000.0)
    assert m._lockout["b"] >= first_expiry


def test_is_locked_false_for_unknown_role():
    m = _machine()
    assert m.is_locked("c") is False


def test_lock_expires_after_duration(monkeypatch):
    m = _machine(lockout=0.0)
    # Set lock expiry in the past
    m._lockout["b"] = time.monotonic() - 1.0
    assert m.is_locked("b") is False


# ══════════════════════════════════════════════════════════════════════════════
# Grace period auto-release (_check_grace)
# ══════════════════════════════════════════════════════════════════════════════


def test_grace_expires_and_releases_floor():
    m = _machine(grace_a=0.001)  # 1 ms grace
    m.try_speech_start("a")
    m.on_speech_end("a")
    # Force expiry by backdating the grace expiry
    m._grace_expiry = time.monotonic() - 1.0
    m._check_grace()
    assert m.state == FloorState.IDLE
    assert m._floor_holder is None


def test_grace_not_expired_floor_still_held():
    m = _machine(grace_a=60000.0)  # 60 s grace
    m.try_speech_start("a")
    m.on_speech_end("a")
    m._check_grace()
    # Floor holder should still be "a"
    assert m._floor_holder == "a"


def test_b_can_claim_after_a_grace_expires():
    m = _machine(grace_a=0.001)
    m.try_speech_start("a")
    m.on_speech_end("a")
    m._grace_expiry = time.monotonic() - 1.0
    assert m.try_speech_start("b") is True


# ══════════════════════════════════════════════════════════════════════════════
# get_status
# ══════════════════════════════════════════════════════════════════════════════


def test_get_status_returns_dict():
    m = _machine()
    assert isinstance(m.get_status(), dict)


def test_get_status_idle_state():
    m = _machine()
    s = m.get_status()
    assert s["state"] == "idle"
    assert s["floor_holder"] is None
    assert s["a_locked"] is False
    assert s["b_locked"] is False


def test_get_status_a_speaking():
    m = _machine()
    m.try_speech_start("a")
    s = m.get_status()
    assert s["state"] == "a_speaking"
    assert s["floor_holder"] == "a"


def test_get_status_lock_remaining_ms_positive():
    m = _machine(lockout=0.0)
    m.lock_user("b", duration_ms=5000.0)
    s = m.get_status()
    assert s["b_lock_remaining_ms"] > 0


def test_get_status_lock_remaining_zero_when_not_locked():
    m = _machine()
    s = m.get_status()
    assert s["a_lock_remaining_ms"] == 0
    assert s["b_lock_remaining_ms"] == 0


def test_get_status_grace_ms_matches_constructor():
    m = _machine(grace_a=3000.0, grace_b=500.0)
    s = m.get_status()
    assert s["grace_ms"]["a"] == 3000.0
    assert s["grace_ms"]["b"] == 500.0


# ══════════════════════════════════════════════════════════════════════════════
# __repr__
# ══════════════════════════════════════════════════════════════════════════════


def test_repr_contains_state():
    m = _machine()
    assert "state=idle" in repr(m)


def test_repr_contains_floor():
    m = _machine()
    assert "floor=None" in repr(m)


def test_repr_contains_lock_info_when_locked():
    m = _machine(lockout=0.0)
    m.lock_user("a", duration_ms=5000.0)
    r = repr(m)
    assert "A_locked" in r
