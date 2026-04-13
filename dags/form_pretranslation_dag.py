"""
dags/form_pretranslation_dag.py

Airflow DAG — form_pretranslation_dag
Triggered by: form_scraper_dag (task_trigger_pretranslation)
              when Scenario A (new form) or Scenario B (updated form) is detected.

Trigger conf:
    {"form_id": "<uuid-string>"}

Pipeline (one form per DAG run):
    load_form_entry
        → ocr_extract_text
            ┌──────────────────────┐
            ▼                      ▼
    translate_spanish      translate_portuguese   (parallel)
            │                      │
            ▼                      ▼
    legal_review_spanish  legal_review_portuguese (parallel)
            │                      │
            ▼                      ▼
    reconstruct_pdf_spanish  reconstruct_pdf_portuguese (parallel)
            └──────────┬───────────┘
                       ▼
            store_and_update_catalog
                       ▼
               log_summary

Each task instantiates the classes it needs internally.
Airflow runs each task in its own process — instances are not shared.
"""

import logging
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from sqlalchemy.orm import Session

from courtaccess.core import gcs
from courtaccess.core.legal_review import LegalReviewer
from courtaccess.core.ocr_printed import OCREngine
from courtaccess.core.reconstruct_pdf import reconstruct_pdf
from courtaccess.core.translation import Translator
from courtaccess.languages import get_language_config
from dags.gpu_pool import GPU_POOL_NAME
from db.database import get_sync_engine
from db.queries import forms as form_queries
from db.queries.audit import write_audit_sync

logger = logging.getLogger(__name__)

# ── Paths (inside Docker container) ──────────────────────────────────────────
PROJECT_ROOT = "/opt/airflow"
_GCS_BUCKET_FORMS = os.getenv("GCS_BUCKET_FORMS")
AIRFLOW_SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000001"

# ── NLLB-200 language codes ───────────────────────────────────────────────────
LANG_EN = "eng_Latn"
LANG_ES = "spa_Latn"
LANG_PT = "por_Latn"

# ── Vertex/Llama retry settings ─────────────────────────────────────────────────
Vertex_RETRY_DELAYS = [1, 3, 9]  # seconds — exponential backoff

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
# Helpers — use class instances passed in, not module-level functions
# ══════════════════════════════════════════════════════════════════════════════


def _translate_regions(
    regions: list[dict],
    target_lang: str,
    translator: Translator,
) -> list[dict]:
    """Translate each OCR region using the provided Translator instance."""
    out = []
    for region in regions:
        src = region.get("text", "").strip()
        if not src:
            out.append({**region, "translated_text": "", "translation_confidence": 1.0})
            continue
        result = translator.translate_text(src, target_lang)
        out.append(
            {
                **region,
                "translated_text": result["translated"],
                "translation_confidence": result["confidence"],
            }
        )
    return out


def _legal_review_with_retry(
    text: str,
    reviewer: LegalReviewer,
) -> dict:
    """
    Call reviewer.review_legal_terms() up to len(Vertex_RETRY_DELAYS) times.
    On total failure returns a 'skipped' result so the pipeline continues
    and flags the form for mandatory human review.
    """
    last_err = None
    for attempt, delay in enumerate(Vertex_RETRY_DELAYS, start=1):
        try:
            result = reviewer.review_legal_terms(text)
            result["skipped"] = False
            logger.info("Legal review succeeded on attempt %d.", attempt)
            return result
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Legal review attempt %d/%d failed: %s. Retrying in %ds.",
                attempt,
                len(Vertex_RETRY_DELAYS),
                exc,
                delay,
            )
            if attempt < len(Vertex_RETRY_DELAYS):
                time.sleep(delay)

    logger.error(
        "Legal review failed after all retries. "
        "AUDIT: Legal review skipped — human review is mandatory. "
        "Last error: %s",
        last_err,
    )
    return {
        "status": "skipped",
        "corrections": [],
        "skipped": True,
        "reason": str(last_err),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Task 1 — load_form_entry (unchanged)
# ══════════════════════════════════════════════════════════════════════════════


def task_load_form_entry(**context) -> dict:
    conf = context["dag_run"].conf or {}
    form_id = conf.get("form_id")
    if not form_id:
        raise ValueError("DAG triggered without 'form_id' in conf. Expected conf={'form_id': '<uuid>'}.")

    logger.info("Loading DB entry for form_id='%s'.", form_id)

    engine = get_sync_engine()
    with Session(engine) as session:
        form = form_queries.get_form_by_id_sync(session, uuid.UUID(str(form_id)))
        if form is None:
            raise ValueError(f"form_id '{form_id}' not found in DB.")

        # ── Eagerly read all relationship data while session is open ─────────
        versions = sorted(list(form.versions), key=lambda v: v.version, reverse=True)
        if not versions:
            raise ValueError(f"DB form '{form_id}' has no version records.")
        latest = versions[0]

        # ── Extract all scalar values NOW — before session closes ────────────
        orig_uri = str(latest.file_path_original) if latest.file_path_original else None
        if not orig_uri:
            raise ValueError(f"DB form '{form_id}' missing file_path_original.")
        if not orig_uri.startswith("gs://"):
            raise ValueError(f"Expected GCS URI for file_path_original, got: {orig_uri}")

        already_has_es = bool(latest.file_path_es)
        already_has_pt = bool(latest.file_path_pt)
        existing_es_path = str(latest.file_path_es) if latest.file_path_es else None
        existing_pt_path = str(latest.file_path_pt) if latest.file_path_pt else None
        version_num = latest.version
        form_name = str(form.form_name)
        form_slug = str(form.form_slug) if form.form_slug else "form"
        file_type = str(form.file_type or "pdf").lower()
        preprocessing_flags = list(form.preprocessing_flags or [])

    # ── All ORM access is done — session is now closed ───────────────────────

    # Safety net: DOCX forms must be routed through docx_pipeline_dag, not here.
    # This guard fires before any work (download, OCR, translation) begins, so
    # the failure is immediate and the error message is actionable.
    # It protects against any future bypass of the routing logic in
    # form_scraper_dag.task_prepare_trigger_confs.
    if file_type == "docx":
        raise ValueError(
            f"form_id '{form_id}' has file_type='{file_type}' and must be processed by "
            "'docx_pipeline_dag', not 'form_pretranslation_dag'. "
            "Check task_prepare_trigger_confs routing logic in form_scraper_dag."
        )

    if already_has_es and already_has_pt:
        logger.info("Form '%s' already translated. Skipping.", form_id)
        context["ti"].xcom_push(key="form_meta", value={"skip": True, "form_id": form_id})
        return {"skip": True, "form_id": form_id}

    dag_run_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
    work_dir = Path(f"/tmp/courtaccess/form_pretranslation/{dag_run_id}")  # noqa: S108  # nosec B108
    work_dir.mkdir(parents=True, exist_ok=True)
    local_orig = str(work_dir / f"original.{file_type}")

    b, bl = gcs.parse_gcs_uri(orig_uri)
    gcs.download_file(b, bl, local_orig, correlation_id=form_id)

    slug_stem = form_slug
    out_dir = Path(local_orig).parent

    form_meta = {
        "form_id": form_id,
        "form_name": form_name,
        "form_slug": form_slug,
        "version": version_num,
        "original_gcs_uri": orig_uri,
        "original_path": local_orig,
        "output_es": str(out_dir / f"{slug_stem}_es.pdf"),
        "output_pt": str(out_dir / f"{slug_stem}_pt.pdf"),
        "skip": False,
        "already_has_es": already_has_es,
        "already_has_pt": already_has_pt,
        "existing_es_path": existing_es_path,
        "existing_pt_path": existing_pt_path,
        "is_mislabeled": "mislabeled" in str(preprocessing_flags),
    }

    logger.info(
        "Form loaded: '%s' (v%d) | original='%s' | output_es='%s' | output_pt='%s' | mislabeled=%s",
        form_meta["form_name"],
        form_meta["version"],
        form_meta["original_path"],
        form_meta["output_es"],
        form_meta["output_pt"],
        form_meta["is_mislabeled"],
    )
    context["ti"].xcom_push(key="form_meta", value=form_meta)
    return form_meta


# ══════════════════════════════════════════════════════════════════════════════
# Task 2 — ocr_extract_text
# ══════════════════════════════════════════════════════════════════════════════


def task_ocr_extract_text(**context) -> dict:
    """Extract text regions via OCREngine. Instance created per task run."""
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")

    if form_meta.get("skip"):
        logger.info("Skipping OCR — form already has translations.")
        ti.xcom_push(key="ocr_result", value={"regions": [], "full_text": ""})
        return {}

    engine = OCREngine().load()
    result = engine.extract_text_from_pdf(form_meta["original_path"])
    logger.info(
        "OCR complete: %d region(s), %d chars.",
        len(result["regions"]),
        len(result["full_text"]),
    )
    ti.xcom_push(key="ocr_result", value=result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 3 & 4 — translate_spanish / translate_portuguese
# ══════════════════════════════════════════════════════════════════════════════


def task_translate_spanish(**context) -> dict:
    """Translate OCR regions to Spanish. Translator instance created here."""
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        logger.info("Skipping Spanish translation — already exists.")
        ti.xcom_push(key="regions_es", value=[])
        return {}

    config = get_language_config("spanish")
    translator = Translator(config).load()
    try:
        regions_es = _translate_regions(ocr_result["regions"], LANG_ES, translator)
    finally:
        translator.unload()

    logger.info("Spanish translation complete: %d region(s).", len(regions_es))
    ti.xcom_push(key="regions_es", value=regions_es)
    return {"count": len(regions_es)}


def task_translate_portuguese(**context) -> dict:
    """Translate OCR regions to Portuguese. Translator instance created here."""
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        logger.info("Skipping Portuguese translation — already exists.")
        ti.xcom_push(key="regions_pt", value=[])
        return {}

    config = get_language_config("portuguese")
    translator = Translator(config).load()
    try:
        regions_pt = _translate_regions(ocr_result["regions"], LANG_PT, translator)
    finally:
        translator.unload()

    logger.info("Portuguese translation complete: %d region(s).", len(regions_pt))
    ti.xcom_push(key="regions_pt", value=regions_pt)
    return {"count": len(regions_pt)}


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 5 & 6 — legal_review_spanish / legal_review_portuguese
# ══════════════════════════════════════════════════════════════════════════════


def task_legal_review_spanish(**context) -> dict:
    """Legal review for Spanish. LegalReviewer instance created here."""
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")
    regions_es = ti.xcom_pull(task_ids="translate_spanish", key="regions_es")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        ti.xcom_push(
            key="legal_review_es",
            value={"status": "skipped_existing", "skipped": False},
        )
        return {}

    config = get_language_config("spanish")
    reviewer = LegalReviewer(config, glossary={})
    translated = "\n".join(r.get("translated_text", "") for r in (regions_es or []))
    review = _legal_review_with_retry(
        text=f"ORIGINAL:\n{ocr_result.get('full_text', '')}\n\nSPANISH:\n{translated}",
        reviewer=reviewer,
    )

    if review["skipped"]:
        logger.warning("Spanish legal review SKIPPED — form flagged for human review.")
    else:
        logger.info(
            "Spanish legal review: %d correction(s).",
            len(review.get("corrections", [])),
        )
    ti.xcom_push(key="legal_review_es", value=review)
    return review


def task_legal_review_portuguese(**context) -> dict:
    """Legal review for Portuguese. LegalReviewer instance created here."""
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")
    regions_pt = ti.xcom_pull(task_ids="translate_portuguese", key="regions_pt")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        ti.xcom_push(
            key="legal_review_pt",
            value={"status": "skipped_existing", "skipped": False},
        )
        return {}

    config = get_language_config("portuguese")
    reviewer = LegalReviewer(config, glossary={})
    translated = "\n".join(r.get("translated_text", "") for r in (regions_pt or []))
    review = _legal_review_with_retry(
        text=f"ORIGINAL:\n{ocr_result.get('full_text', '')}\n\nPORTUGUESE:\n{translated}",
        reviewer=reviewer,
    )

    if review["skipped"]:
        logger.warning("Portuguese legal review SKIPPED — form flagged for human review.")
    else:
        logger.info(
            "Portuguese legal review: %d correction(s).",
            len(review.get("corrections", [])),
        )
    ti.xcom_push(key="legal_review_pt", value=review)
    return review


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 7 & 8 — reconstruct_pdf_spanish / reconstruct_pdf_portuguese
# (unchanged — reconstruct_pdf is still a module-level function)
# ══════════════════════════════════════════════════════════════════════════════


def task_reconstruct_pdf_spanish(**context) -> dict:
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    regions_es = ti.xcom_pull(task_ids="translate_spanish", key="regions_es")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        logger.info("Skipping Spanish PDF reconstruction — already exists.")
        ti.xcom_push(key="path_es", value=None)
        return {}

    out_path = form_meta["output_es"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Reconstructing Spanish PDF → '%s'.", out_path)

    try:
        reconstruct_pdf(
            original_path=form_meta["original_path"],
            translated_regions=regions_es,
            output_path=out_path,
        )
    except ValueError as exc:
        logger.warning("Spanish PDF reconstruction skipped — not a valid PDF: %s.", exc)
        ti.xcom_push(key="path_es", value=None)
        return {"path_es": None, "skipped": True}

    logger.info("Spanish PDF saved.")
    ti.xcom_push(key="path_es", value=out_path)
    return {"path_es": out_path}


def task_reconstruct_pdf_portuguese(**context) -> dict:
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    regions_pt = ti.xcom_pull(task_ids="translate_portuguese", key="regions_pt")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        logger.info("Skipping Portuguese PDF reconstruction — already exists.")
        ti.xcom_push(key="path_pt", value=None)
        return {}

    out_path = form_meta["output_pt"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Reconstructing Portuguese PDF → '%s'.", out_path)

    try:
        reconstruct_pdf(
            original_path=form_meta["original_path"],
            translated_regions=regions_pt,
            output_path=out_path,
        )
    except ValueError as exc:
        logger.warning("Portuguese PDF reconstruction skipped — not a valid PDF: %s.", exc)
        ti.xcom_push(key="path_pt", value=None)
        return {"path_pt": None, "skipped": True}

    logger.info("Portuguese PDF saved.")
    ti.xcom_push(key="path_pt", value=out_path)
    return {"path_pt": out_path}


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 9-10 — store, summary
# ══════════════════════════════════════════════════════════════════════════════


def task_store_and_update_catalog(**context) -> dict:
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    path_es = ti.xcom_pull(task_ids="reconstruct_pdf_spanish", key="path_es")
    path_pt = ti.xcom_pull(task_ids="reconstruct_pdf_portuguese", key="path_pt")
    review_es = ti.xcom_pull(task_ids="legal_review_spanish", key="legal_review_es")
    review_pt = ti.xcom_pull(task_ids="legal_review_portuguese", key="legal_review_pt")

    if form_meta.get("skip"):
        logger.info("Skipping catalog update — form already fully translated.")
        return {}

    form_id = form_meta["form_id"]
    now = datetime.utcnow().isoformat() + "Z"
    audit_notes = []

    if review_es and review_es.get("skipped"):
        audit_notes.append("Legal review skipped due to API failure (Spanish). Human review mandatory.")
    if review_pt and review_pt.get("skipped"):
        audit_notes.append("Legal review skipped due to API failure (Portuguese). Human review mandatory.")

    engine = get_sync_engine()
    form_uuid = uuid.UUID(str(form_id))
    es_uri = None
    pt_uri = None

    with Session(engine) as session:
        form = form_queries.get_form_by_id_sync(session, form_uuid)
        if form is None:
            raise ValueError(f"form_id '{form_id}' not found in DB during store.")

        # ── Eagerly read all relationship data while session is open ─────────
        versions = sorted(list(form.versions), key=lambda v: v.version, reverse=True)
        if not versions:
            raise ValueError(f"DB form '{form_id}' has no version records during store.")
        latest = versions[0]

        # ── Extract all scalars inside the session ───────────────────────────
        slug = form.form_slug or "form"
        vnum = latest.version
        existing_file_path_es = str(latest.file_path_es) if latest.file_path_es else None
        existing_file_path_pt = str(latest.file_path_pt) if latest.file_path_pt else None
        existing_file_type_es = latest.file_type_es
        existing_file_type_pt = latest.file_type_pt
        preprocessing_flags = list(form.preprocessing_flags or [])

        # Upload translated PDFs to GCS (if produced)
        if path_es:
            blob_es = f"forms/{slug}/v{vnum}/{slug}_es.pdf"
            gcs.upload_file(path_es, _GCS_BUCKET_FORMS, blob_es, correlation_id=form_id)
            es_uri = f"gs://{_GCS_BUCKET_FORMS}/{blob_es}"

        if path_pt:
            blob_pt = f"forms/{slug}/v{vnum}/{slug}_pt.pdf"
            gcs.upload_file(path_pt, _GCS_BUCKET_FORMS, blob_pt, correlation_id=form_id)
            pt_uri = f"gs://{_GCS_BUCKET_FORMS}/{blob_pt}"

        # Update DB version row with translated URIs (use extracted locals)
        form_queries.update_form_version_translations_sync(
            session,
            form_id=form_uuid,
            version=vnum,
            file_path_es=es_uri or existing_file_path_es,
            file_path_pt=pt_uri or existing_file_path_pt,
            file_type_es="pdf" if es_uri else existing_file_type_es,
            file_type_pt="pdf" if pt_uri else existing_file_type_pt,
        )

        # Update catalog fields: needs_human_review + preprocessing_flags
        if (
            (review_es and review_es.get("skipped")) or (review_pt and review_pt.get("skipped"))
        ) and "legal_review_skipped" not in preprocessing_flags:
            preprocessing_flags.append("legal_review_skipped")

        form_queries.update_form_catalog_fields_sync(
            session,
            form_uuid,
            needs_human_review=True,
            preprocessing_flags=preprocessing_flags,
        )

        session.commit()

    logger.info(
        "DB updated for '%s': ES=%s, PT=%s.",
        form_id,
        es_uri or form_meta.get("existing_es_path"),
        pt_uri or form_meta.get("existing_pt_path"),
    )
    for note in audit_notes:
        logger.warning("AUDIT: %s", note)

    # Audit log (system user) — never block pipeline on failure.
    try:
        with get_sync_engine().begin() as conn:
            write_audit_sync(
                conn,
                user_id=AIRFLOW_SYSTEM_USER_ID,
                action_type="form_pretranslation_completed",
                details={
                    "form_id": str(form_id),
                    "version": form_meta.get("version"),
                    "es_uri": es_uri,
                    "pt_uri": pt_uri,
                    "audit_notes": audit_notes,
                },
            )
    except Exception as exc:
        logger.warning("Audit write failed for form_pretranslation_completed: %s", exc)

    result = {
        "form_id": form_id,
        "es_uri": es_uri,
        "pt_uri": pt_uri,
        "updated_at": now,
        "audit_notes": audit_notes,
    }
    context["ti"].xcom_push(key="store_result", value=result)
    return result


def task_log_summary(**context) -> None:
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")
    review_es = ti.xcom_pull(task_ids="legal_review_spanish", key="legal_review_es")
    review_pt = ti.xcom_pull(task_ids="legal_review_portuguese", key="legal_review_pt")
    store_result = ti.xcom_pull(task_ids="store_and_update_catalog", key="store_result")

    if form_meta and form_meta.get("skip"):
        logger.info(
            "══ Form Pre-Translation Summary ══\n  form_id : %s\n  result  : SKIPPED",
            form_meta.get("form_id"),
        )
        return

    regions = len(ocr_result.get("regions", [])) if ocr_result else 0
    es_skip = review_es.get("skipped", True) if review_es else True
    pt_skip = review_pt.get("skipped", True) if review_pt else True
    es_corr = len(review_es.get("corrections", [])) if (review_es and not es_skip) else 0
    pt_corr = len(review_pt.get("corrections", [])) if (review_pt and not pt_skip) else 0

    logger.info(
        "══ Form Pre-Translation Summary ══\n"
        "  form_id           : %s\n  form_name         : %s\n"
        "  version           : %s\n  is_mislabeled     : %s\n"
        "  OCR regions       : %d\n"
        "  ES legal review   : %s (%d correction(s))\n"
        "  PT legal review   : %s (%d correction(s))\n"
        "  Spanish PDF       : %s\n  Portuguese PDF    : %s\n"
        "  languages_avail   : %s\n  needs_human_review: True\n"
        "  completed_at      : %s",
        form_meta.get("form_id") if form_meta else "unknown",
        form_meta.get("form_name") if form_meta else "unknown",
        form_meta.get("version") if form_meta else "unknown",
        form_meta.get("is_mislabeled") if form_meta else "unknown",
        regions,
        "SKIPPED" if es_skip else "OK",
        es_corr,
        "SKIPPED" if pt_skip else "OK",
        pt_corr,
        store_result.get("path_es") if store_result else "unknown",
        store_result.get("path_pt") if store_result else "unknown",
        store_result.get("langs") if store_result else "unknown",
        store_result.get("updated_at") if store_result else "unknown",
    )
    if store_result:
        for note in store_result.get("audit_notes", []):
            logger.warning("AUDIT NOTE: %s", note)


def task_cleanup_workdir(**context) -> None:
    """
    Final cleanup task — remove the per-run /tmp working directory.

    Runs with trigger_rule='all_done' so it executes whether upstream tasks
    succeeded, failed, or were skipped, preventing unbounded /tmp accumulation
    on long-running Airflow workers.
    """
    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta") or {}

    # Derive work_dir from form_meta or fall back to reconstructing from dag_run_id.
    original_path = form_meta.get("original_path")
    if original_path:
        work_dir = Path(original_path).parent
    else:
        dag_run_id = context["dag_run"].run_id if context.get("dag_run") else "manual"
        work_dir = Path(f"/tmp/courtaccess/form_pretranslation/{dag_run_id}")  # noqa: S108  # nosec B108

    if work_dir.exists():
        try:
            shutil.rmtree(work_dir)
            logger.info("Cleaned up work directory: %s", work_dir)
        except Exception as exc:
            logger.warning("Could not remove work directory %s: %s", work_dir, exc)
    else:
        logger.debug("Work directory already absent (skip=True path?): %s", work_dir)


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition
# ══════════════════════════════════════════════════════════════════════════════

with DAG(
    dag_id="form_pretranslation_dag",
    description=(
        "Triggered by form_scraper_dag (Scenarios A & B). "
        "Extracts text, translates to ES+PT, validates legal terms, "
        "reconstructs PDFs, and updates the form catalog."
    ),
    schedule=None,
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=2,
    tags=["courtaccess", "forms", "translation", "ocr"],
) as dag:
    t1_load = PythonOperator(task_id="load_form_entry", python_callable=task_load_form_entry)
    t2_ocr = PythonOperator(task_id="ocr_extract_text", python_callable=task_ocr_extract_text, pool=GPU_POOL_NAME)
    t3_es = PythonOperator(task_id="translate_spanish", python_callable=task_translate_spanish, pool=GPU_POOL_NAME)
    t4_pt = PythonOperator(
        task_id="translate_portuguese", python_callable=task_translate_portuguese, pool=GPU_POOL_NAME
    )
    t5_rev_es = PythonOperator(task_id="legal_review_spanish", python_callable=task_legal_review_spanish)
    t6_rev_pt = PythonOperator(task_id="legal_review_portuguese", python_callable=task_legal_review_portuguese)
    t7_rec_es = PythonOperator(task_id="reconstruct_pdf_spanish", python_callable=task_reconstruct_pdf_spanish)
    t8_rec_pt = PythonOperator(task_id="reconstruct_pdf_portuguese", python_callable=task_reconstruct_pdf_portuguese)
    t9_store = PythonOperator(task_id="store_and_update_catalog", python_callable=task_store_and_update_catalog)
    t10_sum = PythonOperator(task_id="log_summary", python_callable=task_log_summary)
    t11_cleanup = PythonOperator(
        task_id="cleanup_workdir",
        python_callable=task_cleanup_workdir,
        # 'all_done' ensures cleanup runs whether upstream tasks succeeded,
        # failed, or were skipped — preventing /tmp accumulation on errors.
        trigger_rule="all_done",
    )

    t1_load >> t2_ocr
    # Sequential: ES pipeline completes fully before PT starts.
    # In real mode each language loads ~3.2 GB (spaCy + NLLB);
    # running them serially halves peak memory per DAG run.
    t2_ocr >> t3_es >> t5_rev_es >> t7_rec_es
    t7_rec_es >> t4_pt >> t6_rev_pt >> t8_rec_pt
    t8_rec_pt >> t9_store >> t10_sum >> t11_cleanup
