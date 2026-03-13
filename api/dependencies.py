"""
api/dependencies.py

FastAPI dependency injection for authentication and database access.
Uses Firebase token verification — no local JWT creation needed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_or_create_user, verify_token
from db.database import AsyncSessionLocal
from db.models import User

bearer_scheme = HTTPBearer()


# ── Database session dependency ───────────────────────────────────────────────

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Auth dependencies ─────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify Bearer token and return the current user. Raises 401 if invalid."""
    claims = verify_token(credentials.credentials)
    return await get_or_create_user(claims, db)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """
    Dependency factory for role-based access control.
    Usage: Depends(require_role("court_official", "admin"))
    """
    async def check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user
    return check_role


async def require_verified_email(
    user: User = Depends(get_current_user),
) -> User:
    """Ensures the user's email is verified. Used on document upload routes."""
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required",
        )
    return user