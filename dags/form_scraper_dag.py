"""
dags/form_scraper_dag.py

Airflow DAG — form_scraper_dag
Scheduled: every Monday at 06:00 UTC

Pipeline flow:
  scrape_and_classify → preprocess_data → validate_catalog → detect_anomalies
      → detect_bias → trigger_pretranslation → log_summary → dvc_version_data

MIGRATED from data_pipeline/dags/form_scraper_dag.py.
All src.* imports updated to courtaccess.* package imports.
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from courtaccess.core.validation import run_preprocessing
from courtaccess.forms.scraper import run_scrape
from courtaccess.monitoring.drift import run_bias_detection

logger = logging.getLogger(__name__)

# ── Paths (inside Docker container) ──────────────────────────────────────────
CATALOG_PATH = "/opt/airflow/courtaccess/data/form_catalog.json"
FORMS_DIR = "/opt/airflow/forms"
METRICS_PATH = "/opt/airflow/courtaccess/data/catalog_metrics.json"
ANOMALY_REPORT_PATH = "/opt/airflow/courtaccess/data/anomaly_report.json"
PREPROCESS_REPORT_PATH = "/opt/airflow/courtaccess/data/preprocess_report.json"
BIAS_REPORT_PATH = "/opt/airflow/courtaccess/data/bias_report.json"
PROJECT_ROOT = "/opt/airflow"

# ── Anomaly thresholds ───────────────────────────────────────────────────────
THRESHOLD_FORM_DROP_PCT = 20  # Alert if active forms drop >20%
THRESHOLD_MASS_NEW_FORMS = 50  # Alert if >50 new forms in one run
THRESHOLD_DOWNLOAD_FAIL_PCT = 10  # Alert if >10% of forms fail to download
THRESHOLD_MIN_PDF_SIZE_BYTES = 1024  # Alert if PDF is <1KB (likely error page)
THRESHOLD_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # Alert if PDF is >50MB
THRESHOLD_SCHEMA_ERRORS = 0  # Alert if any schema validation errors

# ── Catalog schema ────────────────────────────────────────────────────────────
REQUIRED_TOP_FIELDS = {
    "form_id",
    "form_name",
    "form_slug",
    "source_url",
    "status",
    "content_hash",
    "current_version",
    "needs_human_review",
    "created_at",
    "last_scraped_at",
    "appearances",
    "versions",
}
REQUIRED_VERSION_FIELDS = {
    "version",
    "content_hash",
    "file_path_original",
    "file_path_es",
    "file_path_pt",
    "created_at",
}
REQUIRED_APPEARANCE_FIELDS = {"division", "section_heading"}

# ── DAG default args ──────────────────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "courtaccess",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": 60,
    "email_on_failure": False,
    "email_on_retry": False,
}

# ══════════════════════════════════════════════════════════════════════════════
# Task functions
# ══════════════════════════════════════════════════════════════════════════════


def task_scrape_and_classify(**context) -> dict:
    """Task 1 — Run the scraper, classify every form, update the catalog."""
    logger.info("Starting weekly mass.gov form scrape.")
    result = run_scrape()
    logger.info("Scrape finished. Summary: %s", result["counts"])
    context["ti"].xcom_push(key="scrape_result", value=result)
    return result


def task_preprocess_data(**context) -> dict:
    """
    Task 2 — Clean, normalize, and validate the scraped data.
    Preprocessing steps:
      1. File type detection   4. Form name cleanup
      2. PDF integrity         5. Slug normalization
      3. Empty file removal    6. Duplicate detection
    """
    logger.info("Starting data preprocessing.")
    catalog_path = Path(CATALOG_PATH)
    if not catalog_path.exists():
        logger.error("Catalog file not found — cannot preprocess.")
        return {"error": "catalog_missing"}

    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    report = run_preprocessing(catalog, FORMS_DIR)

    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    logger.info("Catalog saved with preprocessing updates.")

    report_path = Path(PREPROCESS_REPORT_PATH)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Preprocessing report saved to %s", PREPROCESS_REPORT_PATH)

    context["ti"].xcom_push(key="preprocess_report", value=report)
    return report


def task_validate_catalog(**context) -> dict:
    """Task 3 — Validate the catalog JSON after preprocessing."""
    from collections import Counter

    logger.info("Starting catalog validation.")
    errors = []
    warnings = []

    catalog_path = Path(CATALOG_PATH)
    if not catalog_path.exists():
        logger.error("Catalog file not found: %s", CATALOG_PATH)
        return {"valid": False, "errors": 1}

    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    status_counts = Counter()
    division_counts = Counter()
    forms_with_es = forms_with_pt = missing_pdfs = total_versions = 0
    seen_ids: set = set()
    seen_urls: set = set()

    for i, entry in enumerate(catalog):
        prefix = f"Entry [{i}]"
        missing = REQUIRED_TOP_FIELDS - set(entry.keys())
        if missing:
            errors.append(f"{prefix}: missing fields {missing}")
            continue

        fid = entry["form_id"]
        if fid in seen_ids:
            errors.append(f"{prefix}: duplicate form_id '{fid}'")
        seen_ids.add(fid)

        url = entry["source_url"]
        if url in seen_urls:
            errors.append(f"{prefix}: duplicate source_url '{url}'")
        seen_urls.add(url)

        if entry["status"] not in ("active", "archived"):
            errors.append(f"{prefix}: invalid status '{entry['status']}'")
        status_counts[entry["status"]] += 1

        if not isinstance(entry["current_version"], int) or entry["current_version"] < 1:
            errors.append(f"{prefix}: invalid current_version {entry['current_version']}")

        for j, app in enumerate(entry.get("appearances", [])):
            app_missing = REQUIRED_APPEARANCE_FIELDS - set(app.keys())
            if app_missing:
                errors.append(f"{prefix} appearance[{j}]: missing {app_missing}")
            else:
                division_counts[app["division"]] += 1

        versions = entry.get("versions", [])
        if len(versions) == 0:
            errors.append(f"{prefix}: no versions")
        total_versions += len(versions)

        for j, ver in enumerate(versions):
            ver_missing = REQUIRED_VERSION_FIELDS - set(ver.keys())
            if ver_missing:
                errors.append(f"{prefix} version[{j}]: missing {ver_missing}")
                continue
            if j == 0 and entry["status"] == "active":
                fp = ver["file_path_original"]
                if fp and not Path(fp).exists():
                    missing_pdfs += 1
                    warnings.append(f"{prefix}: PDF not found at '{fp}'")
            if j == 0:
                if ver.get("file_path_es"):
                    forms_with_es += 1
                if ver.get("file_path_pt"):
                    forms_with_pt += 1

    active = status_counts.get("active", 0)
    archived = status_counts.get("archived", 0)
    metrics = {
        "valid": len(errors) == 0,
        "total_forms": len(catalog),
        "active_forms": active,
        "archived_forms": archived,
        "total_versions": total_versions,
        "forms_with_es": forms_with_es,
        "forms_with_pt": forms_with_pt,
        "unique_divisions": len(division_counts),
        "division_breakdown": dict(division_counts),
        "missing_pdfs": missing_pdfs,
        "errors": len(errors),
        "warnings": len(warnings),
    }

    metrics_path = Path(METRICS_PATH)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    logger.info(
        "Validation complete: %d forms, %d active, %d archived, "
        "%d errors, %d warnings, %d missing PDFs, %d with ES, %d with PT",
        len(catalog),
        active,
        archived,
        len(errors),
        len(warnings),
        missing_pdfs,
        forms_with_es,
        forms_with_pt,
    )
    if errors:
        for e in errors[:10]:
            logger.error("  %s", e)
        if len(errors) > 10:
            logger.error("  ... and %d more errors", len(errors) - 10)

    context["ti"].xcom_push(key="validation_metrics", value=metrics)
    return metrics


def task_detect_anomalies(**context) -> dict:
    """
    Task 4 — Detect data anomalies by comparing current run metrics against
    thresholds and previous run metrics.
    """
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scrape_and_classify", key="scrape_result")
    metrics = ti.xcom_pull(task_ids="validate_catalog", key="validation_metrics")

    if not result or not metrics:
        logger.warning("Missing scrape result or validation metrics — skipping anomaly detection.")
        return {"anomalies": [], "severity": "skipped"}

    anomalies = []
    counts = result["counts"]

    prev_metrics = None
    prev_metrics_path = Path(ANOMALY_REPORT_PATH).parent / "prev_catalog_metrics.json"
    metrics_path = Path(METRICS_PATH)
    if prev_metrics_path.exists():
        try:
            with open(prev_metrics_path, encoding="utf-8") as f:
                prev_metrics = json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not load previous metrics — first run or corrupted file.")

    if prev_metrics and prev_metrics.get("active_forms", 0) > 0:
        prev_active = prev_metrics["active_forms"]
        curr_active = metrics.get("active_forms", 0)
        drop_pct = ((prev_active - curr_active) / prev_active) * 100
        if drop_pct > THRESHOLD_FORM_DROP_PCT:
            anomalies.append(
                {
                    "check": "form_count_drop",
                    "severity": "CRITICAL",
                    "message": f"Active forms dropped by {drop_pct:.1f}% ({prev_active} → {curr_active}). Threshold: {THRESHOLD_FORM_DROP_PCT}%",
                    "prev": prev_active,
                    "current": curr_active,
                }
            )

    new_count = counts.get("new", 0)
    if new_count > THRESHOLD_MASS_NEW_FORMS:
        anomalies.append(
            {
                "check": "mass_new_forms",
                "severity": "WARNING",
                "message": f"{new_count} new forms detected in a single run. Threshold: {THRESHOLD_MASS_NEW_FORMS}.",
                "count": new_count,
            }
        )

    total_checked = sum(counts.values())
    total_expected = metrics.get("total_forms", 0)
    if total_expected > 0 and total_checked > 0 and prev_metrics:
        prev_total = prev_metrics.get("total_forms", 0)
        if prev_total > 0:
            fail_pct = 100 - (total_checked / prev_total) * 100
            if fail_pct > THRESHOLD_DOWNLOAD_FAIL_PCT:
                anomalies.append(
                    {
                        "check": "download_failure_rate",
                        "severity": "WARNING",
                        "message": f"Only {total_checked}/{prev_total} forms found ({fail_pct:.1f}% failure rate). Threshold: {THRESHOLD_DOWNLOAD_FAIL_PCT}%",
                        "found": total_checked,
                        "expected": prev_total,
                    }
                )

    forms_dir = Path(FORMS_DIR)
    tiny_pdfs = []
    huge_pdfs = []
    if forms_dir.exists():
        for pdf_file in forms_dir.rglob("*.pdf"):
            size = pdf_file.stat().st_size
            if size < THRESHOLD_MIN_PDF_SIZE_BYTES:
                tiny_pdfs.append({"file": str(pdf_file), "size_bytes": size})
            elif size > THRESHOLD_MAX_PDF_SIZE_BYTES:
                huge_pdfs.append({"file": str(pdf_file), "size_bytes": size})
    if tiny_pdfs:
        anomalies.append(
            {
                "check": "tiny_pdfs",
                "severity": "WARNING",
                "message": f"{len(tiny_pdfs)} PDF(s) under {THRESHOLD_MIN_PDF_SIZE_BYTES} bytes.",
                "count": len(tiny_pdfs),
                "files": tiny_pdfs[:10],
            }
        )
    if huge_pdfs:
        anomalies.append(
            {
                "check": "huge_pdfs",
                "severity": "WARNING",
                "message": f"{len(huge_pdfs)} PDF(s) exceed {THRESHOLD_MAX_PDF_SIZE_BYTES // (1024 * 1024)}MB.",
                "count": len(huge_pdfs),
                "files": huge_pdfs[:10],
            }
        )

    schema_errors = metrics.get("errors", 0)
    if schema_errors > THRESHOLD_SCHEMA_ERRORS:
        anomalies.append(
            {
                "check": "schema_violations",
                "severity": "CRITICAL",
                "message": f"{schema_errors} schema validation error(s) found in catalog.",
                "count": schema_errors,
            }
        )

    missing_pdfs = metrics.get("missing_pdfs", 0)
    if missing_pdfs > 0:
        anomalies.append(
            {
                "check": "missing_pdfs",
                "severity": "WARNING",
                "message": f"{missing_pdfs} PDF(s) in catalog but not on disk.",
                "count": missing_pdfs,
            }
        )

    has_critical = any(a["severity"] == "CRITICAL" for a in anomalies)
    has_warning = any(a["severity"] == "WARNING" for a in anomalies)
    overall_severity = "CRITICAL" if has_critical else ("WARNING" if has_warning else "OK")

    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "severity": overall_severity,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "thresholds": {
            "form_drop_pct": THRESHOLD_FORM_DROP_PCT,
            "mass_new_forms": THRESHOLD_MASS_NEW_FORMS,
            "download_fail_pct": THRESHOLD_DOWNLOAD_FAIL_PCT,
            "min_pdf_size_bytes": THRESHOLD_MIN_PDF_SIZE_BYTES,
            "max_pdf_size_bytes": THRESHOLD_MAX_PDF_SIZE_BYTES,
            "schema_errors": THRESHOLD_SCHEMA_ERRORS,
        },
    }

    report_path = Path(ANOMALY_REPORT_PATH)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    if metrics_path.exists():
        import shutil

        shutil.copy2(str(metrics_path), str(prev_metrics_path))

    if not anomalies:
        logger.info("No anomalies detected. All checks passed.")
    else:
        for a in anomalies:
            if a["severity"] == "CRITICAL":
                logger.critical("ANOMALY [%s]: %s", a["check"], a["message"])
            else:
                logger.warning("ANOMALY [%s]: %s", a["check"], a["message"])
        logger.info("Anomaly detection complete: %d anomaly(ies), severity: %s", len(anomalies), overall_severity)

    context["ti"].xcom_push(key="anomaly_report", value=report)
    return report


def task_detect_bias(**context) -> dict:
    """Task 5 — Detect data coverage bias using data slicing."""
    logger.info("Starting bias detection / data slicing.")
    catalog_path = Path(CATALOG_PATH)
    if not catalog_path.exists():
        logger.error("Catalog file not found — cannot detect bias.")
        return {"error": "catalog_missing"}

    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    report = run_bias_detection(catalog)

    report_path = Path(BIAS_REPORT_PATH)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Bias report saved to %s", BIAS_REPORT_PATH)

    context["ti"].xcom_push(key="bias_report", value=report)
    return report


def task_trigger_pretranslation(**context) -> None:
    """
    Task 6 — Trigger form_pretranslation_dag for each form needing translation.
    """
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scrape_and_classify", key="scrape_result")
    if result is None:
        logger.warning("No scrape result found in XCom — nothing to trigger.")
        return

    queue: list[str] = result.get("pretranslation_queue", [])
    if not queue:
        logger.info("No forms need pre-translation this cycle.")
        return

    logger.info("Triggering form_pretranslation_dag for %d form(s): %s", len(queue), queue)

    from airflow.operators.trigger_dagrun import TriggerDagRunOperator

    for form_id in queue:
        TriggerDagRunOperator(
            task_id=f"trigger_pretranslation_{form_id}",
            trigger_dag_id="form_pretranslation_dag",
            conf={"form_id": form_id},
            dag=dag,
        ).execute(context)


def task_log_summary(**context) -> None:
    """Task 7 — Write final audit-style summary to Airflow log."""
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scrape_and_classify", key="scrape_result")
    preproc = ti.xcom_pull(task_ids="preprocess_data", key="preprocess_report")
    metrics = ti.xcom_pull(task_ids="validate_catalog", key="validation_metrics")
    anomaly = ti.xcom_pull(task_ids="detect_anomalies", key="anomaly_report")
    bias = ti.xcom_pull(task_ids="detect_bias", key="bias_report")

    if result is None:
        logger.warning("No scrape result available for summary.")
        return

    c = result["counts"]
    total = sum(c.values())
    logger.info(
        "══ Weekly Form Scrape Summary ══\n"
        "  Total forms checked : %d\n"
        "  New                 : %d\n"
        "  Updated             : %d\n"
        "  Archived (404)      : %d\n"
        "  Renamed             : %d\n"
        "  No change           : %d\n"
        "  Pre-translation jobs: %d",
        total,
        c["new"],
        c["updated"],
        c["deleted"],
        c["renamed"],
        c["no_change"],
        len(result.get("pretranslation_queue", [])),
    )
    if preproc:
        logger.info(
            "══ Preprocessing Report ══\n"
            "  Forms processed   : %d\n"
            "  Names normalized  : %d\n"
            "  Slugs normalized  : %d\n"
            "  Mislabeled files  : %d\n"
            "  Empty files       : %d\n"
            "  Corrupt files     : %d\n"
            "  Duplicate hashes  : %d",
            preproc.get("total_processed", 0),
            preproc.get("names_normalized", 0),
            preproc.get("slugs_normalized", 0),
            preproc.get("mislabeled_files", 0),
            preproc.get("empty_files", 0),
            preproc.get("corrupt_files", 0),
            preproc.get("duplicate_hashes", 0),
        )
    if metrics:
        logger.info(
            "══ Validation Metrics ══\n"
            "  Active forms   : %d\n  Archived forms : %d\n"
            "  Forms with ES  : %d\n  Forms with PT  : %d\n"
            "  Missing PDFs   : %d\n  Errors         : %d\n  Valid          : %s",
            metrics.get("active_forms", 0),
            metrics.get("archived_forms", 0),
            metrics.get("forms_with_es", 0),
            metrics.get("forms_with_pt", 0),
            metrics.get("missing_pdfs", 0),
            metrics.get("errors", 0),
            metrics.get("valid", False),
        )
    if anomaly:
        logger.info(
            "══ Anomaly Report ══\n  Severity       : %s\n  Anomalies found: %d",
            anomaly.get("severity", "unknown"),
            anomaly.get("anomaly_count", 0),
        )
        for a in anomaly.get("anomalies", []):
            logger.info("    [%s] %s: %s", a["severity"], a["check"], a["message"])
    if bias:
        logger.info(
            "══ Bias Detection Report ══\n"
            "  Active forms analyzed: %d\n  Divisions analyzed   : %d\n  Bias flags           : %d",
            bias.get("total_active_forms", 0),
            len(bias.get("slices", {}).get("by_division", {}).get("data", {})),
            bias.get("bias_count", 0),
        )


def task_dvc_version_data(**context) -> None:
    """Task 8 — Version the scraper outputs using DVC.

    Tracks two outputs with 'dvc add' and pushes to the configured remote:
      - courtaccess/data/form_catalog.json  (catalog)
      - forms/                              (downloaded PDFs, all versions)

    Raises RuntimeError if any DVC command fails so the Airflow task shows
    as FAILED instead of silently succeeding.
    """
    import os

    logger.info("Starting DVC data versioning.")
    dvc_env = os.environ.copy()
    dvc_env["GIT_DISCOVERY_ACROSS_FILESYSTEM"] = "1"

    def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
        """Run a shell command, log its output, optionally raise on failure."""
        logger.info("Running: %s", " ".join(cmd))
        try:
            result = subprocess.run(  # noqa: S603
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                env=dvc_env,
                timeout=300,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Command not found: {cmd[0]}. Is it installed in the Docker image?") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command timed out after 300s: {' '.join(cmd)}") from None

        if result.stdout.strip():
            logger.info("  stdout: %s", result.stdout.strip())
        if result.stderr.strip():
            logger.info("  stderr: %s", result.stderr.strip())

        if check and result.returncode != 0:
            raise RuntimeError(
                f"Command failed (rc={result.returncode}): {' '.join(cmd)}\n  stderr: {result.stderr.strip()}"
            )
        return result

    # 1. Ensure git safe.directory is set (defense-in-depth — also set in airflow-init)
    _run(["git", "config", "--global", "--add", "safe.directory", PROJECT_ROOT])

    # 2. Verify DVC remote is configured before attempting any tracking
    remote_check = _run(["dvc", "remote", "list"])
    if not remote_check.stdout.strip():
        raise RuntimeError(
            "No DVC remote configured! The airflow-init service should have set this up. "
            "Run: dvc remote add -d local_storage /opt/airflow/dvc_storage"
        )
    logger.info("DVC remote verified: %s", remote_check.stdout.strip())

    # 3. Track data with DVC
    _run(["dvc", "add", "courtaccess/data/form_catalog.json"], check=True)
    _run(["dvc", "add", "forms"], check=True)
    logger.info("DVC add completed for catalog and forms.")

    # 4. Push to remote storage
    _run(["dvc", "push"], check=True)
    logger.info("DVC push completed — data versioned and stored in remote.")


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition
# ══════════════════════════════════════════════════════════════════════════════

with DAG(
    dag_id="form_scraper_dag",
    description="Weekly scrape of mass.gov court forms — preprocess, validate, detect anomalies, version & update catalog",
    schedule="0 6 * * 1",
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    tags=["courtaccess", "forms", "scraping", "preprocessing", "dvc", "anomaly-detection", "bias-detection"],
) as dag:
    t1_scrape = PythonOperator(task_id="scrape_and_classify", python_callable=task_scrape_and_classify)
    t2_preprocess = PythonOperator(task_id="preprocess_data", python_callable=task_preprocess_data)
    t3_validate = PythonOperator(task_id="validate_catalog", python_callable=task_validate_catalog)
    t4_anomaly = PythonOperator(task_id="detect_anomalies", python_callable=task_detect_anomalies)
    t5_bias = PythonOperator(task_id="detect_bias", python_callable=task_detect_bias)
    t6_trigger = PythonOperator(task_id="trigger_pretranslation", python_callable=task_trigger_pretranslation)
    t7_summary = PythonOperator(task_id="log_summary", python_callable=task_log_summary)
    t8_dvc = PythonOperator(task_id="dvc_version_data", python_callable=task_dvc_version_data)

    t1_scrape >> t2_preprocess >> t3_validate >> t4_anomaly >> t5_bias >> t6_trigger >> t7_summary >> t8_dvc
