"""
dags/tests/test_form_scraper_dag.py

Unit tests for dags/form_scraper_dag.py.

Covers:
  - _get_actor_id: no dag_run → system user; valid UUID → returned as-is;
      invalid UUID string → falls back to system user
  - task_validate_catalog: empty catalog → valid=False; valid forms → correct
      counts; duplicate form_id → error; duplicate source_url → error;
      invalid status → error; no versions → error
  - task_detect_anomalies: missing inputs → severity=skipped; mass new forms
      above threshold → WARNING anomaly; below threshold → no anomaly
  - _write_single_form_to_db: IntegrityError triggers retry with suffixed slug
  - task_cleanup_local_forms: empty gcs_path_map → 0 deletions; local files
      listed in map are deleted
  - task_write_catalog_to_db: empty forms → returns written=0; all-fail
      scenario raises RuntimeError
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module under test — imported AFTER env vars are set in conftest.py
# ---------------------------------------------------------------------------
import dags.form_scraper_dag as dag_mod
from dags.tests.conftest import _make_context

_SYSTEM_USER = "00000000-0000-0000-0000-000000000001"
_VALID_USER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag_run(conf: dict | None = None) -> MagicMock:
    dr = MagicMock()
    dr.conf = conf or {}
    return dr


def _make_valid_form(
    form_id: str | None = None,
    source_url: str | None = None,
    status: str = "active",
    versions: list | None = None,
) -> dict:
    fid = form_id or str(uuid.uuid4())
    return {
        "form_id": fid,
        "form_name": f"Form {fid[:8]}",
        "form_slug": f"form-{fid[:8]}",
        "source_url": source_url or f"https://mass.gov/forms/{fid[:8]}.pdf",
        "status": status,
        "current_version": 1,
        "appearances": [{"division": "Civil", "section_heading": "General"}],
        "versions": versions if versions is not None else [{"version": 1, "file_path_original": "/tmp/form.pdf"}],
    }


# ===========================================================================
# _get_actor_id
# ===========================================================================


def test_get_actor_id_returns_system_user_when_no_dag_run() -> None:
    """No dag_run → must return AIRFLOW_SYSTEM_USER_ID."""
    ctx = {"dag_run": None}
    assert dag_mod._get_actor_id(ctx) == _SYSTEM_USER


def test_get_actor_id_returns_system_user_when_no_conf() -> None:
    """dag_run with no conf → must return AIRFLOW_SYSTEM_USER_ID."""
    dr = MagicMock()
    dr.conf = None
    ctx = {"dag_run": dr}
    assert dag_mod._get_actor_id(ctx) == _SYSTEM_USER


def test_get_actor_id_returns_system_user_when_conf_empty() -> None:
    """Empty conf → must return AIRFLOW_SYSTEM_USER_ID."""
    ctx = {"dag_run": _make_dag_run({})}
    assert dag_mod._get_actor_id(ctx) == _SYSTEM_USER


def test_get_actor_id_returns_valid_uuid() -> None:
    """Valid UUID in triggered_by_user_id → must be returned unchanged."""
    ctx = {"dag_run": _make_dag_run({"triggered_by_user_id": _VALID_USER_ID})}
    result = dag_mod._get_actor_id(ctx)
    assert result == _VALID_USER_ID


def test_get_actor_id_falls_back_on_invalid_uuid() -> None:
    """Invalid UUID string → must fall back to AIRFLOW_SYSTEM_USER_ID."""
    ctx = {"dag_run": _make_dag_run({"triggered_by_user_id": "not-a-uuid"})}
    result = dag_mod._get_actor_id(ctx)
    assert result == _SYSTEM_USER


def test_get_actor_id_falls_back_on_non_string() -> None:
    """Non-string value for triggered_by_user_id must fall back to system user."""
    ctx = {"dag_run": _make_dag_run({"triggered_by_user_id": 12345})}
    result = dag_mod._get_actor_id(ctx)
    assert result == _SYSTEM_USER


# ===========================================================================
# task_validate_catalog
# ===========================================================================


def _validate_context(forms: list) -> dict:
    ctx = _make_context()
    xcom_store = {"forms_preprocessed": forms}

    def _pull(task_ids, key):
        if key == "forms_preprocessed":
            return xcom_store.get("forms_preprocessed")
        if key == "forms":
            return xcom_store.get("forms_preprocessed")
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    return ctx


def test_validate_catalog_empty_returns_valid_false() -> None:
    """Empty catalog must return valid=False."""
    ctx = _validate_context([])
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["valid"] is False


def test_validate_catalog_single_valid_form_returns_valid_true(monkeypatch) -> None:
    """Single fully-valid form must return valid=True."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    forms = [_make_valid_form(versions=[{"version": 1, "file_path_original": "/tmp/f.pdf"}])]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["valid"] is True
    assert result["total_forms"] == 1


def test_validate_catalog_duplicate_form_id_is_error(monkeypatch) -> None:
    """Two entries with the same form_id must produce at least one error."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    fid = str(uuid.uuid4())
    forms = [
        _make_valid_form(form_id=fid, source_url="https://mass.gov/a"),
        _make_valid_form(form_id=fid, source_url="https://mass.gov/b"),
    ]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["errors"] >= 1
    assert result["valid"] is False


def test_validate_catalog_duplicate_source_url_is_error(monkeypatch) -> None:
    """Two entries with the same source_url must produce at least one error."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    url = "https://mass.gov/duplicate.pdf"
    forms = [
        _make_valid_form(source_url=url),
        _make_valid_form(source_url=url),
    ]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["errors"] >= 1


def test_validate_catalog_invalid_status_is_error(monkeypatch) -> None:
    """Status other than 'active'/'archived' must produce an error."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    forms = [_make_valid_form(status="unknown_status")]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["errors"] >= 1


def test_validate_catalog_no_versions_is_error(monkeypatch) -> None:
    """Form with no versions must produce an error."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    forms = [_make_valid_form(versions=[])]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["errors"] >= 1


def test_validate_catalog_counts_active_forms(monkeypatch) -> None:
    """active_forms count must reflect only active-status entries."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    forms = [
        _make_valid_form(status="active"),
        _make_valid_form(status="active"),
        _make_valid_form(status="archived"),
    ]
    ctx = _validate_context(forms)
    result = dag_mod.task_validate_catalog(**ctx)
    assert result["active_forms"] == 2
    assert result["archived_forms"] == 1


def test_validate_catalog_pushes_metrics_xcom(monkeypatch) -> None:
    """task_validate_catalog must push validation_metrics to XCom (needs at least one form)."""
    monkeypatch.setattr("dags.form_scraper_dag.gcs.parse_gcs_uri", lambda uri: ("b", "blob"))
    monkeypatch.setattr("dags.form_scraper_dag.gcs.blob_exists", lambda b, bl: True)

    forms = [_make_valid_form()]
    ctx = _validate_context(forms)
    dag_mod.task_validate_catalog(**ctx)
    ctx["ti"].xcom_push.assert_called_once()
    assert ctx["ti"].xcom_push.call_args.kwargs.get("key") == "validation_metrics"


# ===========================================================================
# task_detect_anomalies
# ===========================================================================


def _detect_context(scrape_result: dict | None, metrics: dict | None, forms: list | None = None) -> dict:
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "scrape_result":
            return scrape_result
        if key == "validation_metrics":
            return metrics
        if key in ("forms_preprocessed", "forms"):
            return forms or []
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    return ctx


def test_detect_anomalies_missing_inputs_returns_skipped() -> None:
    """Missing scrape_result or metrics must return severity='skipped'."""
    ctx = _detect_context(None, None)
    result = dag_mod.task_detect_anomalies(**ctx)
    assert result["severity"] == "skipped"


def _mock_mlflow_patches():
    """
    Return a combined patch context that replaces the mlflow module with a full
    MagicMock.  task_detect_anomalies imports mlflow lazily inside the function,
    so we must patch sys.modules to intercept that import.
    """
    import sys

    mock_mlf = MagicMock()
    # Make start_run usable as a context manager
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    mock_mlf.start_run.return_value = cm
    return patch.dict(sys.modules, {"mlflow": mock_mlf})


def test_detect_anomalies_no_anomalies_when_below_thresholds() -> None:
    """No anomaly when new forms count is below THRESHOLD_MASS_NEW_FORMS."""
    scrape_result = {"counts": {"new": 1, "updated": 0, "unchanged": 10, "removed": 0}}
    metrics = {"active_forms": 10, "errors": 0}
    ctx = _detect_context(scrape_result, metrics)
    with (
        patch("dags.form_scraper_dag._prev_active_forms_count", return_value=None),
        _mock_mlflow_patches(),
    ):
        result = dag_mod.task_detect_anomalies(**ctx)
    assert result["anomalies"] == []


def test_detect_anomalies_mass_new_forms_triggers_warning() -> None:
    """new forms > THRESHOLD_MASS_NEW_FORMS must produce a WARNING anomaly."""
    # THRESHOLD_MASS_NEW_FORMS is set to 50 in conftest
    scrape_result = {"counts": {"new": 100, "updated": 0, "unchanged": 5, "removed": 0}}
    metrics = {"active_forms": 105, "errors": 0}
    ctx = _detect_context(scrape_result, metrics)
    with (
        patch("dags.form_scraper_dag._prev_active_forms_count", return_value=None),
        _mock_mlflow_patches(),
    ):
        result = dag_mod.task_detect_anomalies(**ctx)
    mass_anomaly = [a for a in result["anomalies"] if a["check"] == "mass_new_forms"]
    assert len(mass_anomaly) == 1
    assert mass_anomaly[0]["severity"] == "WARNING"


def test_detect_anomalies_form_count_drop_triggers_critical() -> None:
    """Active form count drop > threshold must produce a CRITICAL anomaly."""
    # prev=100, curr=50 → 50% drop > 20% threshold
    scrape_result = {"counts": {"new": 0, "updated": 0, "unchanged": 50, "removed": 50}}
    metrics = {"active_forms": 50, "errors": 0}
    ctx = _detect_context(scrape_result, metrics)
    with (
        patch("dags.form_scraper_dag._prev_active_forms_count", return_value=100),
        _mock_mlflow_patches(),
    ):
        result = dag_mod.task_detect_anomalies(**ctx)
    drop_anomaly = [a for a in result["anomalies"] if a["check"] == "form_count_drop"]
    assert len(drop_anomaly) == 1
    assert drop_anomaly[0]["severity"] == "CRITICAL"


def test_detect_anomalies_no_drop_when_below_threshold() -> None:
    """Small form count drop (below threshold) must NOT produce an anomaly."""
    # prev=100, curr=95 → 5% drop < 20% threshold
    scrape_result = {"counts": {"new": 0, "updated": 0, "unchanged": 95, "removed": 5}}
    metrics = {"active_forms": 95, "errors": 0}
    ctx = _detect_context(scrape_result, metrics)
    with (
        patch("dags.form_scraper_dag._prev_active_forms_count", return_value=100),
        _mock_mlflow_patches(),
    ):
        result = dag_mod.task_detect_anomalies(**ctx)
    drop_anomaly = [a for a in result["anomalies"] if a["check"] == "form_count_drop"]
    assert len(drop_anomaly) == 0


# ===========================================================================
# task_cleanup_local_forms
# ===========================================================================


def test_cleanup_local_forms_empty_map_returns_zero(monkeypatch) -> None:
    """Empty gcs_path_map must return deleted=0, failed=0 without side effects."""
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value={})
    result = dag_mod.task_cleanup_local_forms(**ctx)
    assert result == {"deleted": 0, "failed": 0}


def test_cleanup_local_forms_deletes_listed_files(tmp_path: Path) -> None:
    """Files listed in gcs_path_map must be deleted from the local filesystem."""
    local_file = tmp_path / "form.pdf"
    local_file.write_bytes(b"dummy")
    assert local_file.exists()

    gcs_path_map = {str(local_file): "gs://test-forms/forms/form/v1/form.pdf"}
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value=gcs_path_map)
    result = dag_mod.task_cleanup_local_forms(**ctx)
    assert result["deleted"] == 1
    assert result["failed"] == 0
    assert not local_file.exists()


def test_cleanup_local_forms_counts_failed_for_missing_file() -> None:
    """Files that no longer exist at cleanup time must not crash and count as failed=0."""
    gcs_path_map = {"/nonexistent/path/ghost.pdf": "gs://test-forms/forms/ghost.pdf"}
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value=gcs_path_map)
    # missing_ok=True in unlink — so this should succeed with deleted=1
    result = dag_mod.task_cleanup_local_forms(**ctx)
    # unlink(missing_ok=True) means deleted increments (no error for missing files)
    assert result["failed"] == 0


# ===========================================================================
# _write_single_form_to_db
# ===========================================================================


def test_write_single_form_integrity_error_retries_with_suffixed_slug() -> None:
    """On IntegrityError for slug collision, must retry with suffixed slug."""
    from sqlalchemy.exc import IntegrityError

    call_log: list[str] = []
    attempt_count = 0

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def begin(self):
            return self

        def __call__(self, *args, **kwargs):
            return self

    class FakeSessionCtx:
        """Simulates 'with FakeSession(engine) as session, session.begin()' pattern."""

        def __init__(self, engine):
            pass

        def __enter__(self):
            return _FakeSession()

        def __exit__(self, *a, **kw):
            pass

    class _FakeSession:
        def begin(self):
            return self

        def __enter__(self):
            nonlocal attempt_count
            attempt_count += 1
            return self

        def __exit__(self, exc_type, *a):
            return False

    def _fake_write(session, catalog_row):
        call_log.append(catalog_row["form_slug"])
        # First call raises IntegrityError (slug collision)
        if len(call_log) == 1:
            exc = MagicMock()
            exc.orig = "DETAIL: Key (form_slug)=(test-form) already exists."
            raise IntegrityError("INSERT", {}, exc)

    # Patch form_queries to use our fake writer
    with (
        patch("dags.form_scraper_dag.form_queries.upsert_form_catalog_sync", side_effect=_fake_write),
        patch("dags.form_scraper_dag.form_queries.upsert_form_version_sync"),
        patch("dags.form_scraper_dag.form_queries.upsert_form_appearance_sync"),
    ):
        entry = _make_valid_form()
        engine = MagicMock()
        dag_mod._write_single_form_to_db(engine, entry, FakeSessionCtx, IntegrityError)

    # Must have attempted twice — second slug is suffixed
    assert len(call_log) == 2
    original_slug = entry["form_slug"]
    assert call_log[0] == original_slug
    assert call_log[1].startswith(original_slug)
    assert call_log[1] != original_slug  # suffix was appended


# ===========================================================================
# task_write_catalog_to_db
# ===========================================================================


def test_write_catalog_to_db_empty_forms_returns_zero(monkeypatch) -> None:
    """No forms in XCom must return written=0, failed=0 immediately."""
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value=[])
    result = dag_mod.task_write_catalog_to_db(**ctx)
    assert result == {"written": 0, "failed": 0}


def test_write_catalog_to_db_all_fail_raises_runtime_error(monkeypatch) -> None:
    """If every entry fails to write, RuntimeError must be raised."""
    monkeypatch.setattr("dags.form_scraper_dag.get_sync_engine", lambda: MagicMock())
    monkeypatch.setattr(
        "dags.form_scraper_dag._write_single_form_to_db",
        MagicMock(side_effect=Exception("DB down")),
    )

    forms = [_make_valid_form(), _make_valid_form()]
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value=forms)
    with pytest.raises(RuntimeError, match="every entry failed"):
        dag_mod.task_write_catalog_to_db(**ctx)
