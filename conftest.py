"""
conftest.py — Root pytest configuration for court-access-ai.

Shared fixtures available to all test modules across the project:
  - mock_db_session   : async SQLAlchemy session mock
  - mock_gcs_client   : Google Cloud Storage client mock
  - mock_vertex_ai    : Vertex AI Llama response mock
  - mock_redis        : Redis client mock (function-scoped)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from courtaccess.core.legal_review import LegalReviewer
from courtaccess.core.ocr_printed import OCREngine
from courtaccess.core.translation import Translator
from courtaccess.languages import get_language_config

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
