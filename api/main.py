"""
api/main.py

FastAPI application entry point for the CourtAccess AI API.

Startup / lifespan:
  - Initializes async SQLAlchemy engine (connection pool)
  - Pre-warms courtaccess config (validates env vars on boot)

Routers registered:
  /auth        — register, login, refresh, me, logout
  /documents   — upload, status, list, delete
  /forms       — catalog search, detail, human review
  /sessions    — real-time interpretation session management + WebSocket

Middleware:
  - CORS (origins from ALLOWED_ORIGINS env var)
  - GZip compression (responses > 1KB)
  - Request ID header injection (X-Request-ID)

Health / meta:
  GET /        — root (API name + version)
  GET /health  — health check (used by Docker/GCP health probes)
  GET /docs    — Swagger UI (disabled in production)
  GET /redoc   — ReDoc (disabled in production)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import firebase_admin
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import auth as auth_router
from api.routes import documents as documents_router
from api.routes import forms as forms_router
from api.routes import realtime as realtime_router
from api.schemas.schemas import ErrorDetail, HealthResponse
from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

# Path to the built React frontend (only exists after `pnpm build` / in production image)
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Application lifespan
# ══════════════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Async context manager for startup/shutdown logic.

    Startup:
      - Validate settings (will raise immediately if required env vars missing)
      - Initialize DB engine + connection pool
      - (future) warm ML model endpoints

    Shutdown:
      - Dispose DB engine connection pool
      - (future) flush in-flight metrics
    """
    settings = get_settings()
    logger.info(
        "CourtAccess AI API starting — env=%s, debug=%s",
        settings.app_env,
        settings.debug,
    )

    # ── Initialize Firebase Admin SDK ────────────────────────────────────────
    # Credentials auto-detected from GOOGLE_APPLICATION_CREDENTIALS env var (local)
    # or Workload Identity (GKE). No arguments needed.
    if not firebase_admin._apps:  # Only initialize once
        firebase_admin.initialize_app()
        logger.info("Firebase Admin SDK initialized")

    # ── Initialize Database ───────────────────────────────────────────────────
    from db.database import init_db

    await init_db()
    logger.info("Database connection pool initialized")

    logger.info("Startup complete.")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("CourtAccess AI API shutting down.")
    from db.database import close_db

    await close_db()
    logger.info("Database connection pool closed")


# ══════════════════════════════════════════════════════════════════════════════
# Application factory
# ══════════════════════════════════════════════════════════════════════════════


def create_app() -> FastAPI:
    """
    Build and configure the FastAPI application.
    Callable by tests (override settings before calling) and by uvicorn.
    """
    settings = get_settings()

    app = FastAPI(
        title="CourtAccess AI API",
        description=(
            "REST + WebSocket API for the CourtAccess AI system. "
            "Provides real-time court interpretation (speech-to-speech), "
            "document translation (PDF → ES/PT), and access to the "
            "pre-translated Massachusetts court form catalog."
        ),
        version="0.1.0",
        contact={
            "name": "CourtAccess AI Team",
            "url": "https://github.com/SunnyYadav16/court-access-ai",
        },
        license_info={"name": "MIT"},
        lifespan=lifespan,
        # Disable interactive docs in production to reduce attack surface.
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )

    # ── Middleware ─────────────────────────────────────────────────────────
    _configure_middleware(app, settings)

    # ── Exception handlers ─────────────────────────────────────────────────
    _register_exception_handlers(app)

    # ── Routers ────────────────────────────────────────────────────────────
    app.include_router(auth_router.router)
    app.include_router(documents_router.router)
    app.include_router(forms_router.router)
    app.include_router(realtime_router.router)

    # ── Static frontend assets (/assets/*, /favicon.ico, etc.) ─────────────
    # Only mounted when the production build exists (not in local `uvicorn --reload` dev)
    if (_FRONTEND_DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")
        logger.info("Serving frontend static assets from %s", _FRONTEND_DIST)

    # ── Meta endpoints ─────────────────────────────────────────────────────
    _register_meta_endpoints(app)

    return app


# ══════════════════════════════════════════════════════════════════════════════
# Middleware configuration
# ══════════════════════════════════════════════════════════════════════════════


def _configure_middleware(app: FastAPI, settings) -> None:
    # ── CORS ─────────────────────────────────────────────────────────────────
    allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    # ── GZip ─────────────────────────────────────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # ── Request ID ────────────────────────────────────────────────────────────
    @app.middleware("http")
    async def add_request_id(request: Request, call_next) -> Response:
        """Inject X-Request-ID into every request/response for distributed tracing."""
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ══════════════════════════════════════════════════════════════════════════════
# Exception handlers
# ══════════════════════════════════════════════════════════════════════════════


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all handler — return a structured error body for any unhandled exception.
        Logs the full traceback in production; surfaces detail in development.
        """
        logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
        settings = get_settings()
        return JSONResponse(
            status_code=500,
            content=ErrorDetail(
                code="internal_server_error",
                message="An unexpected error occurred" if settings.app_env == "production" else str(exc),
            ).model_dump(),
        )

    # API path prefixes that should return JSON 404 (not fallthrough to React)
    _api_prefixes = ("/api/", "/auth/", "/ws/", "/health", "/docs", "/redoc", "/openapi")

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> Response:
        path = request.url.path
        # True API miss → JSON error
        if any(path.startswith(p) for p in _api_prefixes):
            return JSONResponse(
                status_code=404,
                content=ErrorDetail(
                    code="not_found",
                    message=f"The requested path '{path}' was not found",
                ).model_dump(),
            )
        # Frontend route (e.g. /sessions, /documents) → serve index.html
        # React Router handles the route on the client side.
        index = _FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        # Fallback when no frontend build exists (local dev without pnpm build)
        return JSONResponse(
            status_code=404,
            content=ErrorDetail(
                code="not_found",
                message=f"The requested path '{path}' was not found",
            ).model_dump(),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Meta endpoints
# ══════════════════════════════════════════════════════════════════════════════


def _register_meta_endpoints(app: FastAPI) -> None:
    @app.get("/", tags=["meta"], include_in_schema=False)
    async def root() -> Response:
        """Serve the React SPA root, falling back to JSON if no build exists."""
        index = _FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({"name": "CourtAccess AI API", "version": "0.1.0", "docs": "/docs"})

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["meta"],
        summary="Health check",
        description=(
            "Used by Docker health checks and GCP load balancer probes. "
            "Returns 200 OK when the application is ready to serve requests."
        ),
    )
    async def health() -> HealthResponse:
        settings = get_settings()
        return HealthResponse(
            status="ok",
            version="0.1.0",
            environment=settings.app_env,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Entrypoint
# ══════════════════════════════════════════════════════════════════════════════

# Module-level app instance — used by:
#   uvicorn api.main:app --reload
#   gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker
app = create_app()
