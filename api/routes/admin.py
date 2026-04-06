"""
api/routes/admin.py

Admin-only endpoints for the CourtAccess AI API.

All routes are gated by require_role("admin") and require a valid Bearer token.

Endpoints:
  GET  /admin/users             — List all users with their roles
  GET  /admin/users/{user_id}   — Get a single user's profile
  POST /admin/users/{user_id}/role — Promote or demote a user's role
  GET  /admin/role-requests      — List pending role upgrade requests
  POST /admin/role-requests/{request_id}/approve — Approve a role request
  POST /admin/role-requests/{request_id}/reject  — Reject a role request
  GET  /admin/audit-logs         — Paginated audit trail
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import UserResponse
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    # Every route in this file requires admin role.
    # Individual routes still declare the dependency explicitly for
    # OpenAPI schema visibility.
    dependencies=[Depends(require_role("admin"))],
)

_AdminUser = Annotated[CurrentUser, Depends(require_role("admin"))]


# ══════════════════════════════════════════════════════════════════════════════
# Response models
# ══════════════════════════════════════════════════════════════════════════════


class RoleAssignRequest(BaseModel):
    role_name: str  # "public" | "court_official" | "interpreter" | "admin"


class RoleRequestDecision(BaseModel):
    notes: str | None = None


class RoleRequestSummary(BaseModel):
    request_id: uuid.UUID
    user_id: uuid.UUID
    requested_role_id: int
    status: str
    requested_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/users
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/users",
    summary="List all users (admin only)",
    response_model=list[UserResponse],
)
async def list_users(
    admin: _AdminUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> list[UserResponse]:
    """Return all registered users, ordered by created_at desc."""
    from db.models import User

    result = await db.execute(
        select(User).order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    users = result.scalars().all()
    return [UserResponse.from_orm_user(u) for u in users]


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/users/{user_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/users/{user_id}",
    summary="Get a user's profile (admin only)",
    response_model=UserResponse,
)
async def get_user(
    user_id: uuid.UUID,
    admin: _AdminUser,
    db: DBSession,
) -> UserResponse:
    from db.models import User

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.from_orm_user(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/users/{user_id}/role
# ══════════════════════════════════════════════════════════════════════════════


_ROLE_MAP = {"public": 1, "court_official": 2, "interpreter": 3, "admin": 4}


@router.post(
    "/users/{user_id}/role",
    summary="Set a user's role (admin only)",
    response_model=UserResponse,
)
async def set_user_role(
    user_id: uuid.UUID,
    body: RoleAssignRequest,
    admin: _AdminUser,
    db: DBSession,
) -> UserResponse:
    """Directly promote or demote any user to any role."""
    from db.models import User
    from db.queries.audit import write_audit

    role_id = _ROLE_MAP.get(body.role_name)
    if role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown role '{body.role_name}'. Must be one of: {list(_ROLE_MAP)}",
        )

    result = await db.execute(select(User).where(User.user_id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_role_id = target.role_id
    target.role_id = role_id
    target.role_approved_by = admin.user_id
    target.role_approved_at = datetime.now(tz=UTC)

    await write_audit(
        db,
        user_id=admin.user_id,
        action_type="admin_role_change",
        details={
            "target_user_id": str(user_id),
            "old_role_id": old_role_id,
            "new_role_id": role_id,
            "new_role_name": body.role_name,
        },
    )
    await db.commit()
    await db.refresh(target)

    logger.info(
        "Admin role change: target_user=%s old_role=%s new_role=%s by admin=%s",
        user_id,
        old_role_id,
        role_id,
        admin.user_id,
    )
    return UserResponse.from_orm_user(target)


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/role-requests
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/role-requests",
    summary="List role upgrade requests (admin only)",
    response_model=list[RoleRequestSummary],
)
async def list_role_requests(
    admin: _AdminUser,
    db: DBSession,
    pending_only: bool = Query(default=True, description="If true, return only 'pending' requests"),
) -> list[RoleRequestSummary]:
    from db.models import RoleRequest

    q = select(RoleRequest).order_by(desc(RoleRequest.requested_at))
    if pending_only:
        q = q.where(RoleRequest.status == "pending")
    result = await db.execute(q)
    return result.scalars().all()


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/role-requests/{request_id}/approve
# POST /admin/role-requests/{request_id}/reject
# ══════════════════════════════════════════════════════════════════════════════


async def _resolve_role_request(
    request_id: uuid.UUID,
    decision: str,  # "approved" | "rejected"
    admin_user_id: uuid.UUID,
    db: DBSession,
    notes: str | None,
) -> RoleRequestSummary:
    from db.models import RoleRequest, User
    from db.queries.audit import write_audit

    result = await db.execute(select(RoleRequest).where(RoleRequest.request_id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role request not found")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role request is already '{req.status}'",
        )

    req.status = decision
    req.reviewed_by = admin_user_id
    req.reviewed_at = datetime.now(tz=UTC)

    if decision == "approved":
        user_result = await db.execute(select(User).where(User.user_id == req.user_id))
        target = user_result.scalar_one_or_none()
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {req.user_id} not found — cannot apply role approval.",
            )
        target.role_id = req.requested_role_id
        target.role_approved_by = admin_user_id
        target.role_approved_at = req.reviewed_at

    await write_audit(
        db,
        user_id=admin_user_id,
        action_type=f"role_request_{decision}",
        details={"request_id": str(request_id), "notes": notes},
    )
    await db.commit()
    await db.refresh(req)
    return req


@router.post(
    "/role-requests/{request_id}/approve",
    summary="Approve a role request (admin only)",
    response_model=RoleRequestSummary,
)
async def approve_role_request(
    request_id: uuid.UUID,
    body: RoleRequestDecision,
    admin: _AdminUser,
    db: DBSession,
) -> RoleRequestSummary:
    return await _resolve_role_request(request_id, "approved", admin.user_id, db, body.notes)


@router.post(
    "/role-requests/{request_id}/reject",
    summary="Reject a role request (admin only)",
    response_model=RoleRequestSummary,
)
async def reject_role_request(
    request_id: uuid.UUID,
    body: RoleRequestDecision,
    admin: _AdminUser,
    db: DBSession,
) -> RoleRequestSummary:
    return await _resolve_role_request(request_id, "rejected", admin.user_id, db, body.notes)


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/audit-logs
# ══════════════════════════════════════════════════════════════════════════════


class AuditLogSummary(BaseModel):
    audit_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    action_type: str
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get(
    "/audit-logs",
    summary="List audit logs (admin only)",
    response_model=list[AuditLogSummary],
)
async def list_audit_logs(
    admin: _AdminUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> list[AuditLogSummary]:
    from db.models import AuditLog

    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    return result.scalars().all()
