"""
conftest.py — Root pytest configuration for court-access-ai.

Shared fixtures available to all test modules across the project:
  - mock_db_session   : async SQLAlchemy session mock
  - mock_gcs_client   : Google Cloud Storage client mock
  - mock_vertex_ai    : Vertex AI / Groq Llama response mock
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

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
    Mock Vertex AI / Groq Llama response for legal review and document classification.
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
