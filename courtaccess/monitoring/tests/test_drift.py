"""
courtaccess/monitoring/tests/test_drift.py

Unit tests for courtaccess.monitoring.drift and courtaccess.monitoring.anomaly.
The anomaly module is small enough for combined coverage here (see architecture notes).
"""

from courtaccess.monitoring.anomaly import run_anomaly_detection

# ── Anomaly detection tests ───────────────────────────────────────────────────


def test_no_anomalies_clean_run():
    catalog = [
        {
            "form_id": "F001",
            "form_name": "Small Claims",
            "source_url": "https://mass.gov/a",
            "content_hash": "abc123",
            "status": "active",
            "version": 1,
            "last_checked": "2024-01-01",
            "file_path_original": "/tmp/F001.pdf",  # noqa: S108  # nosec B108
        }
    ]
    run_metrics = {"new_forms": 1, "updated": 0, "failed_downloads": 0, "total_attempted": 1, "active_count": 1}
    result = run_anomaly_detection(catalog, run_metrics)
    # Missing PDF on disk is expected in unit tests — filter that check
    non_pdf_anomalies = [a for a in result["anomalies"] if a["check"] != "missing_pdfs"]
    assert len(non_pdf_anomalies) == 0


def test_critical_form_drop():
    catalog = [
        {
            "form_id": "F001",
            "form_name": "X",
            "source_url": "u",
            "content_hash": "h",
            "status": "active",
            "version": 1,
            "last_checked": "2024-01-01",
        }
    ]
    run_metrics = {
        "new_forms": 0,
        "updated": 0,
        "failed_downloads": 0,
        "total_attempted": 20,
        "active_count": 10,
    }  # 50% drop
    prev_metrics = {"active_count": 20}
    result = run_anomaly_detection(catalog, run_metrics, prev_metrics)
    checks = [a["check"] for a in result["anomalies"]]
    assert "form_count_drop" in checks
    assert result["has_critical"] is True


def test_empty_catalog_critical():
    result = run_anomaly_detection(
        [], {"new_forms": 0, "updated": 0, "failed_downloads": 0, "total_attempted": 5, "active_count": 0}
    )
    checks = [a["check"] for a in result["anomalies"]]
    assert "empty_catalog" in checks
    assert result["has_critical"] is True


def test_high_download_failure_rate():
    catalog = []
    run_metrics = {
        "new_forms": 0,
        "updated": 0,
        "failed_downloads": 5,
        "total_attempted": 10,
        "active_count": 0,
    }  # 50% fail
    result = run_anomaly_detection(catalog, run_metrics)
    checks = [a["check"] for a in result["anomalies"]]
    assert "high_download_failures" in checks


def test_schema_violation():
    bad_entry = {"form_id": "F001"}  # missing required fields
    result = run_anomaly_detection(
        [bad_entry], {"new_forms": 0, "updated": 0, "failed_downloads": 0, "total_attempted": 1, "active_count": 0}
    )
    checks = [a["check"] for a in result["anomalies"]]
    assert "schema_violations" in checks


def test_mass_new_forms_warning():
    catalog = []
    run_metrics = {"new_forms": 100, "updated": 0, "failed_downloads": 0, "total_attempted": 100, "active_count": 0}
    result = run_anomaly_detection(catalog, run_metrics)
    checks = [a["check"] for a in result["anomalies"]]
    assert "mass_new_forms" in checks
