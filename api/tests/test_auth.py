"""
api/tests/test_auth.py

Unit tests for pure functions in api/auth.py.
No HTTP calls — exercises business logic directly.

Each test makes substantive assertions that would fail if the
corresponding code path were removed or broken.
"""

import os

os.environ.setdefault("GCS_BUCKET_TRANSCRIPTS", "test-transcripts")
os.environ.setdefault("USE_REAL_SPEECH", "false")
os.environ.setdefault("ROOM_JWT_SECRET", "test-room-jwt-secret-for-testing-only")
os.environ.setdefault("ROOM_JWT_EXPIRY_HOURS", "4")
os.environ.setdefault("ROOM_CODE_EXPIRY_MINUTES", "30")

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import firebase_admin.auth as _fb_auth
import jwt
import pytest
from fastapi import HTTPException

from api.auth import (
    _hash_email_for_logging,
    create_room_token,
    get_or_create_user,
    get_websocket_user,
    verify_firebase_token,
    verify_room_token,
)

# ---------------------------------------------------------------------------
# _hash_email_for_logging
# ---------------------------------------------------------------------------


def test_hash_email_returns_8_char_hex() -> None:
    result = _hash_email_for_logging("user@example.com")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_email_is_deterministic() -> None:
    email = "alice@court.gov"
    assert _hash_email_for_logging(email) == _hash_email_for_logging(email)


def test_hash_email_differs_for_different_inputs() -> None:
    assert _hash_email_for_logging("a@b.com") != _hash_email_for_logging("c@d.com")


# ---------------------------------------------------------------------------
# verify_firebase_token
# ---------------------------------------------------------------------------


def test_verify_firebase_token_success() -> None:
    claims = {"uid": "abc", "email": "u@example.com", "email_verified": True}
    with patch("firebase_admin.auth.verify_id_token", return_value=claims):
        result = verify_firebase_token("fake-token")
    assert result["uid"] == "abc"
    assert result["email"] == "u@example.com"


def test_verify_firebase_token_expired_raises_401() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.ExpiredIdTokenError("expired", cause=None),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("expired-token")
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_verify_firebase_token_revoked_raises_401() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.RevokedIdTokenError("revoked"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("revoked-token")
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


def test_verify_firebase_token_invalid_raises_401() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.InvalidIdTokenError("invalid"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("bad-token")
    assert exc_info.value.status_code == 401
    assert "invalid" in exc_info.value.detail.lower()


def test_verify_firebase_token_disabled_user_raises_401() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.UserDisabledError("disabled"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("disabled-user-token")
    assert exc_info.value.status_code == 401
    assert "disabled" in exc_info.value.detail.lower()


def test_verify_firebase_token_generic_exception_raises_401() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=RuntimeError("unexpected"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("broken-token")
    assert exc_info.value.status_code == 401


def test_verify_firebase_token_includes_www_authenticate_header() -> None:
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.ExpiredIdTokenError("expired", cause=None),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        verify_firebase_token("expired-token")
    assert "WWW-Authenticate" in exc_info.value.headers
    assert exc_info.value.headers["WWW-Authenticate"] == "Bearer"


# ---------------------------------------------------------------------------
# create_room_token / verify_room_token
# ---------------------------------------------------------------------------

_SESSION_ID = uuid.uuid4()
_RT_REQUEST_ID = uuid.uuid4()


def test_create_room_token_returns_string() -> None:
    token = create_room_token(_SESSION_ID, _RT_REQUEST_ID, "Alice")
    assert isinstance(token, str)
    assert len(token) > 20


def test_verify_room_token_round_trip() -> None:
    token = create_room_token(_SESSION_ID, _RT_REQUEST_ID, "Alice")
    payload = verify_room_token(token)
    assert payload["session_id"] == str(_SESSION_ID)
    assert payload["rt_request_id"] == str(_RT_REQUEST_ID)
    assert payload["partner_name"] == "Alice"
    assert payload["type"] == "room"
    assert payload["sub"] == "guest"


def test_room_token_has_expiry_claim() -> None:
    """Token must include an 'exp' claim so it actually expires."""
    token = create_room_token(_SESSION_ID, _RT_REQUEST_ID, "Bob")
    # Decode without verification to inspect claims
    payload = jwt.decode(token, options={"verify_signature": False})
    assert "exp" in payload
    # exp should be ~4 hours from now
    exp_dt = datetime.fromtimestamp(payload["exp"], tz=UTC)
    now = datetime.now(tz=UTC)
    assert timedelta(hours=3, minutes=50) < (exp_dt - now) < timedelta(hours=4, minutes=10)


def test_verify_room_token_expired_raises_401() -> None:
    from courtaccess.core.config import get_settings

    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": "guest",
        "type": "room",
        "session_id": str(_SESSION_ID),
        "rt_request_id": str(_RT_REQUEST_ID),
        "partner_name": "Bob",
        "iat": now - timedelta(hours=5),
        "exp": now - timedelta(hours=1),
    }
    expired_token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    with pytest.raises(HTTPException) as exc_info:
        verify_room_token(expired_token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_verify_room_token_tampered_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_room_token("totally.not.valid.jwt.string")
    assert exc_info.value.status_code == 401


def test_verify_room_token_wrong_secret_raises_401() -> None:
    """Token signed with a different secret must be rejected."""
    now = datetime.now(tz=UTC)
    payload = {
        "sub": "guest",
        "type": "room",
        "session_id": str(_SESSION_ID),
        "rt_request_id": str(_RT_REQUEST_ID),
        "partner_name": "Alice",
        "iat": now,
        "exp": now + timedelta(hours=4),
    }
    # Sign with the WRONG secret
    bad_token = jwt.encode(payload, "wrong-secret-totally-different", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        verify_room_token(bad_token)
    assert exc_info.value.status_code == 401


def test_verify_room_token_wrong_type_raises_401() -> None:
    from courtaccess.core.config import get_settings

    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": "guest",
        "type": "NOT_ROOM",
        "session_id": str(_SESSION_ID),
        "rt_request_id": str(_RT_REQUEST_ID),
        "partner_name": "Alice",
        "iat": now,
        "exp": now + timedelta(hours=4),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    with pytest.raises(HTTPException) as exc_info:
        verify_room_token(token)
    assert exc_info.value.status_code == 401


def test_verify_room_token_wrong_sub_raises_401() -> None:
    from courtaccess.core.config import get_settings

    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": "user",  # wrong sub — should be "guest"
        "type": "room",
        "session_id": str(_SESSION_ID),
        "rt_request_id": str(_RT_REQUEST_ID),
        "partner_name": "Alice",
        "iat": now,
        "exp": now + timedelta(hours=4),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    with pytest.raises(HTTPException) as exc_info:
        verify_room_token(token)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_or_create_user — helpers
# ---------------------------------------------------------------------------


def _mock_db_returning(first_result, second_result=None):
    """Build an async mock db with up to two execute() responses."""
    db = AsyncMock()
    r1 = MagicMock()
    r1.scalar_one_or_none = MagicMock(return_value=first_result)
    if second_result is None:
        db.execute = AsyncMock(return_value=r1)
    else:
        r2 = MagicMock()
        r2.scalar_one_or_none = MagicMock(return_value=second_result)
        db.execute = AsyncMock(side_effect=[r1, r2])
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# get_or_create_user — existing user found by firebase_uid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_existing_returns_same_object() -> None:
    existing = MagicMock()
    existing.last_login_at = None
    existing.email_verified = False
    db = _mock_db_returning(first_result=existing)

    result = await get_or_create_user(
        {"uid": "fb123", "email": "u@ex.com", "email_verified": True},
        db,
    )
    assert result is existing


@pytest.mark.asyncio
async def test_get_or_create_user_existing_updates_last_login_at() -> None:
    """Route must update last_login_at on every login — not just first."""
    existing = MagicMock()
    existing.last_login_at = datetime(2020, 1, 1, tzinfo=UTC)  # old timestamp
    existing.email_verified = False
    db = _mock_db_returning(first_result=existing)

    before = datetime.now(tz=UTC)
    await get_or_create_user(
        {"uid": "fb123", "email": "u@ex.com", "email_verified": True},
        db,
    )
    after = datetime.now(tz=UTC)

    # last_login_at must have been set to a recent time
    assert existing.last_login_at is not None
    assert before <= existing.last_login_at <= after


@pytest.mark.asyncio
async def test_get_or_create_user_existing_updates_email_verified() -> None:
    """Route must sync email_verified from the current token claims."""
    existing = MagicMock()
    existing.last_login_at = None
    existing.email_verified = False  # was False in DB
    db = _mock_db_returning(first_result=existing)

    await get_or_create_user(
        {"uid": "fb123", "email": "u@ex.com", "email_verified": True},  # now True
        db,
    )
    assert existing.email_verified is True


@pytest.mark.asyncio
async def test_get_or_create_user_existing_commits_and_refreshes() -> None:
    existing = MagicMock()
    existing.last_login_at = None
    existing.email_verified = False
    db = _mock_db_returning(first_result=existing)

    await get_or_create_user(
        {"uid": "fb123", "email": "u@ex.com", "email_verified": True},
        db,
    )
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(existing)


# ---------------------------------------------------------------------------
# get_or_create_user — missing/blank email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_no_email_raises_401() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_or_create_user({"uid": "fb123", "email": ""}, db)
    assert exc_info.value.status_code == 401
    assert "email" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_or_create_user_whitespace_email_raises_401() -> None:
    """An email that is only whitespace must be rejected (same as empty)."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_or_create_user({"uid": "fb123", "email": "   "}, db)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_or_create_user — email backfill (uid not in DB, email match)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_backfills_firebase_uid() -> None:
    existing_by_email = MagicMock()
    existing_by_email.firebase_uid = None  # starts with no UID
    existing_by_email.auth_provider = None
    existing_by_email.last_login_at = None
    existing_by_email.email_verified = False
    db = _mock_db_returning(first_result=None, second_result=existing_by_email)

    result = await get_or_create_user(
        {"uid": "newuid", "email": "u@ex.com", "email_verified": True},
        db,
    )
    assert result is existing_by_email
    # Route must write the new UID onto the existing row
    assert existing_by_email.firebase_uid == "newuid"


@pytest.mark.asyncio
async def test_get_or_create_user_backfill_sets_auth_provider() -> None:
    existing_by_email = MagicMock()
    existing_by_email.firebase_uid = None
    existing_by_email.auth_provider = None
    existing_by_email.last_login_at = None
    existing_by_email.email_verified = False
    db = _mock_db_returning(first_result=None, second_result=existing_by_email)

    await get_or_create_user(
        {
            "uid": "newuid",
            "email": "u@ex.com",
            "email_verified": True,
            "firebase": {"sign_in_provider": "google.com"},
        },
        db,
    )
    assert existing_by_email.auth_provider == "google.com"


@pytest.mark.asyncio
async def test_get_or_create_user_backfill_commits_and_refreshes() -> None:
    existing_by_email = MagicMock()
    existing_by_email.firebase_uid = None
    existing_by_email.auth_provider = None
    existing_by_email.last_login_at = None
    existing_by_email.email_verified = False
    db = _mock_db_returning(first_result=None, second_result=existing_by_email)

    await get_or_create_user(
        {"uid": "newuid", "email": "u@ex.com", "email_verified": True},
        db,
    )
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(existing_by_email)


# ---------------------------------------------------------------------------
# get_or_create_user — brand new user creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_creates_new_public_user() -> None:
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    await get_or_create_user(
        {
            "uid": "brand_new",
            "email": "new@ex.com",
            "email_verified": False,
            "firebase": {"sign_in_provider": "google.com"},
        },
        db,
    )
    assert len(added_users) == 1
    created = added_users[0]
    assert created.role_id == 1  # public — not promoted without SAML


@pytest.mark.asyncio
async def test_new_user_has_all_required_fields_populated() -> None:
    """Every field the application reads later must be set at creation time."""
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    before = datetime.now(tz=UTC)
    await get_or_create_user(
        {
            "uid": "brand_new",
            "email": "new@ex.com",
            "name": "John Doe",
            "email_verified": False,
            "firebase": {"sign_in_provider": "google.com"},
        },
        db,
    )
    after = datetime.now(tz=UTC)

    u = added_users[0]
    assert u.firebase_uid == "brand_new"
    assert u.email == "new@ex.com"
    assert u.name == "John Doe"
    assert u.auth_provider == "google.com"
    assert u.email_verified is False
    assert u.mfa_enabled is False
    # Timestamps must be set to a recent UTC time
    assert u.created_at is not None
    assert before <= u.created_at <= after
    assert u.last_login_at is not None
    assert before <= u.last_login_at <= after


@pytest.mark.asyncio
async def test_new_user_without_name_uses_email_prefix() -> None:
    """When Firebase claims have no 'name', fall back to email local part."""
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    await get_or_create_user(
        {
            "uid": "uid_no_name",
            "email": "alice@court.gov",
            # no 'name' key in claims
            "email_verified": True,
        },
        db,
    )
    u = added_users[0]
    assert u.name == "alice"  # email.split("@")[0]


@pytest.mark.asyncio
async def test_new_user_creation_commits_and_refreshes() -> None:
    db = _mock_db_returning(first_result=None, second_result=None)
    await get_or_create_user(
        {"uid": "x", "email": "x@x.com", "email_verified": True},
        db,
    )
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited()


# ---------------------------------------------------------------------------
# get_or_create_user — SAML auto-promotion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_saml_auto_promotes_to_court_official() -> None:
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    await get_or_create_user(
        {
            "uid": "saml_user",
            "email": "judge@mass.gov",
            "email_verified": True,
            "firebase": {"sign_in_provider": "saml.massgov"},
        },
        db,
    )
    assert len(added_users) == 1
    u = added_users[0]
    assert u.role_id == 2  # court_official, not public


@pytest.mark.asyncio
async def test_saml_user_auth_provider_set_correctly() -> None:
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    await get_or_create_user(
        {
            "uid": "saml_user",
            "email": "judge@mass.gov",
            "email_verified": True,
            "firebase": {"sign_in_provider": "saml.massgov"},
        },
        db,
    )
    u = added_users[0]
    assert u.auth_provider == "saml.massgov"
    assert u.firebase_uid == "saml_user"
    assert u.email == "judge@mass.gov"


@pytest.mark.asyncio
async def test_google_user_not_promoted_to_court_official() -> None:
    """Only saml.massgov triggers auto-promotion. Google sign-in must stay public."""
    db = _mock_db_returning(first_result=None, second_result=None)
    added_users = []
    db.add = MagicMock(side_effect=lambda u: added_users.append(u))

    await get_or_create_user(
        {
            "uid": "google_uid",
            "email": "also_a_judge@court.gov",
            "email_verified": True,
            "firebase": {"sign_in_provider": "google.com"},  # not SAML
        },
        db,
    )
    assert added_users[0].role_id == 1  # stays public


# ---------------------------------------------------------------------------
# get_websocket_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_websocket_user_valid_room_jwt_returns_guest() -> None:
    token = create_room_token(_SESSION_ID, _RT_REQUEST_ID, "Participant")
    db = AsyncMock()
    ws_user = await get_websocket_user(token, db)
    assert ws_user.is_guest is True
    assert ws_user.partner_name == "Participant"
    assert ws_user.session_id == _SESSION_ID
    assert ws_user.rt_request_id == _RT_REQUEST_ID


@pytest.mark.asyncio
async def test_get_websocket_user_room_jwt_does_not_hit_db() -> None:
    """Room JWT path must be fully local — no DB or Firebase calls."""
    token = create_room_token(_SESSION_ID, _RT_REQUEST_ID, "Participant")
    db = AsyncMock()
    await get_websocket_user(token, db)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_websocket_user_firebase_token_returns_non_guest() -> None:
    mock_user_obj = MagicMock()
    mock_user_obj.firebase_uid = "fb_uid_xyz"
    mock_user_obj.user_id = uuid.uuid4()
    mock_user_obj.email = "judge@court.gov"
    mock_user_obj.name = "Judge Smith"
    mock_user_obj.role_id = 2
    mock_db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=mock_user_obj)
    mock_db.execute = AsyncMock(return_value=r)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    firebase_claims = {
        "uid": "fb_uid_xyz",
        "email": "judge@court.gov",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    with patch("firebase_admin.auth.verify_id_token", return_value=firebase_claims):
        ws_user = await get_websocket_user("firebase-id-token", mock_db)

    assert ws_user.is_guest is False
    assert ws_user.firebase_uid == "fb_uid_xyz"
    assert ws_user.email == "judge@court.gov"


@pytest.mark.asyncio
async def test_get_websocket_user_invalid_token_raises_401() -> None:
    """If neither room JWT nor Firebase token succeeds, must raise 401."""
    mock_db = AsyncMock()
    with (
        patch(
            "firebase_admin.auth.verify_id_token",
            side_effect=_fb_auth.InvalidIdTokenError("bad"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_websocket_user("garbage-token", mock_db)
    assert exc_info.value.status_code == 401
