"""
courtaccess/monitoring/anomaly.py

Anomaly detection for the form catalog and data pipeline metrics.
Ported from task_detect_anomalies in data_pipeline/dags/form_scraper_dag.py.

Checks:
  1. Form count drop    — active forms dropped > THRESHOLD_FORM_DROP_PCT %
  2. Mass new forms     — > THRESHOLD_MASS_NEW_FORMS new forms in one run
  3. Download failures  — > THRESHOLD_DOWNLOAD_FAIL_PCT % of forms failed
  4. Empty catalog      — catalog has zero active entries
  5. Schema violations  — any structural errors in catalog entries
  6. Missing PDFs       — files in catalog but not on disk

OUTPUT CONTRACT:
  {
      "anomalies":     [{"check": str, "severity": "warning"|"critical", "detail": str}],
      "anomaly_count": int,
      "has_critical":  bool,
  }
"""

import os

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

# Required fields in every catalog entry
REQUIRED_FIELDS = {
    "form_id",
    "form_name",
    "source_url",
    "content_hash",
    "status",
    "version",
    "last_checked",
}


def run_anomaly_detection(
    catalog: list[dict],
    run_metrics: dict,
    previous_run_metrics: dict | None = None,
) -> dict:
    """
    Run all anomaly checks on the current catalog and run metrics.

    Args:
        catalog:               Full form catalog (list of dicts).
        run_metrics:           Metrics from the current DAG run:
                               {"new_forms": int, "updated": int, "failed_downloads": int,
                                "total_attempted": int, "active_count": int}
        previous_run_metrics:  Metrics from the last successful run (optional).
                               Used for form-count-drop check.

    Returns:
        Dict matching OUTPUT CONTRACT above.
    """
    threshold_form_drop = float(os.getenv("ANOMALY_FORM_DROP_PCT", "20.0"))
    threshold_mass_new = int(os.getenv("ANOMALY_MASS_NEW_FORMS", "50"))
    threshold_download_fail = float(os.getenv("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0"))

    anomalies = []

    # Check 1: Form count drop vs last run
    if previous_run_metrics:
        prev_active = previous_run_metrics.get("active_count", 0)
        curr_active = run_metrics.get("active_count", 0)
        if prev_active > 0:
            drop_pct = (prev_active - curr_active) / prev_active * 100
            if drop_pct > threshold_form_drop:
                anomalies.append(
                    {
                        "check": "form_count_drop",
                        "severity": "critical",
                        "detail": (
                            f"Active form count dropped {drop_pct:.1f}% "
                            f"({prev_active} → {curr_active}). "
                            f"Threshold: {threshold_form_drop}%."
                        ),
                    }
                )

    # Check 2: Mass new forms (potential scraper error)
    new_forms = run_metrics.get("new_forms", 0)
    if new_forms > threshold_mass_new:
        anomalies.append(
            {
                "check": "mass_new_forms",
                "severity": "warning",
                "detail": (
                    f"{new_forms} new forms detected in one run. "
                    f"Threshold: {threshold_mass_new}. "
                    "Possible scraper regression or mass.gov restructure."
                ),
            }
        )

    # Check 3: High download failure rate
    total_attempted = run_metrics.get("total_attempted", 0)
    failed = run_metrics.get("failed_downloads", 0)
    if total_attempted > 0:
        fail_pct = failed / total_attempted * 100
        if fail_pct > threshold_download_fail:
            anomalies.append(
                {
                    "check": "high_download_failures",
                    "severity": "critical",
                    "detail": (
                        f"{failed}/{total_attempted} downloads failed ({fail_pct:.1f}%). "
                        f"Threshold: {threshold_download_fail}%. "
                        "Possible mass.gov outage or network issue."
                    ),
                }
            )

    # Check 4: Empty catalog
    active_entries = [e for e in catalog if e.get("status") == "active"]
    if not active_entries:
        anomalies.append(
            {
                "check": "empty_catalog",
                "severity": "critical",
                "detail": "Catalog has zero active entries. Possible scraper total failure.",
            }
        )

    # Check 5: Schema violations
    violations = _check_schema(catalog)
    if violations:
        anomalies.append(
            {
                "check": "schema_violations",
                "severity": "warning",
                "detail": f"{len(violations)} catalog entr(ies) missing required fields: {violations[:3]}",
            }
        )

    # Check 6: Missing PDFs
    missing_pdfs = []
    for entry in active_entries:
        file_path = entry.get("file_path_original")
        if file_path and not os.path.exists(file_path):
            missing_pdfs.append(entry.get("form_id", "unknown"))
    if missing_pdfs:
        anomalies.append(
            {
                "check": "missing_pdfs",
                "severity": "warning",
                "detail": f"{len(missing_pdfs)} form(s) listed in catalog but PDF missing on disk: {missing_pdfs[:5]}",
            }
        )

    has_critical = any(a["severity"] == "critical" for a in anomalies)
    if has_critical:
        logger.error(
            "[ANOMALY] %d anomaly(ies) detected, %d CRITICAL: %s",
            len(anomalies),
            sum(1 for a in anomalies if a["severity"] == "critical"),
            [a["check"] for a in anomalies],
        )
    elif anomalies:
        logger.warning("[ANOMALY] %d warning(s): %s", len(anomalies), [a["check"] for a in anomalies])
    else:
        logger.info("[ANOMALY] No anomalies detected.")

    return {
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "has_critical": has_critical,
    }


def _check_schema(catalog: list[dict]) -> list[str]:
    """Return list of form_ids with missing required fields."""
    violations = []
    for entry in catalog:
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            violations.append(f"{entry.get('form_id', '?')}: missing {missing}")
    return violations
