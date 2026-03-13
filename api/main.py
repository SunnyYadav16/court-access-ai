"""
api/main.py

FastAPI application entry point for the CourtAccess AI API.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import firebase_admin
from firebase_admin import credentials
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Initialize Firebase Admin SDK
    if not firebase_admin._apps:
        from dotenv import load_dotenv
        load_dotenv()  # ensure .env vars are in os.environ
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        logger.info("Firebase cred path: %s", cred_path)
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialized with service account")
        else:
            firebase_admin.initialize_app()
            logger.info("Firebase Admin SDK initialized with default credentials")

    logger.info(
        "CourtAccess AI API starting — env=%s, debug=%s",
        settings.app_env,
        settings.debug,
    )
    logger.info("Startup complete.")
    yield

    logger.info("CourtAccess AI API shutting down.")


def create_app() -> FastAPI:
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
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )

    _configure_middleware(app, settings)
    _register_exception_handlers(app)

    app.include_router(auth_router.router)
    app.include_router(documents_router.router)
    app.include_router(forms_router.router)
    app.include_router(realtime_router.router)

    _register_meta_endpoints(app)

    return app


def _configure_middleware(app: FastAPI, settings) -> None:
    allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def add_request_id(request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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


def _register_meta_endpoints(app: FastAPI) -> None:
    @app.get("/", tags=["meta"], include_in_schema=False)
    async def root() -> dict:
        return {"name": "CourtAccess AI API", "version": "0.1.0", "docs": "/docs"}

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        settings = get_settings()
        return HealthResponse(status="ok", version="0.1.0", environment=settings.app_env)


app = create_app()