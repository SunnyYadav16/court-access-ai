"""
api/tests/test_dependencies.py

Unit tests for FastAPI dependency functions in api/dependencies.py.
Tests require_role and require_verified_email directly (no HTTP layer).
"""

import os

os.environ.setdefault("GCS_BUCKET_TRANSCRIPTS", "test-transcripts")
os.environ.setdefault("USE_REAL_SPEECH", "false")
os.environ.setdefault("ROOM_JWT_SECRET", "test-room-jwt-secret-for-testing-only")
os.environ.setdefault("ROOM_JWT_EXPIRY_HOURS", "4")
os.environ.setdefault("ROOM_CODE_EXPIRY_MINUTES", "30")

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.dependencies import require_role, require_verified_email

_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _user(role_id: int = 1, email_verified: bool = True) -> MagicMock:
    u = MagicMock()
    u.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    u.role_id = role_id
    u.email = "t@example.com"
    u.email_verified = email_verified
    return u


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_role_admin_passes_admin_user() -> None:
    checker = require_role("admin")
    admin_user = _user(role_id=4)
    result = await checker(user=admin_user)
    assert result is admin_user


@pytest.mark.asyncio
async def test_require_role_admin_rejects_public_user() -> None:
    checker = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_user(role_id=1))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_court_official_accepts_court_official() -> None:
    checker = require_role("court_official")
    result = await checker(user=_user(role_id=2))
    assert result.role_id == 2


@pytest.mark.asyncio
async def test_require_role_court_official_rejects_interpreter() -> None:
    checker = require_role("court_official")
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_user(role_id=3))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_multiple_roles_accepts_any_listed() -> None:
    checker = require_role("admin", "court_official")
    for role_id in (2, 4):
        result = await checker(user=_user(role_id=role_id))
        assert result.role_id == role_id


@pytest.mark.asyncio
async def test_require_role_multiple_roles_rejects_unlisted() -> None:
    checker = require_role("admin", "court_official")
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_user(role_id=1))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_error_message_mentions_required_roles() -> None:
    checker = require_role("admin")
    with pytest.raises(HTTPException) as exc_info:
        await checker(user=_user(role_id=1))
    assert "admin" in exc_info.value.detail


# ---------------------------------------------------------------------------
# require_verified_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_verified_email_passes_verified_user() -> None:
    user = _user(email_verified=True)
    result = await require_verified_email(user=user)
    assert result is user


@pytest.mark.asyncio
async def test_require_verified_email_rejects_unverified_user() -> None:
    user = _user(email_verified=False)
    with pytest.raises(HTTPException) as exc_info:
        await require_verified_email(user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_verified_email_detail_mentions_verification() -> None:
    user = _user(email_verified=False)
    with pytest.raises(HTTPException) as exc_info:
        await require_verified_email(user=user)
    assert "verif" in exc_info.value.detail.lower()
