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

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from api.routes import auth as auth_router
from api.routes import documents as documents_router
from api.routes import forms as forms_router
from api.routes import realtime as realtime_router
from api.schemas.schemas import ErrorDetail, HealthResponse
from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

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

    # TODO: Initialize real async DB engine once db/models.py is wired
    # from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    # engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
    # app.state.db_engine = engine
    # app.state.AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    logger.info("Startup complete.")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("CourtAccess AI API shutting down.")
    # if hasattr(app.state, "db_engine"):
    #     await app.state.db_engine.dispose()


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

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ErrorDetail(
                code="not_found",
                message=f"The requested path '{request.url.path}' was not found",
            ).model_dump(),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Meta endpoints
# ══════════════════════════════════════════════════════════════════════════════


def _register_meta_endpoints(app: FastAPI) -> None:
    @app.get("/", tags=["meta"], include_in_schema=False)
    async def root() -> dict:
        return {"name": "CourtAccess AI API", "version": "0.1.0", "docs": "/docs"}

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
