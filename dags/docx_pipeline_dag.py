"""
dags/docx_pipeline_dag.py

Production Airflow DAG — docx_pipeline_dag

Thin pipeline for DOCX document translation:
    validate_upload → translate_docx → upload_to_gcs → finalize → log_summary

Five tasks instead of nine (vs document_pipeline_dag):
  - No classify_document  — classification already happened at upload time in the API
  - No ocr_printed_text   — DOCX text is already in the XML, no OCR needed
  - No legal_review       — called inside translate_docx as a single atomic operation
  - No reconstruct_pdf    — python-docx handles read + write in one step

One DAG run = one DOCX + one target language.

DB rows are created by POST /documents/upload before the DAG is triggered.
The DAG only ever UPDATEs — it never INSERTs.

Trigger conf (sent by POST /documents/upload):
    {
        "session_id":       "<uuid>",
        "request_id":       "<uuid>",
        "user_id":          "<uuid>",
        "gcs_input_path":   "gs://courtaccess-ai-uploads/<session_id>/<filename>.docx",
        "target_lang":      "es" | "pt",
        "nllb_target":      "spa_Latn" | "por_Latn",
        "filename":         "<filename>.docx",
        "start_time":       "<ISO-8601>",
        "original_format":  "docx"
    }

WORKER NOTE:
    All tasks share /tmp/courtaccess/{dag_run_id}/ on the same worker.
    Works with LocalExecutor (Docker Compose on GCE VM). If migrating to
    Cloud Composer, replace with GCS-backed intermediates.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.providers.standard.operators.python import PythonOperator
from sqlalchemy.orm import Session

from courtaccess.core import gcs
from db.database import get_sync_engine
from db.queries import forms as form_queries

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_GCS_BUCKET_UPLOADS = os.getenv("GCS_BUCKET_UPLOADS")
_GCS_BUCKET_TRANSLATED = os.getenv("GCS_BUCKET_TRANSLATED")
_GCS_BUCKET_FORMS = os.getenv("GCS_BUCKET_FORMS")  # catalog bucket (pretranslation path)
_SIGNED_URL_EXPIRY = int(os.getenv("SIGNED_URL_EXPIRY_SECONDS"))
_GCP_SA_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON")

# Strip +asyncpg — Airflow tasks run in sync processes, asyncpg is unusable here
_DB_URL = os.getenv("DATABASE_URL").replace("+asyncpg", "")
if not _DB_URL:
    raise RuntimeError(
        "DATABASE_URL is not set in the Airflow environment. Add it to &airflow-common-env in docker-compose.yml."
    )

_NLLB_TARGET = {"es": "spa_Latn", "pt": "por_Latn"}

DEFAULT_ARGS = {
    "owner": "courtaccess",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(seconds=60),
    "email_on_failure": False,
    "email_on_retry": False,
}


# ══════════════════════════════════════════════════════════════════════════════
# DB helpers
#
# All writes are fire-and-forget — a failed DB write must never abort the
# translation pipeline. Errors are logged and swallowed.
# ══════════════════════════════════════════════════════════════════════════════


def _engine():
    import sqlalchemy as sa

    return sa.create_engine(_DB_URL, pool_pre_ping=True)


def _update_session(session_id: str, status: str, **fields) -> None:
    """UPDATE sessions — valid statuses: active | processing | completed | failed | ended"""
    try:
        import sqlalchemy as sa

        vals = {"status": status, **fields}
        with _engine().begin() as c:
            query = "UPDATE sessions SET " + ", ".join(f"{k} = :{k}" for k in vals) + " WHERE session_id = :session_id"  # noqa: S608
            c.execute(sa.text(query), {**vals, "session_id": session_id})
    except Exception as exc:
        logger.error("[DB] update sessions failed (sid=%s): %s", session_id, exc)


def _update_request(request_id: str, **fields) -> None:
    """UPDATE document_translation_requests — valid statuses: processing | completed | failed | rejected"""
    try:
        import sqlalchemy as sa

        with _engine().begin() as c:
            # fmt: off
            query = "UPDATE document_translation_requests SET " + ", ".join(f"{k} = :{k}" for k in fields) + " WHERE doc_request_id = :doc_request_id"  # noqa: S608
            # fmt: on
            c.execute(sa.text(query), {**fields, "doc_request_id": request_id})
    except Exception as exc:
        logger.error("[DB] update document_translation_requests failed (rid=%s): %s", request_id, exc)


def _write_step(
    session_id: str,
    step_name: str,
    status: str,  # running | success | failed | skipped
    detail: str = "",
    metadata: dict | None = None,
) -> None:
    """Upsert a row in pipeline_steps. Polled by the frontend progress screen."""
    try:
        import sqlalchemy as sa

        with _engine().begin() as c:
            c.execute(
                sa.text("""
                    INSERT INTO pipeline_steps
                        (session_id, step_name, status, detail, metadata, updated_at)
                    VALUES
                        (:sid, :step, :status, :detail, :meta, :now)
                    ON CONFLICT (session_id, step_name) DO UPDATE SET
                        status     = EXCLUDED.status,
                        detail     = EXCLUDED.detail,
                        metadata   = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "sid": session_id,
                    "step": step_name,
                    "status": status,
                    "detail": detail,
                    "meta": json.dumps(metadata or {}),
                    "now": datetime.now(tz=UTC),
                },
            )
    except Exception as exc:
        logger.error("[DB] write pipeline_steps failed (%s/%s): %s", session_id, step_name, exc)


def _write_audit(user_id: str, session_id: str, request_id: str, action: str, details: dict) -> None:
    """INSERT into audit_logs (immutable — no upsert)."""
    try:
        import sqlalchemy as sa

        with _engine().begin() as c:
            c.execute(
                sa.text("""
                    INSERT INTO audit_logs
                        (audit_id, user_id, session_id, doc_request_id,
                         action_type, details, created_at)
                    VALUES
                        (:aid, :uid, :sid, :rid, :action, :details, :now)
                """),
                {
                    "aid": str(uuid.uuid4()),
                    "uid": user_id,
                    "sid": session_id,
                    "rid": request_id,
                    "action": action,
                    "details": json.dumps(details),
                    "now": datetime.now(tz=UTC),
                },
            )
    except Exception as exc:
        logger.error("[DB] write audit_logs failed (%s): %s", action, exc)


# ══════════════════════════════════════════════════════════════════════════════
# Language config factory
# ══════════════════════════════════════════════════════════════════════════════


def _lang_config(target_lang: str):
    from courtaccess.languages import get_language_config

    name = "spanish" if target_lang == "es" else "portuguese"
    return get_language_config(name)


# ══════════════════════════════════════════════════════════════════════════════
# DAG-level failure callback
# ══════════════════════════════════════════════════════════════════════════════


def _on_dag_failure(context) -> None:
    conf = (context.get("dag_run") or {}).conf or {}
    session_id = conf.get("session_id", "")
    request_id = conf.get("request_id", "")
    form_id = conf.get("form_id")
    task_id = getattr(context.get("task_instance"), "task_id", "unknown")
    msg = f"Pipeline failed at '{task_id}': {context.get('exception', 'unknown error')}"

    # Pretranslation runs (form_id set) have no sessions row — skip FK writes.
    if session_id and not form_id:
        _update_session(session_id, "failed")
        _write_step(session_id, task_id, "failed", msg)
    if request_id and not form_id:
        _update_request(request_id, status="failed", error_message=msg[:500])

    logger.error("[DAG FAILURE] session=%s task=%s: %s", session_id, task_id, msg)


# ══════════════════════════════════════════════════════════════════════════════
# Task 1 — validate_upload
# ══════════════════════════════════════════════════════════════════════════════


def task_validate_upload(**context) -> dict:
    """
    Download DOCX from GCS, verify PK ZIP magic bytes, mark session as 'processing'.
    XCom → upload_meta (small dict, pushed directly)
    """
    import re

    conf = context["dag_run"].conf or {}
    session_id = conf.get("session_id", str(uuid.uuid4()))
    request_id = conf.get("request_id", str(uuid.uuid4()))
    user_id = conf.get("user_id", "unknown")
    gcs_path = conf.get("gcs_input_path", "")
    target_lang = conf.get("target_lang", "es")
    nllb_target = conf.get("nllb_target", _NLLB_TARGET.get(target_lang, "spa_Latn"))

    # Sanitize filename to prevent path traversal
    raw_filename = conf.get("filename", "document.docx")
    safe_name = os.path.basename(raw_filename)
    safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", safe_name)
    if not safe_name or safe_name.startswith("."):
        safe_name = f"document_{uuid.uuid4().hex[:8]}.docx"
    filename = safe_name

    start_time = conf.get("start_time", datetime.now(tz=UTC).isoformat())
    original_format = conf.get("original_format", "docx")
    # form_id is set when triggered from form_scraper_dag (pretranslation path).
    # Those runs have no sessions/document_translation_requests rows, so any write
    # that touches pipeline_steps or sessions via FK will violate constraints.
    form_id = conf.get("form_id")

    if not form_id:
        _update_session(session_id, "processing")
        _write_step(session_id, "validate_upload", "running", "Downloading DOCX from GCS")

    # LocalExecutor on GCE VM: shared /tmp is fine. Switch to GCS-backed tmp if moving to Cloud Composer.
    work_dir = f"/tmp/courtaccess/{context['dag_run'].run_id}"  # noqa: S108 # nosec B108
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    local_docx = str(Path(work_dir) / filename)

    if gcs_path.startswith("gs://"):
        b, bl = gcs.parse_gcs_uri(gcs_path)
        gcs.download_file(b, bl, local_docx)
    else:
        local_docx = gcs_path  # dev/test: conf passes a local path directly

    if not Path(local_docx).exists():
        msg = f"File not found at {local_docx} after download"
        if not form_id:
            _write_step(session_id, "validate_upload", "failed", msg)
            _update_session(session_id, "failed")
            _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    # DOCX files are ZIP archives — check PK ZIP magic bytes
    with open(local_docx, "rb") as fh:
        magic = fh.read(4)
    if not magic.startswith(b"\x50\x4b\x03\x04"):
        msg = f"Not a valid DOCX (ZIP magic bytes missing, got {magic!r})"
        if not form_id:
            _write_step(session_id, "validate_upload", "failed", msg)
            _update_session(session_id, "failed")
            _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    size_mb = round(Path(local_docx).stat().st_size / 1_048_576, 2)
    if not form_id:
        _write_step(
            session_id,
            "validate_upload",
            "success",
            f"DOCX validated · {size_mb} MB · format={original_format}",
            {"size_mb": size_mb, "target_lang": target_lang, "original_format": original_format},
        )

    meta = {
        "session_id": session_id,
        "request_id": request_id,
        "user_id": user_id,
        "local_docx": local_docx,
        "gcs_input_path": gcs_path,
        "target_lang": target_lang,
        "nllb_target": nllb_target,
        "work_dir": work_dir,
        "filename": filename,
        "start_time": start_time,
        "original_format": original_format,
        "form_id": form_id,
    }
    context["ti"].xcom_push(key="upload_meta", value=meta)
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# Task 2 — translate_docx
# ══════════════════════════════════════════════════════════════════════════════


def task_translate_docx(**context) -> dict:
    """
    Translate DOCX using courtaccess.core.docx_translation.translate_docx().
    NLLB + Llama verification in a single atomic step.
    XCom → translate_summary (small stats dict)
    XCom → output_path (str, path to translated DOCX)
    """
    from courtaccess.core.docx_translation import translate_docx
    from courtaccess.core.legal_review import LegalReviewer
    from courtaccess.core.translation import Translator

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    session_id = meta["session_id"]
    target_lang = meta["target_lang"]
    nllb_target = meta["nllb_target"]
    lang_label = "Spanish" if target_lang == "es" else "Portuguese"
    form_id = meta.get("form_id")

    if not form_id:
        _write_step(
            session_id,
            "translate_docx",
            "running",
            f"Translating DOCX to {lang_label} (NLLB + Llama verification)",
        )

    # Load language config, glossary, translator, reviewer — same pattern as PDF DAG
    config = _lang_config(target_lang)

    translator = Translator(config).load()

    _glossary_path = Path("/opt/airflow") / config.glossary_path
    _glossary = json.loads(_glossary_path.read_text()) if _glossary_path.exists() else {}
    reviewer = LegalReviewer(config, glossary=_glossary, verification_mode="document")

    output_path = str(Path(meta["work_dir"]) / f"output_{target_lang}.docx")

    summary = translate_docx(
        input_path=meta["local_docx"],
        output_path=output_path,
        translator=translator,
        reviewer=reviewer,
        nllb_target=nllb_target,
    )

    # Copy output to mounted data dir for inspection (dev only)
    if os.getenv("APP_ENV") == "development":
        shutil.copy2(output_path, f"/opt/airflow/data/output_{target_lang}.docx")

    size_mb = round(Path(output_path).stat().st_size / 1_048_576, 2)
    if not form_id:
        _write_step(
            session_id,
            "translate_docx",
            "success",
            f"{summary['translated_runs']}/{summary['total_runs']} runs translated · "
            f"{summary['llama_corrections_count']} Llama correction(s) · "
            f"{summary['elapsed_seconds']}s · {size_mb} MB",
            {
                **summary,
                "output_size_mb": size_mb,
            },
        )

    ti.xcom_push(key="output_path", value=output_path)
    ti.xcom_push(key="translate_summary", value=summary)
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Task 3 — upload_to_gcs
# ══════════════════════════════════════════════════════════════════════════════


def task_upload_to_gcs(**context) -> dict:
    """
    Upload translated DOCX to GCS and push ``gcs_result`` XCom.

    Two paths, selected by whether ``form_id`` is in the trigger conf:

    **User-upload path** (no form_id):
        Uploads to ``GCS_BUCKET_TRANSLATED/{session_id}/output_{lang}.docx``.
        Generates a signed URL and writes it to ``document_translation_requests``
        so the frontend can poll for a download link.

    **Pretranslation path** (form_id present):
        Uploads to ``GCS_BUCKET_FORMS/forms/{slug}/v{version}/{slug}_{lang}.docx``
        — the same canonical path used by all catalog forms.
        Signed URL and ``_update_request`` are skipped (no user-facing request row
        exists for a catalog form; ``task_finalize`` handles the DB catalog update).

    XCom → gcs_result (always pushed, same key in both paths)
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    output_path = ti.xcom_pull(task_ids="translate_docx", key="output_path")
    session_id = meta["session_id"]
    request_id = meta["request_id"]
    target_lang = meta["target_lang"]

    conf = context["dag_run"].conf or {}
    form_id = conf.get("form_id")

    if form_id:
        # ── Pretranslation path: upload to the catalog bucket ───────────────────
        # Resolve slug + version from DB to build the canonical GCS path.
        try:
            form_uuid = uuid.UUID(str(form_id))
            engine = get_sync_engine()
            with Session(engine) as orm_session:
                form = form_queries.get_form_by_id_sync(orm_session, form_uuid)
                if form is None:
                    raise ValueError(f"form_id '{form_id}' not found in DB.")
                versions = sorted(list(form.versions), key=lambda v: v.version, reverse=True)
                if not versions:
                    raise ValueError(f"form_id '{form_id}' has no version records.")
                slug = str(form.form_slug or "form")
                vnum = versions[0].version
        except Exception as exc:
            raise RuntimeError(
                f"task_upload_to_gcs: could not resolve slug/version for form_id='{form_id}': {exc}"
            ) from exc

        blob = f"forms/{slug}/v{vnum}/{slug}_{target_lang}.docx"
        gcs_uri_str = f"gs://{_GCS_BUCKET_FORMS}/{blob}"

        b, bl = gcs.parse_gcs_uri(gcs_uri_str)
        gcs.upload_file(output_path, b, bl)
        logger.info("Catalog DOCX uploaded: %s (%s)", gcs_uri_str, target_lang.upper())

        result = {"gcs_uri": gcs_uri_str, "signed_url": None, "signed_url_expires_at": None}
    else:
        # ── User-upload path: existing logic ────────────────────────────────────
        gcs_uri_str = f"gs://{_GCS_BUCKET_TRANSLATED}/{session_id}/output_{target_lang}.docx"

        _write_step(session_id, "upload_to_gcs", "running", f"Uploading to {gcs_uri_str}")
        b, bl = gcs.parse_gcs_uri(gcs_uri_str)
        gcs.upload_file(output_path, b, bl)

        signed_url = gcs.generate_signed_url(b, bl, _SIGNED_URL_EXPIRY, _GCP_SA_JSON)
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=_SIGNED_URL_EXPIRY)

        # Write URL immediately — don`t wait for finalize
        _update_request(
            request_id,
            output_file_gcs_path=gcs_uri_str,
            signed_url=signed_url,
            signed_url_expires_at=expires_at,
        )
        _write_step(
            session_id,
            "upload_to_gcs",
            "success",
            f"Uploaded · signed URL expires in {_SIGNED_URL_EXPIRY // 60} min",
            {"gcs_uri": gcs_uri_str},
        )

        result = {
            "gcs_uri": gcs_uri_str,
            "signed_url": signed_url,
            "signed_url_expires_at": expires_at.isoformat(),
        }

    ti.xcom_push(key="gcs_result", value=result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Task 4 — finalize
# ══════════════════════════════════════════════════════════════════════════════


def task_finalize(**context) -> dict:
    """
    Write final metrics to both tables.

    sessions:
        status       → 'completed'
        completed_at → now()

    translation_requests:
        status                  → 'completed'
        llama_corrections_count → from translate_docx summary
        processing_time_seconds → wall clock from start_time in conf
        completed_at            → now()

    If the trigger conf contains a ``form_id`` key (pretranslation path,
    triggered by form_scraper_dag), also update the form_versions catalog
    row with the translated DOCX URI so the catalog reflects both languages.
    The regular user-upload path has no form_id and is completely unaffected.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    translate_summary = ti.xcom_pull(task_ids="translate_docx", key="translate_summary") or {}
    session_id = meta["session_id"]
    request_id = meta["request_id"]
    target_lang = meta.get("target_lang", "es")

    # form_id is only present when triggered from form_scraper_dag (pretranslation path).
    conf = context["dag_run"].conf or {}
    form_id = conf.get("form_id")

    now = datetime.now(tz=UTC)
    try:
        start = datetime.fromisoformat(meta.get("start_time", now.isoformat()))
        processing_secs = round((now - start).total_seconds(), 1)
    except (ValueError, TypeError):
        processing_secs = None

    # Skip user-session / translation-request DB updates on the pretranslation
    # path — no sessions or document_translation_requests row was ever inserted
    # for a catalog form trigger, so running these UPDATEs would silently match
    # 0 rows and generate FK violation noise in the logs.
    if not form_id:
        _update_session(session_id, "completed", completed_at=now)
        _update_request(
            request_id,
            status="completed",
            llama_corrections_count=translate_summary.get("llama_corrections_count", 0),
            processing_time_seconds=processing_secs,
            completed_at=now,
        )

    # ── Optional catalog update (pretranslation path only) ──────────────────────
    # When form_id is set, record the translated DOCX URI in form_versions so
    # the catalog reflects the output (same role as task_store_and_update_catalog
    # in form_pretranslation_dag, but adapted for single-language DOCX runs).
    if form_id:
        gcs_result = ti.xcom_pull(task_ids="upload_to_gcs", key="gcs_result") or {}
        gcs_uri = gcs_result.get("gcs_uri", "")
        if gcs_uri:
            try:
                form_uuid = uuid.UUID(str(form_id))
                engine = get_sync_engine()
                with Session(engine) as orm_session:
                    form = form_queries.get_form_by_id_sync(orm_session, form_uuid)
                    if form is None:
                        logger.warning("Catalog update skipped: form_id='%s' not found in DB.", form_id)
                    else:
                        versions = sorted(list(form.versions), key=lambda v: v.version, reverse=True)
                        if not versions:
                            logger.warning(
                                "Catalog update skipped: form_id='%s' has no version records.",
                                form_id,
                            )
                        else:
                            latest_ver = versions[0]
                            vnum = latest_ver.version
                            # Read existing paths so we only overwrite the field
                            # for the language being produced in this run.
                            existing_es = str(latest_ver.file_path_es) if latest_ver.file_path_es else None
                            existing_pt = str(latest_ver.file_path_pt) if latest_ver.file_path_pt else None
                            existing_type_es = latest_ver.file_type_es
                            existing_type_pt = latest_ver.file_type_pt

                            form_queries.update_form_version_translations_sync(
                                orm_session,
                                form_id=form_uuid,
                                version=vnum,
                                file_path_es=gcs_uri if target_lang == "es" else existing_es,
                                file_path_pt=gcs_uri if target_lang == "pt" else existing_pt,
                                file_type_es="docx" if target_lang == "es" else existing_type_es,
                                file_type_pt="docx" if target_lang == "pt" else existing_type_pt,
                            )
                            orm_session.commit()
                            logger.info(
                                "Catalog updated: form_id=%s v%d lang=%s uri=%s",
                                form_id,
                                vnum,
                                target_lang,
                                gcs_uri,
                            )
            except Exception as exc:
                # Never let a catalog update failure abort pipeline finalization.
                logger.warning(
                    "Catalog update failed for form_id=%s lang=%s: %s",
                    form_id,
                    target_lang,
                    exc,
                    exc_info=True,
                )
        else:
            logger.warning("Catalog update skipped: no GCS URI in gcs_result for form_id=%s.", form_id)

    logger.info(
        "Finalized: session=%s lang=%s corrections=%d time=%.1fs",
        session_id,
        target_lang,
        translate_summary.get("llama_corrections_count", 0),
        processing_secs or 0,
    )
    return {"finalized": True, "processing_time_seconds": processing_secs}


# ══════════════════════════════════════════════════════════════════════════════
# Task 5 — log_summary
# ══════════════════════════════════════════════════════════════════════════════


def task_log_summary(**context) -> None:
    """
    Write audit log entry, clean up local work directory.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta") or {}
    translate_summary = ti.xcom_pull(task_ids="translate_docx", key="translate_summary") or {}
    gcs_result = ti.xcom_pull(task_ids="upload_to_gcs", key="gcs_result") or {}
    session_id = meta.get("session_id", "unknown")

    logger.info(
        "══ DOCX Pipeline Summary ══\n"
        "  session_id          : %s\n"
        "  target_lang         : %s\n"
        "  total_runs          : %d\n"
        "  translated_runs     : %d\n"
        "  fill_suffixes       : %d\n"
        "  llama_corrections   : %d\n"
        "  output_gcs_uri      : %s",
        session_id,
        meta.get("target_lang", "unknown"),
        translate_summary.get("total_runs", 0),
        translate_summary.get("translated_runs", 0),
        translate_summary.get("fill_suffixes_found", 0),
        translate_summary.get("llama_corrections_count", 0),
        gcs_result.get("gcs_uri", "unknown"),
    )

    form_id = meta.get("form_id")
    if not form_id:
        _write_step(
            session_id,
            "log_summary",
            "success",
            f"Pipeline complete — {meta.get('target_lang', '').upper()} DOCX translation ready",
        )
        _write_audit(
            user_id=meta.get("user_id", ""),
            session_id=session_id,
            request_id=meta.get("request_id", ""),
            action="docx_pipeline_completed",
            details={
                "target_lang": meta.get("target_lang"),
                "total_runs": translate_summary.get("total_runs", 0),
                "translated_runs": translate_summary.get("translated_runs", 0),
                "llama_corrections": translate_summary.get("llama_corrections_count", 0),
                "gcs_uri": gcs_result.get("gcs_uri", ""),
            },
        )

    work_dir = meta.get("work_dir", "")
    if work_dir and Path(work_dir).exists():
        try:
            shutil.rmtree(work_dir)
            logger.info("Cleaned up work dir: %s", work_dir)
        except Exception as exc:
            logger.warning("Could not clean up %s: %s", work_dir, exc)


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition
# ══════════════════════════════════════════════════════════════════════════════

with DAG(
    dag_id="docx_pipeline_dag",
    description=("DOCX document translation: validate → translate (NLLB + Llama) → GCS upload. One language per run."),
    schedule=None,
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    on_failure_callback=_on_dag_failure,
    render_template_as_native_obj=True,
    tags=["courtaccess", "documents", "docx", "translation"],
) as dag:
    t1 = PythonOperator(task_id="validate_upload", python_callable=task_validate_upload)
    t2 = PythonOperator(task_id="translate_docx", python_callable=task_translate_docx)
    t3 = PythonOperator(task_id="upload_to_gcs", python_callable=task_upload_to_gcs)
    t4 = PythonOperator(task_id="finalize", python_callable=task_finalize)
    t5 = PythonOperator(task_id="log_summary", python_callable=task_log_summary)

    t1 >> t2 >> t3 >> t4 >> t5
