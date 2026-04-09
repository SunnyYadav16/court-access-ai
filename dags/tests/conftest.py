"""
dags/tests/conftest.py

Shared fixtures for DAG unit tests.

Design:
  - Sets all env vars that DAG modules evaluate at import time BEFORE any
    DAG module is imported.  Failure to set these causes crashes:
      - document_pipeline_dag.py / docx_pipeline_dag.py:
          int(os.getenv("SIGNED_URL_EXPIRY_SECONDS"))
          os.getenv("DATABASE_URL").replace("+asyncpg", "")
      - form_scraper_dag.py:
          float(os.getenv("ANOMALY_FORM_DROP_PCT"))
          int(os.getenv("ANOMALY_MASS_NEW_FORMS"))
          float(os.getenv("ANOMALY_DOWNLOAD_FAIL_PCT"))
          int(os.getenv("ANOMALY_MIN_PDF_SIZE_BYTES"))
          int(os.getenv("ANOMALY_MAX_PDF_SIZE_BYTES"))
          int(os.getenv("ANOMALY_SCHEMA_ERRORS"))
  - Provides _make_context() helper — builds a minimal Airflow task context
    with dag_run.conf dict and a MagicMock ti (XCom push/pull auto-handled).
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# MUST run before any dags.* import that evaluates os.getenv() at module level
# ---------------------------------------------------------------------------
os.environ.setdefault("SIGNED_URL_EXPIRY_SECONDS", "3600")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/testdb")
os.environ.setdefault("GCS_BUCKET_UPLOADS", "test-uploads")
os.environ.setdefault("GCS_BUCKET_TRANSLATED", "test-translated")
os.environ.setdefault("GCS_BUCKET_FORMS", "test-forms")
os.environ.setdefault("GCP_SERVICE_ACCOUNT_JSON", "")

# form_scraper_dag.py anomaly thresholds
# Force MLflow to use local file store — prevents retry loops to mlflow:5000
# in test environments (MLFLOW_TRACKING_URI may be set to a Docker hostname).
os.environ["MLFLOW_TRACKING_URI"] = "file:///tmp/courtaccess-test-mlruns"

os.environ.setdefault("ANOMALY_FORM_DROP_PCT", "20.0")
os.environ.setdefault("ANOMALY_MASS_NEW_FORMS", "50")
os.environ.setdefault("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0")
os.environ.setdefault("ANOMALY_MIN_PDF_SIZE_BYTES", "1000")
os.environ.setdefault("ANOMALY_MAX_PDF_SIZE_BYTES", "52428800")
os.environ.setdefault("ANOMALY_SCHEMA_ERRORS", "5")

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Context factory
# ---------------------------------------------------------------------------


def _make_context(conf: dict | None = None, run_id: str = "manual__test-run") -> dict:
    """
    Build a minimal Airflow task context dict.

    dag_run.conf  — the trigger conf dict (caller-supplied or empty)
    ti            — MagicMock; xcom_push/pull return None by default
    dag_run.run_id — stable string for work_dir paths in tests
    """
    dag_run = MagicMock()
    dag_run.conf = conf or {}
    dag_run.run_id = run_id
    ti = MagicMock()
    ti.xcom_pull = MagicMock(return_value=None)
    ti.xcom_push = MagicMock()
    return {"dag_run": dag_run, "ti": ti}
