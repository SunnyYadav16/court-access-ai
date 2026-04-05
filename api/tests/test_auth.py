"""
api/tests/test_auth.py

Unit tests for the authentication and identity-merging logic in api/auth.py.
Proves that the backend correctly handles edge cases (like expired tokens)
and merges existing users to avoid duplicates.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from firebase_admin import auth as firebase_auth

from api.auth import get_or_create_user, verify_firebase_token
from db.models import User


# ══════════════════════════════════════════════════════════════════════════════
# Test verify_firebase_token (Security Guard)
# ══════════════════════════════════════════════════════════════════════════════


def test_verify_firebase_token_success():
    """Valid token should return the decoded claims."""
    with patch("api.auth.firebase_auth.verify_id_token") as mock_verify:
        mock_verify.return_value = {"uid": "abc12345", "email": "test@example.com"}
        claims = verify_firebase_token("fake-valid-token")
        assert claims["uid"] == "abc12345"
        mock_verify.assert_called_once_with("fake-valid-token", check_revoked=True)


def test_verify_firebase_token_expired():
    """Expired token should raise HTTPException(401) with 'Token expired'."""
    with patch("api.auth.firebase_auth.verify_id_token", side_effect=firebase_auth.ExpiredIdTokenError("expired", MagicMock())):
        with pytest.raises(HTTPException) as exc:
            verify_firebase_token("fake-expired-token")
        assert exc.value.status_code == 401
        assert "Token expired" in exc.value.detail


def test_verify_firebase_token_revoked():
    """Revoked token should raise HTTPException(401)."""
    with patch("api.auth.firebase_auth.verify_id_token", side_effect=firebase_auth.RevokedIdTokenError("revoked")):
        with pytest.raises(HTTPException) as exc:
            verify_firebase_token("fake-revoked-token")
        assert exc.value.status_code == 401
        assert "Token revoked" in exc.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# Test get_or_create_user (Identity Merging)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_or_create_user_new():
    """A completely new user should be created with role_id=1 (public)."""
    claims = {
        "uid": "new-uid",
        "email": "newuser@example.com",
        "name": "New User",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"}
    }
    
    # Mock DB where user does not exist by UID or Email
    mock_db = AsyncMock()
    # First execute() is for UID lookup, second is for Email lookup
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.side_effect = [None, None]
    mock_db.execute.return_value = mock_result
    
    user = await get_or_create_user(claims, mock_db)
    
    assert user.firebase_uid == "new-uid"
    assert user.email == "newuser@example.com"
    assert user.role_id == 1  # Public role
    
    # Verify DB add + commit was called
    mock_db.add.assert_called_once()
    mock_db.commit.assert_called_once()
    mock_db.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_user_saml_promotion():
    """A saml.massgov user should be auto-promoted to role_id=2 (court_official)."""
    claims = {
        "uid": "saml-uid",
        "email": "official@mass.gov",
        "firebase": {"sign_in_provider": "saml.massgov"}
    }
    
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.side_effect = [None, None]
    mock_db.execute.return_value = mock_result
    
    user = await get_or_create_user(claims, mock_db)
    
    assert user.firebase_uid == "saml-uid"
    assert user.role_id == 2  # Court Official role
    assert user.auth_provider == "saml.massgov"


@pytest.mark.asyncio
async def test_get_or_create_user_identity_merge():
    """If user logs in with new UID but existing email, account should be backfilled/merged."""
    claims = {
        "uid": "new-oauth-uid",
        "email": "existing@example.com",
        "firebase": {"sign_in_provider": "microsoft.com"}
    }
    
    # Simulate existing DB user with the same email but different/no Firebase UID
    existing_user = User(
        user_id=uuid.uuid4(),
        email="existing@example.com",
        firebase_uid=None,  # Legacy account before Firebase, or different provider
        role_id=3  # e.g., an interpreter
    )
    
    mock_db = AsyncMock()
    # First call (UID lookup) returns None. Second call (Email lookup) returns existing_user.
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.side_effect = [None, existing_user]
    mock_db.execute.return_value = mock_result
    
    user = await get_or_create_user(claims, mock_db)
    
    # Should be the same exact Python object
    assert user is existing_user
    # The UID and provider should now be backfilled
    assert user.firebase_uid == "new-oauth-uid"
    assert user.auth_provider == "microsoft.com"
    # Role should remain untouched (protects against downgrade)
    assert user.role_id == 3
    
    # Verify DB add was NOT called, but commit was
    mock_db.add.assert_not_called()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_user_missing_email():
    """Tokens without an email address should be rejected."""
    claims = {"uid": "ano-uid", "email": ""}
    
    # Does not even need to touch the DB
    with pytest.raises(HTTPException) as exc:
        await get_or_create_user(claims, AsyncMock())
        
    assert exc.value.status_code == 401
    assert "Email address required" in exc.value.detail
