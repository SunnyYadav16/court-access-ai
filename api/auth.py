"""
api/auth.py

JWT authentication for the CourtAccess AI API.

Token strategy:
  - Access tokens:  short-lived (30 min), used in Authorization: Bearer header
  - Refresh tokens: long-lived (7 days), used only to issue new access tokens
  - Algorithm:      HS256 with SECRET_KEY from settings

Roles (defined in api/schemas/schemas.py):
  public | court_official | interpreter | admin

Usage:
    token = create_access_token(subject="user-uuid", role=UserRole.PUBLIC)
    payload = decode_token(token)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

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
