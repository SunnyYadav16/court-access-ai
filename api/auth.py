"""
api/auth.py

Authentication for the CourtAccess AI API.

FIREBASE AUTHENTICATION:
  - verify_firebase_token()     — Validate Firebase ID token and extract claims
  - get_or_create_user()         — Find or create user from Firebase claims
  - _hash_email_for_logging()    — Privacy-safe email hashing for logs

Roles (defined in api/schemas/schemas.py):
  public | court_official | interpreter | admin
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import firebase_admin.auth as firebase_auth
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Privacy helpers
# ══════════════════════════════════════════════════════════════════════════════


def _hash_email_for_logging(email: str) -> str:
    """
    Hash email for privacy-safe logging.
    Returns first 8 characters of SHA-256 hash (sufficient for log correlation).
    """
    return hashlib.sha256(email.encode()).hexdigest()[:8]


# ══════════════════════════════════════════════════════════════════════════════
# Firebase Authentication (Primary)
# ══════════════════════════════════════════════════════════════════════════════


def verify_firebase_token(token: str) -> dict[str, Any]:
    """
    Verify a Firebase ID token and return decoded claims.

    Args:
        token: Firebase ID token from the Authorization header

    Returns:
        Dict containing Firebase claims:
            {
                "uid": "abc123...",
                "email": "user@example.com",
                "email_verified": True,
                "name": "User Name",
                "firebase": {
                    "sign_in_provider": "google.com"  # or "password", "microsoft.com", "saml.massgov"
                },
                "iat": 1234567890,
                "exp": 1234571490,
                ...
            }

    Raises:
        HTTPException: 401 with specific error message for each failure case
    """
    try:
        # verify_id_token() does the following:
        # 1. Downloads Google's public keys (cached, auto-rotated)
        # 2. Verifies the JWT signature
        # 3. Checks expiry (exp), audience (aud), issuer (iss)
        # 4. Returns decoded payload
        decoded_token = firebase_auth.verify_id_token(token, check_revoked=False)
        return decoded_token

    except firebase_auth.ExpiredIdTokenError as exc:
        logger.warning("Firebase token expired: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except firebase_auth.RevokedIdTokenError as exc:
        logger.warning("Firebase token revoked: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revoked",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except firebase_auth.InvalidIdTokenError as exc:
        logger.warning("Invalid Firebase token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except firebase_auth.UserDisabledError as exc:
        logger.warning("Firebase user disabled: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    except Exception as exc:
        logger.exception("Firebase token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_or_create_user(claims: dict[str, Any], db: AsyncSession):
    """
    Find or create a user from Firebase token claims.

    Args:
        claims: Decoded Firebase ID token claims from verify_firebase_token()
        db: Async SQLAlchemy session

    Returns:
        User ORM object

    Business logic:
        - If user exists: Update last_login_at and email_verified, return user
        - If new user:
            - Extract profile data from claims
            - Auto-assign court_official role (role_id=2) if auth_provider is "saml.massgov"
            - Otherwise assign public role (role_id=1)
            - Create user record
    """
    from db.models import User  # Import here to avoid circular dependency

    firebase_uid = claims["uid"]
    email = claims.get("email", "")
    name = claims.get("name", "")
    email_verified = claims.get("email_verified", False)

    # Reject tokens without a usable email
    if not email or not email.strip():
        logger.warning("Firebase token missing email: firebase_uid=%s", firebase_uid)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email address required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Hash email for privacy-safe logging
    hashed_email = _hash_email_for_logging(email)

    # Extract auth provider from Firebase claims
    firebase_info = claims.get("firebase", {})
    auth_provider = firebase_info.get("sign_in_provider", "unknown")

    # Check if user exists by firebase_uid
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()

    if user:
        # Existing user — update last login and email verification status
        user.last_login_at = datetime.now(tz=UTC)
        user.email_verified = email_verified
        await db.commit()
        await db.refresh(user)
        logger.info("User logged in: firebase_uid=%s email_hash=%s", firebase_uid, hashed_email)
        return user

    # User not found by firebase_uid — check if account exists by email
    result = await db.execute(select(User).where(User.email == email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        # Backfill Firebase UID for existing email-based account
        logger.info(
            "Backfilling Firebase UID for existing user: email_hash=%s firebase_uid=%s",
            hashed_email,
            firebase_uid,
        )
        existing_user.firebase_uid = firebase_uid
        existing_user.auth_provider = auth_provider
        existing_user.last_login_at = datetime.now(tz=UTC)
        existing_user.email_verified = email_verified
        await db.commit()
        await db.refresh(existing_user)
        return existing_user

    # New user — create account
    # Auto-promote to court_official (role_id=2) if authenticated via Mass.gov SAML
    # Otherwise assign public role (role_id=1)
    role_id = 2 if auth_provider == "saml.massgov" else 1

    user = User(
        firebase_uid=firebase_uid,
        email=email,
        name=name if name else email.split("@")[0],
        role_id=role_id,
        auth_provider=auth_provider,
        email_verified=email_verified,
        mfa_enabled=False,
        last_login_at=datetime.now(tz=UTC),
        created_at=datetime.now(tz=UTC),
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(
        "New user created: firebase_uid=%s email_hash=%s role_id=%s auth_provider=%s",
        firebase_uid,
        hashed_email,
        role_id,
        auth_provider,
    )

    return user
