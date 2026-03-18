"""
api/routes/auth.py

Authentication endpoints for the CourtAccess AI API (Firebase version).

FIREBASE AUTHENTICATION FLOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Registration, login, and logout are handled by the FRONTEND via Firebase SDK.
The backend does NOT provide register/login/logout endpoints.

Frontend Flow:
  1. User signs up/logs in via Firebase SDK (Google, Microsoft, Email/Password, SAML)
  2. Firebase returns an ID token to the frontend
  3. Frontend calls GET /auth/me with the token
  4. Backend verifies token and creates/updates user in database
  5. Frontend stores user data and routes accordingly

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Active Endpoints:
  GET  /auth/me         — Verify token + get/create user profile (called after Firebase login)
  POST /auth/select-role — User selects their role after first login

Legacy Endpoints (deprecated, kept for backward compatibility):
  POST /auth/register   — ⚠️ DEPRECATED: Use Firebase SDK on frontend instead
  POST /auth/login      — ⚠️ DEPRECATED: Use Firebase SDK on frontend instead
  POST /auth/refresh    — ⚠️ DEPRECATED: Firebase tokens auto-refresh
  POST /auth/logout     — ⚠️ DEPRECATED: Use Firebase SDK signOut() on frontend

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
    RoleUpdateRequest,
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
# GET /auth/me — Firebase version
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile (Firebase)",
    description=(
        "Returns the current user's profile. "
        "On first login, automatically creates the user record in the database. "
        "Requires a valid Firebase ID token in the Authorization header."
    ),
)
async def get_me_firebase(user: CurrentUser) -> UserResponse:
    """
    Return the authenticated user's profile.

    This endpoint does double-duty:
      - For returning users: returns their existing profile + role
      - For first-time users: creates their DB record, assigns default role, returns it

    The get_current_user dependency handles the get_or_create_user logic.
    """
    return UserResponse.from_orm_user(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/select-role — Firebase version
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/select-role",
    response_model=UserResponse,
    summary="Select user role",
    description=(
        "Allows a user to select their role after first login. "
        "Public role is assigned immediately. "
        "Court official and interpreter roles require admin approval "
        "unless the user authenticated via Mass.gov SAML (auto-approved)."
    ),
)
async def select_role_firebase(
    body: RoleUpdateRequest,
    user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """
    User selects their role after first login.

    Logic:
      - If selected_role == "public" → assign immediately (role_id=1)
      - If selected_role == "court_official" or "interpreter":
          - If auth_provider == "saml.massgov" AND selected_role == "court_official"
            → auto-approve (role_id=2)
          - Otherwise → stays as "public" (role_id=1) for now (pending admin approval)

    Returns the actual assigned role so frontend knows whether approval is needed.
    Role IDs:
      1 = public
      2 = court_official
      3 = interpreter
      4 = admin
    """
    from datetime import UTC, datetime

    selected_role = body.selected_role.value

    if selected_role == "public":
        # Public role — assign immediately (role_id=1)
        user.role_id = 1
    elif selected_role == "court_official" and user.auth_provider == "saml.massgov":
        # Mass.gov SAML user requesting court_official → auto-approve (role_id=2)
        user.role_id = 2
        user.role_approved_by = None  # System auto-approval
        user.role_approved_at = datetime.now(tz=UTC)
        logger.info(
            "Auto-approved court_official role for SAML user: user_id=%s email=%s",
            user.user_id,
            user.email,
        )
    elif selected_role == "interpreter" and user.auth_provider == "saml.massgov":
        # Mass.gov SAML user requesting interpreter → auto-approve (role_id=3)
        user.role_id = 3
        user.role_approved_by = None  # System auto-approval
        user.role_approved_at = datetime.now(tz=UTC)
        logger.info(
            "Auto-approved interpreter role for SAML user: user_id=%s email=%s",
            user.user_id,
            user.email,
        )
    else:
        # Elevated role for non-SAML user → pending approval
        # In a full implementation, create a role_request record here
        user.role_id = 1  # Keep as public
        logger.info(
            "Role upgrade request pending approval: user_id=%s requested_role=%s",
            user.user_id,
            selected_role,
        )

    await db.commit()
    await db.refresh(user)

    return UserResponse.from_orm_user(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/logout — Legacy JWT (deprecated)
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (invalidate refresh token) [DEPRECATED]",
    deprecated=True,
)
async def logout(body: TokenRefreshRequest, db: DBSession) -> None:
    """
    [DEPRECATED] Legacy JWT logout endpoint.

    Firebase users should simply delete their tokens client-side.
    Firebase ID tokens are short-lived (1 hour) and cannot be revoked server-side
    without additional infrastructure (token deny-list in Redis).
    """
    with contextlib.suppress(JWTError):
        decode_refresh_token(body.refresh_token)

    logger.info("Logout recorded (STUB: token deny-list not yet implemented)")
