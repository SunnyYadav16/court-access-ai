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

"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter

from api.auth import _hash_email_for_logging
from api.dependencies import CurrentUser, DBSession
from api.schemas.schemas import RoleUpdateRequest, UserResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


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
    from db.models import RoleRequest

    selected_role = body.selected_role.value
    email_hash = _hash_email_for_logging(user.email)

    # Map role name to role_id
    role_name_to_id = {
        "public": 1,
        "court_official": 2,
        "interpreter": 3,
        "admin": 4,
    }

    if selected_role == "public":
        # Public role — assign immediately (role_id=1)
        user.role_id = 1
    elif selected_role == "court_official" and user.auth_provider == "saml.massgov":
        # Mass.gov SAML user requesting court_official → auto-approve (role_id=2)
        user.role_id = 2
        user.role_approved_by = None  # System auto-approval
        user.role_approved_at = datetime.now(tz=UTC)
        logger.info(
            "Auto-approved court_official role for SAML user: user_id=%s email_hash=%s",
            user.user_id,
            email_hash,
        )
    elif selected_role == "interpreter" and user.auth_provider == "saml.massgov":
        # Mass.gov SAML user requesting interpreter → auto-approve (role_id=3)
        user.role_id = 3
        user.role_approved_by = None  # System auto-approval
        user.role_approved_at = datetime.now(tz=UTC)
        logger.info(
            "Auto-approved interpreter role for SAML user: user_id=%s email_hash=%s",
            user.user_id,
            email_hash,
        )
    else:
        # Elevated role for non-SAML user → create pending role request
        user.role_id = 1  # Keep as public until approved
        requested_role_id = role_name_to_id.get(selected_role, 1)

        role_request = RoleRequest(
            request_id=uuid.uuid4(),
            user_id=user.user_id,
            requested_role_id=requested_role_id,
            status="pending",
            requested_at=datetime.now(tz=UTC),
        )
        db.add(role_request)

        logger.info(
            "Role upgrade request created: user_id=%s email_hash=%s requested_role=%s request_id=%s",
            user.user_id,
            email_hash,
            selected_role,
            role_request.request_id,
        )

    await db.commit()
    await db.refresh(user)

    return UserResponse.from_orm_user(user)
