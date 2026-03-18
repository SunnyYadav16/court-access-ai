"""
api/dependencies.py

FastAPI dependency injection for the CourtAccess AI API.

Provides:
  get_db()              — async SQLAlchemy session (per-request)
  get_current_user()    — validates Bearer token, returns user dict
  require_role(*roles)  — role-gating dependency factory

Usage in route handlers:
    @router.get("/protected")
    async def endpoint(
        db: AsyncSession = Depends(get_db),
        user: dict = Depends(get_current_user),
    ):
        ...

    # Role-gating:
    @router.delete("/admin-only")
    async def admin_endpoint(
        _=Depends(require_role("admin")),
        user: dict = Depends(get_current_user),
    ):
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_or_create_user, verify_firebase_token
from api.schemas.schemas import UserRole
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ── OAuth2 bearer token extractor ─────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


# ══════════════════════════════════════════════════════════════════════════════
# Database session
# ══════════════════════════════════════════════════════════════════════════════


async def get_db():
    """
    Yield an AsyncSession scoped to the current request lifecycle.
    
    Yields a SQLAlchemy AsyncSession taken from the application's connection pool. If an exception occurs while the session is in use, the session is rolled back; the session is always closed after use.
    
    Returns:
        AsyncSession: an async SQLAlchemy session for database operations during the request
    """
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ══════════════════════════════════════════════════════════════════════════════
# Authentication dependency
# ══════════════════════════════════════════════════════════════════════════════


_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

_EXPIRED_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Token has expired",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Authenticate the request using a Firebase Bearer token and return the corresponding User ORM object.
    
    Verifies the provided ID token, maps its claims to a user record, and returns the matching or newly created User ORM instance.
    
    Returns:
        User ORM object representing the authenticated user.
    
    Raises:
        HTTP 401 if the Authorization bearer token is missing, invalid, or expired.
    """
    if credentials is None:
        raise _CREDENTIALS_EXCEPTION

    # Verify Firebase token and extract claims
    claims = verify_firebase_token(credentials.credentials)

    # Get or create user from claims
    user = await get_or_create_user(claims, db)

    return user


# ══════════════════════════════════════════════════════════════════════════════
# Role-based access control
# ══════════════════════════════════════════════════════════════════════════════


def require_role(*allowed_roles: str):
    """
    Create a FastAPI dependency that restricts access to users to the specified roles.
    
    Accepts role names (strings) or UserRole enum values and maps them to internal role IDs:
      public = 1, court_official = 2, interpreter = 3, admin = 4.
    Invalid role names are ignored when building the allowed set.
    
    Returns:
        A dependency callable that, when used, returns the authenticated User ORM object if the user's `role_id` is one of the allowed role IDs; raises HTTP 403 otherwise.
    """
    # Map role names to role_ids
    role_name_to_id = {
        "public": 1,
        "court_official": 2,
        "interpreter": 3,
        "admin": 4,
    }

    allowed_role_ids = {role_name_to_id.get(r.value if isinstance(r, UserRole) else r) for r in allowed_roles}
    allowed_role_ids.discard(None)  # Remove None if any invalid role names

    async def _check(
        user: Annotated[Any, Depends(get_current_user)],
    ):
        """
        Ensure the authenticated user's role is one of the allowed roles.
        
        Parameters:
            user (Any): The current authenticated user ORM object (must have `role_id` and `user_id` attributes).
        
        Returns:
            Any: The same authenticated user object when their role is permitted.
        
        Raises:
            HTTPException: HTTP 403 Forbidden if the user's role_id is not in the allowed set.
        """
        if user.role_id not in allowed_role_ids:
            logger.warning(
                "Role check failed: user_id=%s role_id=%s required_role_ids=%s",
                user.user_id,
                user.role_id,
                allowed_role_ids,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires one of: {sorted(allowed_roles)}",
            )
        return user

    return _check


async def require_verified_email(
    user: Annotated[Any, Depends(get_current_user)],
):
    """
    Require that the authenticated user's email address is verified.
    
    Raises HTTPException with status 403 if the user's email is not verified.
    
    Returns:
        The authenticated user object.
    
    Raises:
        HTTPException: If the user's `email_verified` is False (403 Forbidden).
    """
    if not user.email_verified:
        logger.warning(
            "Email verification required: user_id=%s email=%s",
            user.user_id,
            user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Please verify your email before using this feature.",
        )
    return user


# ══════════════════════════════════════════════════════════════════════════════
# Convenience type aliases for route signatures
# ══════════════════════════════════════════════════════════════════════════════

# Import User model for type hints

if TYPE_CHECKING:
    pass

CurrentUser = Annotated[Any, Depends(get_current_user)]  # Returns User ORM object
DBSession = Annotated[AsyncSession, Depends(get_db)]
