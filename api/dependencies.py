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

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import decode_token
from api.schemas.schemas import UserRole
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# ── OAuth2 bearer token extractor ─────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


# ══════════════════════════════════════════════════════════════════════════════
# Database session
# ══════════════════════════════════════════════════════════════════════════════


async def get_db() -> AsyncSession:  # type: ignore[return]
    """
    Yield an async SQLAlchemy session for the duration of the request.

    The session is obtained from the connection pool initialised in
    api/main.py lifespan. Rolls back on exception, closes unconditionally.

    NOTE: Replace the stub below with the real import once db/models.py
          and the engine are wired up:

        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            yield session
    """
    # STUB — yields None until the real DB engine is wired in main.py lifespan.
    # Route handlers that call get_db() will need the real implementation
    # before making any ORM calls.
    logger.debug("get_db() called — STUB: no real session yet")
    yield None  # type: ignore[misc]


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
) -> dict:
    """
    Validate the Bearer token and return the current user dict.

    Returns a minimal dict:
        {
            "user_id": str,   # UUID string from token 'sub' claim
            "role":    str,   # One of UserRole values
        }

    Raises HTTP 401 if:
      - Authorization header is missing
      - Token is malformed or expired
      - Token is a refresh token (wrong type)

    NOTE: In production this should also query the database to confirm
          the user still exists and is not banned. Wire in get_db() once
          db/models.py is ready.
    """
    if credentials is None:
        raise _CREDENTIALS_EXCEPTION

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except JWTError as exc:
        logger.warning("Token validation failed: %s", exc)
        if "expired" in str(exc).lower():
            raise _EXPIRED_EXCEPTION from exc
        raise _CREDENTIALS_EXCEPTION from exc

    return {"user_id": payload.sub, "role": payload.role}


# ══════════════════════════════════════════════════════════════════════════════
# Role-based access control
# ══════════════════════════════════════════════════════════════════════════════


def require_role(*allowed_roles: str):
    """
    Dependency factory — gate an endpoint to specific roles.

    Usage:
        @router.get("/admin")
        async def admin_only(_=Depends(require_role("admin", "court_official"))):
            ...

    Raises HTTP 403 if the authenticated user's role is not in *allowed_roles*.
    """
    allowed_set = {r.value if isinstance(r, UserRole) else r for r in allowed_roles}

    async def _check(
        user: Annotated[dict, Depends(get_current_user)],
    ) -> dict:
        if user["role"] not in allowed_set:
            logger.warning(
                "Role check failed: user_id=%s role=%s required=%s",
                user["user_id"],
                user["role"],
                allowed_set,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires one of: {sorted(allowed_set)}",
            )
        return user

    return _check


# ══════════════════════════════════════════════════════════════════════════════
# Convenience type aliases for route signatures
# ══════════════════════════════════════════════════════════════════════════════

CurrentUser = Annotated[dict, Depends(get_current_user)]
DBSession = Annotated[AsyncSession | None, Depends(get_db)]
