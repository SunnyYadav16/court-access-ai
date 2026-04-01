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
    Works with LocalExecutor (Docker Compose). For KubernetesExecutor
    replace with GCS-backed intermediates.
    Tag: TODO-GKE-WORKDIR
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

from courtaccess.core import gcs

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_GCS_BUCKET_UPLOADS = os.getenv("GCS_BUCKET_UPLOADS")
_GCS_BUCKET_TRANSLATED = os.getenv("GCS_BUCKET_TRANSLATED")
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
    """UPDATE translation_requests — valid statuses: processing | completed | failed | rejected"""
    try:
        import sqlalchemy as sa

        with _engine().begin() as c:
            # fmt: off
            query = "UPDATE translation_requests SET " + ", ".join(f"{k} = :{k}" for k in fields) + " WHERE request_id = :request_id"  # noqa: S608
            # fmt: on
            c.execute(sa.text(query), {**fields, "request_id": request_id})
    except Exception as exc:
        logger.error("[DB] update translation_requests failed (rid=%s): %s", request_id, exc)


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
                        (audit_id, user_id, session_id, request_id,
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
    task_id = getattr(context.get("task_instance"), "task_id", "unknown")
    msg = f"Pipeline failed at '{task_id}': {context.get('exception', 'unknown error')}"

    if session_id:
        _update_session(session_id, "failed")
        _write_step(session_id, task_id, "failed", msg)
    if request_id:
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
    conf = context["dag_run"].conf or {}
    session_id = conf.get("session_id", str(uuid.uuid4()))
    request_id = conf.get("request_id", str(uuid.uuid4()))
    user_id = conf.get("user_id", "unknown")
    gcs_path = conf.get("gcs_input_path", "")
    target_lang = conf.get("target_lang", "es")
    nllb_target = conf.get("nllb_target", _NLLB_TARGET.get(target_lang, "spa_Latn"))
    filename = conf.get("filename", "document.docx")
    start_time = conf.get("start_time", datetime.now(tz=UTC).isoformat())
    original_format = conf.get("original_format", "docx")

    _update_session(session_id, "processing")
    _write_step(session_id, "validate_upload", "running", "Downloading DOCX from GCS")

    # TODO-GKE-WORKDIR: replace with GCS-backed tmp for KubernetesExecutor
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
        _write_step(session_id, "validate_upload", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    # DOCX files are ZIP archives — check PK ZIP magic bytes
    with open(local_docx, "rb") as fh:
        magic = fh.read(4)
    if not magic.startswith(b"\x50\x4b\x03\x04"):
        msg = f"Not a valid DOCX (ZIP magic bytes missing, got {magic!r})"
        _write_step(session_id, "validate_upload", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    size_mb = round(Path(local_docx).stat().st_size / 1_048_576, 2)
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
    Upload translated DOCX to GCS and generate a signed URL.
    GCS path: gs://courtaccess-ai-translated/{session_id}/output_{lang}.docx

    Writes output_file_gcs_path, signed_url, signed_url_expires_at to
    translation_requests immediately.

    XCom → gcs_result
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    output_path = ti.xcom_pull(task_ids="translate_docx", key="output_path")
    session_id = meta["session_id"]
    request_id = meta["request_id"]
    target_lang = meta["target_lang"]

    gcs_uri_str = f"gs://{_GCS_BUCKET_TRANSLATED}/{session_id}/output_{target_lang}.docx"

    _write_step(session_id, "upload_to_gcs", "running", f"Uploading to {gcs_uri_str}")
    b, bl = gcs.parse_gcs_uri(gcs_uri_str)
    gcs.upload_file(output_path, b, bl)

    signed_url = gcs.generate_signed_url(b, bl, _SIGNED_URL_EXPIRY, _GCP_SA_JSON)
    expires_at = datetime.now(tz=UTC) + timedelta(seconds=_SIGNED_URL_EXPIRY)

    # Write URL immediately — don't wait for finalize
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
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    translate_summary = ti.xcom_pull(task_ids="translate_docx", key="translate_summary") or {}
    session_id = meta["session_id"]
    request_id = meta["request_id"]

    now = datetime.now(tz=UTC)
    try:
        start = datetime.fromisoformat(meta.get("start_time", now.isoformat()))
        processing_secs = round((now - start).total_seconds(), 1)
    except (ValueError, TypeError):
        processing_secs = None

    _update_session(session_id, "completed", completed_at=now)
    _update_request(
        request_id,
        status="completed",
        llama_corrections_count=translate_summary.get("llama_corrections_count", 0),
        processing_time_seconds=processing_secs,
        completed_at=now,
    )

    logger.info(
        "Finalized: session=%s lang=%s corrections=%d time=%.1fs",
        session_id,
        meta.get("target_lang"),
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
