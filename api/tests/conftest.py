"""
api/tests/conftest.py

Shared fixtures for the API test suite.

Design:
  - Sets 5 env vars that are absent from .env BEFORE any imports that
    could trigger Settings() instantiation.
  - Builds a minimal FastAPI test app (no lifespan) with all routes
    mounted and get_current_user / get_db overridden via dependency_overrides.
  - Exposes client / admin_client / unverified_client / saml_client /
    interpreter_client / court_official_client_b fixtures.
"""

import os

# ---------------------------------------------------------------------------
# MUST run before any courtaccess/api import that calls get_settings()
# ---------------------------------------------------------------------------
os.environ.setdefault("GCS_BUCKET_TRANSCRIPTS", "test-transcripts")
os.environ.setdefault("USE_REAL_SPEECH", "false")
os.environ.setdefault("ROOM_JWT_SECRET", "test-room-jwt-secret-for-testing-only")
os.environ.setdefault("ROOM_JWT_EXPIRY_HOURS", "4")
os.environ.setdefault("ROOM_CODE_EXPIRY_MINUTES", "30")

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# User factory
# ---------------------------------------------------------------------------

_FIXED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_FIXED_USER_ID_B = uuid.UUID("00000000-0000-0000-0000-000000000002")
_FIXED_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _make_user(
    role_id: int = 1,
    email_verified: bool = True,
    auth_provider: str = "google.com",
    user_id: uuid.UUID | None = None,
) -> MagicMock:
    """Return a mock User ORM object with all fields FastAPI routes need."""
    user = MagicMock()
    user.user_id = user_id if user_id is not None else _FIXED_USER_ID
    user.email = "test@example.com"
    user.name = "Test User"
    user.role_id = role_id
    user.firebase_uid = "test-firebase-uid-abc123"
    user.auth_provider = auth_provider
    user.email_verified = email_verified
    user.mfa_enabled = False
    user.role_approved_by = None
    user.role_approved_at = None
    user.created_at = _FIXED_TS
    user.last_login_at = _FIXED_TS
    return user


# ---------------------------------------------------------------------------
# Fixtures: users
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user() -> MagicMock:
    """Public user, email verified."""
    return _make_user(role_id=1, email_verified=True)


@pytest.fixture
def mock_admin_user() -> MagicMock:
    """Admin user (role_id=4)."""
    return _make_user(role_id=4, email_verified=True)


@pytest.fixture
def mock_court_official_user() -> MagicMock:
    """Court official via SAML (role_id=2)."""
    return _make_user(role_id=2, email_verified=True, auth_provider="saml.massgov")


@pytest.fixture
def mock_interpreter_user() -> MagicMock:
    """Interpreter user (role_id=3)."""
    return _make_user(role_id=3, email_verified=True)


@pytest.fixture
def mock_court_official_user_b() -> MagicMock:
    """Second court official with a different user_id — for ownership tests."""
    return _make_user(role_id=2, email_verified=True, user_id=_FIXED_USER_ID_B)


# ---------------------------------------------------------------------------
# Fixture: database session
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    """
    Mock AsyncSession.

    execute() returns a universal mock result supporting:
      .scalar_one_or_none() → None
      .scalar_one()         → 0
      .first()              → None
      .scalars().all()      → []
      .all()                → []

    Individual tests can override execute.return_value or execute.side_effect
    for specific call sequences.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    result.scalar_one = MagicMock(return_value=0)
    result.first = MagicMock(return_value=None)
    result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.close = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------


def _build_app(user_fn, db: AsyncMock) -> FastAPI:
    """
    Minimal FastAPI app without lifespan.
    Includes all route modules and health + root meta-endpoints.
    """
    from api.dependencies import get_current_user, get_db
    from api.routes import admin as admin_router
    from api.routes import auth as auth_router
    from api.routes import documents as documents_router
    from api.routes import forms as forms_router
    from api.routes import interpreter as interpreter_router
    from api.routes import realtime as realtime_router
    from api.schemas.schemas import HealthResponse

    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(documents_router.router, prefix="/api")
    app.include_router(forms_router.router, prefix="/api")
    app.include_router(admin_router.router, prefix="/api")
    app.include_router(interpreter_router.router, prefix="/api")
    app.include_router(realtime_router.router, prefix="/api")

    @app.get("/health", response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok", version="0.1.0", environment="test")

    @app.get("/")
    async def root():
        from fastapi.responses import JSONResponse

        return JSONResponse({"name": "CourtAccess AI API", "version": "0.1.0"})

    async def _override_db():
        yield db

    app.dependency_overrides[get_current_user] = user_fn
    app.dependency_overrides[get_db] = _override_db
    return app


# ---------------------------------------------------------------------------
# Fixtures: HTTP clients
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(mock_user: MagicMock, mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient authenticated as a public verified user."""
    app = _build_app(user_fn=lambda: mock_user, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_client(mock_admin_user: MagicMock, mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient authenticated as an admin user."""
    app = _build_app(user_fn=lambda: mock_admin_user, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def saml_client(mock_court_official_user: MagicMock, mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient authenticated as a SAML court official."""
    app = _build_app(user_fn=lambda: mock_court_official_user, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def interpreter_client(mock_interpreter_user: MagicMock, mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient authenticated as an interpreter user."""
    app = _build_app(user_fn=lambda: mock_interpreter_user, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def court_official_client_b(mock_court_official_user_b: MagicMock, mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient as a second court official (different user_id) — for ownership tests."""
    app = _build_app(user_fn=lambda: mock_court_official_user_b, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def unverified_client(mock_db: AsyncMock) -> AsyncClient:
    """AsyncClient authenticated as a user whose email is NOT verified."""
    unverified_user = _make_user(role_id=1, email_verified=False)
    app = _build_app(user_fn=lambda: unverified_user, db=mock_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
