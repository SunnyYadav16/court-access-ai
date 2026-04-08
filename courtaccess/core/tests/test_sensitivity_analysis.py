"""
Unit tests for courtaccess/core/sensitivity_analysis.py

Functions under test:
  _stdev                    — pure: population std-dev
  _pearson                  — pure: Pearson correlation coefficient
  _load_catalog             — reads JSON, returns [] on missing file
  run_threshold_sweep       — grid search over bias-detection thresholds
  run_input_characteristics — DB queries with graceful fallback
  run_sensitivity_analysis  — orchestrator combining both sub-analyses

Design notes:
  - _stdev and _pearson are pure math helpers: tested with known values,
    edge cases, and numerical correctness verified by hand.
  - _load_catalog uses a real tmp_path filesystem; no mocking required.
  - run_threshold_sweep has a lazy import of run_bias_detection from
    courtaccess.monitoring.drift. Mocked via patch.dict("sys.modules")
    so no real drift module is required.
  - run_input_characteristics queries PostgreSQL via sqlalchemy. The DB
    path is exercised by: (a) no DATABASE_URL → None, (b) DB unavailable
    (import/connect raises) → None. A real-rows path is exercised by
    injecting a mock sqlalchemy engine via sys.modules patching.
  - run_sensitivity_analysis is tested by patching both sub-analysis
    functions and the mlflow / config imports so no real ML infra needed.
"""

import json
import math
from unittest.mock import MagicMock, patch

import pytest

from courtaccess.core.sensitivity_analysis import (
    COVERAGE_SWEEP,
    EXPERIMENT_NAME,
    UNDERSERVED_SWEEP,
    _load_catalog,
    _pearson,
    _stdev,
    run_input_characteristics,
    run_sensitivity_analysis,
    run_threshold_sweep,
)

# ─────────────────────────────────────────────────────────────────────────────
# _stdev — pure population standard deviation
# ─────────────────────────────────────────────────────────────────────────────


class TestStdev:
    def test_empty_list_returns_zero(self):
        assert _stdev([]) == 0.0

    def test_single_value_returns_zero(self):
        assert _stdev([42.0]) == 0.0

    def test_two_identical_values_returns_zero(self):
        assert _stdev([7.0, 7.0]) == 0.0

    def test_two_values_correct_result(self):
        # mean=3, sum_sq=(2-3)^2+(4-3)^2=2, /n=1, sqrt=1
        assert _stdev([2.0, 4.0]) == pytest.approx(1.0)

    def test_classic_example_returns_two(self):
        # [2,4,4,4,5,5,7,9] → population stdev = 2.0
        assert _stdev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0)

    def test_all_zeros_returns_zero(self):
        assert _stdev([0.0, 0.0, 0.0]) == 0.0

    def test_large_uniform_list_returns_zero(self):
        assert _stdev([3.0] * 100) == 0.0

    def test_return_type_is_float(self):
        assert isinstance(_stdev([1, 2, 3]), float)

    def test_three_values_known_result(self):
        # [1, 2, 3]: mean=2, sum_sq=2, /3, sqrt = sqrt(2/3)
        expected = math.sqrt(2 / 3)
        assert _stdev([1.0, 2.0, 3.0]) == pytest.approx(expected)


# ─────────────────────────────────────────────────────────────────────────────
# _pearson — Pearson correlation coefficient
# ─────────────────────────────────────────────────────────────────────────────


class TestPearson:
    def test_empty_lists_returns_none(self):
        assert _pearson([], []) is None

    def test_single_pair_returns_none(self):
        # n=1 < 2
        assert _pearson([1.0], [2.0]) is None

    def test_mismatched_length_returns_none(self):
        assert _pearson([1.0, 2.0], [3.0]) is None

    def test_constant_x_returns_none(self):
        # den_x = sqrt(0) = 0 → None
        assert _pearson([5.0, 5.0, 5.0], [1.0, 2.0, 3.0]) is None

    def test_constant_y_returns_none(self):
        # den_y = sqrt(0) = 0 → None
        assert _pearson([1.0, 2.0, 3.0], [4.0, 4.0, 4.0]) is None

    def test_perfectly_correlated_returns_one(self):
        # y = 2x: [1,2,3], [2,4,6]
        result = _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
        assert result == pytest.approx(1.0)

    def test_perfectly_anticorrelated_returns_minus_one(self):
        # y = -2x+8: [1,2,3], [6,4,2]
        result = _pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0])
        assert result == pytest.approx(-1.0)

    def test_uncorrelated_near_zero(self):
        # Orthogonal-ish data
        result = _pearson([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 2.0, 4.0])
        # mean_x=2.5 mean_y=3. num=(1-2.5)(2-3)+(2-2.5)(4-3)+(3-2.5)(2-3)+(4-2.5)(4-3)
        # = (1.5)(1) + (-0.5)(1) + (0.5)(-1) + (1.5)(1) = 1.5 - 0.5 - 0.5 + 1.5 = 2.0
        # den_x=sqrt(1.25+0.25+0.25+2.25)=sqrt(5) den_y=sqrt(1+1+1+1)=2
        # r = 2.0/(sqrt(5)*2) = 1/sqrt(5) ≈ 0.447
        assert result == pytest.approx(1 / math.sqrt(5), rel=1e-5)

    def test_result_bounded_between_minus_one_and_one(self):
        import random

        random.seed(42)
        xs = [random.gauss(0, 1) for _ in range(50)]
        ys = [random.gauss(0, 1) for _ in range(50)]
        r = _pearson(xs, ys)
        assert r is not None
        assert -1.0 <= r <= 1.0

    def test_returns_float_not_none_for_valid_inputs(self):
        result = _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
        assert isinstance(result, float)


# ─────────────────────────────────────────────────────────────────────────────
# _load_catalog — filesystem helper
# ─────────────────────────────────────────────────────────────────────────────


class TestLoadCatalog:
    def test_missing_file_returns_empty_list(self, tmp_path):
        result = _load_catalog(tmp_path / "nonexistent.json")
        assert result == []

    def test_empty_array_file_returns_empty_list(self, tmp_path):
        p = tmp_path / "catalog.json"
        p.write_text("[]", encoding="utf-8")
        result = _load_catalog(p)
        assert result == []

    def test_valid_catalog_returns_list_of_dicts(self, tmp_path):
        p = tmp_path / "catalog.json"
        data = [{"form_id": "abc", "status": "active"}, {"form_id": "xyz", "status": "inactive"}]
        p.write_text(json.dumps(data), encoding="utf-8")
        result = _load_catalog(p)
        assert result == data

    def test_returns_list_type(self, tmp_path):
        p = tmp_path / "catalog.json"
        p.write_text('[{"a": 1}]', encoding="utf-8")
        assert isinstance(_load_catalog(p), list)

    def test_single_entry_catalog(self, tmp_path):
        p = tmp_path / "catalog.json"
        entry = {"form_id": "f1", "status": "active", "language": "spa_Latn"}
        p.write_text(json.dumps([entry]), encoding="utf-8")
        result = _load_catalog(p)
        assert len(result) == 1
        assert result[0]["form_id"] == "f1"

    def test_malformed_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            _load_catalog(p)


# ─────────────────────────────────────────────────────────────────────────────
# run_threshold_sweep — grid search over bias thresholds
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_drift(bias_count=0, bias_flags=None):
    """Return a mock sys.modules entry for courtaccess.monitoring.drift."""
    mock_drift = MagicMock()
    mock_drift.run_bias_detection.return_value = {
        "bias_count": bias_count,
        "bias_flags": bias_flags or [],
    }
    return mock_drift


class TestRunThresholdSweep:
    def test_grid_has_correct_number_of_entries(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        expected = len(UNDERSERVED_SWEEP) * len(COVERAGE_SWEEP)
        assert len(result["grid"]) == expected

    def test_grid_entry_has_required_keys(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        entry = result["grid"][0]
        assert "underserved_threshold" in entry
        assert "translation_coverage_threshold" in entry
        assert "bias_flags_count" in entry
        assert "critical_flags_count" in entry

    def test_result_has_threshold_sensitivity_score_key(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        assert "threshold_sensitivity_score" in result

    def test_sensitivity_score_is_float(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        assert isinstance(result["threshold_sensitivity_score"], float)

    def test_uniform_bias_counts_yield_zero_sensitivity(self):
        # All cells return bias_count=3 → std-dev = 0
        mock_drift = _make_mock_drift(bias_count=3)
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        assert result["threshold_sensitivity_score"] == pytest.approx(0.0)

    def test_run_bias_detection_called_for_each_grid_cell(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            run_threshold_sweep([], mlflow=None)
        expected_calls = len(UNDERSERVED_SWEEP) * len(COVERAGE_SWEEP)
        assert mock_drift.run_bias_detection.call_count == expected_calls

    def test_run_bias_detection_receives_underserved_threshold_kwarg(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            run_threshold_sweep([], mlflow=None)
        # Every call should pass underserved_threshold as a kwarg
        for c in mock_drift.run_bias_detection.call_args_list:
            assert "underserved_threshold" in c.kwargs

    def test_run_bias_detection_receives_coverage_threshold_kwarg(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            run_threshold_sweep([], mlflow=None)
        for c in mock_drift.run_bias_detection.call_args_list:
            assert "translation_coverage_min" in c.kwargs

    def test_critical_flags_counted_correctly(self):
        # One CRITICAL flag in every report
        critical_flag = {"severity": "CRITICAL", "label": "test"}
        mock_drift = _make_mock_drift(bias_count=1, bias_flags=[critical_flag])
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        for entry in result["grid"]:
            assert entry["critical_flags_count"] == 1

    def test_severity_case_insensitive(self):
        # "critical" lowercase should also be counted
        critical_flag = {"severity": "critical"}
        mock_drift = _make_mock_drift(bias_count=1, bias_flags=[critical_flag])
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        # .upper() is applied → "CRITICAL" == "CRITICAL"
        for entry in result["grid"]:
            assert entry["critical_flags_count"] == 1

    def test_mlflow_none_does_not_raise(self):
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=None)
        assert "grid" in result

    def test_mlflow_log_params_called_per_cell(self):
        mock_drift = _make_mock_drift()
        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=None)
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            run_threshold_sweep([], mlflow=mock_mlflow)
        expected_cell_calls = len(UNDERSERVED_SWEEP) * len(COVERAGE_SWEEP)
        # log_params called once per cell
        assert mock_mlflow.log_params.call_count == expected_cell_calls

    def test_mlflow_error_does_not_propagate(self):
        # If MLflow raises inside the loop, the sweep must still complete
        mock_drift = _make_mock_drift()
        mock_mlflow = MagicMock()
        mock_mlflow.start_run.side_effect = RuntimeError("mlflow down")
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            result = run_threshold_sweep([], mlflow=mock_mlflow)
        assert len(result["grid"]) == len(UNDERSERVED_SWEEP) * len(COVERAGE_SWEEP)

    def test_catalog_passed_to_run_bias_detection(self):
        catalog = [{"form_id": "f1"}, {"form_id": "f2"}]
        mock_drift = _make_mock_drift()
        with patch.dict("sys.modules", {"courtaccess.monitoring.drift": mock_drift}):
            run_threshold_sweep(catalog, mlflow=None)
        # First positional arg to each call should be the catalog
        for c in mock_drift.run_bias_detection.call_args_list:
            assert c.args[0] is catalog


# ─────────────────────────────────────────────────────────────────────────────
# run_input_characteristics — DB query with graceful fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestRunInputCharacteristics:
    def test_no_database_url_returns_none(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        result = run_input_characteristics(mlflow=None)
        assert result is None

    def test_db_connection_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        # Mock sqlalchemy and db.database so the inner import works but engine raises
        mock_sa = MagicMock()
        mock_db = MagicMock()
        mock_db.get_sync_engine.side_effect = Exception("connection refused")
        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result is None

    def test_empty_rows_returns_zero_row_count(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()
        # Simulate empty query result
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn
        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result is not None
        assert result["row_count"] == 0

    def test_empty_rows_result_has_required_keys(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn
        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert "time_confidence_correlation" in result
        assert "avg_confidence_by_language" in result
        assert "avg_corrections_by_language" in result
        assert "correction_rate_by_language" in result

    def test_empty_rows_correlation_is_none(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn
        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result["time_confidence_correlation"] is None

    def test_with_rows_returns_correct_row_count(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()

        # Two rows: spa_Latn with confidence 0.9, processing_time 10
        #           spa_Latn with confidence 0.8, processing_time 20
        rows = [
            ("spa_Latn", 0.9, 2, 10.0),
            ("spa_Latn", 0.8, 1, 20.0),
        ]
        ocr_rows = []  # no OCR rows → correction_rate empty

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.side_effect = [rows, ocr_rows]
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn

        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result["row_count"] == 2

    def test_with_rows_avg_confidence_computed_per_language(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()

        rows = [
            ("spa_Latn", 0.9, 0, 10.0),
            ("spa_Latn", 0.7, 0, 20.0),
        ]
        ocr_rows = []

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.side_effect = [rows, ocr_rows]
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn

        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result["avg_confidence_by_language"]["spa_Latn"] == pytest.approx(0.8)

    def test_with_rows_correction_rate_computed(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://localhost/test")
        mock_sa = MagicMock()
        mock_db = MagicMock()

        rows = [("spa_Latn", 0.9, 2, 10.0)]
        # OCR row: lang, total_regions=10, corrections=2
        ocr_rows = [("spa_Latn", 10, 2)]

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.side_effect = [rows, ocr_rows]
        mock_db.get_sync_engine.return_value.connect.return_value = mock_conn

        with patch.dict("sys.modules", {"sqlalchemy": mock_sa, "db.database": mock_db}):
            result = run_input_characteristics(mlflow=None)
        assert result["correction_rate_by_language"]["spa_Latn"] == pytest.approx(0.2)

    def test_mlflow_none_does_not_raise(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        # Returns None without crashing
        result = run_input_characteristics(mlflow=None)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# run_sensitivity_analysis — orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class TestRunSensitivityAnalysis:
    def _make_sweep_result(self):
        return {"grid": [], "threshold_sensitivity_score": 0.0}

    def test_returns_dict_with_both_sub_analysis_keys(self, tmp_path):
        catalog = tmp_path / "catalog.json"
        catalog.write_text("[]", encoding="utf-8")
        mock_drift = _make_mock_drift()
        # Patch mlflow and config so no real connections made
        mock_mlflow_mod = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.mlflow_tracking_uri = None
        with (
            patch.dict(
                "sys.modules",
                {
                    "mlflow": mock_mlflow_mod,
                    "courtaccess.core.config": mock_config,
                    "courtaccess.monitoring.drift": mock_drift,
                },
            ),
            patch("os.getenv", return_value=None),
        ):
            result = run_sensitivity_analysis(catalog_path=catalog)
        assert "threshold_sweep" in result
        assert "input_characteristics" in result

    def test_threshold_sweep_key_has_grid(self, tmp_path):
        catalog = tmp_path / "catalog.json"
        catalog.write_text("[]", encoding="utf-8")
        mock_drift = _make_mock_drift()
        mock_mlflow_mod = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.mlflow_tracking_uri = None
        with (
            patch.dict(
                "sys.modules",
                {
                    "mlflow": mock_mlflow_mod,
                    "courtaccess.core.config": mock_config,
                    "courtaccess.monitoring.drift": mock_drift,
                },
            ),
            patch("os.getenv", return_value=None),
        ):
            result = run_sensitivity_analysis(catalog_path=catalog)
        assert "grid" in result["threshold_sweep"]

    def test_mlflow_import_failure_does_not_crash(self, tmp_path):
        # Simulate mlflow not installed: inject None so import raises ImportError
        catalog = tmp_path / "catalog.json"
        catalog.write_text("[]", encoding="utf-8")
        mock_drift = _make_mock_drift()
        with (
            patch.dict(
                "sys.modules",
                {
                    "mlflow": None,  # None entry → ImportError on `import mlflow`
                    "courtaccess.monitoring.drift": mock_drift,
                },
            ),
            patch("os.getenv", return_value=None),
        ):
            result = run_sensitivity_analysis(catalog_path=catalog)
        assert "threshold_sweep" in result

    def test_catalog_path_none_uses_default(self):
        # Calling with catalog_path=None should use DEFAULT_CATALOG_PATH.
        # The default path likely does not exist in CI, so _load_catalog returns [].
        mock_drift = _make_mock_drift()
        mock_mlflow_mod = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.mlflow_tracking_uri = None
        with (
            patch.dict(
                "sys.modules",
                {
                    "mlflow": mock_mlflow_mod,
                    "courtaccess.core.config": mock_config,
                    "courtaccess.monitoring.drift": mock_drift,
                },
            ),
            patch("os.getenv", return_value=None),
        ):
            result = run_sensitivity_analysis(catalog_path=None)
        assert "threshold_sweep" in result

    def test_input_characteristics_is_none_when_no_db(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_URL", raising=False)
        catalog = tmp_path / "catalog.json"
        catalog.write_text("[]", encoding="utf-8")
        mock_drift = _make_mock_drift()
        mock_mlflow_mod = MagicMock()
        mock_config = MagicMock()
        mock_config.settings.mlflow_tracking_uri = None
        with patch.dict(
            "sys.modules",
            {
                "mlflow": mock_mlflow_mod,
                "courtaccess.core.config": mock_config,
                "courtaccess.monitoring.drift": mock_drift,
            },
        ):
            result = run_sensitivity_analysis(catalog_path=catalog)
        assert result["input_characteristics"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Module-level constants sanity checks
# ─────────────────────────────────────────────────────────────────────────────


class TestModuleConstants:
    def test_underserved_sweep_has_nine_values(self):
        assert len(UNDERSERVED_SWEEP) == 9

    def test_underserved_sweep_range_is_0_1_to_0_9(self):
        assert UNDERSERVED_SWEEP[0] == pytest.approx(0.1)
        assert UNDERSERVED_SWEEP[-1] == pytest.approx(0.9)

    def test_coverage_sweep_has_seven_values(self):
        # range(10, 45, 5) → 10, 15, 20, 25, 30, 35, 40
        assert len(COVERAGE_SWEEP) == 7

    def test_coverage_sweep_starts_at_10(self):
        assert COVERAGE_SWEEP[0] == 10

    def test_coverage_sweep_ends_at_40(self):
        assert COVERAGE_SWEEP[-1] == 40

    def test_experiment_name_is_string(self):
        assert isinstance(EXPERIMENT_NAME, str)
        assert len(EXPERIMENT_NAME) > 0
