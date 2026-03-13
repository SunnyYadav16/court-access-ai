"""
api/routes/auth.py

Firebase-based authentication endpoints for CourtAccess AI.

Endpoints:
  GET  /auth/me             — Return authenticated user profile
  GET  /auth/check-email    — Check if email exists (for password reset UX)
  POST /auth/select-role    — User selects their role on first login
  POST /auth/approve-role   — Admin approves a role upgrade
  POST /auth/revoke         — Admin revokes all sessions for a user
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import CurrentUser, DBSession, get_current_user, require_role
from api.schemas.schemas import (
    AuthStatusResponse,
    RoleApprovalRequest,
    RoleUpdateRequest,
    UserResponse,
)
from db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

VALID_ROLES = {"public", "court_official", "interpreter", "admin"}


# ══════════════════════════════════════════════════════════════════════════════
# GET /auth/me
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/me", response_model=AuthStatusResponse, summary="Get current user profile")
async def get_me(user: CurrentUser) -> AuthStatusResponse:
    """Return current user info. Frontend calls this on app load."""
    return AuthStatusResponse(
        is_authenticated=True,
        user=UserResponse.model_validate(user),
        requires_email_verification=not user.email_verified,
        requires_role_selection=user.role == "public",
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /auth/check-email
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/check-email", summary="Check if email exists")
async def check_email(email: str, db: DBSession) -> dict:
    """
    Public endpoint — check if an email exists in the database.
    Used by the frontend before sending a password reset link.
    Firebase silently succeeds for unknown emails, so we check here instead.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    return {"exists": user is not None}


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/select-role
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/select-role", response_model=UserResponse, summary="Select user role")
async def select_role(
    body: RoleUpdateRequest,
    user: CurrentUser,
    db: DBSession,
) -> UserResponse:
    """
    User selects their role after first login.
    - 'public': applied immediately
    - 'court_official' / 'interpreter': stored as pending until admin approves
    - Exception: saml.massgov users get 'court_official' immediately
    """
    if body.selected_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    auto_approve = (
        body.selected_role == "court_official"
        and user.auth_provider == "saml.massgov"
    )

    if body.selected_role == "public" or auto_approve:
        user.role = body.selected_role
        user.role_approved_at = datetime.now(timezone.utc)
        user.role_approved_by = "auto" if auto_approve else "self"
    else:
        user.role = body.selected_role  # pending admin approval

    await db.commit()
    await db.refresh(user)
    logger.info("Role selected: user_id=%s role=%s", user.user_id, user.role)
    return UserResponse.model_validate(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/approve-role
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/approve-role", response_model=UserResponse, summary="Approve role (admin only)")
async def approve_role(
    body: RoleApprovalRequest,
    db: DBSession,
    admin: User = Depends(require_role("admin")),
) -> UserResponse:
    """Admin approves a user's role and embeds it in their Firebase JWT."""
    if body.approved_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    result = await db.execute(select(User).where(User.firebase_uid == body.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = body.approved_role
    user.role_approved_by = str(admin.user_id)
    user.role_approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    # Embed role in Firebase JWT custom claims
    # Frontend must call getIdToken(true) to pick up the new claim
    firebase_auth.set_custom_user_claims(body.user_id, {"role": body.approved_role})
    logger.info("Role approved: target=%s role=%s by admin=%s", body.user_id, body.approved_role, admin.user_id)

    return UserResponse.model_validate(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /auth/revoke
# ══════════════════════════════════════════════════════════════════════════════


@router.post("/revoke", summary="Revoke all sessions (admin only)")
async def revoke_user(
    body: RoleApprovalRequest,
    admin: User = Depends(require_role("admin")),
) -> dict:
    """Admin immediately invalidates all sessions for a user."""
    firebase_auth.revoke_refresh_tokens(body.user_id)
    logger.info("Sessions revoked: target=%s by admin=%s", body.user_id, admin.user_id)
    return {"revoked": True, "user_id": body.user_id}