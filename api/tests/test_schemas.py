"""
api/tests/test_schemas.py

Pure-Python validation tests for api/schemas/schemas.py.

No HTTP calls — exercises Pydantic model construction, field
constraints, enum values, and the UserResponse.from_orm_user()
class method.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from api.schemas.schemas import (
    ROLE_ID_TO_NAME,
    DocumentStatus,
    ErrorDetail,
    FormSearchRequest,
    Language,
    RoleUpdateRequest,
    RoomCreateRequest,
    RoomJoinRequest,
    SessionCreateRequest,
    SessionStatus,
    SessionType,
    TargetLanguage,
    TranscriptSegment,
    UploadRequest,
    UserResponse,
    UserRole,
    WebSocketMessage,
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_user_role_public_value() -> None:
    assert UserRole.PUBLIC == "public"


def test_user_role_court_official_value() -> None:
    assert UserRole.COURT_OFFICIAL == "court_official"


def test_user_role_interpreter_value() -> None:
    assert UserRole.INTERPRETER == "interpreter"


def test_user_role_admin_value() -> None:
    assert UserRole.ADMIN == "admin"


def test_language_codes() -> None:
    assert Language.ENGLISH == "en"
    assert Language.SPANISH == "es"
    assert Language.PORTUGUESE == "pt"


def test_target_language_nllb_codes() -> None:
    assert TargetLanguage.SPANISH == "spa_Latn"
    assert TargetLanguage.PORTUGUESE == "por_Latn"


def test_document_status_all_values() -> None:
    values = {s.value for s in DocumentStatus}
    assert values == {"pending", "processing", "translated", "approved", "rejected", "error"}


def test_session_status_values() -> None:
    assert SessionStatus.ACTIVE == "active"
    assert SessionStatus.COMPLETED == "completed"
    assert SessionStatus.FAILED == "failed"
    assert SessionStatus.ENDED == "ended"


def test_session_type_values() -> None:
    assert SessionType.REALTIME == "realtime"
    assert SessionType.DOCUMENT == "document"


# ---------------------------------------------------------------------------
# ROLE_ID_TO_NAME mapping
# ---------------------------------------------------------------------------


def test_role_id_map_covers_all_roles() -> None:
    assert ROLE_ID_TO_NAME[1] == "public"
    assert ROLE_ID_TO_NAME[2] == "court_official"
    assert ROLE_ID_TO_NAME[3] == "interpreter"
    assert ROLE_ID_TO_NAME[4] == "admin"


def test_role_id_map_unknown_id_returns_none() -> None:
    assert ROLE_ID_TO_NAME.get(99) is None


# ---------------------------------------------------------------------------
# UserResponse.from_orm_user
# ---------------------------------------------------------------------------


def _mock_orm_user(role_id: int = 1) -> MagicMock:
    user = MagicMock()
    user.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user.email = "alice@example.com"
    user.name = "Alice"
    user.role_id = role_id
    user.firebase_uid = "firebase-uid-abc"
    user.auth_provider = "google.com"
    user.email_verified = True
    user.mfa_enabled = False
    user.role_approved_by = None
    user.role_approved_at = None
    user.created_at = datetime(2024, 1, 1, tzinfo=UTC)
    user.last_login_at = datetime(2024, 6, 1, tzinfo=UTC)
    return user


def test_from_orm_user_role_public() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user(role_id=1))
    assert resp.role == "public"


def test_from_orm_user_role_court_official() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user(role_id=2))
    assert resp.role == "court_official"


def test_from_orm_user_role_interpreter() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user(role_id=3))
    assert resp.role == "interpreter"


def test_from_orm_user_role_admin() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user(role_id=4))
    assert resp.role == "admin"


def test_from_orm_user_unknown_role_id_yields_unknown() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user(role_id=99))
    assert resp.role == "unknown"


def test_from_orm_user_email_preserved() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user())
    assert resp.email == "alice@example.com"


def test_from_orm_user_firebase_uid_preserved() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user())
    assert resp.firebase_uid == "firebase-uid-abc"


def test_from_orm_user_created_at_preserved() -> None:
    resp = UserResponse.from_orm_user(_mock_orm_user())
    assert resp.created_at == datetime(2024, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# RoleUpdateRequest
# ---------------------------------------------------------------------------


def test_role_update_request_valid_public() -> None:
    r = RoleUpdateRequest(selected_role="public")
    assert r.selected_role == UserRole.PUBLIC


def test_role_update_request_valid_interpreter() -> None:
    r = RoleUpdateRequest(selected_role="interpreter")
    assert r.selected_role == UserRole.INTERPRETER


def test_role_update_request_invalid_role_raises() -> None:
    with pytest.raises(ValidationError):
        RoleUpdateRequest(selected_role="superuser")


def test_role_update_request_missing_field_raises() -> None:
    with pytest.raises(ValidationError):
        RoleUpdateRequest()


# ---------------------------------------------------------------------------
# UploadRequest
# ---------------------------------------------------------------------------


def test_upload_request_defaults_to_both_languages() -> None:
    r = UploadRequest()
    assert Language.SPANISH in r.target_languages
    assert Language.PORTUGUESE in r.target_languages


def test_upload_request_notes_within_limit() -> None:
    r = UploadRequest(notes="x" * 500)
    assert len(r.notes) == 500


def test_upload_request_notes_exceeds_limit_raises() -> None:
    with pytest.raises(ValidationError):
        UploadRequest(notes="x" * 501)


def test_upload_request_notes_none_allowed() -> None:
    r = UploadRequest(notes=None)
    assert r.notes is None


# ---------------------------------------------------------------------------
# RoomCreateRequest
# ---------------------------------------------------------------------------


def test_room_create_request_consent_true_accepted() -> None:
    r = RoomCreateRequest(
        target_language="es",
        partner_name="Maria",
        consent_acknowledged=True,
    )
    assert r.consent_acknowledged is True


def test_room_create_request_consent_false_accepted_by_pydantic() -> None:
    """Pydantic accepts False — consent validation is enforced in the route handler."""
    r = RoomCreateRequest(
        target_language="es",
        partner_name="Maria",
        consent_acknowledged=False,
    )
    assert r.consent_acknowledged is False


def test_room_create_request_partner_name_max_length() -> None:
    r = RoomCreateRequest(
        target_language="es",
        partner_name="A" * 100,
        consent_acknowledged=True,
    )
    assert len(r.partner_name) == 100


def test_room_create_request_partner_name_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        RoomCreateRequest(
            target_language="es",
            partner_name="A" * 101,
            consent_acknowledged=True,
        )


def test_room_create_request_invalid_language_raises() -> None:
    """'en' is not a valid target_language (must be 'es' or 'pt')."""
    with pytest.raises(ValidationError):
        RoomCreateRequest(
            target_language="en",  # English is the court official's language, not the partner's
            partner_name="Maria",
            consent_acknowledged=True,
        )


# ---------------------------------------------------------------------------
# RoomJoinRequest
# ---------------------------------------------------------------------------


def test_room_join_request_valid_code() -> None:
    r = RoomJoinRequest(room_code="ABCD1234")
    assert r.room_code == "ABCD1234"


def test_room_join_request_minimum_length() -> None:
    r = RoomJoinRequest(room_code="ABCD")
    assert r.room_code == "ABCD"


def test_room_join_request_too_short_raises() -> None:
    with pytest.raises(ValidationError):
        RoomJoinRequest(room_code="ABC")


def test_room_join_request_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        RoomJoinRequest(room_code="ABCDEFGHI")  # 9 chars > 8


def test_room_join_request_lowercase_raises() -> None:
    with pytest.raises(ValidationError):
        RoomJoinRequest(room_code="abcd1234")


def test_room_join_request_special_chars_raises() -> None:
    with pytest.raises(ValidationError):
        RoomJoinRequest(room_code="ABCD-123")


def test_room_join_request_partner_name_optional() -> None:
    r = RoomJoinRequest(room_code="ABCD1234")
    assert r.partner_name is None


# ---------------------------------------------------------------------------
# TranscriptSegment
# ---------------------------------------------------------------------------


def test_transcript_segment_confidence_at_zero() -> None:
    seg = TranscriptSegment(
        speaker_id="sp1",
        original_text="hello",
        translation_confidence=0.0,
        timestamp_ms=100,
    )
    assert seg.translation_confidence == 0.0


def test_transcript_segment_confidence_at_one() -> None:
    seg = TranscriptSegment(
        speaker_id="sp1",
        original_text="hello",
        translation_confidence=1.0,
        timestamp_ms=100,
    )
    assert seg.translation_confidence == 1.0


def test_transcript_segment_confidence_above_one_raises() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(
            speaker_id="sp1",
            original_text="hello",
            translation_confidence=1.01,
            timestamp_ms=100,
        )


def test_transcript_segment_confidence_below_zero_raises() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(
            speaker_id="sp1",
            original_text="hello",
            translation_confidence=-0.01,
            timestamp_ms=100,
        )


def test_transcript_segment_has_auto_segment_id() -> None:
    seg = TranscriptSegment(speaker_id="sp1", original_text="hello", timestamp_ms=0)
    assert seg.segment_id is not None
    uuid.UUID(str(seg.segment_id))  # raises if not a valid UUID


def test_transcript_segment_is_final_default_false() -> None:
    seg = TranscriptSegment(speaker_id="sp1", original_text="hello", timestamp_ms=0)
    assert seg.is_final is False


# ---------------------------------------------------------------------------
# FormSearchRequest
# ---------------------------------------------------------------------------


def test_form_search_request_q_max_length() -> None:
    r = FormSearchRequest(q="x" * 200)
    assert len(r.q) == 200


def test_form_search_request_q_too_long_raises() -> None:
    with pytest.raises(ValidationError):
        FormSearchRequest(q="x" * 201)


def test_form_search_request_page_size_max_100() -> None:
    r = FormSearchRequest(page_size=100)
    assert r.page_size == 100


def test_form_search_request_page_size_above_max_raises() -> None:
    with pytest.raises(ValidationError):
        FormSearchRequest(page_size=101)


def test_form_search_request_page_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        FormSearchRequest(page=0)


def test_form_search_request_defaults() -> None:
    r = FormSearchRequest()
    assert r.page == 1
    assert r.page_size == 20
    assert r.q is None
    assert r.division is None
    assert r.language is None


# ---------------------------------------------------------------------------
# SessionCreateRequest
# ---------------------------------------------------------------------------


def test_session_create_request_default_target_language() -> None:
    r = SessionCreateRequest(type=SessionType.REALTIME)
    assert r.target_language == TargetLanguage.SPANISH


def test_session_create_request_default_source_language() -> None:
    r = SessionCreateRequest(type=SessionType.REALTIME)
    assert r.source_language == "en"


# ---------------------------------------------------------------------------
# WebSocketMessage
# ---------------------------------------------------------------------------


def test_websocket_message_empty_payload_default() -> None:
    msg = WebSocketMessage(type="ping")
    assert msg.payload == {}


def test_websocket_message_type_preserved() -> None:
    msg = WebSocketMessage(type="transcript", payload={"text": "hello"})
    assert msg.type == "transcript"
    assert msg.payload["text"] == "hello"


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------


def test_error_detail_construction() -> None:
    err = ErrorDetail(code="NOT_FOUND", message="Resource not found")
    assert err.code == "NOT_FOUND"
    assert err.message == "Resource not found"
    assert err.details == {}


def test_error_detail_with_extra_details() -> None:
    err = ErrorDetail(code="VALIDATION", message="Bad input", details={"field": "email"})
    assert err.details["field"] == "email"
