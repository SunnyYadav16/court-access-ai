"""
dags/tests/test_docx_pipeline_dag.py

Unit tests for dags/docx_pipeline_dag.py.

Covers:
  - task_validate_upload: bad DOCX magic bytes → AirflowFailException; valid
      DOCX → meta returned + XCom pushed; session marked 'processing';
      filename path-traversal sanitised; nllb_target defaults correctly
  - task_finalize (user-upload path): processing_time_seconds computed;
      invalid start_time → None; sessions / requests updated with status=completed
  - task_finalize (pretranslation path, form_id in conf):
      _update_session/_update_request NOT called; catalog updated via
      update_form_version_translations_sync for ES and PT; form not found →
      logged warning, no crash; catalog update failure → logged warning, no crash
  - task_upload_to_gcs (pretranslation path, form_id in conf):
      uploads to GCS_BUCKET_FORMS canonical path; signed_url=None in result;
      _update_request NOT called; form not found → RuntimeError raised
  - _on_dag_failure: writes failed status to session and request
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module under test — imported AFTER env vars are set in conftest.py
# ---------------------------------------------------------------------------
import dags.docx_pipeline_dag as dag_mod
from dags.tests.conftest import _make_context

_PATCH_BASE = "dags.docx_pipeline_dag"

_SESSION_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000020"))
_REQUEST_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000021"))
_USER_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_docx(tmp_path: Path, name: str = "doc.docx") -> Path:
    """Write a file with DOCX/ZIP PK magic bytes."""
    p = tmp_path / name
    p.write_bytes(b"\x50\x4b\x03\x04" + b"\x00" * 100)
    return p


def _base_conf(docx_path: str) -> dict:
    return {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "user_id": _USER_ID,
        "gcs_input_path": docx_path,  # local path → bypasses GCS download
        "target_lang": "es",
        "nllb_target": "spa_Latn",
        "filename": Path(docx_path).name,
        "start_time": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat(),
        "original_format": "docx",
    }


# ===========================================================================
# task_validate_upload
# ===========================================================================


def _patched_validate(monkeypatch, tmp_path: Path):
    """Return a context-manager-style patcher for DB helpers."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)


def test_validate_upload_bad_magic_raises(monkeypatch, tmp_path: Path) -> None:
    """File with wrong magic bytes must raise AirflowFailException."""
    from airflow.exceptions import AirflowFailException

    _patched_validate(monkeypatch, tmp_path)
    bad_file = tmp_path / "bad.docx"
    bad_file.write_bytes(b"NOTAZIP garbage content here")
    ctx = _make_context(_base_conf(str(bad_file)))
    with pytest.raises(AirflowFailException, match="magic"):
        dag_mod.task_validate_upload(**ctx)


def test_validate_upload_bad_magic_sets_session_failed(monkeypatch, tmp_path: Path) -> None:
    """After bad magic bytes, session status must be set to 'failed'."""
    from airflow.exceptions import AirflowFailException

    calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda sid, status, **kw: calls.append((sid, status)))
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)

    bad_file = tmp_path / "bad.docx"
    bad_file.write_bytes(b"BAD")
    ctx = _make_context(_base_conf(str(bad_file)))
    with pytest.raises(AirflowFailException):
        dag_mod.task_validate_upload(**ctx)
    assert any(s == "failed" for _, s in calls)


def test_validate_upload_valid_docx_returns_meta(monkeypatch, tmp_path: Path) -> None:
    """Valid DOCX must return a meta dict with all required keys."""
    _patched_validate(monkeypatch, tmp_path)
    docx = _make_valid_docx(tmp_path)
    ctx = _make_context(_base_conf(str(docx)))
    result = dag_mod.task_validate_upload(**ctx)
    assert result["session_id"] == _SESSION_ID
    assert result["request_id"] == _REQUEST_ID
    assert result["target_lang"] == "es"
    assert "work_dir" in result
    assert "local_docx" in result


def test_validate_upload_pushes_xcom(monkeypatch, tmp_path: Path) -> None:
    """Valid DOCX must push upload_meta to XCom."""
    _patched_validate(monkeypatch, tmp_path)
    docx = _make_valid_docx(tmp_path)
    ctx = _make_context(_base_conf(str(docx)))
    dag_mod.task_validate_upload(**ctx)
    ctx["ti"].xcom_push.assert_called_once()
    call_kwargs = ctx["ti"].xcom_push.call_args.kwargs
    assert call_kwargs.get("key") == "upload_meta"


def test_validate_upload_marks_session_processing(monkeypatch, tmp_path: Path) -> None:
    """Valid DOCX must mark the session as 'processing'."""
    calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda sid, status, **kw: calls.append((sid, status)))
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)

    docx = _make_valid_docx(tmp_path)
    ctx = _make_context(_base_conf(str(docx)))
    dag_mod.task_validate_upload(**ctx)
    assert ("processing" in [s for _, s in calls]) or any(s == "processing" for _, s in calls)


def test_validate_upload_sanitizes_path_traversal(monkeypatch, tmp_path: Path) -> None:
    """Filenames with ../ must be sanitised — no path traversal allowed."""
    _patched_validate(monkeypatch, tmp_path)
    docx = _make_valid_docx(tmp_path, "legit.docx")
    conf = _base_conf(str(docx))
    conf["filename"] = "../../../etc/passwd"
    ctx = _make_context(conf)
    result = dag_mod.task_validate_upload(**ctx)
    assert ".." not in result["filename"]
    assert "/" not in result["filename"]


def test_validate_upload_nllb_target_defaults_for_es(monkeypatch, tmp_path: Path) -> None:
    """When nllb_target is absent and target_lang=es, default 'spa_Latn' is used."""
    _patched_validate(monkeypatch, tmp_path)
    docx = _make_valid_docx(tmp_path)
    conf = _base_conf(str(docx))
    conf.pop("nllb_target", None)
    ctx = _make_context(conf)
    result = dag_mod.task_validate_upload(**ctx)
    assert result["nllb_target"] == "spa_Latn"


def test_validate_upload_nllb_target_defaults_for_pt(monkeypatch, tmp_path: Path) -> None:
    """When nllb_target is absent and target_lang=pt, default 'por_Latn' is used."""
    _patched_validate(monkeypatch, tmp_path)
    docx = _make_valid_docx(tmp_path)
    conf = _base_conf(str(docx))
    conf["target_lang"] = "pt"
    conf.pop("nllb_target", None)
    ctx = _make_context(conf)
    result = dag_mod.task_validate_upload(**ctx)
    assert result["nllb_target"] == "por_Latn"


# ===========================================================================
# task_finalize
# ===========================================================================


def _make_finalize_context(
    start_time: str | None = None,
    llama_corrections: int = 2,
) -> dict:
    ctx = _make_context()
    meta = {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "target_lang": "es",
        "start_time": start_time or (datetime.now(tz=UTC) - timedelta(seconds=45)).isoformat(),
    }
    translate_summary = {
        "llama_corrections_count": llama_corrections,
        "total_runs": 20,
        "translated_runs": 18,
    }

    def _xcom_pull(task_ids, key):
        if task_ids == "validate_upload" and key == "upload_meta":
            return meta
        if task_ids == "translate_docx" and key == "translate_summary":
            return translate_summary
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_xcom_pull)
    return ctx


def test_finalize_sets_session_completed(monkeypatch) -> None:
    """task_finalize must set session status to 'completed'."""
    calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda sid, status, **kw: calls.append(status))
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)

    ctx = _make_finalize_context()
    dag_mod.task_finalize(**ctx)
    assert "completed" in calls


def test_finalize_sets_request_completed(monkeypatch) -> None:
    """task_finalize must set request status to 'completed'."""
    req_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda rid, **kw: req_calls.append(kw))

    ctx = _make_finalize_context()
    dag_mod.task_finalize(**ctx)
    assert any(c.get("status") == "completed" for c in req_calls)


def test_finalize_computes_positive_processing_time(monkeypatch) -> None:
    """task_finalize must compute a positive processing_time_seconds."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)

    start = (datetime.now(tz=UTC) - timedelta(seconds=30)).isoformat()
    ctx = _make_finalize_context(start_time=start)
    result = dag_mod.task_finalize(**ctx)
    assert result["processing_time_seconds"] is not None
    assert result["processing_time_seconds"] > 0


def test_finalize_invalid_start_time_returns_none(monkeypatch) -> None:
    """Unparseable start_time must not crash; processing_time_seconds must be None."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)

    ctx = _make_finalize_context(start_time="INVALID-TIMESTAMP")
    result = dag_mod.task_finalize(**ctx)
    assert result["processing_time_seconds"] is None


def test_finalize_propagates_llama_corrections(monkeypatch) -> None:
    """task_finalize must forward llama_corrections_count to _update_request."""
    req_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda rid, **kw: req_calls.append(kw))

    ctx = _make_finalize_context(llama_corrections=5)
    dag_mod.task_finalize(**ctx)
    assert any(c.get("llama_corrections_count") == 5 for c in req_calls)


# ===========================================================================
# _on_dag_failure
# ===========================================================================


def test_on_dag_failure_writes_failed_to_session(monkeypatch) -> None:
    """_on_dag_failure must set session status to 'failed'."""
    calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda sid, status, **kw: calls.append(status))
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)

    ctx = {
        "dag_run": MagicMock(conf={"session_id": _SESSION_ID, "request_id": _REQUEST_ID}),
        "task_instance": MagicMock(task_id="translate_docx"),
        "exception": Exception("OOM"),
    }
    dag_mod._on_dag_failure(ctx)
    assert "failed" in calls


def test_on_dag_failure_writes_failed_to_request(monkeypatch) -> None:
    """_on_dag_failure must set request status to 'failed'."""
    req_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda rid, **kw: req_calls.append(kw))
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)

    ctx = {
        "dag_run": MagicMock(conf={"session_id": _SESSION_ID, "request_id": _REQUEST_ID}),
        "task_instance": MagicMock(task_id="upload_to_gcs"),
        "exception": Exception("timeout"),
    }
    dag_mod._on_dag_failure(ctx)
    assert any(c.get("status") == "failed" for c in req_calls)


def test_on_dag_failure_graceful_no_conf(monkeypatch) -> None:
    """_on_dag_failure must not crash when conf is empty."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)

    ctx = {
        "dag_run": MagicMock(conf={}),
        "task_instance": MagicMock(task_id="validate_upload"),
        "exception": Exception("fail"),
    }
    # Must not raise
    dag_mod._on_dag_failure(ctx)


# ===========================================================================
# task_upload_to_gcs — pretranslation path (form_id in conf)
# ===========================================================================

_FORM_ID = str(uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))
_FORM_SLUG = "petition-for-custody"
_FORM_VERSION = 3


def _make_upload_context(
    form_id: str | None = None,
    target_lang: str = "es",
    output_path: str = "/tmp/output_es.docx",
) -> dict:
    """Build a context suitable for task_upload_to_gcs tests."""
    from dags.tests.conftest import _make_context

    conf = {}
    if form_id:
        conf["form_id"] = form_id
    ctx = _make_context(conf=conf)

    meta = {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "target_lang": target_lang,
    }

    def _pull(task_ids, key):
        if task_ids == "validate_upload" and key == "upload_meta":
            return meta
        if task_ids == "translate_docx" and key == "output_path":
            return output_path
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    return ctx


def _mock_orm_form(slug: str = _FORM_SLUG, version: int = _FORM_VERSION) -> MagicMock:
    """Return a mock ORM form object with one version."""
    mock_ver = MagicMock()
    mock_ver.version = version
    mock_ver.file_path_es = None
    mock_ver.file_path_pt = None
    mock_ver.file_type_es = None
    mock_ver.file_type_pt = None

    mock_form = MagicMock()
    mock_form.form_slug = slug
    mock_form.versions = [mock_ver]
    return mock_form


def _patch_upload_to_gcs_pretrans(monkeypatch, mock_form):
    """Patch all external calls for pretranslation upload path."""
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(
        f"{_PATCH_BASE}.gcs.parse_gcs_uri", lambda uri: ("test-forms", uri.split("gs://test-forms/")[1])
    )
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.generate_signed_url", lambda *a, **kw: "https://signed.url")
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
    ):
        yield


def test_upload_to_gcs_pretrans_uses_catalog_bucket(monkeypatch) -> None:
    """Pretranslation path must use the canonical catalog path (slug/version/lang)."""
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.parse_gcs_uri", lambda uri: ("bucket", "blob"))
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
    ):
        ctx = _make_upload_context(form_id=_FORM_ID, target_lang="es")
        result = dag_mod.task_upload_to_gcs(**ctx)

    # GCS URI must follow the canonical catalog path pattern:
    # gs://<GCS_BUCKET_FORMS>/forms/<slug>/v<version>/<slug>_<lang>.docx
    assert _FORM_SLUG in result["gcs_uri"]
    assert f"v{_FORM_VERSION}" in result["gcs_uri"]
    assert "_es.docx" in result["gcs_uri"]
    # Must NOT use the translated-documents bucket (user-upload path)
    assert "translated" not in result["gcs_uri"]


def test_upload_to_gcs_pretrans_signed_url_is_none(monkeypatch) -> None:
    """Pretranslation path must not generate a signed URL (returns None)."""
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.parse_gcs_uri", lambda uri: ("test-forms", "blob"))
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
    ):
        ctx = _make_upload_context(form_id=_FORM_ID, target_lang="es")
        result = dag_mod.task_upload_to_gcs(**ctx)

    assert result["signed_url"] is None
    assert result["signed_url_expires_at"] is None


def test_upload_to_gcs_pretrans_does_not_call_update_request(monkeypatch) -> None:
    """Pretranslation path must NOT call _update_request (no request row in DB)."""
    update_request_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: update_request_calls.append(a))
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.parse_gcs_uri", lambda uri: ("test-forms", "blob"))
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
    ):
        ctx = _make_upload_context(form_id=_FORM_ID)
        dag_mod.task_upload_to_gcs(**ctx)

    assert len(update_request_calls) == 0


def test_upload_to_gcs_pretrans_form_not_found_raises(monkeypatch) -> None:
    """Pretranslation path: form_id not found in DB must raise RuntimeError."""
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=None),
    ):
        ctx = _make_upload_context(form_id=_FORM_ID)
        with pytest.raises(RuntimeError, match="could not resolve slug/version"):
            dag_mod.task_upload_to_gcs(**ctx)


def test_upload_to_gcs_pretrans_pushes_gcs_result_xcom(monkeypatch) -> None:
    """Pretranslation path must push gcs_result to XCom."""
    monkeypatch.setattr(f"{_PATCH_BASE}._write_step", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.parse_gcs_uri", lambda uri: ("test-forms", "blob"))
    monkeypatch.setattr(f"{_PATCH_BASE}.gcs.upload_file", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
    ):
        ctx = _make_upload_context(form_id=_FORM_ID)
        dag_mod.task_upload_to_gcs(**ctx)

    ctx["ti"].xcom_push.assert_called_once()
    assert ctx["ti"].xcom_push.call_args.kwargs.get("key") == "gcs_result"


# ===========================================================================
# task_finalize — pretranslation path (form_id in conf)
# ===========================================================================


def _make_finalize_pretrans_context(
    form_id: str | None = _FORM_ID,
    target_lang: str = "es",
    gcs_uri: str = "gs://test-forms/forms/petition-for-custody/v3/petition-for-custody_es.docx",
    start_time: str | None = None,
) -> dict:
    from dags.tests.conftest import _make_context

    conf = {}
    if form_id:
        conf["form_id"] = form_id
    ctx = _make_context(conf=conf)

    meta = {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "target_lang": target_lang,
        "start_time": start_time or (datetime.now(tz=UTC) - timedelta(seconds=20)).isoformat(),
    }
    translate_summary = {"llama_corrections_count": 1, "total_runs": 10, "translated_runs": 9}
    gcs_result = {"gcs_uri": gcs_uri}

    def _pull(task_ids, key):
        if task_ids == "validate_upload" and key == "upload_meta":
            return meta
        if task_ids == "translate_docx" and key == "translate_summary":
            return translate_summary
        if task_ids == "upload_to_gcs" and key == "gcs_result":
            return gcs_result
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    return ctx


def test_finalize_pretrans_skips_update_session(monkeypatch) -> None:
    """Pretranslation path must NOT call _update_session (no session row for catalog runs)."""
    session_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: session_calls.append(a))
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync"),
    ):
        ctx = _make_finalize_pretrans_context()
        dag_mod.task_finalize(**ctx)

    assert len(session_calls) == 0


def test_finalize_pretrans_skips_update_request(monkeypatch) -> None:
    """Pretranslation path must NOT call _update_request (no request row for catalog runs)."""
    request_calls = []
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: request_calls.append(a))
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync"),
    ):
        ctx = _make_finalize_pretrans_context()
        dag_mod.task_finalize(**ctx)

    assert len(request_calls) == 0


def test_finalize_pretrans_updates_catalog_with_es_uri(monkeypatch) -> None:
    """Pretranslation path (ES) must call update_form_version_translations_sync with file_path_es set."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()
    catalog_calls = []

    def _fake_update(session, form_id, version, **kwargs):
        catalog_calls.append({"form_id": form_id, "version": version, **kwargs})

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync", side_effect=_fake_update),
    ):
        gcs_uri = "gs://test-forms/forms/petition-for-custody/v3/petition-for-custody_es.docx"
        ctx = _make_finalize_pretrans_context(target_lang="es", gcs_uri=gcs_uri)
        dag_mod.task_finalize(**ctx)

    assert len(catalog_calls) == 1
    assert catalog_calls[0]["file_path_es"] == gcs_uri
    assert catalog_calls[0]["file_type_es"] == "docx"
    # PT fields must be preserved (None in this case — form has no existing PT)
    assert catalog_calls[0]["file_path_pt"] is None


def test_finalize_pretrans_updates_catalog_with_pt_uri(monkeypatch) -> None:
    """Pretranslation path (PT) must call update_form_version_translations_sync with file_path_pt set."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()
    catalog_calls = []

    def _fake_update(session, form_id, version, **kwargs):
        catalog_calls.append({"form_id": form_id, "version": version, **kwargs})

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync", side_effect=_fake_update),
    ):
        gcs_uri = "gs://test-forms/forms/petition-for-custody/v3/petition-for-custody_pt.docx"
        ctx = _make_finalize_pretrans_context(target_lang="pt", gcs_uri=gcs_uri)
        dag_mod.task_finalize(**ctx)

    assert len(catalog_calls) == 1
    assert catalog_calls[0]["file_path_pt"] == gcs_uri
    assert catalog_calls[0]["file_type_pt"] == "docx"
    assert catalog_calls[0]["file_path_es"] is None


def test_finalize_pretrans_preserves_existing_es_when_running_pt(monkeypatch) -> None:
    """PT run must preserve the existing ES path in the catalog update."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)

    # Form already has an ES path
    mock_form = _mock_orm_form()
    existing_es = "gs://test-forms/forms/petition-for-custody/v3/petition-for-custody_es.docx"
    mock_form.versions[0].file_path_es = existing_es
    mock_form.versions[0].file_type_es = "docx"

    catalog_calls = []

    def _fake_update(session, form_id, version, **kwargs):
        catalog_calls.append(kwargs)

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync", side_effect=_fake_update),
    ):
        pt_uri = "gs://test-forms/forms/petition-for-custody/v3/petition-for-custody_pt.docx"
        ctx = _make_finalize_pretrans_context(target_lang="pt", gcs_uri=pt_uri)
        dag_mod.task_finalize(**ctx)

    assert catalog_calls[0]["file_path_es"] == existing_es
    assert catalog_calls[0]["file_type_es"] == "docx"


def test_finalize_pretrans_form_not_found_does_not_crash(monkeypatch) -> None:
    """form_id not in DB must log a warning and return normally — never crash finalize."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=None),
    ):
        ctx = _make_finalize_pretrans_context()
        result = dag_mod.task_finalize(**ctx)  # must not raise

    assert result["finalized"] is True


def test_finalize_pretrans_catalog_exception_does_not_abort(monkeypatch) -> None:
    """Catalog update failure must be swallowed — finalize must return normally."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}.get_sync_engine", lambda: MagicMock())

    from unittest.mock import patch

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=session_ctx)
    session_ctx.__exit__ = MagicMock(return_value=False)
    mock_form = _mock_orm_form()

    with (
        patch(f"{_PATCH_BASE}.Session", return_value=session_ctx),
        patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form),
        patch(
            f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync",
            side_effect=Exception("DB connection lost"),
        ),
    ):
        ctx = _make_finalize_pretrans_context()
        result = dag_mod.task_finalize(**ctx)  # must not raise

    assert result["finalized"] is True


def test_finalize_pretrans_no_gcs_uri_skips_catalog_update(monkeypatch) -> None:
    """If gcs_result has no URI, catalog update must be skipped without crash."""
    monkeypatch.setattr(f"{_PATCH_BASE}._update_session", lambda *a, **kw: None)
    monkeypatch.setattr(f"{_PATCH_BASE}._update_request", lambda *a, **kw: None)

    from unittest.mock import patch

    catalog_calls = []
    with patch(
        f"{_PATCH_BASE}.form_queries.update_form_version_translations_sync",
        side_effect=lambda *a, **kw: catalog_calls.append(1),
    ):
        ctx = _make_finalize_pretrans_context(gcs_uri="")
        result = dag_mod.task_finalize(**ctx)

    assert result["finalized"] is True
    assert len(catalog_calls) == 0
