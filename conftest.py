"""
conftest.py — Root pytest configuration for court-access-ai.

Shared fixtures available to all test modules across the project:
  - mock_db_session   : async SQLAlchemy session mock
  - mock_gcs_client   : Google Cloud Storage client mock
  - mock_vertex_ai    : Vertex AI Llama response mock
  - mock_redis        : Redis client mock (function-scoped)
"""

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

# Graceful fallback for local ML testing outside of Docker.
# If an /opt/airflow/models/... path doesn't exist, but ./models/... does
# (which means we're running Pytest natively on Mac), we rewrite the env var.
for env_key in [
    "NLLB_MODEL_PATH", 
    "QWEN_VL_MODEL_PATH", 
    "WHISPER_MODEL_PATH", 
    "PIPER_TTS_ES_PATH", 
    "PIPER_TTS_PT_PATH"
]:
    val = os.getenv(env_key)
    if val and val.startswith("/opt/airflow/") and not os.path.exists(val):
        local_path = val.replace("/opt/airflow/", "./")
        if os.path.exists(local_path):
            os.environ[env_key] = local_path

import pytest
from httpx import ASGITransport, AsyncClient

from api.dependencies import get_current_user, get_db
from api.main import create_app
from courtaccess.core.legal_review import LegalReviewer
from courtaccess.core.ocr_printed import OCREngine
from courtaccess.core.translation import Translator
from courtaccess.languages import get_language_config
from db.models import User

# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db_session():
    """
    Mock async SQLAlchemy session.
    Used by api/tests/ and courtaccess/forms/tests/ wherever DB queries are made.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    yield session


# ── Cloud Storage ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_gcs_client():
    """
    Mock Google Cloud Storage client.
    Used by tests that upload/download files to/from GCS buckets.
    Returns a fake signed URL when generate_signed_url() is called.
    """
    fake_signed_url = "https://storage.googleapis.com/fake-bucket/fake-object?X-Goog-Signature=abc123"

    blob = MagicMock()
    blob.upload_from_string = MagicMock()
    blob.upload_from_file = MagicMock()
    blob.download_as_bytes = MagicMock(return_value=b"%PDF-1.4 fake pdf content")
    blob.generate_signed_url = MagicMock(return_value=fake_signed_url)
    blob.exists = MagicMock(return_value=True)
    blob.delete = MagicMock()

    bucket = MagicMock()
    bucket.blob = MagicMock(return_value=blob)

    client = MagicMock()
    client.bucket = MagicMock(return_value=bucket)

    yield client


# ── LLM / Vertex AI ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_vertex_ai():
    """
    Mock Vertex AI Llama response for legal review and document classification.
    Used by courtaccess/core/tests/test_legal_review.py and test_classify_document.py.

    Shape matches the response schema in courtaccess/core/legal_review.py.
    Update this fixture when the real response schema is finalized.
    """
    yield {
        "verified_translation": "El acusado se declara no culpable.",
        "accuracy_score": 0.95,
        "accuracy_note": "Translation is accurate. Legal terminology preserved.",
        "correction_count": 1,
        "corrections": [
            {
                "original": "no es culpable",
                "corrected": "se declara no culpable",
                "reason": "Legal phrasing for 'pleads not guilty' requires reflexive form.",
            }
        ],
    }


# ── Redis ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    """
    Mock Redis client. Patches redis.Redis so no real instance is needed.
    get() returns None by default (cache miss), set() and ping() succeed.

    Function-scoped (default) so each test receives a fresh MagicMock with
    clean call counts and default return values — prevents state leakage when
    one test overrides mock_redis.get.return_value or asserts call counts.

    Use in tests that exercise LegalReviewer with USE_VERTEX_LEGAL_REVIEW=true:

        def test_cache_miss(mock_redis, reviewer_es, monkeypatch):
            monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "true")
            monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
            with patch("redis.Redis.from_url", return_value=mock_redis):
                result = reviewer_es.verify_batch(["the court"], ["el tribunal"])
            mock_redis.get.assert_called_once()

    To simulate a cache hit, override get() return value in the test:
        mock_redis.get.return_value = b"el tribunal"
    """
    mock = MagicMock()
    mock.get.return_value = None  # default: cache miss
    mock.set.return_value = True
    mock.ping.return_value = True
    yield mock


# ── Language configs ──────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def reviewer_es(spanish_config):
    """Spanish LegalReviewer, empty glossary, stub mode."""
    return LegalReviewer(spanish_config, glossary={})


@pytest.fixture(scope="session")
def reviewer_pt(portuguese_config):
    """Portuguese LegalReviewer, empty glossary, stub mode."""
    return LegalReviewer(portuguese_config, glossary={})


@pytest.fixture(scope="session")
def ocr_engine():
    """OCREngine in stub mode (USE_REAL_OCR=false). Session-scoped."""
    return OCREngine().load()


@pytest.fixture(scope="session")
def spanish_config():
    return get_language_config("spanish")


@pytest.fixture(scope="session")
def portuguese_config():
    return get_language_config("portuguese")


@pytest.fixture(scope="session")
def translator_es(spanish_config):
    return Translator(spanish_config).load()


@pytest.fixture(scope="session")
def translator_pt(portuguese_config):
    return Translator(portuguese_config).load()


# ── API / Web ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_user():
    """
    Returns a mock User ORM object for dependency injection.
    Role: public (role_id=1), email_verified=True.
    """
    user = User(
        user_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        email="test@example.com",
        name="Test User",
        role_id=1,  # public
        firebase_uid="fake-firebase-uid",
        auth_provider="password",
        email_verified=True,
        mfa_enabled=False,
        created_at=datetime.now(tz=UTC),
        last_login_at=datetime.now(tz=UTC),
    )
    return user


@pytest.fixture
def app_with_overrides(mock_db_session, mock_user):
    """
    FastAPI app instance with dependencies overridden for testing.
    Bypasses real DB and real Firebase token verification.
    """
    app = create_app()

    # Override Database session
    async def _get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = _get_db

    # Override Firebase Auth
    async def _get_current_user():
        return mock_user

    app.dependency_overrides[get_current_user] = _get_current_user

    yield app
    app.dependency_overrides = {}


@pytest.fixture
async def client(app_with_overrides):
    """
    Async HTTP client for testing API routes.
    Uses the app with dependency overrides.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app_with_overrides), base_url="http://test"
    ) as ac:
        yield ac
