"""
dags/tests/test_docx_pipeline_dag.py

Unit tests for dags/docx_pipeline_dag.py.

Covers:
  - task_validate_upload: bad DOCX magic bytes → AirflowFailException; valid
      DOCX → meta returned + XCom pushed; session marked 'processing';
      filename path-traversal sanitised; nllb_target defaults correctly
  - task_finalize: processing_time_seconds computed; invalid start_time → None;
      sessions / requests updated with status=completed
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
