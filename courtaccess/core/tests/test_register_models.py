"""
Unit tests for courtaccess/core/register_models.py

Functions under test:
  _parse_dvc_file  — pure: parse md5/size/path from a .dvc pointer file
  register_models  — orchestration: iterate DVC_MODELS, log to MLflow

Design notes:
  - _parse_dvc_file reads from a real tmp_path file; no mocking required.
  - register_models lazy-imports mlflow. Inject None into sys.modules to
    simulate mlflow unavailable, or inject a MagicMock for the happy path.
  - All DVC files are looked up under `project_root/models/`. Tests create
    that directory structure in tmp_path so no real model weights are needed.
  - The llama-4-maverick entry is always appended at the end and has no
    DVC file — its presence in the result list is always asserted.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from courtaccess.core.register_models import DVC_MODELS, _parse_dvc_file, register_models

# ── Helpers ───────────────────────────────────────────────────────────────────

_SAMPLE_DVC = """\
outs:
- md5: abc123def456abcd
  size: 612000000
  path: whisper-large-v3
"""

_PARTIAL_DVC_MD5_ONLY = "outs:\n- md5: deadbeef1234\n"
_PARTIAL_DVC_SIZE_ONLY = "outs:\n- size: 999\n"
_EMPTY_DVC = ""


def _make_mock_mlflow():
    """MagicMock mlflow with context-manager-compatible start_run."""
    m = MagicMock()
    m.start_run.return_value.__enter__ = MagicMock(return_value=None)
    m.start_run.return_value.__exit__ = MagicMock(return_value=False)
    return m


def _setup_models_dir(tmp_path: Path) -> Path:
    """Create tmp_path/models/ and return it."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    return models_dir


# ─────────────────────────────────────────────────────────────────────────────
# _parse_dvc_file — pure parsing function
# ─────────────────────────────────────────────────────────────────────────────


class TestParseDvcFile:

    def test_missing_file_returns_none(self, tmp_path):
        assert _parse_dvc_file(tmp_path / "nonexistent.dvc") is None

    def test_returns_dict_for_valid_content(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_SAMPLE_DVC)
        result = _parse_dvc_file(p)
        assert isinstance(result, dict)

    def test_md5_extracted_correctly(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_SAMPLE_DVC)
        result = _parse_dvc_file(p)
        assert result["md5"] == "abc123def456abcd"

    def test_size_bytes_extracted_as_int(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_SAMPLE_DVC)
        result = _parse_dvc_file(p)
        assert result["size_bytes"] == 612000000

    def test_path_extracted_correctly(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_SAMPLE_DVC)
        result = _parse_dvc_file(p)
        assert result["path"] == "whisper-large-v3"

    def test_missing_md5_defaults_to_unknown(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_PARTIAL_DVC_SIZE_ONLY)
        result = _parse_dvc_file(p)
        assert result["md5"] == "unknown"

    def test_missing_size_defaults_to_zero(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_PARTIAL_DVC_MD5_ONLY)
        result = _parse_dvc_file(p)
        assert result["size_bytes"] == 0

    def test_missing_path_defaults_to_stem(self, tmp_path):
        p = tmp_path / "whisper-large-v3.dvc"
        p.write_text(_PARTIAL_DVC_MD5_ONLY)
        result = _parse_dvc_file(p)
        assert result["path"] == "whisper-large-v3"

    def test_empty_file_returns_all_defaults(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_EMPTY_DVC)
        result = _parse_dvc_file(p)
        assert result["md5"] == "unknown"
        assert result["size_bytes"] == 0

    def test_result_has_three_keys(self, tmp_path):
        p = tmp_path / "model.dvc"
        p.write_text(_SAMPLE_DVC)
        result = _parse_dvc_file(p)
        assert set(result.keys()) == {"md5", "size_bytes", "path"}


# ─────────────────────────────────────────────────────────────────────────────
# register_models — orchestration
# ─────────────────────────────────────────────────────────────────────────────


class TestRegisterModels:

    def test_returns_list(self, tmp_path):
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        assert isinstance(result, list)

    def test_result_length_is_dvc_models_plus_llama(self, tmp_path):
        # 6 DVC models + 1 llama = 7 total
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        assert len(result) == len(DVC_MODELS) + 1

    def test_llama_entry_always_present_as_last_item(self, tmp_path):
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        assert result[-1]["model_name"] == "llama-4-maverick"

    def test_missing_dvc_files_have_registered_false(self, tmp_path):
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        dvc_entries = result[:-1]  # exclude llama
        for entry in dvc_entries:
            assert entry["registered"] is False

    def test_missing_dvc_files_have_reason_dvc_file_missing(self, tmp_path):
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        dvc_entries = result[:-1]
        for entry in dvc_entries:
            assert entry["reason"] == "dvc_file_missing"

    def test_llama_has_reason_mlflow_unavailable_when_no_mlflow(self, tmp_path):
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        assert result[-1]["reason"] == "mlflow_unavailable"

    def test_valid_dvc_file_entry_has_correct_md5(self, tmp_path):
        models_dir = _setup_models_dir(tmp_path)
        dvc_filename, display_name, _ = DVC_MODELS[0]
        (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        entry = next(r for r in result if r.get("model_name") == display_name)
        assert entry["md5"] == "abc123def456abcd"

    def test_size_mb_computed_correctly(self, tmp_path):
        models_dir = _setup_models_dir(tmp_path)
        dvc_filename, display_name, _ = DVC_MODELS[0]
        (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        entry = next(r for r in result if r.get("model_name") == display_name)
        # 612000000 / 1_048_576 ≈ 583.7 MB
        assert entry["size_mb"] == pytest.approx(612000000 / 1_048_576, rel=0.01)

    def test_with_mock_mlflow_registered_true_for_found_file(self, tmp_path):
        models_dir = _setup_models_dir(tmp_path)
        dvc_filename, display_name, _ = DVC_MODELS[0]
        (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        mock_mlflow = _make_mock_mlflow()
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            result = register_models(project_root=str(tmp_path))
        entry = next(r for r in result if r.get("model_name") == display_name)
        assert entry["registered"] is True

    def test_with_mock_mlflow_start_run_called_per_found_model(self, tmp_path):
        models_dir = _setup_models_dir(tmp_path)
        # Create all DVC files
        for dvc_filename, _, _ in DVC_MODELS:
            (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        mock_mlflow = _make_mock_mlflow()
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            register_models(project_root=str(tmp_path))
        # One call per DVC model + 1 for llama
        assert mock_mlflow.start_run.call_count == len(DVC_MODELS) + 1

    def test_mlflow_raise_inside_run_sets_registered_false(self, tmp_path):
        models_dir = _setup_models_dir(tmp_path)
        dvc_filename, display_name, _ = DVC_MODELS[0]
        (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        mock_mlflow = _make_mock_mlflow()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(side_effect=RuntimeError("mlflow down"))
        with patch.dict("sys.modules", {"mlflow": mock_mlflow}):
            result = register_models(project_root=str(tmp_path))
        entry = next(r for r in result if r.get("model_name") == display_name)
        assert entry["registered"] is False

    def test_gcs_remote_reads_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GCS_BUCKET_MODELS", "my-model-bucket")
        models_dir = _setup_models_dir(tmp_path)
        dvc_filename, display_name, _ = DVC_MODELS[0]
        (models_dir / dvc_filename).write_text(_SAMPLE_DVC)
        with patch.dict("sys.modules", {"mlflow": None}):
            result = register_models(project_root=str(tmp_path))
        entry = next(r for r in result if r.get("model_name") == display_name)
        assert entry["gcs_remote"] == "my-model-bucket"
