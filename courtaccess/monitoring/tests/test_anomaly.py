"""
Tests for courtaccess/monitoring/anomaly.py

Coverage:
  - REQUIRED_FIELDS constant
  - _check_schema  — valid / missing fields / missing form_id
  - run_anomaly_detection — output contract
  - Check 1: form count drop (thresholds, prev_active=0, no prev_metrics)
  - Check 2: mass new forms (threshold boundaries)
  - Check 3: download failure rate (threshold boundaries, total=0)
  - Check 4: empty catalog (no active entries)
  - Check 5: schema violations
  - Check 6: missing PDFs (on-disk check)
  - has_critical logic
  - Multiple simultaneous anomalies
"""

from __future__ import annotations

import pytest

from courtaccess.monitoring.anomaly import (
    REQUIRED_FIELDS,
    _check_schema,
    run_anomaly_detection,
)

# ── shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def thresholds(monkeypatch):
    """Set known anomaly thresholds for every test in this module."""
    monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
    monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "50")
    monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0")


def _good_entry(form_id="F001", file_path: str | None = None) -> dict:
    """Return a catalog entry with all required fields."""
    entry = {
        "form_id": form_id,
        "form_name": "Test Form",
        "source_url": "https://example.com/form.pdf",
        "content_hash": "abc123",
        "status": "active",
        "version": 1,
        "last_checked": "2025-01-01T00:00:00Z",
    }
    if file_path is not None:
        entry["file_path_original"] = file_path
    return entry


def _base_metrics(**kwargs) -> dict:
    defaults = {
        "new_forms": 0,
        "updated": 0,
        "failed_downloads": 0,
        "total_attempted": 10,
        "active_count": 10,
    }
    defaults.update(kwargs)
    return defaults


# ══════════════════════════════════════════════════════════════════════════════
# REQUIRED_FIELDS constant
# ══════════════════════════════════════════════════════════════════════════════


class TestRequiredFields:
    def test_is_a_set(self):
        assert isinstance(REQUIRED_FIELDS, set)

    def test_contains_form_id(self):
        assert "form_id" in REQUIRED_FIELDS

    def test_contains_form_name(self):
        assert "form_name" in REQUIRED_FIELDS

    def test_contains_source_url(self):
        assert "source_url" in REQUIRED_FIELDS

    def test_contains_content_hash(self):
        assert "content_hash" in REQUIRED_FIELDS

    def test_contains_status(self):
        assert "status" in REQUIRED_FIELDS

    def test_contains_version(self):
        assert "version" in REQUIRED_FIELDS

    def test_contains_last_checked(self):
        assert "last_checked" in REQUIRED_FIELDS

    def test_has_exactly_seven_fields(self):
        assert len(REQUIRED_FIELDS) == 7


# ══════════════════════════════════════════════════════════════════════════════
# _check_schema
# ══════════════════════════════════════════════════════════════════════════════


class TestCheckSchema:
    def test_empty_catalog_returns_empty_list(self):
        assert _check_schema([]) == []

    def test_all_valid_entries_returns_empty_list(self):
        catalog = [_good_entry("F001"), _good_entry("F002")]
        assert _check_schema(catalog) == []

    def test_entry_missing_one_field_is_flagged(self):
        entry = _good_entry("F001")
        del entry["content_hash"]
        violations = _check_schema([entry])
        assert len(violations) == 1
        assert "F001" in violations[0]
        assert "content_hash" in violations[0]

    def test_entry_missing_multiple_fields_is_one_violation(self):
        entry = _good_entry("F002")
        del entry["content_hash"]
        del entry["version"]
        violations = _check_schema([entry])
        assert len(violations) == 1

    def test_missing_form_id_uses_question_mark(self):
        entry = _good_entry("F001")
        del entry["form_id"]
        violations = _check_schema([entry])
        assert "?" in violations[0]

    def test_multiple_invalid_entries_each_flagged(self):
        e1 = _good_entry("F001")
        del e1["version"]
        e2 = _good_entry("F002")
        del e2["last_checked"]
        violations = _check_schema([e1, e2])
        assert len(violations) == 2

    def test_mix_valid_and_invalid(self):
        valid = _good_entry("F001")
        invalid = _good_entry("F002")
        del invalid["status"]
        violations = _check_schema([valid, invalid])
        assert len(violations) == 1
        assert "F002" in violations[0]


# ══════════════════════════════════════════════════════════════════════════════
# run_anomaly_detection — output contract
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputContract:
    def test_returns_dict_with_required_keys(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        assert "anomalies" in result
        assert "anomaly_count" in result
        assert "has_critical" in result

    def test_anomaly_count_equals_len_anomalies(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        assert result["anomaly_count"] == len(result["anomalies"])

    def test_clean_run_has_no_anomalies(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        assert result["anomalies"] == []
        assert result["anomaly_count"] == 0
        assert result["has_critical"] is False

    def test_anomalies_is_a_list(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        assert isinstance(result["anomalies"], list)

    def test_each_anomaly_has_check_severity_detail(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "0")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=1))
        assert len(result["anomalies"]) >= 1
        for a in result["anomalies"]:
            assert "check" in a
            assert "severity" in a
            assert "detail" in a

    def test_severity_values_are_warning_or_critical(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "0")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=1))
        for a in result["anomalies"]:
            assert a["severity"] in ("warning", "critical")


# ══════════════════════════════════════════════════════════════════════════════
# Check 1: form count drop
# ══════════════════════════════════════════════════════════════════════════════


class TestFormCountDrop:
    def test_no_previous_metrics_skips_check(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics(), previous_run_metrics=None)
        checks = [a["check"] for a in result["anomalies"]]
        assert "form_count_drop" not in checks

    def test_previous_active_zero_skips_check(self, thresholds):
        prev = {"active_count": 0}
        result = run_anomaly_detection([_good_entry()], _base_metrics(active_count=5), prev)
        checks = [a["check"] for a in result["anomalies"]]
        assert "form_count_drop" not in checks

    def test_drop_below_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
        prev = {"active_count": 100}
        curr = _base_metrics(active_count=85)  # 15% drop < 20%
        result = run_anomaly_detection([_good_entry()], curr, prev)
        checks = [a["check"] for a in result["anomalies"]]
        assert "form_count_drop" not in checks

    def test_drop_at_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
        prev = {"active_count": 100}
        curr = _base_metrics(active_count=80)  # exactly 20% — not strictly greater
        result = run_anomaly_detection([_good_entry()], curr, prev)
        checks = [a["check"] for a in result["anomalies"]]
        assert "form_count_drop" not in checks

    def test_drop_above_threshold_critical_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
        prev = {"active_count": 100}
        curr = _base_metrics(active_count=70)  # 30% drop > 20%
        result = run_anomaly_detection([_good_entry()], curr, prev)
        drop_checks = [a for a in result["anomalies"] if a["check"] == "form_count_drop"]
        assert len(drop_checks) == 1
        assert drop_checks[0]["severity"] == "critical"

    def test_drop_detail_contains_counts(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
        prev = {"active_count": 100}
        curr = _base_metrics(active_count=60)
        result = run_anomaly_detection([_good_entry()], curr, prev)
        drop_checks = [a for a in result["anomalies"] if a["check"] == "form_count_drop"]
        assert "100" in drop_checks[0]["detail"]
        assert "60" in drop_checks[0]["detail"]

    def test_increase_in_forms_no_flag(self, thresholds):
        prev = {"active_count": 80}
        curr = _base_metrics(active_count=100)
        result = run_anomaly_detection([_good_entry()], curr, prev)
        checks = [a["check"] for a in result["anomalies"]]
        assert "form_count_drop" not in checks


# ══════════════════════════════════════════════════════════════════════════════
# Check 2: mass new forms
# ══════════════════════════════════════════════════════════════════════════════


class TestMassNewForms:
    def test_zero_new_forms_no_flag(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=0))
        checks = [a["check"] for a in result["anomalies"]]
        assert "mass_new_forms" not in checks

    def test_new_forms_below_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "50")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=49))
        checks = [a["check"] for a in result["anomalies"]]
        assert "mass_new_forms" not in checks

    def test_new_forms_at_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "50")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=50))
        checks = [a["check"] for a in result["anomalies"]]
        assert "mass_new_forms" not in checks

    def test_new_forms_above_threshold_warning_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "50")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=51))
        mass_checks = [a for a in result["anomalies"] if a["check"] == "mass_new_forms"]
        assert len(mass_checks) == 1
        assert mass_checks[0]["severity"] == "warning"

    def test_mass_new_forms_detail_contains_count(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "10")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=99))
        mass_checks = [a for a in result["anomalies"] if a["check"] == "mass_new_forms"]
        assert "99" in mass_checks[0]["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Check 3: download failure rate
# ══════════════════════════════════════════════════════════════════════════════


class TestDownloadFailures:
    def test_zero_total_attempted_skips_check(self, thresholds):
        metrics = _base_metrics(total_attempted=0, failed_downloads=0)
        result = run_anomaly_detection([_good_entry()], metrics)
        checks = [a["check"] for a in result["anomalies"]]
        assert "high_download_failures" not in checks

    def test_failure_rate_below_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0")
        metrics = _base_metrics(total_attempted=100, failed_downloads=9)  # 9% < 10%
        result = run_anomaly_detection([_good_entry()], metrics)
        checks = [a["check"] for a in result["anomalies"]]
        assert "high_download_failures" not in checks

    def test_failure_rate_at_threshold_no_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0")
        metrics = _base_metrics(total_attempted=100, failed_downloads=10)  # exactly 10%
        result = run_anomaly_detection([_good_entry()], metrics)
        checks = [a["check"] for a in result["anomalies"]]
        assert "high_download_failures" not in checks

    def test_failure_rate_above_threshold_critical_flag(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "10.0")
        metrics = _base_metrics(total_attempted=100, failed_downloads=11)  # 11% > 10%
        result = run_anomaly_detection([_good_entry()], metrics)
        fail_checks = [a for a in result["anomalies"] if a["check"] == "high_download_failures"]
        assert len(fail_checks) == 1
        assert fail_checks[0]["severity"] == "critical"

    def test_all_downloads_failed_critical_flag(self, thresholds):
        metrics = _base_metrics(total_attempted=10, failed_downloads=10)
        result = run_anomaly_detection([_good_entry()], metrics)
        fail_checks = [a for a in result["anomalies"] if a["check"] == "high_download_failures"]
        assert len(fail_checks) == 1

    def test_failure_detail_contains_counts(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "5.0")
        metrics = _base_metrics(total_attempted=50, failed_downloads=10)
        result = run_anomaly_detection([_good_entry()], metrics)
        fail_checks = [a for a in result["anomalies"] if a["check"] == "high_download_failures"]
        assert "10" in fail_checks[0]["detail"]
        assert "50" in fail_checks[0]["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Check 4: empty catalog
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyCatalog:
    def test_catalog_with_active_entry_no_flag(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "empty_catalog" not in checks

    def test_empty_catalog_list_critical_flag(self, thresholds):
        result = run_anomaly_detection([], _base_metrics(active_count=0))
        empty_checks = [a for a in result["anomalies"] if a["check"] == "empty_catalog"]
        assert len(empty_checks) == 1
        assert empty_checks[0]["severity"] == "critical"

    def test_only_inactive_entries_critical_flag(self, thresholds):
        inactive = {**_good_entry(), "status": "deprecated"}
        result = run_anomaly_detection([inactive], _base_metrics())
        empty_checks = [a for a in result["anomalies"] if a["check"] == "empty_catalog"]
        assert len(empty_checks) == 1

    def test_mix_active_and_inactive_no_empty_flag(self, thresholds):
        inactive = {**_good_entry("F001"), "status": "deprecated"}
        active = _good_entry("F002")
        result = run_anomaly_detection([inactive, active], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "empty_catalog" not in checks


# ══════════════════════════════════════════════════════════════════════════════
# Check 5: schema violations
# ══════════════════════════════════════════════════════════════════════════════


class TestSchemaViolations:
    def test_all_valid_no_schema_flag(self, thresholds):
        result = run_anomaly_detection([_good_entry("F001"), _good_entry("F002")], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "schema_violations" not in checks

    def test_one_invalid_entry_schema_warning(self, thresholds):
        invalid = _good_entry("F001")
        del invalid["version"]
        result = run_anomaly_detection([invalid], _base_metrics())
        schema_checks = [a for a in result["anomalies"] if a["check"] == "schema_violations"]
        assert len(schema_checks) == 1
        assert schema_checks[0]["severity"] == "warning"

    def test_schema_detail_includes_count(self, thresholds):
        e1 = _good_entry("F001")
        del e1["version"]
        e2 = _good_entry("F002")
        del e2["content_hash"]
        result = run_anomaly_detection([e1, e2], _base_metrics())
        schema_checks = [a for a in result["anomalies"] if a["check"] == "schema_violations"]
        assert "2" in schema_checks[0]["detail"]


# ══════════════════════════════════════════════════════════════════════════════
# Check 6: missing PDFs
# ══════════════════════════════════════════════════════════════════════════════


class TestMissingPDFs:
    def test_no_file_path_field_no_missing_flag(self, thresholds):
        entry = _good_entry("F001")  # no file_path_original key
        result = run_anomaly_detection([entry], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "missing_pdfs" not in checks

    def test_file_path_none_no_missing_flag(self, thresholds):
        entry = _good_entry("F001")
        entry["file_path_original"] = None
        result = run_anomaly_detection([entry], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "missing_pdfs" not in checks

    def test_existing_file_no_missing_flag(self, thresholds, tmp_path):
        pdf = tmp_path / "form.pdf"
        pdf.write_bytes(b"%PDF")
        entry = _good_entry("F001", file_path=str(pdf))
        result = run_anomaly_detection([entry], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "missing_pdfs" not in checks

    def test_missing_file_warning_flag(self, thresholds, tmp_path):
        missing_path = str(tmp_path / "nonexistent.pdf")
        entry = _good_entry("F001", file_path=missing_path)
        result = run_anomaly_detection([entry], _base_metrics())
        pdf_checks = [a for a in result["anomalies"] if a["check"] == "missing_pdfs"]
        assert len(pdf_checks) == 1
        assert pdf_checks[0]["severity"] == "warning"

    def test_missing_pdf_detail_contains_form_id(self, thresholds, tmp_path):
        missing_path = str(tmp_path / "nonexistent.pdf")
        entry = _good_entry("FORM-XYZ", file_path=missing_path)
        result = run_anomaly_detection([entry], _base_metrics())
        pdf_checks = [a for a in result["anomalies"] if a["check"] == "missing_pdfs"]
        assert "FORM-XYZ" in pdf_checks[0]["detail"]

    def test_inactive_entries_not_checked_for_missing_pdf(self, thresholds, tmp_path):
        # Inactive entries are excluded from active_entries, so not PDF-checked
        missing_path = str(tmp_path / "nonexistent.pdf")
        entry = {**_good_entry("F001", file_path=missing_path), "status": "deprecated"}
        result = run_anomaly_detection([entry], _base_metrics())
        checks = [a["check"] for a in result["anomalies"]]
        assert "missing_pdfs" not in checks


# ══════════════════════════════════════════════════════════════════════════════
# has_critical flag logic
# ══════════════════════════════════════════════════════════════════════════════


class TestHasCritical:
    def test_false_when_no_anomalies(self, thresholds):
        result = run_anomaly_detection([_good_entry()], _base_metrics())
        assert result["has_critical"] is False

    def test_false_when_only_warnings(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "0")
        result = run_anomaly_detection([_good_entry()], _base_metrics(new_forms=1))
        warning_checks = [a for a in result["anomalies"] if a["severity"] == "warning"]
        assert len(warning_checks) >= 1
        assert result["has_critical"] is False

    def test_true_when_any_critical(self, thresholds):
        # Empty catalog → critical
        result = run_anomaly_detection([], _base_metrics(active_count=0))
        assert result["has_critical"] is True

    def test_true_when_form_drop_critical(self, thresholds, monkeypatch):
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "20.0")
        prev = {"active_count": 100}
        curr = _base_metrics(active_count=50)
        result = run_anomaly_detection([_good_entry()], curr, prev)
        assert result["has_critical"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Multiple simultaneous anomalies
# ══════════════════════════════════════════════════════════════════════════════


class TestMultipleAnomalies:
    def test_two_independent_checks_both_flagged(self, thresholds, monkeypatch):
        """Mass new forms (warning) + empty catalog (critical) both fire."""
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "0")
        # Catalog has no active entries (empty_catalog) + new_forms=5 (mass_new_forms)
        result = run_anomaly_detection([], _base_metrics(active_count=0, new_forms=5))
        checks = [a["check"] for a in result["anomalies"]]
        assert "mass_new_forms" in checks
        assert "empty_catalog" in checks
        assert result["anomaly_count"] >= 2
        assert result["has_critical"] is True

    def test_all_six_checks_can_fire(self, thresholds, monkeypatch, tmp_path):
        """Exercise a worst-case scenario where all checks fire at once."""
        monkeypatch.setenv("ANOMALY_FORM_DROP_PCT", "0.0")  # any drop triggers
        monkeypatch.setenv("ANOMALY_MASS_NEW_FORMS", "0")  # any new form triggers
        monkeypatch.setenv("ANOMALY_DOWNLOAD_FAIL_PCT", "0.0")  # any failure triggers

        missing = str(tmp_path / "gone.pdf")
        bad_entry = _good_entry("F001", file_path=missing)
        del bad_entry["version"]  # schema violation
        # Keep status=active so it counts as active (to avoid empty_catalog masking others)

        metrics = _base_metrics(
            new_forms=1,
            failed_downloads=1,
            total_attempted=10,
            active_count=5,
        )
        prev = {"active_count": 10}  # triggers form_count_drop

        result = run_anomaly_detection([bad_entry], metrics, prev)
        checks = {a["check"] for a in result["anomalies"]}
        # All six should be present
        assert "form_count_drop" in checks
        assert "mass_new_forms" in checks
        assert "high_download_failures" in checks
        assert "schema_violations" in checks
        assert "missing_pdfs" in checks
        # empty_catalog won't fire because bad_entry is active
        assert result["anomaly_count"] == len(result["anomalies"])
