"""
api/auth.py

Authentication for the CourtAccess AI API.

FIREBASE AUTHENTICATION (Primary):
  - verify_firebase_token()     — Validate Firebase ID token and extract claims
  - get_or_create_user()         — Find or create user from Firebase claims

LEGACY JWT AUTHENTICATION (Deprecated):
  - create_access_token()        — Issue custom JWT (to be removed)
  - decode_token()               — Validate custom JWT (to be removed)

The Firebase functions are the primary auth mechanism. The JWT functions
are kept temporarily for backward compatibility.

Roles (defined in api/schemas/schemas.py):
  public | court_official | interpreter | admin
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import firebase_admin.auth as firebase_auth
from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────
# bcrypt is the industry standard for password hashing.
# Using "deprecated='auto'" auto-upgrades older hashes on login.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Token settings ────────────────────────────────────────────────────────────
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"

# ── Token type claim ─────────────────────────────────────────────────────────
_ACCESS_TYPE = "access"
_REFRESH_TYPE = "refresh"


# ══════════════════════════════════════════════════════════════════════════════
# Password helpers
# ══════════════════════════════════════════════════════════════════════════════


def hash_password(plain: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the bcrypt *hashed* value."""
    return _pwd_context.verify(plain, hashed)


# ══════════════════════════════════════════════════════════════════════════════
# Token creation
# ══════════════════════════════════════════════════════════════════════════════


def _build_token(
    subject: str,
    role: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Internal helper — build a signed JWT with standard CourtAccess claims."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,  # user UUID string
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),  # Unique token ID (for potential revocation)
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str, role: str) -> str:
    """
    Issue a short-lived (30 min) access token.

    Args:
        subject: User UUID string.
        role:    One of the UserRole enum values.
    """
    return _build_token(
        subject=subject,
        role=role,
        token_type=_ACCESS_TYPE,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(subject: str, role: str) -> str:
    """
    Issue a long-lived (7 day) refresh token.
    Refresh tokens are accepted only at POST /auth/refresh.
    """
    return _build_token(
        subject=subject,
        role=role,
        token_type=_REFRESH_TYPE,
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_token_pair(subject: str, role: str) -> tuple[str, str]:
    """Return (access_token, refresh_token) for a freshly authenticated user."""
    return create_access_token(subject, role), create_refresh_token(subject, role)


# ══════════════════════════════════════════════════════════════════════════════
# Token decoding / validation
# ══════════════════════════════════════════════════════════════════════════════


class TokenPayload:
    """Parsed, validated JWT payload."""

    __slots__ = ("exp", "jti", "role", "sub", "type")

    def __init__(self, sub: str, role: str, type_: str, jti: str, exp: datetime) -> None:
        self.sub = sub
        self.role = role
        self.type = type_
        self.jti = jti
        self.exp = exp


def decode_token(token: str, expected_type: str = _ACCESS_TYPE) -> TokenPayload:
    """
    Decode and validate a JWT.

    Args:
        token:         Raw JWT string.
        expected_type: 'access' or 'refresh' — raises if type doesn't match.

    Raises:
        JWTError: If the token is expired, invalid, or the wrong type.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        logger.warning("JWT decode failure: %s", exc)
        raise

    if raw.get("type") != expected_type:
        raise JWTError(f"Expected token type '{expected_type}', got '{raw.get('type')}'")

    return TokenPayload(
        sub=raw["sub"],
        role=raw["role"],
        type_=raw["type"],
        jti=raw["jti"],
        exp=datetime.fromtimestamp(raw["exp"], tz=UTC),
    )


def decode_refresh_token(token: str) -> TokenPayload:
    """Convenience wrapper — decode a refresh token specifically."""
    return decode_token(token, expected_type=_REFRESH_TYPE)


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
        decoded_token = firebase_auth.verify_id_token(token)
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

    # Extract auth provider from Firebase claims
    firebase_info = claims.get("firebase", {})
    auth_provider = firebase_info.get("sign_in_provider", "unknown")

    # Check if user exists
    result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    user = result.scalar_one_or_none()

    if user:
        # Existing user — update last login and email verification status
        user.last_login_at = datetime.now(tz=UTC)
        user.email_verified = email_verified
        await db.commit()
        await db.refresh(user)
        logger.info("User logged in: firebase_uid=%s email=%s", firebase_uid, email)
        return user

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
        "New user created: firebase_uid=%s email=%s role_id=%s auth_provider=%s",
        firebase_uid,
        email,
        role_id,
        auth_provider,
    )

    return user
