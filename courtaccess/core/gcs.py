"""
courtaccess/core/gcs.py

Synchronous GCS helpers shared across API routes and Airflow DAGs.

All functions are intentionally synchronous. Airflow tasks run in sync
processes and cannot use `await`. Async callers (FastAPI routes) wrap
individual calls with `asyncio.to_thread(gcs.<fn>, ...)` at the call site —
that wrapping stays in the route, not here.

Importing:
    from courtaccess.core import gcs

    # Sync (DAG task):
    gcs.upload_file(local_path, bucket, blob)

    # Async (FastAPI route):
    await asyncio.to_thread(gcs.upload_bytes, bucket, blob, data, "application/pdf")
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _ctx(correlation_id: str | None) -> str:
    """Small log prefix to correlate GCS ops across systems."""
    return f"[corr={correlation_id}] " if correlation_id else ""


def _build_retry():
    from google.api_core.exceptions import DeadlineExceeded, InternalServerError, ServiceUnavailable, TooManyRequests
    from google.api_core.retry import Retry, if_exception_type

    return Retry(
        predicate=if_exception_type(
            DeadlineExceeded,
            ServiceUnavailable,
            TooManyRequests,
            InternalServerError,
        ),
        initial=0.5,
        maximum=8.0,
        multiplier=2.0,
        deadline=30.0,
    )


GCS_RETRY = _build_retry()


@functools.lru_cache(maxsize=1)
def _get_storage_client():
    from google.cloud import storage

    return storage.Client()


@functools.lru_cache(maxsize=8)
def _get_service_account_credentials(service_account_json: str):
    """Build signing credentials from a SA JSON key string (local dev only)."""
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(json.loads(service_account_json))


@functools.lru_cache(maxsize=8)
def _get_storage_client_with_sa(service_account_json: str):
    from google.cloud import storage

    creds = _get_service_account_credentials(service_account_json)
    return storage.Client(credentials=creds)


# ══════════════════════════════════════════════════════════════════════════════
# URI helpers
# ══════════════════════════════════════════════════════════════════════════════


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """
    Split a ``gs://bucket/path/to/blob`` URI into ``(bucket, blob)``.

    >>> parse_gcs_uri("gs://my-bucket/forms/abc/v1/form.pdf")
    ('my-bucket', 'forms/abc/v1/form.pdf')
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI '{uri}'. Expected format: gs://bucket/blob")

    without_scheme = uri[5:]  # strip "gs://"
    bucket, _, blob = without_scheme.partition("/")
    if not bucket or not blob:
        raise ValueError(f"Invalid GCS URI '{uri}'. Missing bucket or blob path.")
    return bucket, blob


def gcs_uri(bucket: str, blob: str) -> str:
    """Return a ``gs://bucket/blob`` URI string."""
    return f"gs://{bucket}/{blob}"


# ══════════════════════════════════════════════════════════════════════════════
# Upload
# ══════════════════════════════════════════════════════════════════════════════


def upload_bytes(
    bucket: str,
    blob: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    *,
    correlation_id: str | None = None,
) -> None:
    """
    Upload raw bytes to GCS.

    Used by API routes (via ``asyncio.to_thread``) to push user-uploaded PDFs
    to the uploads bucket immediately on receipt.
    """
    _get_storage_client().bucket(bucket).blob(blob).upload_from_string(
        data,
        content_type=content_type,
        retry=GCS_RETRY,
    )
    logger.info("%sGCS ↑ bytes → gs://%s/%s (%d bytes)", _ctx(correlation_id), bucket, blob, len(data))


def upload_file(local_path: str, bucket: str, blob: str, *, correlation_id: str | None = None) -> None:
    """
    Upload a local file to GCS by path.

    Used by DAG tasks that produce files on disk (scraper output, reconstructed
    PDFs) and need to push them to GCS after processing completes.
    """
    _get_storage_client().bucket(bucket).blob(blob).upload_from_filename(
        local_path,
        retry=GCS_RETRY,
    )
    logger.info("%sGCS ↑ %s → gs://%s/%s", _ctx(correlation_id), local_path, bucket, blob)


# ══════════════════════════════════════════════════════════════════════════════
# Download
# ══════════════════════════════════════════════════════════════════════════════


def download_file(
    bucket: str,
    blob: str,
    local_path: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """
    Download a GCS blob to a local file path.

    Creates any missing parent directories automatically.
    Used by DAG tasks that need to operate on a file locally before processing.
    """
    from google.api_core.exceptions import Forbidden, NotFound

    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    gcs_blob = _get_storage_client().bucket(bucket).blob(blob)
    try:
        if not gcs_blob.exists(retry=GCS_RETRY):
            raise FileNotFoundError(f"GCS object not found: gs://{bucket}/{blob}")
        gcs_blob.download_to_filename(local_path, retry=GCS_RETRY)
        logger.info("%sGCS ↓ gs://%s/%s → %s", _ctx(correlation_id), bucket, blob, local_path)
    except NotFound as exc:
        raise FileNotFoundError(f"GCS object not found: gs://{bucket}/{blob}") from exc
    except Forbidden as exc:
        raise PermissionError(f"Permission denied for gs://{bucket}/{blob}") from exc


# ══════════════════════════════════════════════════════════════════════════════
# Delete
# ══════════════════════════════════════════════════════════════════════════════


def delete_blob(bucket: str, blob: str, *, correlation_id: str | None = None) -> None:
    """
    Delete a single GCS object.

    Swallows ``NotFound`` — idempotent for callers that may call delete on
    objects that were never uploaded (e.g. a session where the DAG failed
    before the GCS upload step).

    All other exceptions are re-raised so the caller decides whether to log
    and continue or propagate.
    """
    from google.api_core.exceptions import NotFound

    try:
        _get_storage_client().bucket(bucket).blob(blob).delete(retry=GCS_RETRY)
        logger.info("%sGCS ✗ gs://%s/%s deleted", _ctx(correlation_id), bucket, blob)
    except NotFound:
        logger.debug("%sGCS delete: gs://%s/%s not found — already gone", _ctx(correlation_id), bucket, blob)


def blob_exists(bucket: str, blob: str) -> bool:
    """Return True if the GCS object exists, False otherwise."""
    return _get_storage_client().bucket(bucket).blob(blob).exists(retry=GCS_RETRY)


def get_blob_size(bucket: str, blob: str) -> int | None:
    """
    Return the size in bytes of a GCS object, or None if it does not exist
    or the metadata fetch fails.

    Calls ``blob.reload()`` to populate server-side metadata (including
    ``blob.size``) without downloading the object body.
    """
    from google.api_core.exceptions import NotFound

    try:
        gcs_blob = _get_storage_client().bucket(bucket).blob(blob)
        gcs_blob.reload(retry=GCS_RETRY)
        return gcs_blob.size
    except NotFound:
        logger.debug("GCS get_blob_size: gs://%s/%s not found", bucket, blob)
        return None
    except Exception as exc:
        logger.warning("GCS get_blob_size failed for gs://%s/%s: %s", bucket, blob, exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Signed URLs
# ══════════════════════════════════════════════════════════════════════════════


def generate_signed_url(
    bucket: str,
    blob: str,
    expiry_seconds: int,
    service_account_json: str,
    *,
    correlation_id: str | None = None,
) -> str:
    """
    Generate a v4 signed GET URL for a GCS object.

    Auth strategy for URL signing:
      - Local dev: ``service_account_json`` contains the SA key JSON string.
        The key's private key is used directly to sign the URL.
      - Production (GCE / Cloud Run): ``service_account_json`` is empty.
        Uses ``google.auth.compute_engine.Credentials``, which delegates
        signing to the GCE metadata server via the IAM ``signBlob`` API.
        Requires the attached SA to have ``roles/iam.serviceAccountTokenCreator``
        on itself (self-sign permission).

    Note: plain ``storage.Client()`` (ADC without signing) cannot generate
    signed URLs — it lacks the private key material. This function always
    provides credentials that support the signing interface.
    """
    if service_account_json:
        # Local dev — use explicit SA JSON key
        credentials = _get_service_account_credentials(service_account_json)
        client = _get_storage_client_with_sa(service_account_json)
    else:
        # Production — Compute Engine / Workload Identity (GCE, Cloud Run, GKE).
        # Explicitly request the cloud-platform scope so the access token can
        # call the IAM signBlob API.  Without scopes= the default token may lack
        # the signing scope, causing 403 errors even when the SA has the right IAM
        # binding (roles/iam.serviceAccountTokenCreator on itself).
        import google.auth
        import google.auth.transport.requests
        from google.auth.compute_engine import Credentials as ComputeCredentials
        from google.cloud import storage as _storage

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if isinstance(credentials, ComputeCredentials):
            # Refresh so that service_account_email is populated — the GCS client
            # library reads it from the credentials object to build the signed URL.
            credentials.refresh(google.auth.transport.requests.Request())
        # Build a fresh (non-cached) client with the scoped, refreshed credentials.
        # The module-level _get_storage_client() uses plain ADC without signing
        # scopes, so we must not reuse it here.
        client = _storage.Client(credentials=credentials)

    url = (
        client.bucket(bucket)
        .blob(blob)
        .generate_signed_url(
            expiration=timedelta(seconds=expiry_seconds),
            method="GET",
            version="v4",
            credentials=credentials,
        )
    )
    logger.debug(
        "%sGCS signed URL generated: gs://%s/%s (expires in %ds)",
        _ctx(correlation_id),
        bucket,
        blob,
        expiry_seconds,
    )
    return url
