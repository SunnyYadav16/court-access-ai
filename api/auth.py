"""
api/auth.py

Authentication for the CourtAccess AI API.

FIREBASE AUTHENTICATION:
  - verify_firebase_token()     — Validate Firebase ID token and extract claims
  - get_or_create_user()         — Find or create user from Firebase claims
  - _hash_email_for_logging()    — Privacy-safe email hashing for logs

ROOM JWT (anonymous guest access):
  - create_room_token()         — Issue a short-lived JWT scoped to one session
  - verify_room_token()         — Decode and validate a room JWT
  - WebSocketUser               — Unified user context for WebSocket handlers
  - get_websocket_user()        — Accepts Firebase token OR room JWT, returns WebSocketUser

Roles (defined in api/schemas/schemas.py):
  public | court_official | interpreter | admin
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import firebase_admin.auth as firebase_auth
import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.schemas import ROLE_ID_TO_NAME, UserRole
from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ── Room JWT constants ────────────────────────────────────────────────────────
_ROOM_TOKEN_TYPE = "room"  # noqa: S105 — JWT claim type, not a password
_ROOM_TOKEN_SUBJECT = "guest"  # noqa: S105 — JWT subject identifier, not a password
ROOM_TOKEN_EXPIRE_HOURS = 4


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
        decoded_token = firebase_auth.verify_id_token(token, check_revoked=True)
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


# ══════════════════════════════════════════════════════════════════════════════
# Room JWT — anonymous guest access
# ══════════════════════════════════════════════════════════════════════════════


def create_room_token(
    session_id: uuid.UUID,
    rt_request_id: uuid.UUID,
    partner_name: str,
) -> str:
    """
    Issue a short-lived JWT scoped to a single real-time session.

    This is NOT a Firebase token — it is signed with the app's SECRET_KEY
    and is only valid for joining the specific session it was issued for.

    Claims:
        sub          — "guest" (fixed, distinguishes from Firebase UIDs)
        type         — "room"  (distinguishes from other app JWTs)
        session_id   — UUID of the ConversationRoom this token grants access to
        rt_request_id — UUID of the realtime_request row (for audit trail)
        partner_name — Display name shown in the transcript UI
        iat / exp    — Issued-at and expiry (now + 4 h, long enough for a hearing)

    Args:
        session_id:     ID of the real-time session to scope this token to.
        rt_request_id:  ID of the realtime_request DB row (audit linkage).
        partner_name:   Guest's display name (e.g. "Interpreter", "Client").

    Returns:
        Signed JWT string.
    """
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": _ROOM_TOKEN_SUBJECT,
        "type": _ROOM_TOKEN_TYPE,
        "session_id": str(session_id),
        "rt_request_id": str(rt_request_id),
        "partner_name": partner_name,
        "iat": now,
        "exp": now + timedelta(hours=ROOM_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_room_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a room JWT.

    Verifies the signature, expiry, token type, and subject claim.
    Does NOT hit the database — validation is fully local.

    Args:
        token: JWT string previously issued by create_room_token().

    Returns:
        Decoded payload dict with session_id, rt_request_id, partner_name, etc.

    Raises:
        HTTPException 401 if the token is invalid, expired, or not a room token.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.ExpiredSignatureError as exc:
        logger.warning("Room token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Room token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid room token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid room token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != _ROOM_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid room token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("sub") != _ROOM_TOKEN_SUBJECT:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid room token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# ══════════════════════════════════════════════════════════════════════════════
# Unified WebSocket user context
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class WebSocketUser:
    """
    Unified user context for WebSocket handlers.

    Covers both authentication paths:
      - Firebase-authenticated users (court officials, interpreters, admins)
      - Anonymous guests holding a valid room JWT

    Usage in WebSocket handlers:
        ws_user = await get_websocket_user(token, db)
        if ws_user.is_guest:
            # guest path: ws_user.session_id, ws_user.partner_name are set
        else:
            # Firebase path: ws_user.user_id, ws_user.role, ws_user.email are set
    """

    is_guest: bool
    role: UserRole

    # Firebase-authenticated fields (None for guests)
    firebase_uid: str | None
    user_id: uuid.UUID | None
    email: str | None
    name: str | None

    # Guest-specific fields (None for Firebase users)
    session_id: uuid.UUID | None
    rt_request_id: uuid.UUID | None
    partner_name: str | None


async def get_websocket_user(token: str, db: AsyncSession) -> WebSocketUser:
    """
    Accept either a room JWT or a Firebase ID token and return a WebSocketUser.

    Token resolution order:
      1. Try room JWT first — local decode, no network call, no DB hit.
         Succeeds if the token was issued by create_room_token().
      2. Fall back to Firebase token — validates with Google's key server,
         then looks up / creates the user row in the DB.

    This function is intended to be called directly from WebSocket handlers
    (which receive the token from a query param, not an Authorization header).

    Args:
        token: Raw token string from the WebSocket ?token= query param.
        db:    Async SQLAlchemy session for Firebase-path DB lookups.

    Returns:
        WebSocketUser with is_guest=True (room JWT) or is_guest=False (Firebase).

    Raises:
        HTTPException 401 if both verification paths fail.
    """
    # ── Path 1: room JWT (fast — fully local, no network) ─────────────────
    try:
        claims = verify_room_token(token)
        return WebSocketUser(
            is_guest=True,
            role=UserRole.PUBLIC,  # guests are always public-scoped
            firebase_uid=None,
            user_id=None,
            email=None,
            name=claims.get("partner_name"),
            session_id=uuid.UUID(claims["session_id"]),
            rt_request_id=uuid.UUID(claims["rt_request_id"]),
            partner_name=claims.get("partner_name"),
        )
    except HTTPException:
        pass  # Not a room JWT — fall through to Firebase

    # ── Path 2: Firebase ID token (network + DB) ──────────────────────────
    claims = verify_firebase_token(token)  # raises HTTPException on failure
    user = await get_or_create_user(claims, db)
    user_role = ROLE_ID_TO_NAME.get(user.role_id, UserRole.PUBLIC)

    return WebSocketUser(
        is_guest=False,
        role=user_role,
        firebase_uid=user.firebase_uid,
        user_id=user.user_id,
        email=user.email,
        name=user.name,
        session_id=None,
        rt_request_id=None,
        partner_name=None,
    )
