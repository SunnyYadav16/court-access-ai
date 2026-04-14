"""
dags/tests/test_document_pipeline_dag.py

Unit tests for dags/document_pipeline_dag.py.

Covers:
  - _dump / _load: round-trip serialisation
  - task_validate_upload: missing session_id / request_id → AirflowFailException;
      bad PDF magic bytes → AirflowFailException; valid PDF → meta returned +
      XCom pushed; filename path-traversal sanitised
  - task_classify_document: ClassificationError → status=failed; non-legal →
      status=rejected; legal → returns result + XCom pushed
  - _on_dag_failure: does NOT overwrite "rejected" status; overwrites other statuses
  - task_finalize: processing_time_seconds computed; invalid start_time → None;
      sessions / requests updated with status=completed
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module under test — imported AFTER env vars are set in conftest.py
# ---------------------------------------------------------------------------
import dags.document_pipeline_dag as dag_mod
from dags.tests.conftest import _make_context

_PATCH_BASE = "dags.document_pipeline_dag"

_SESSION_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000010"))
_REQUEST_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000011"))
_USER_ID = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_pdf(tmp_path: Path, name: str = "doc.pdf") -> Path:
    """Write a minimal file with PDF magic bytes to tmp_path/name."""
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 %%EOF")
    return p


def _base_conf(pdf_path: str) -> dict:
    return {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "user_id": _USER_ID,
        "gcs_input_path": pdf_path,  # local path → bypasses GCS download
        "target_lang": "es",
        "nllb_target": "spa_Latn",
        "filename": Path(pdf_path).name,
        "start_time": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC).isoformat(),
    }


# ===========================================================================
# _dump / _load helpers
# ===========================================================================


def test_dump_creates_json_file(tmp_path: Path) -> None:
    path = dag_mod._dump(str(tmp_path), "test_key", [{"a": 1}, {"b": 2}])
    assert Path(path).exists()
    assert Path(path).name == "xcom_test_key.json"


def test_dump_load_round_trip(tmp_path: Path) -> None:
    data = [{"text": "hello", "confidence": 0.95}, {"text": "world", "confidence": 0.80}]
    path = dag_mod._dump(str(tmp_path), "regions", data)
    loaded = dag_mod._load(path)
    assert loaded == data


def test_load_round_trip_preserves_nested_types(tmp_path: Path) -> None:
    data = {"key": [1, 2, 3], "nested": {"a": True, "b": None}}
    path = dag_mod._dump(str(tmp_path), "meta", data)
    assert dag_mod._load(path) == data


# ===========================================================================
# task_validate_upload
# ===========================================================================


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_missing_session_id_raises(mock_us, mock_ur, mock_ws) -> None:
    """Missing session_id must raise AirflowFailException immediately."""
    from airflow.exceptions import AirflowFailException

    ctx = _make_context({"request_id": _REQUEST_ID, "gcs_input_path": "/nonexistent"})
    with pytest.raises(AirflowFailException, match="session_id"):
        dag_mod.task_validate_upload(**ctx)


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_missing_request_id_raises(mock_us, mock_ur, mock_ws) -> None:
    """Missing request_id must raise AirflowFailException immediately."""
    from airflow.exceptions import AirflowFailException

    ctx = _make_context({"session_id": _SESSION_ID, "gcs_input_path": "/nonexistent"})
    with pytest.raises(AirflowFailException, match="request_id"):
        dag_mod.task_validate_upload(**ctx)


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_bad_magic_bytes_raises(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """File with wrong magic bytes must raise AirflowFailException."""
    from airflow.exceptions import AirflowFailException

    bad_file = tmp_path / "bad.pdf"
    bad_file.write_bytes(b"NOTAPDF this is garbage")
    ctx = _make_context(_base_conf(str(bad_file)))
    with pytest.raises(AirflowFailException, match="magic"):
        dag_mod.task_validate_upload(**ctx)


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_bad_magic_sets_session_failed(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """After bad magic, _update_session must be called with status=failed."""
    from airflow.exceptions import AirflowFailException

    bad_file = tmp_path / "bad.pdf"
    bad_file.write_bytes(b"GARBAGE")
    ctx = _make_context(_base_conf(str(bad_file)))
    with pytest.raises(AirflowFailException):
        dag_mod.task_validate_upload(**ctx)
    mock_us.assert_any_call(_SESSION_ID, "failed")


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_valid_pdf_returns_meta(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """Valid PDF must return a meta dict with all required keys."""
    pdf = _make_valid_pdf(tmp_path)
    ctx = _make_context(_base_conf(str(pdf)))
    result = dag_mod.task_validate_upload(**ctx)
    assert result["session_id"] == _SESSION_ID
    assert result["request_id"] == _REQUEST_ID
    assert result["target_lang"] == "es"
    assert "work_dir" in result
    assert "local_pdf" in result


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_pushes_xcom(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """Valid PDF must push upload_meta to XCom."""
    pdf = _make_valid_pdf(tmp_path)
    ctx = _make_context(_base_conf(str(pdf)))
    dag_mod.task_validate_upload(**ctx)
    ctx["ti"].xcom_push.assert_called_once()
    call_kwargs = ctx["ti"].xcom_push.call_args.kwargs
    assert call_kwargs.get("key") == "upload_meta"
    assert isinstance(call_kwargs.get("value"), dict)


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_marks_session_processing(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """Valid PDF must mark session as 'processing'."""
    pdf = _make_valid_pdf(tmp_path)
    ctx = _make_context(_base_conf(str(pdf)))
    dag_mod.task_validate_upload(**ctx)
    mock_us.assert_any_call(_SESSION_ID, "processing")


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_sanitizes_path_traversal_filename(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """Filenames with ../ path traversal must be sanitised."""
    pdf = _make_valid_pdf(tmp_path, "legit.pdf")
    conf = _base_conf(str(pdf))
    conf["filename"] = "../../etc/passwd"
    ctx = _make_context(conf)
    result = dag_mod.task_validate_upload(**ctx)
    # Path traversal components must be stripped
    assert ".." not in result["filename"]
    assert "/" not in result["filename"]


@patch(f"{_PATCH_BASE}._write_step")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_validate_upload_nllb_target_defaults_for_es(mock_us, mock_ur, mock_ws, tmp_path: Path) -> None:
    """When target_lang=es and nllb_target is absent, default to 'spa_Latn'."""
    pdf = _make_valid_pdf(tmp_path)
    conf = _base_conf(str(pdf))
    conf.pop("nllb_target", None)
    ctx = _make_context(conf)
    result = dag_mod.task_validate_upload(**ctx)
    assert result["nllb_target"] == "spa_Latn"


# ===========================================================================
# task_classify_document
# ===========================================================================


def _make_classify_context(local_pdf: str) -> dict:
    ctx = _make_context()
    meta = {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "local_pdf": local_pdf,
    }
    ctx["ti"].xcom_pull = MagicMock(return_value=meta)
    return ctx


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_classification_error_raises(
    mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path
) -> None:
    """ClassificationError must re-raise as AirflowFailException."""
    from airflow.exceptions import AirflowFailException

    from courtaccess.core.classify_document import ClassificationError

    mock_classify.side_effect = ClassificationError("model unavailable")
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    with pytest.raises(AirflowFailException, match="Classifier error"):
        dag_mod.task_classify_document(**ctx)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_classification_error_sets_failed_status(
    mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path
) -> None:
    """ClassificationError must set request status='failed' before raising."""
    from unittest.mock import ANY

    from airflow.exceptions import AirflowFailException

    from courtaccess.core.classify_document import ClassificationError

    mock_classify.side_effect = ClassificationError("boom")
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    with pytest.raises(AirflowFailException):
        dag_mod.task_classify_document(**ctx)
    mock_ur.assert_any_call(_REQUEST_ID, status="failed", error_message=ANY)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_non_legal_raises(mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path) -> None:
    """Non-legal document must raise AirflowFailException."""
    from airflow.exceptions import AirflowFailException

    mock_classify.return_value = {"classification": "non_legal", "confidence": 0.92, "reason": "Sports form"}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    with pytest.raises(AirflowFailException, match="Rejected"):
        dag_mod.task_classify_document(**ctx)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_non_legal_sets_rejected_status(
    mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path
) -> None:
    """Non-legal document must set request status='rejected', NOT 'failed'."""
    from airflow.exceptions import AirflowFailException

    mock_classify.return_value = {"classification": "non_legal", "confidence": 0.88, "reason": "Sports"}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    with pytest.raises(AirflowFailException):
        dag_mod.task_classify_document(**ctx)
    # Must call with status=rejected
    from unittest.mock import ANY

    mock_ur.assert_any_call(_REQUEST_ID, status="rejected", error_message=ANY)
    # Must NOT call with status=failed
    failed_calls = [c for c in mock_ur.call_args_list if c.kwargs.get("status") == "failed"]
    assert len(failed_calls) == 0, "rejected documents must not get status=failed"


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_non_legal_writes_not_legal_classification(
    mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path
) -> None:
    """The classification_result written to DB must be 'NOT_LEGAL' for non-legal docs."""
    from airflow.exceptions import AirflowFailException

    mock_classify.return_value = {"classification": "non_legal", "confidence": 0.95, "reason": ""}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    with pytest.raises(AirflowFailException):
        dag_mod.task_classify_document(**ctx)
    classification_calls = [c for c in mock_ur.call_args_list if "classification_result" in c.kwargs]
    assert any(c.kwargs["classification_result"] == "NOT_LEGAL" for c in classification_calls)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_legal_returns_result(mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path) -> None:
    """Legal document must return classification result dict."""
    mock_classify.return_value = {"classification": "legal", "confidence": 0.97, "reason": "Court motion"}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    result = dag_mod.task_classify_document(**ctx)
    assert result["classification"] == "legal"
    assert result["confidence"] == pytest.approx(0.97)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_legal_pushes_xcom(mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path) -> None:
    """Legal document must push classification result to XCom."""
    mock_classify.return_value = {"classification": "legal", "confidence": 0.97, "reason": ""}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    dag_mod.task_classify_document(**ctx)
    ctx["ti"].xcom_push.assert_called_once()
    call_kwargs = ctx["ti"].xcom_push.call_args.kwargs
    assert call_kwargs.get("key") == "classification"
    assert isinstance(call_kwargs.get("value"), dict)


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
@patch("courtaccess.core.classify_document.classify_document")
def test_classify_document_legal_writes_legal_classification(
    mock_classify, mock_ws, mock_us, mock_ur, tmp_path: Path
) -> None:
    """Legal document must write classification_result='LEGAL' to DB."""
    mock_classify.return_value = {"classification": "legal", "confidence": 0.97, "reason": ""}
    ctx = _make_classify_context(str(tmp_path / "test.pdf"))
    dag_mod.task_classify_document(**ctx)
    classification_calls = [c for c in mock_ur.call_args_list if "classification_result" in c.kwargs]
    assert any(c.kwargs["classification_result"] == "LEGAL" for c in classification_calls)


# ===========================================================================
# _on_dag_failure
# ===========================================================================


@patch(f"{_PATCH_BASE}._get_request_status", return_value="rejected")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
def test_on_dag_failure_does_not_overwrite_rejected(mock_ws, mock_us, mock_ur, mock_grs) -> None:
    """If current status is 'rejected', _on_dag_failure must NOT overwrite it."""
    ctx = {
        "dag_run": MagicMock(conf={"session_id": _SESSION_ID, "request_id": _REQUEST_ID}),
        "task_instance": MagicMock(task_id="classify_document"),
        "exception": Exception("test error"),
    }
    dag_mod._on_dag_failure(ctx)
    # _update_request must NOT be called with status=failed
    failed_calls = [c for c in mock_ur.call_args_list if c.kwargs.get("status") == "failed"]
    assert len(failed_calls) == 0, "_on_dag_failure must not overwrite 'rejected' status"


@patch(f"{_PATCH_BASE}._get_request_status", return_value="processing")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
def test_on_dag_failure_overwrites_processing_status(mock_ws, mock_us, mock_ur, mock_grs) -> None:
    """If current status is 'processing', _on_dag_failure MUST set it to 'failed'."""
    from unittest.mock import ANY

    ctx = {
        "dag_run": MagicMock(conf={"session_id": _SESSION_ID, "request_id": _REQUEST_ID}),
        "task_instance": MagicMock(task_id="translate"),
        "exception": Exception("translation failed"),
    }
    dag_mod._on_dag_failure(ctx)
    mock_ur.assert_any_call(_REQUEST_ID, status="failed", error_message=ANY)


@patch(f"{_PATCH_BASE}._get_request_status", return_value="completed")
@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
def test_on_dag_failure_sets_session_failed(mock_ws, mock_us, mock_ur, mock_grs) -> None:
    """_on_dag_failure must always call _update_session with status='failed'."""
    ctx = {
        "dag_run": MagicMock(conf={"session_id": _SESSION_ID, "request_id": _REQUEST_ID}),
        "task_instance": MagicMock(task_id="finalize"),
        "exception": Exception("timeout"),
    }
    dag_mod._on_dag_failure(ctx)
    mock_us.assert_any_call(_SESSION_ID, "failed")


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
@patch(f"{_PATCH_BASE}._write_step")
def test_on_dag_failure_graceful_when_no_session_or_request(mock_ws, mock_us, mock_ur) -> None:
    """_on_dag_failure must not crash when session_id/request_id are absent."""
    ctx = {
        "dag_run": MagicMock(conf={}),
        "task_instance": MagicMock(task_id="validate_upload"),
        "exception": Exception("oops"),
    }
    # Must not raise
    dag_mod._on_dag_failure(ctx)
    mock_us.assert_not_called()
    mock_ur.assert_not_called()


# ===========================================================================
# task_finalize
# ===========================================================================


def _make_finalize_context(
    start_time: str | None = None,
    avg_confidence: float = 0.9,
    corrections_count: int = 3,
) -> dict:
    ctx = _make_context()
    meta = {
        "session_id": _SESSION_ID,
        "request_id": _REQUEST_ID,
        "target_lang": "es",
        "start_time": start_time or (datetime.now(tz=UTC) - timedelta(seconds=30)).isoformat(),
    }
    ocr_summary = {"avg_confidence": avg_confidence, "total_regions": 10, "translatable": 8}
    legal_summary = {"corrections_count": corrections_count, "status": "ok"}

    def _xcom_pull(task_ids, key):
        if task_ids == "validate_upload" and key == "upload_meta":
            return meta
        if task_ids == "ocr_printed_text" and key == "ocr_summary":
            return ocr_summary
        if task_ids == "legal_review" and key == "legal_summary":
            return legal_summary
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_xcom_pull)
    return ctx


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_sets_session_completed(mock_us, mock_ur) -> None:
    """task_finalize must set session status to 'completed'."""
    ctx = _make_finalize_context()
    dag_mod.task_finalize(**ctx)
    mock_us.assert_called_once()
    assert mock_us.call_args[0][1] == "completed"


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_sets_request_completed(mock_us, mock_ur) -> None:
    """task_finalize must set request status to 'completed'."""
    ctx = _make_finalize_context()
    dag_mod.task_finalize(**ctx)
    mock_ur.assert_called_once()
    assert mock_ur.call_args.kwargs.get("status") == "completed"


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_computes_processing_time(mock_us, mock_ur) -> None:
    """task_finalize must compute processing_time_seconds from start_time."""
    start = (datetime.now(tz=UTC) - timedelta(seconds=60)).isoformat()
    ctx = _make_finalize_context(start_time=start)
    result = dag_mod.task_finalize(**ctx)
    assert result["processing_time_seconds"] is not None
    assert result["processing_time_seconds"] > 0


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_invalid_start_time_sets_none(mock_us, mock_ur) -> None:
    """If start_time is unparseable, processing_time_seconds must be None (no crash)."""
    ctx = _make_finalize_context(start_time="not-a-datetime")
    result = dag_mod.task_finalize(**ctx)
    assert result["processing_time_seconds"] is None


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_propagates_llama_corrections_count(mock_us, mock_ur) -> None:
    """task_finalize must forward llama_corrections_count from legal_summary to DB."""
    ctx = _make_finalize_context(corrections_count=7)
    dag_mod.task_finalize(**ctx)
    assert mock_ur.call_args.kwargs.get("llama_corrections_count") == 7


@patch(f"{_PATCH_BASE}._update_request")
@patch(f"{_PATCH_BASE}._update_session")
def test_finalize_propagates_avg_confidence(mock_us, mock_ur) -> None:
    """task_finalize must forward avg_confidence_score from ocr_summary to DB."""
    ctx = _make_finalize_context(avg_confidence=0.82)
    dag_mod.task_finalize(**ctx)
    assert mock_ur.call_args.kwargs.get("avg_confidence_score") == pytest.approx(0.82)
