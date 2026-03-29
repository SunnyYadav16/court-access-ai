"""
dags/form_scraper_dag.py

Airflow DAG — form_scraper_dag
Scheduled: every Monday at 06:00 UTC

Pipeline flow:
  scrape_and_classify → preprocess_data → validate_catalog → detect_anomalies
      → detect_bias → trigger_pretranslation → log_summary → write_manifest

MIGRATED from data_pipeline/dags/form_scraper_dag.py.
All src.* imports updated to courtaccess.* package imports.
"""

import contextlib
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from courtaccess.core import gcs
from courtaccess.core.validation import run_preprocessing
from courtaccess.forms.scraper import run_scrape
from courtaccess.monitoring.drift import run_bias_detection
from db.database import get_sync_engine
from db.queries import forms as form_queries
from db.queries.audit import write_audit_sync

logger = logging.getLogger(__name__)

# ── Paths (inside Docker container) ──────────────────────────────────────────
PROJECT_ROOT = "/opt/airflow"

# ── Runtime infra constants (DAGs use os.getenv directly) ────────────────────
_GCS_BUCKET_FORMS = os.getenv("GCS_BUCKET_FORMS", "courtaccess-ai-forms")
AIRFLOW_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"

# ── Anomaly thresholds ───────────────────────────────────────────────────────
THRESHOLD_FORM_DROP_PCT = 20  # Alert if active forms drop >20%
THRESHOLD_MASS_NEW_FORMS = 50  # Alert if >50 new forms in one run
THRESHOLD_DOWNLOAD_FAIL_PCT = 10  # Alert if >10% of forms fail to download
THRESHOLD_MIN_PDF_SIZE_BYTES = 1024  # Alert if PDF is <1KB (likely error page)
THRESHOLD_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # Alert if PDF is >50MB
THRESHOLD_SCHEMA_ERRORS = 0  # Alert if any schema validation errors

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


def _get_actor_id(context) -> str:
    """
    Resolve audit actor for this DAG run.

    - API-triggered run: use dag_run.conf["triggered_by_user_id"]
    - Scheduled run:     fall back to the fixed Airflow system user
    """
    conf = (context.get("dag_run") or {}).conf or {}
    actor_id = conf.get("triggered_by_user_id")
    return actor_id if actor_id else AIRFLOW_SYSTEM_USER_ID


def task_scrape_and_classify(**context) -> dict:
    """Task 1 — Run the scraper, classify every form, update the catalog."""
    logger.info("Starting weekly mass.gov form scrape.")
    existing_forms = form_queries.get_all_forms_sync()
    active_existing = sum(1 for f in existing_forms if f.get("status") == "active")
    logger.info(
        "Loaded existing catalog from DB: %d row(s) total, %d active (used for URL/hash matching before scrape).",
        len(existing_forms),
        active_existing,
    )
    result = run_scrape(existing_catalog=existing_forms)
    logger.info("Scrape finished. Summary: %s", result["counts"])
    context["ti"].xcom_push(key="scrape_result", value=result)
    context["ti"].xcom_push(key="forms", value=result.get("forms", []))
    return result


def task_upload_forms_to_gcs(**context) -> dict:
    """
    Task 1b — Upload locally downloaded form files to GCS.

    For each form/version/path key:
      - gs://... → leave as-is
      - local existing file → upload to gs://{_GCS_BUCKET_FORMS}/forms/{slug}/v{version}/{slug}{suffix}.{ext}
        then delete local file, record mapping.
    """
    ti = context["ti"]
    forms: list[dict] = ti.xcom_pull(task_ids="scrape_and_classify", key="forms") or []

    if not forms:
        logger.warning("No forms found in XCom — skipping GCS upload task.")
        ti.xcom_push(key="gcs_path_map", value={})
        return {"uploaded": 0, "skipped": 0, "failed": 0}

    correlation_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
    gcs_path_map: dict[str, str] = {}
    uploaded = skipped = failed = 0

    def _suffix_for(key: str) -> str:
        return {"file_path_original": "", "file_path_es": "_es", "file_path_pt": "_pt"}[key]

    def _ext_for(key: str, ver: dict) -> str:
        if key == "file_path_original":
            return (ver.get("file_type") or "pdf").lower()
        if key == "file_path_es":
            return (ver.get("file_type_es") or ver.get("file_type") or "pdf").lower()
        if key == "file_path_pt":
            return (ver.get("file_type_pt") or ver.get("file_type") or "pdf").lower()
        return "pdf"

    updated_forms: list[dict] = []

    for entry in forms:
        form_id = entry.get("form_id")
        slug = entry.get("form_slug") or "form"
        versions = entry.get("versions") or []
        new_versions: list[dict] = []

        for ver in versions:
            vnum = ver.get("version")
            new_ver = dict(ver)

            for key in ("file_path_original", "file_path_es", "file_path_pt"):
                path_val = ver.get(key)
                if not path_val:
                    continue

                if isinstance(path_val, str) and path_val.startswith("gs://"):
                    # already uploaded
                    skipped += 1
                    continue

                local_path = str(path_val)
                p = Path(local_path)

                ext = _ext_for(key, ver)
                suffix = _suffix_for(key)
                blob = f"forms/{slug}/v{vnum}/{slug}{suffix}.{ext}"
                uri = f"gs://{_GCS_BUCKET_FORMS}/{blob}"

                if gcs.blob_exists(_GCS_BUCKET_FORMS, blob):
                    logger.info("GCS blob already exists, skipping upload: gs://%s/%s", _GCS_BUCKET_FORMS, blob)
                    skipped += 1
                    new_ver[key] = uri
                    with contextlib.suppress(Exception):
                        p.unlink()
                    continue

                if not p.exists():
                    failed += 1
                    logger.warning("Local file missing (skip upload): %s", local_path)
                    continue

                try:
                    gcs.upload_file(local_path, _GCS_BUCKET_FORMS, blob, correlation_id=correlation_id)
                except Exception as exc:
                    failed += 1
                    logger.warning("GCS upload failed for %s → %s: %s", local_path, uri, exc)
                    continue

                uploaded += 1
                gcs_path_map[local_path] = uri
                new_ver[key] = uri

                # Best-effort delete; if delete fails, keep going.
                try:
                    p.unlink()
                except Exception as exc:
                    logger.warning("Could not delete local file %s after upload: %s", local_path, exc)

            # cleanup empty version dir: /opt/airflow/forms/{form_id}/v{version}
            with contextlib.suppress(Exception):
                version_dir = Path("/opt/airflow/forms") / str(form_id) / f"v{vnum}"
                if version_dir.exists() and not any(version_dir.iterdir()):
                    version_dir.rmdir()

            new_versions.append(new_ver)

        # cleanup empty form dir: /opt/airflow/forms/{form_id}
        with contextlib.suppress(Exception):
            form_dir = Path("/opt/airflow/forms") / str(form_id)
            if form_dir.exists() and not any(form_dir.iterdir()):
                form_dir.rmdir()

        updated_entry = dict(entry)
        updated_entry["versions"] = new_versions
        updated_forms.append(updated_entry)

    ti.xcom_push(key="forms", value=updated_forms)
    ti.xcom_push(key="gcs_path_map", value=gcs_path_map)

    logger.info(
        "GCS upload complete: uploaded=%d skipped=%d failed=%d mapped=%d",
        uploaded,
        skipped,
        failed,
        len(gcs_path_map),
    )
    return {"uploaded": uploaded, "skipped": skipped, "failed": failed}


def _write_single_form_to_db(engine, entry: dict, session_class, integrity_error_class) -> None:
    """Write one form entry (catalog + versions + appearances) to DB.

    Uses an isolated Session so failures cannot poison other entries.
    Handles form_slug unique-constraint collisions by suffixing the slug
    with the first 8 chars of form_id and retrying once.
    """
    form_id = uuid.UUID(str(entry["form_id"]))

    def _build_catalog_row(slug_override: str | None = None) -> dict:
        row = {
            "form_id": form_id,
            "form_name": entry.get("form_name", ""),
            "form_slug": slug_override or entry.get("form_slug", ""),
            "source_url": entry.get("source_url", ""),
            "file_type": entry.get("file_type", "pdf"),
            "status": entry.get("status", "active"),
            "content_hash": entry.get("content_hash", ""),
            "current_version": entry.get("current_version", 1),
            "needs_human_review": bool(entry.get("needs_human_review", True)),
            "created_at": entry.get("created_at"),
            "last_scraped_at": entry.get("last_scraped_at"),
            "last_updated_at": entry.get("last_updated_at"),
            "preprocessing_flags": entry.get("preprocessing_flags"),
        }
        if row["created_at"] is None:
            row.pop("created_at")
        if row["last_scraped_at"] is None:
            row.pop("last_scraped_at")
        if row["last_updated_at"] is None:
            row.pop("last_updated_at")
        return row

    def _do_write(session, catalog_row: dict) -> None:
        form_queries.upsert_form_catalog_sync(session, catalog_row)

        for ver in entry.get("versions") or []:
            version_row = {
                "version": int(ver.get("version", 1)),
                "content_hash": ver.get("content_hash", entry.get("content_hash", "")),
                "file_type": ver.get("file_type", entry.get("file_type", "pdf")),
                "file_path_original": ver.get("file_path_original", ""),
                "file_path_es": ver.get("file_path_es"),
                "file_path_pt": ver.get("file_path_pt"),
                "file_type_es": ver.get("file_type_es"),
                "file_type_pt": ver.get("file_type_pt"),
            }
            if ver.get("created_at"):
                version_row["created_at"] = ver.get("created_at")
            form_queries.upsert_form_version_sync(session, form_id, version_row)

        for app in entry.get("appearances") or []:
            div = app.get("division")
            heading = app.get("section_heading")
            if not div or not heading:
                continue
            form_queries.upsert_form_appearance_sync(session, form_id, div, heading)

    catalog_row = _build_catalog_row()

    try:
        with session_class(engine) as session, session.begin():
            _do_write(session, catalog_row)
    except integrity_error_class as exc:
        # Likely form_slug unique constraint collision (form_catalog_form_slug_key).
        # ON CONFLICT (form_id) cannot intercept a violation on a different
        # unique column. Retry with a suffixed slug in a fresh session.
        suffixed_slug = f"{entry.get('form_slug', '')}-{str(form_id)[:8]}"
        logger.warning(
            "Slug collision for form_id=%s slug=%r — retrying with '%s'. (%s)",
            form_id,
            entry.get("form_slug"),
            suffixed_slug,
            exc.orig,
        )
        catalog_row = _build_catalog_row(slug_override=suffixed_slug)
        with session_class(engine) as session, session.begin():
            _do_write(session, catalog_row)


def task_write_catalog_to_db(**context) -> dict:
    """
    Task 1c — Upsert the scraped catalog into the DB (sync).

    Uses ON CONFLICT upserts and never aborts the pipeline for a single bad entry.
    """
    from sqlalchemy.orm import Session

    ti = context["ti"]
    forms = (
        ti.xcom_pull(task_ids="upload_forms_to_gcs", key="forms")
        or ti.xcom_pull(task_ids="scrape_and_classify", key="forms")
        or []
    )

    if not forms:
        logger.warning("No forms found in XCom — skipping DB write task.")
        return {"written": 0, "failed": 0}

    from sqlalchemy.exc import IntegrityError

    engine = get_sync_engine()
    written = failed = 0

    # ── Each entry gets its own Session so a rollback on entry N cannot      ──
    # ── poison the connection state for entries N+1 … 22.                   ──
    # ── Previously a single shared Session was used: after the first         ──
    # ── form_slug unique-constraint violation, SQLAlchemy marked the session ──
    # ── inactive, causing every subsequent session.begin() to raise          ──
    # ── InvalidRequestError, silently failing all 22 writes and leaving the  ──
    # ── DB empty — which made every re-run classify all forms as "New".      ──
    for entry in forms:
        try:
            _write_single_form_to_db(engine, entry, Session, IntegrityError)
            written += 1
        except Exception as exc:
            failed += 1
            logger.error(
                "DB write failed for form_id=%s: %s",
                entry.get("form_id"),
                exc,
                exc_info=True,
            )
            continue

    if failed > 0 and written == 0:
        raise RuntimeError(
            f"write_catalog_to_db: every entry failed ({failed}/{len(forms)}). "
            "Check ERROR logs above for the root cause."
        )

    if failed > 0:
        fail_pct = (failed / len(forms)) * 100
        logger.warning(
            "write_catalog_to_db: %d/%d entries failed (%.0f%%) — see ERROR logs above.",
            failed,
            len(forms),
            fail_pct,
        )
        # Raise if more than half of writes failed — this prevents a silent
        # empty-DB state where the next run again sees all forms as "New".
        if fail_pct > 50:
            raise RuntimeError(
                f"write_catalog_to_db: {fail_pct:.0f}% of entries failed "
                f"({failed}/{len(forms)}). Raising to prevent silent data loss — "
                "check ERROR logs above for the root cause."
            )

    return {"written": written, "failed": failed}


def task_preprocess_data(**context) -> dict:
    """
    Task 2 — Clean, normalize, and validate the scraped data.
    Preprocessing steps:
      1. File type detection   4. Form name cleanup
      2. PDF integrity         5. Slug normalization
      3. Empty file removal    6. Duplicate detection
    """
    logger.info("Starting data preprocessing.")
    ti = context["ti"]
    # Prefer the GCS-resolved form list pushed by upload_forms_to_gcs (gs:// paths).
    # Fall back to scrape_and_classify only if upload_forms_to_gcs was skipped.
    forms = (
        ti.xcom_pull(task_ids="upload_forms_to_gcs", key="forms")
        or ti.xcom_pull(task_ids="scrape_and_classify", key="forms")
        or []
    )
    if not forms:
        logger.error("No forms catalog found in XCom — cannot preprocess.")
        return {"error": "catalog_missing"}

    report = run_preprocessing(forms, "/opt/airflow/forms")

    context["ti"].xcom_push(key="preprocess_report", value=report)
    context["ti"].xcom_push(key="forms_preprocessed", value=forms)
    return report


def task_validate_catalog(**context) -> dict:
    """Task 3 — Validate the catalog JSON after preprocessing."""
    from collections import Counter

    logger.info("Starting catalog validation.")
    errors = []
    warnings = []

    ti = context["ti"]
    forms = (
        ti.xcom_pull(task_ids="preprocess_data", key="forms_preprocessed")
        or ti.xcom_pull(task_ids="scrape_and_classify", key="forms")
        or []
    )
    if not forms:
        logger.error("No forms catalog found in XCom — cannot validate.")
        return {"valid": False, "errors": 1}

    status_counts = Counter()
    division_counts = Counter()
    forms_with_es = forms_with_pt = missing_pdfs = total_versions = 0
    seen_ids: set = set()
    seen_urls: set = set()

    for i, entry in enumerate(forms):
        prefix = f"Entry [{i}]"
        # Field presence checks are no longer useful once data is DB-backed.
        # Keep business/data-quality validations below.

        fid = entry.get("form_id")
        if not fid:
            errors.append(f"{prefix}: missing form_id")
            continue
        if fid in seen_ids:
            errors.append(f"{prefix}: duplicate form_id '{fid}'")
        seen_ids.add(fid)

        url = entry.get("source_url")
        if not url:
            errors.append(f"{prefix}: missing source_url")
            continue
        if url in seen_urls:
            errors.append(f"{prefix}: duplicate source_url '{url}'")
        seen_urls.add(url)

        status_val = entry.get("status")
        if status_val not in ("active", "archived"):
            errors.append(f"{prefix}: invalid status '{status_val}'")
        status_counts[status_val] += 1

        cv = entry.get("current_version")
        if not isinstance(cv, int) or cv < 1:
            errors.append(f"{prefix}: invalid current_version {cv}")

        for j, app in enumerate(entry.get("appearances", [])):
            div = app.get("division")
            heading = app.get("section_heading")
            if not div or not heading:
                errors.append(f"{prefix} appearance[{j}]: missing division/section_heading")
            else:
                division_counts[div] += 1

        versions = entry.get("versions", [])
        if len(versions) == 0:
            errors.append(f"{prefix}: no versions")
        total_versions += len(versions)

        for j, ver in enumerate(versions):
            if j == 0 and entry["status"] == "active":
                fp = ver.get("file_path_original")
                if fp:
                    # If DB already points at GCS, treat it as present.
                    if isinstance(fp, str) and fp.startswith("gs://"):
                        pass
                    elif not Path(fp).exists():
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
        "total_forms": len(forms),
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

    logger.info(
        "Validation complete: %d forms, %d active, %d archived, "
        "%d errors, %d warnings, %d missing PDFs, %d with ES, %d with PT",
        len(forms),
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


def _prev_active_forms_count() -> int | None:
    """
    Best-effort lookup for the previous successful run's active form count.

    Priority:
      1) Last audit_logs entry for action_type='form_scrape_completed' → details.active_forms
      2) Fallback: COUNT(*) from form_catalog where status='active'
    """

    try:
        engine = get_sync_engine()
        with engine.begin() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT (details->>'active_forms')::int AS active_forms
                    FROM audit_logs
                    WHERE action_type = 'form_scrape_completed'
                      AND details ? 'active_forms'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
            ).first()
            if row and row[0] is not None:
                return int(row[0])

            row2 = conn.execute(sa.text("SELECT COUNT(*) FROM form_catalog WHERE status = 'active'")).first()
            return int(row2[0]) if row2 else None
    except Exception as exc:
        logger.warning("Could not query previous active form count: %s", exc)
        return None


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

    prev_active = _prev_active_forms_count()
    curr_active = int(metrics.get("active_forms", 0) or 0)
    if prev_active and prev_active > 0:
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

    # Scan only files referenced by the current run's preprocessed catalog,
    # instead of walking the entire forms/ directory.
    forms = (
        ti.xcom_pull(task_ids="preprocess_data", key="forms_preprocessed")
        or ti.xcom_pull(task_ids="scrape_and_classify", key="forms")
        or []
    )
    tiny_pdfs = []
    huge_pdfs = []
    for entry in forms:
        versions = entry.get("versions") or []
        latest = versions[0] if versions else None
        if not latest:
            continue

        for key in ("file_path_original", "file_path_es", "file_path_pt"):
            fp = latest.get(key)
            if not fp or not isinstance(fp, str) or fp.startswith("gs://"):
                continue
            p = Path(fp)
            if not p.exists():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size < THRESHOLD_MIN_PDF_SIZE_BYTES:
                tiny_pdfs.append({"file": str(p), "size_bytes": size})
            elif size > THRESHOLD_MAX_PDF_SIZE_BYTES:
                huge_pdfs.append({"file": str(p), "size_bytes": size})
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
    ti = context["ti"]
    forms = (
        ti.xcom_pull(task_ids="preprocess_data", key="forms_preprocessed")
        or ti.xcom_pull(task_ids="scrape_and_classify", key="forms")
        or []
    )
    if not forms:
        logger.error("No forms catalog found in XCom — cannot detect bias.")
        return {"error": "catalog_missing"}

    report = run_bias_detection(forms)

    context["ti"].xcom_push(key="bias_report", value=report)
    return report


def task_prepare_trigger_confs(**context) -> list[dict]:
    """
    Task 6a — Prepare confs for trigger_pretranslation task.

    Each entry includes a unique ``trigger_run_id`` to prevent ``logical_date``
    collision deduplication when multiple forms are triggered in the same second.
    Without this, ``TriggerDagRunOperator.expand()`` silently drops runs whose
    auto-generated ``run_id`` collides with an earlier mapped instance's.

    Returns a list of dicts shaped for ``expand_kwargs()``:
        [{"conf": {"form_id": ...}, "trigger_run_id": "pretranslation__<uuid>__<dag_run>"}, ...]
    """
    ti = context["ti"]
    result = ti.xcom_pull(task_ids="scrape_and_classify", key="scrape_result")
    if result is None:
        logger.warning("No scrape result found in XCom — nothing to trigger.")
        return []

    queue: list[str] = result.get("pretranslation_queue", [])
    if not queue:
        logger.info("No forms need pre-translation this cycle.")
        return []

    dag_run_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
    logger.info("Preparing trigger confs for %d form(s): %s", len(queue), queue)

    return [
        {
            "conf": {"form_id": form_id},
            "trigger_run_id": f"pretranslation__{form_id}__{dag_run_id}",
        }
        for form_id in queue
    ]


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

    # ── Append DB audit write (never raise) ───────────────────────────────────
    try:
        dag_run_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
        details = {
            "counts": c,
            "pretranslation_queued": len(result.get("pretranslation_queue", [])),
            "dag_run_id": dag_run_id,
            # active_forms must stay top-level — _prev_active_forms_count() reads details->>'active_forms'
            "active_forms": (metrics or {}).get("active_forms", 0) if isinstance(metrics, dict) else 0,
            "catalog_metrics": metrics or {},
            "preprocess_report": preproc or {},
            "anomaly_report": anomaly or {},
            "bias_report": bias or {},
        }
        engine = get_sync_engine()
        with engine.begin() as conn:
            write_audit_sync(
                conn,
                user_id=_get_actor_id(context),
                action_type="form_scrape_completed",
                details=details,
            )
    except Exception as exc:
        logger.warning("Could not write form_scrape_completed audit log: %s", exc)


def task_write_manifest(**context) -> dict:
    """Task 8 — Build and upload the weekly form catalog manifest to GCS.

    Queries the DB for all active forms, builds a JSON snapshot of the full
    catalog (one entry per form at its current version), and uploads it to a
    fixed GCS path. GCS Object Versioning on the bucket preserves every
    historical manifest automatically.
    """
    correlation_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
    all_forms = form_queries.get_all_forms_sync()

    active_forms = [f for f in all_forms if f.get("status") == "active"]

    manifest_forms = []
    for form in active_forms:
        versions = sorted(form.get("versions") or [], key=lambda v: v.get("version", 0), reverse=True)
        latest = versions[0] if versions else {}
        manifest_forms.append(
            {
                "form_id": str(form.get("form_id", "")),
                "form_slug": form.get("form_slug", ""),
                "version": latest.get("version"),
                "content_hash": latest.get("content_hash") or form.get("content_hash"),
                "gcs_path_original": latest.get("file_path_original"),
                "gcs_path_es": latest.get("file_path_es"),
                "gcs_path_pt": latest.get("file_path_pt"),
            }
        )

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "scraper_run_id": correlation_id,
        "total_active_forms": len(active_forms),
        "forms": manifest_forms,
    }

    payload = json.dumps(manifest, indent=2).encode()
    blob = "manifests/form_catalog_manifest.json"
    gcs.upload_bytes(_GCS_BUCKET_FORMS, blob, payload, "application/json", correlation_id=correlation_id)

    logger.info(
        "Manifest uploaded: gs://%s/%s (%d active forms, %d bytes)",
        _GCS_BUCKET_FORMS,
        blob,
        len(active_forms),
        len(payload),
    )
    return {"total_active_forms": len(active_forms), "manifest_bytes": len(payload)}


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
    is_paused_upon_creation=False,
    tags=["courtaccess", "forms", "scraping", "preprocessing", "anomaly-detection", "bias-detection"],
) as dag:
    t1_scrape = PythonOperator(task_id="scrape_and_classify", python_callable=task_scrape_and_classify)
    t1b_gcs = PythonOperator(task_id="upload_forms_to_gcs", python_callable=task_upload_forms_to_gcs)
    t1c_db = PythonOperator(task_id="write_catalog_to_db", python_callable=task_write_catalog_to_db)
    t2_preprocess = PythonOperator(task_id="preprocess_data", python_callable=task_preprocess_data)
    t3_validate = PythonOperator(task_id="validate_catalog", python_callable=task_validate_catalog)
    t4_anomaly = PythonOperator(task_id="detect_anomalies", python_callable=task_detect_anomalies)
    t5_bias = PythonOperator(task_id="detect_bias", python_callable=task_detect_bias)
    from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator

    t6_prepare = PythonOperator(task_id="prepare_trigger_confs", python_callable=task_prepare_trigger_confs)
    t6_trigger = TriggerDagRunOperator.partial(
        task_id="trigger_pretranslation",
        trigger_dag_id="form_pretranslation_dag",
    ).expand_kwargs(t6_prepare.output)
    t7_summary = PythonOperator(task_id="log_summary", python_callable=task_log_summary)
    t8_manifest = PythonOperator(task_id="write_manifest", python_callable=task_write_manifest)

    (
        t1_scrape
        >> t1b_gcs
        >> t1c_db
        >> t2_preprocess
        >> t3_validate
        >> t4_anomaly
        >> t5_bias
        >> t6_prepare
        >> t6_trigger
        >> t7_summary
        >> t8_manifest
    )
