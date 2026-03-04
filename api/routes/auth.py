"""
api/routes/auth.py

Authentication endpoints for the CourtAccess AI API.

Endpoints:
  POST /auth/register  — Create a new user account
  POST /auth/login     — Exchange credentials for a JWT token pair
  POST /auth/refresh   — Rotate a refresh token into a new access token
  GET  /auth/me        — Return the authenticated user's profile
  POST /auth/logout    — Invalidate refresh token (client-side + token deny-list)
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from jose import JWTError

from api.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_token_pair,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from api.dependencies import CurrentUser, DBSession
from api.schemas.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenRefreshRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── In-memory user store (replace with DB in production) ─────────────────────
# Schema: { user_id_str: { "user_id", "username", "email", "hashed_password", "role", "preferred_language", "created_at" } }
_users_by_id: dict[str, dict] = {}
_users_by_username: dict[str, str] = {}  # username → user_id
_users_by_email: dict[str, str] = {}  # email    → user_id


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/register
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(body: RegisterRequest, db: DBSession) -> UserResponse:
    """
    Create a new user account.

    Business rules:
      - Username and email must be unique
      - Password is bcrypt hashed before storage
      - Default role is 'public'

    TODO (production):
      - Persist to db via db/models.py User model
      - Send email verification link
      - Rate-limit registration by IP
    """
    if body.username.lower() in _users_by_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )
    if body.email.lower() in _users_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user_id = str(uuid.uuid4())
    now = datetime.now(tz=UTC)
    user = {
        "user_id": uuid.UUID(user_id),
        "username": body.username,
        "email": body.email.lower(),
        "hashed_password": hash_password(body.password),
        "role": body.role.value,
        "preferred_language": body.preferred_language.value,
        "created_at": now,
    }

    _users_by_id[user_id] = user
    _users_by_username[body.username.lower()] = user_id
    _users_by_email[body.email.lower()] = user_id

    logger.info("New user registered: user_id=%s username=%s role=%s", user_id, body.username, body.role)

    return UserResponse(
        user_id=user["user_id"],
        username=user["username"],
        email=user["email"],
        role=user["role"],
        preferred_language=user["preferred_language"],
        created_at=user["created_at"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/login
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with username and password",
)
async def login(body: LoginRequest, db: DBSession) -> TokenResponse:
    """
    Validate credentials and return a JWT access + refresh token pair.

    TODO (production):
      - Query User from DB by username
      - Add brute-force protection (lockout after N failures)
    """
    uid = _users_by_username.get(body.username.lower())
    if not uid:
        # Deliberately vague — don't reveal whether username exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = _users_by_id[uid]
    if not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, refresh_token = create_token_pair(subject=uid, role=user["role"])
    logger.info("Login successful: user_id=%s role=%s", uid, user["role"])

    from api.auth import ACCESS_TOKEN_EXPIRE_MINUTES

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",  # noqa: S106
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/refresh
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh an access token",
    description=(
        "Exchange a valid refresh token for a new access + refresh token pair. The old refresh token is invalidated."
    ),
)
async def refresh_token(body: TokenRefreshRequest, db: DBSession) -> TokenResponse:
    """
    Rotate the refresh token and issue a new access token.

    Design note: refresh token rotation — the old refresh token is invalidated
    on every use. This limits the damage window if a refresh token is leaked.

    TODO (production):
      - Check refresh token against deny-list (Redis SET with TTL)
      - Add old refresh token to deny-list after successful rotation
    """
    try:
        payload = decode_refresh_token(body.refresh_token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = _users_by_id.get(payload.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found",
        )

    access_token, new_refresh = create_token_pair(subject=payload.sub, role=payload.role)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh,
        token_type="bearer",  # noqa: S106
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /auth/me
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(user: CurrentUser, db: DBSession) -> UserResponse:
    """
    Return the profile of the currently authenticated user.

    TODO (production): Query user from DB by user["user_id"].
    """
    uid = user["user_id"]
    db_user = _users_by_id.get(uid)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserResponse(
        user_id=db_user["user_id"],
        username=db_user["username"],
        email=db_user["email"],
        role=db_user["role"],
        preferred_language=db_user["preferred_language"],
        created_at=db_user["created_at"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/logout
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (invalidate refresh token)",
)
async def logout(body: TokenRefreshRequest, db: DBSession) -> None:
    """
    Invalidate the provided refresh token server-side.

    Client should also delete the access token from local storage.

    TODO (production):
      - Add refresh token JTI to Redis deny-list with TTL = token expiry
      - Return 204 even if token is already expired (idempotent logout)
    """
    with contextlib.suppress(JWTError):
        decode_refresh_token(body.refresh_token)

    logger.info("Logout recorded (STUB: token deny-list not yet implemented)")
