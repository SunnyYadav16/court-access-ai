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
    Yield an async SQLAlchemy session for the duration of the request.

    The session is obtained from the connection pool initialized in
    api/main.py lifespan. Rolls back on exception, closes unconditionally.
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
    Validate the Firebase Bearer token and return the current User ORM object.

    Flow:
        1. Extract Bearer token from Authorization header
        2. Verify Firebase ID token (signature, expiry, issuer)
        3. Find or create user in database from token claims
        4. Return User ORM object

    Returns:
        User ORM object with all fields populated

    Raises HTTP 401 if:
      - Authorization header is missing
      - Token is malformed, expired, revoked, or invalid
      - Firebase user account is disabled
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
    Dependency factory — gate an endpoint to specific roles.

    Usage:
        @router.get("/admin")
        async def admin_only(user=Depends(require_role("admin", "court_official"))):
            # user is a User ORM object
            ...

    Raises HTTP 403 if the authenticated user's role is not in *allowed_roles*.
    Role name to role_id mapping:
      public = 1
      court_official = 2
      interpreter = 3
      admin = 4
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
    Dependency — ensure the user has verified their email.

    Usage:
        @router.post("/documents/upload")
        async def upload(user=Depends(require_verified_email)):
            # user.email_verified is guaranteed to be True
            ...

    Raises HTTP 403 if the user's email is not verified.
    Used on sensitive operations like document uploads and session creation.
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
