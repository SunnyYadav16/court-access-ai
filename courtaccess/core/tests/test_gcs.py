"""
Unit tests for courtaccess/core/gcs.py

Functions under test:
  parse_gcs_uri         — pure URI parser (no I/O)
  gcs_uri               — pure URI builder (no I/O)
  _ctx                  — pure log prefix helper (no I/O)
  upload_bytes          — GCS upload (mocked client)
  upload_file           — GCS upload from local path (mocked client)
  download_file         — GCS download with error mapping (mocked client)
  delete_blob           — idempotent delete, swallows NotFound (mocked client)
  blob_exists           — existence check (mocked client)
  get_blob_size         — metadata fetch, returns None on error (mocked client)
  generate_signed_url   — signed URL generation (mocked client + credentials)

Design notes:
  - All GCS network I/O is mocked via patch("courtaccess.core.gcs._get_storage_client").
    patching the function directly bypasses the lru_cache — each test gets a fresh
    MagicMock chain without polluting the real cache.
  - google.api_core.exceptions (NotFound, Forbidden) are real exception classes
    from the installed google-cloud-core package and are raised directly in tests.
  - _get_service_account_credentials / _get_storage_client_with_sa are patched
    separately for generate_signed_url tests that use a SA JSON key.
  - Pure functions (parse_gcs_uri, gcs_uri, _ctx) need no patching.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import Forbidden, NotFound

import courtaccess.core.gcs as gcs_mod
from courtaccess.core.gcs import gcs_uri, parse_gcs_uri

# ── Mock builder ──────────────────────────────────────────────────────────────


def _make_gcs_mock():
    """Build a mock storage client chain: client → bucket → blob."""
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    return mock_client, mock_bucket, mock_blob


# ─────────────────────────────────────────────────────────────────────────────
# parse_gcs_uri — pure function
# ─────────────────────────────────────────────────────────────────────────────


class TestParseGcsUri:
    def test_valid_uri_returns_bucket_and_blob(self):
        bucket, blob = parse_gcs_uri("gs://my-bucket/forms/abc/form.pdf")
        assert bucket == "my-bucket"
        assert blob == "forms/abc/form.pdf"

    def test_blob_with_nested_path(self):
        _, blob = parse_gcs_uri("gs://bucket/a/b/c/d.txt")
        assert blob == "a/b/c/d.txt"

    def test_missing_gs_prefix_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid GCS URI"):
            parse_gcs_uri("s3://bucket/blob")

    def test_no_scheme_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_gcs_uri("bucket/blob")

    def test_missing_blob_raises_value_error(self):
        with pytest.raises(ValueError, match="Missing bucket or blob"):
            parse_gcs_uri("gs://bucket-only")

    def test_empty_bucket_raises_value_error(self):
        # "gs:///blob" — empty string before the first "/"
        with pytest.raises(ValueError):
            parse_gcs_uri("gs:///blob-only")

    def test_bucket_name_returned_exactly(self):
        bucket, _ = parse_gcs_uri("gs://court-access-forms/abc.pdf")
        assert bucket == "court-access-forms"


# ─────────────────────────────────────────────────────────────────────────────
# gcs_uri — pure function
# ─────────────────────────────────────────────────────────────────────────────


class TestGcsUri:
    def test_returns_gs_scheme_uri(self):
        assert gcs_uri("my-bucket", "folder/file.pdf") == "gs://my-bucket/folder/file.pdf"

    def test_bucket_and_blob_joined_with_slash(self):
        assert gcs_uri("b", "p") == "gs://b/p"

    def test_roundtrip_with_parse_gcs_uri(self):
        bucket, blob = parse_gcs_uri(gcs_uri("bucket", "blob/path.txt"))
        assert bucket == "bucket"
        assert blob == "blob/path.txt"


# ─────────────────────────────────────────────────────────────────────────────
# _ctx — pure log prefix helper
# ─────────────────────────────────────────────────────────────────────────────


class TestCtx:
    def test_with_correlation_id_returns_prefix(self):
        assert gcs_mod._ctx("abc-123") == "[corr=abc-123] "

    def test_none_returns_empty_string(self):
        assert gcs_mod._ctx(None) == ""

    def test_empty_string_returns_empty_string(self):
        assert gcs_mod._ctx("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# upload_bytes
# ─────────────────────────────────────────────────────────────────────────────


class TestUploadBytes:
    def test_calls_upload_from_string_with_data(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_bytes("my-bucket", "folder/file.pdf", b"data")
        args, _ = mock_blob.upload_from_string.call_args
        assert args[0] == b"data"

    def test_content_type_passed_to_upload(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_bytes("b", "f", b"x", content_type="application/pdf")
        _, kwargs = mock_blob.upload_from_string.call_args
        assert kwargs.get("content_type") == "application/pdf"

    def test_default_content_type_is_octet_stream(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_bytes("b", "f", b"x")
        _, kwargs = mock_blob.upload_from_string.call_args
        assert kwargs.get("content_type") == "application/octet-stream"

    def test_correct_bucket_and_blob_addressed(self):
        mock_client, mock_bucket, _ = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_bytes("target-bucket", "path/to/blob", b"x")
        mock_client.bucket.assert_called_with("target-bucket")
        mock_bucket.blob.assert_called_with("path/to/blob")


# ─────────────────────────────────────────────────────────────────────────────
# upload_file
# ─────────────────────────────────────────────────────────────────────────────


class TestUploadFile:
    def test_calls_upload_from_filename_with_path(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_file("/fake/report.pdf", "bucket", "reports/report.pdf")
        args, _ = mock_blob.upload_from_filename.call_args
        assert args[0] == "/fake/report.pdf"

    def test_correct_bucket_and_blob_addressed(self):
        mock_client, mock_bucket, _ = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.upload_file("/fake/path/x", "my-bucket", "path/blob")
        mock_client.bucket.assert_called_with("my-bucket")
        mock_bucket.blob.assert_called_with("path/blob")


# ─────────────────────────────────────────────────────────────────────────────
# download_file
# ─────────────────────────────────────────────────────────────────────────────


class TestDownloadFile:
    def test_creates_parent_directories(self, tmp_path):
        dest = tmp_path / "nested" / "dir" / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = True
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.download_file("bucket", "blob", str(dest))
        assert dest.parent.exists()

    def test_calls_download_to_filename_when_blob_exists(self, tmp_path):
        dest = tmp_path / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = True
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.download_file("b", "f", str(dest))
        mock_blob.download_to_filename.assert_called_once()

    def test_raises_file_not_found_when_blob_does_not_exist(self, tmp_path):
        dest = tmp_path / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = False
        with (
            patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client),
            pytest.raises(FileNotFoundError),
        ):
            gcs_mod.download_file("b", "f", str(dest))

    def test_not_found_exception_raises_file_not_found(self, tmp_path):
        dest = tmp_path / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.side_effect = NotFound("gs://b/f")
        with (
            patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client),
            pytest.raises(FileNotFoundError),
        ):
            gcs_mod.download_file("b", "f", str(dest))

    def test_forbidden_exception_raises_permission_error(self, tmp_path):
        dest = tmp_path / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.side_effect = Forbidden("gs://b/f")
        with (
            patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client),
            pytest.raises(PermissionError),
        ):
            gcs_mod.download_file("b", "f", str(dest))

    def test_file_not_found_error_contains_bucket_and_blob(self, tmp_path):
        dest = tmp_path / "file.pdf"
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = False
        with (
            patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client),
            pytest.raises(FileNotFoundError, match="gs://my-bucket/my-blob"),
        ):
            gcs_mod.download_file("my-bucket", "my-blob", str(dest))


# ─────────────────────────────────────────────────────────────────────────────
# delete_blob
# ─────────────────────────────────────────────────────────────────────────────


class TestDeleteBlob:
    def test_calls_delete_on_blob(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.delete_blob("bucket", "blob")
        mock_blob.delete.assert_called_once()

    def test_not_found_is_swallowed(self):
        # Idempotent — deleting a non-existent object must not raise
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.delete.side_effect = NotFound("gs://b/f")
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.delete_blob("b", "f")  # must not raise

    def test_other_exceptions_are_re_raised(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.delete.side_effect = RuntimeError("unexpected")
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client), pytest.raises(RuntimeError):
            gcs_mod.delete_blob("b", "f")

    def test_correct_bucket_and_blob_addressed(self):
        mock_client, mock_bucket, _ = _make_gcs_mock()
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.delete_blob("del-bucket", "del-blob")
        mock_client.bucket.assert_called_with("del-bucket")
        mock_bucket.blob.assert_called_with("del-blob")


# ─────────────────────────────────────────────────────────────────────────────
# blob_exists
# ─────────────────────────────────────────────────────────────────────────────


class TestBlobExists:
    def test_returns_true_when_blob_exists(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = True
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            assert gcs_mod.blob_exists("b", "f") is True

    def test_returns_false_when_blob_does_not_exist(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.exists.return_value = False
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            assert gcs_mod.blob_exists("b", "f") is False


# ─────────────────────────────────────────────────────────────────────────────
# get_blob_size
# ─────────────────────────────────────────────────────────────────────────────


class TestGetBlobSize:
    def test_returns_size_on_success(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.size = 12345
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            assert gcs_mod.get_blob_size("b", "f") == 12345

    def test_returns_none_when_not_found(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.reload.side_effect = NotFound("gs://b/f")
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            assert gcs_mod.get_blob_size("b", "f") is None

    def test_returns_none_on_generic_exception(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.reload.side_effect = Exception("network error")
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            assert gcs_mod.get_blob_size("b", "f") is None

    def test_calls_reload_before_reading_size(self):
        # reload() populates server-side metadata (including .size)
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.size = 999
        call_order = []
        mock_blob.reload.side_effect = lambda **_: call_order.append("reload")
        with patch("courtaccess.core.gcs._get_storage_client", return_value=mock_client):
            gcs_mod.get_blob_size("b", "f")
        mock_blob.reload.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# generate_signed_url
# ─────────────────────────────────────────────────────────────────────────────


class TestGenerateSignedUrl:
    _FAKE_SA = '{"type": "service_account", "project_id": "test"}'

    def test_returns_signed_url_string(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
        mock_creds = MagicMock()
        with (
            patch("courtaccess.core.gcs._get_storage_client_with_sa", return_value=mock_client),
            patch("courtaccess.core.gcs._get_service_account_credentials", return_value=mock_creds),
        ):
            result = gcs_mod.generate_signed_url("bucket", "blob", 3600, self._FAKE_SA)
        assert result == "https://storage.googleapis.com/signed"

    def test_uses_v4_signing_and_get_method(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.generate_signed_url.return_value = "https://signed"
        mock_creds = MagicMock()
        with (
            patch("courtaccess.core.gcs._get_storage_client_with_sa", return_value=mock_client),
            patch("courtaccess.core.gcs._get_service_account_credentials", return_value=mock_creds),
        ):
            gcs_mod.generate_signed_url("b", "f", 3600, self._FAKE_SA)
        _, kwargs = mock_blob.generate_signed_url.call_args
        assert kwargs.get("version") == "v4"
        assert kwargs.get("method") == "GET"

    def test_expiry_passed_as_timedelta(self):
        mock_client, _, mock_blob = _make_gcs_mock()
        mock_blob.generate_signed_url.return_value = "https://signed"
        mock_creds = MagicMock()
        with (
            patch("courtaccess.core.gcs._get_storage_client_with_sa", return_value=mock_client),
            patch("courtaccess.core.gcs._get_service_account_credentials", return_value=mock_creds),
        ):
            gcs_mod.generate_signed_url("b", "f", 7200, self._FAKE_SA)
        _, kwargs = mock_blob.generate_signed_url.call_args
        assert kwargs.get("expiration") == timedelta(seconds=7200)

    def test_correct_bucket_and_blob_addressed(self):
        mock_client, mock_bucket, mock_blob = _make_gcs_mock()
        mock_blob.generate_signed_url.return_value = "https://signed"
        mock_creds = MagicMock()
        with (
            patch("courtaccess.core.gcs._get_storage_client_with_sa", return_value=mock_client),
            patch("courtaccess.core.gcs._get_service_account_credentials", return_value=mock_creds),
        ):
            gcs_mod.generate_signed_url("sign-bucket", "sign-blob", 60, self._FAKE_SA)
        mock_client.bucket.assert_called_with("sign-bucket")
        mock_bucket.blob.assert_called_with("sign-blob")
