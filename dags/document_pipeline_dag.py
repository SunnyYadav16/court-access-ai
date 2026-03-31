"""
dags/document_pipeline_dag.py

Production Airflow DAG — document_pipeline_dag

Matches the verified test pipeline exactly:
    classify_document → ocr_printed_text → translate
    → legal_review → reconstruct_pdf → upload_to_gcs
    → finalize → log_summary

One DAG run = one document + one target language.
The frontend triggers a second run for the other language
via the "Translate Now" button on the results page.

DB rows are created by POST /documents/upload before the DAG is triggered.
The DAG only ever UPDATEs — it never INSERTs.

Trigger conf (sent by POST /documents/upload):
    {
        "session_id":     "<uuid>",   — polling key for GET /documents/{session_id}
        "request_id":     "<uuid>",
        "user_id":        "<uuid>",
        "gcs_input_path": "gs://courtaccess-ai-uploads/<session_id>/<filename>.pdf",
        "target_lang":    "es" | "pt",
        "nllb_target":    "spa_Latn" | "por_Latn",
        "filename":       "<filename>.pdf",
        "start_time":     "<ISO-8601>"
    }

Heavy XCom (translated_regions / verified_regions — potentially thousands of
region dicts) is written to JSON files in work_dir and pushed as file paths,
keeping Airflow's metadata DB lean.

WORKER NOTE:
    All tasks share /tmp/courtaccess/{dag_run_id}/ on the same worker.
    Works with LocalExecutor (Docker Compose). For KubernetesExecutor (GKE /
    Cloud Composer) replace with GCS-backed intermediates — each task downloads
    what it needs at the start and uploads its output before exiting.
    Tag: TODO-GKE-WORKDIR
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.providers.standard.operators.python import PythonOperator

from courtaccess.core import gcs

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_GCS_BUCKET_UPLOADS = os.getenv("GCS_BUCKET_UPLOADS", "courtaccess-ai-uploads")
_GCS_BUCKET_TRANSLATED = os.getenv("GCS_BUCKET_TRANSLATED", "courtaccess-ai-translated")
_SIGNED_URL_EXPIRY = int(os.getenv("SIGNED_URL_EXPIRY_SECONDS", "3600"))
_GCP_SA_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")

# Strip +asyncpg — Airflow tasks run in sync processes, asyncpg is unusable here
_DB_URL = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
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


@functools.cache
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


def _get_request_status(request_id: str) -> str | None:
    """Return the current status of a translation_request row, or None on error."""
    try:
        import sqlalchemy as sa

        with _engine().begin() as c:
            row = c.execute(
                sa.text("SELECT status FROM translation_requests WHERE request_id = :rid"),
                {"rid": request_id},
            ).fetchone()
        return row[0] if row else None
    except Exception as exc:
        logger.error("[DB] _get_request_status failed (rid=%s): %s", request_id, exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Heavy XCom helpers
#
# translated_regions and verified_regions can be thousands of dicts.
# Writing them to Airflow's metadata DB via XCom would bloat it quickly.
# Write to JSON files in work_dir; push only the file path via XCom.
# ══════════════════════════════════════════════════════════════════════════════


def _dump(work_dir: str, key: str, data) -> str:
    path = str(Path(work_dir) / f"xcom_{key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# Language config factory
# ══════════════════════════════════════════════════════════════════════════════


def _lang_config(target_lang: str):
    from courtaccess.languages import get_language_config

    name = "spanish" if target_lang == "es" else "portuguese"
    return get_language_config(name)


# ══════════════════════════════════════════════════════════════════════════════
# DAG-level failure callback
# Sets both tables to failed/error state so the frontend stops polling.
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
        # Do not overwrite a 'rejected' status set by task_classify_document.
        # Read the current DB status first and only fall back to 'failed' when
        # the request has not already been given a terminal rejection state.
        current_status = _get_request_status(request_id)
        if current_status != "rejected":
            _update_request(request_id, status="failed", error_message=msg[:500])

    logger.error("[DAG FAILURE] session=%s task=%s: %s", session_id, task_id, msg)


# ══════════════════════════════════════════════════════════════════════════════
# Task 1 — validate_upload
# ══════════════════════════════════════════════════════════════════════════════


def task_validate_upload(**context) -> dict:
    """
    Download PDF from GCS, verify magic bytes, mark session as 'processing'.
    XCom → upload_meta (small dict, pushed directly)
    """
    conf = context["dag_run"].conf or {}

    # session_id and request_id MUST be provided by POST /documents/upload.
    # Falling back to a random UUID would silently write to non-existent DB rows.
    session_id = conf.get("session_id")
    request_id = conf.get("request_id")
    for key, val in (("session_id", session_id), ("request_id", request_id)):
        if not val:
            raise AirflowFailException(
                f"DAG conf is missing required key '{key}'. "
                "This DAG must be triggered by POST /documents/upload, not manually without conf."
            )
    user_id = conf.get("user_id", "unknown")
    gcs_path = conf.get("gcs_input_path", "")
    target_lang = conf.get("target_lang", "es")
    nllb_target = conf.get("nllb_target", _NLLB_TARGET.get(target_lang, "spa_Latn"))
    _raw_filename = conf.get("filename", "document.pdf")
    # Sanitize: strip directory components first (guards against absolute paths
    # and ../ traversal injected via conf), then remove any character that isn't
    # alphanumeric, underscore, hyphen, or dot — same policy as the upload route.
    _safe_filename = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", Path(_raw_filename).name)
    filename = _safe_filename if _safe_filename and not _safe_filename.startswith(".") else "document.pdf"
    start_time = conf.get("start_time", datetime.now(tz=UTC).isoformat())

    _update_session(session_id, "processing")
    _write_step(session_id, "validate_upload", "running", "Downloading from GCS")

    # TODO-GKE-WORKDIR: replace with GCS-backed tmp for KubernetesExecutor
    work_dir = f"/tmp/courtaccess/{context['dag_run'].run_id}"  # noqa: S108 # nosec B108
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    local_pdf = str(Path(work_dir) / filename)

    if gcs_path.startswith("gs://"):
        b, bl = gcs.parse_gcs_uri(gcs_path)
        gcs.download_file(b, bl, local_pdf)
    else:
        local_pdf = gcs_path  # dev/test: conf passes a local path directly

    if not Path(local_pdf).exists():
        msg = f"File not found at {local_pdf} after download"
        _write_step(session_id, "validate_upload", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    with open(local_pdf, "rb") as fh:
        magic = fh.read(5)
    if not magic.startswith(b"%PDF-"):
        msg = f"Not a valid PDF (magic={magic!r})"
        _write_step(session_id, "validate_upload", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg)

    size_mb = round(Path(local_pdf).stat().st_size / 1_048_576, 2)
    _write_step(
        session_id,
        "validate_upload",
        "success",
        f"PDF validated · {size_mb} MB",
        {"size_mb": size_mb, "target_lang": target_lang},
    )

    meta = {
        "session_id": session_id,
        "request_id": request_id,
        "user_id": user_id,
        "local_pdf": local_pdf,
        "gcs_input_path": gcs_path,
        "target_lang": target_lang,
        "nllb_target": nllb_target,
        "work_dir": work_dir,
        "filename": filename,
        "start_time": start_time,
    }
    context["ti"].xcom_push(key="upload_meta", value=meta)
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# Task 2 — classify_document
# ══════════════════════════════════════════════════════════════════════════════


def task_classify_document(**context) -> dict:
    """
    Classify PDF as legal or non-legal via Llama 4 (Vertex AI).
    Non-legal → hard fail, status set to 'rejected'.
    Writes classification_result to translation_requests.
    XCom → classification
    """
    from courtaccess.core.classify_document import ClassificationError, classify_document

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    session_id = meta["session_id"]
    request_id = meta["request_id"]

    _write_step(session_id, "classify_document", "running", "Analysing document type")

    try:
        result = classify_document(meta["local_pdf"])
    except ClassificationError as exc:
        msg = f"Classifier error: {exc}"
        _write_step(session_id, "classify_document", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="failed", error_message=msg)
        raise AirflowFailException(msg) from exc

    # Write classification result regardless of outcome
    _update_request(
        request_id,
        classification_result="LEGAL" if result["classification"] == "legal" else "NOT_LEGAL",
    )

    if result["classification"] != "legal":
        msg = f"Rejected: non-legal document (confidence={result['confidence']:.2f}, reason={result.get('reason', '')})"
        _write_step(session_id, "classify_document", "failed", msg)
        _update_session(session_id, "failed")
        _update_request(request_id, status="rejected", error_message=msg)
        raise AirflowFailException(msg)

    _write_step(
        session_id,
        "classify_document",
        "success",
        f"LEGAL · confidence={result['confidence']:.2f} · {result.get('reason', '')}",
        result,
    )
    ti.xcom_push(key="classification", value=result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Task 3 — ocr_printed_text
# ══════════════════════════════════════════════════════════════════════════════


def task_ocr_printed_text(**context) -> dict:
    """
    Extract text regions via OCREngine.extract_text_from_pdf().

    Page routing (inside OCREngine):
        DIGITAL → PyMuPDF _get_block_units (vector text + full layout metadata)
        SCANNED → PaddleOCR → Tesseract → PyMuPDF (fallback chain)
        BLANK   → skipped

    Heavy payload (regions list) → xcom_regions.json
    XCom → regions_path   (str, path to JSON)
    XCom → ocr_summary    (small stats dict, pushed directly)
    """
    from courtaccess.core.ocr_printed import OCREngine

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    session_id = meta["session_id"]

    _write_step(session_id, "ocr_printed_text", "running", "Extracting text regions")

    engine = OCREngine().load()
    result = engine.extract_text_from_pdf(meta["local_pdf"])
    regions = result["regions"]

    total = len(regions)
    translatable = sum(1 for r in regions if not r.get("preserve", False))
    preserved = total - translatable
    avg_conf = sum(r.get("confidence", 1.0) for r in regions) / max(total, 1)
    engine_label = "PaddleOCR" if os.getenv("USE_REAL_OCR", "false").lower() == "true" else "PyMuPDF"

    _write_step(
        session_id,
        "ocr_printed_text",
        "success",
        f"{engine_label}: {total} regions · {translatable} translatable · avg {avg_conf:.2f} conf",
        {
            "total_regions": total,
            "translatable": translatable,
            "preserved": preserved,
            "avg_confidence": round(avg_conf, 3),
            "engine": engine_label,
        },
    )

    regions_path = _dump(meta["work_dir"], "regions", regions)
    summary = {
        "total_regions": total,
        "translatable": translatable,
        "avg_confidence": round(avg_conf, 3),
        "full_text": result["full_text"],
    }
    ti.xcom_push(key="regions_path", value=regions_path)
    ti.xcom_push(key="ocr_summary", value=summary)
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Task 4 — translate
# ══════════════════════════════════════════════════════════════════════════════


def task_translate(**context) -> dict:
    """
    Translate all non-preserved regions via NLLB-200 batch_translate().

    Matches test script exactly:
        texts    = [r['text'] for r in translatable_regions]
        nllb_out = translator.batch_translate(texts, nllb_target)

    preserve=True regions carry original text as translated_text so
    reconstruct_pdf can reinsert them after redaction.

    Heavy payload → xcom_translated_regions.json
    XCom → translated_regions_path  (str)
    XCom → translate_summary        (small stats dict)
    """
    from courtaccess.core.translation import Translator

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    regions_path = ti.xcom_pull(task_ids="ocr_printed_text", key="regions_path")
    session_id = meta["session_id"]
    target_lang = meta["target_lang"]
    nllb_target = meta["nllb_target"]
    lang_label = "Spanish" if target_lang == "es" else "Portuguese"

    regions = _load(regions_path)
    translatable = [r for r in regions if not r.get("preserve", False) and r.get("text", "").strip()]

    _write_step(
        session_id,
        "translate",
        "running",
        f"NLLB-200: translating {len(translatable)} regions to {lang_label}",
        {"total_regions": len(translatable), "target_lang": target_lang},
    )

    config = _lang_config(target_lang)
    translator = Translator(config).load()
    texts = [r["text"] for r in translatable]

    t0 = time.time()
    nllb_out = translator.batch_translate(texts, nllb_target)
    elapsed = round(time.time() - t0, 1)

    # Count regions where NLLB actually changed the text (same logic as test script)
    nllb_changed = sum(1 for o, n in zip(texts, nllb_out, strict=False) if o != n)

    # Build lookup: original text → translated text
    text_to_trans = dict(zip(texts, nllb_out, strict=False))

    # Enrich every region with translated_text
    translated_regions = []
    for region in regions:
        if region.get("preserve", False) or not region.get("text", "").strip():
            translated_regions.append({**region, "translated_text": region.get("text", "")})
        else:
            translated_regions.append(
                {
                    **region,
                    "translated_text": text_to_trans.get(region["text"], region["text"]),
                }
            )

    _write_step(
        session_id,
        "translate",
        "success",
        f"NLLB-200: {nllb_changed}/{len(translatable)} regions changed in {elapsed}s",
        {"regions_changed": nllb_changed, "total_sent": len(translatable), "elapsed_seconds": elapsed},
    )

    path = _dump(meta["work_dir"], "translated_regions", translated_regions)
    summary = {"regions_translated": nllb_changed, "total_sent": len(translatable), "elapsed_seconds": elapsed}
    ti.xcom_push(key="translated_regions_path", value=path)
    ti.xcom_push(key="translate_summary", value=summary)
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Task 5 — legal_review
# ══════════════════════════════════════════════════════════════════════════════


def task_legal_review(**context) -> dict:
    """
    Verify translated legal terminology via LegalReviewer.verify_batch()
    (Llama 4, Vertex AI, Redis-cached).

    Matches test script exactly:
        verified = reviewer.verify_batch(texts, nllb_out, batch_size=16)

    Only non-preserved regions are sent to Llama. Corrections merged back.
    Falls back gracefully: if Vertex unavailable, NLLB output returned unchanged.

    Heavy payload → xcom_verified_regions.json
    XCom → verified_regions_path  (str)
    XCom → legal_summary          (small stats dict)
    """
    from courtaccess.core.legal_review import LegalReviewer

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    translated_regions_path = ti.xcom_pull(task_ids="translate", key="translated_regions_path")
    session_id = meta["session_id"]
    target_lang = meta["target_lang"]
    lang_label = "Spanish" if target_lang == "es" else "Portuguese"

    translated_regions = _load(translated_regions_path)

    # Only non-preserved regions go to Llama — matches test script
    reviewable = [r for r in translated_regions if not r.get("preserve", False)]
    orig_texts = [r.get("text", "") for r in reviewable]
    trans_texts = [r.get("translated_text", "") for r in reviewable]

    _write_step(
        session_id,
        "legal_review",
        "running",
        f"Llama: verifying {len(reviewable)} spans in {lang_label}",
    )

    config = _lang_config(target_lang)
    import json
    from pathlib import Path

    _glossary_path = Path("/opt/airflow") / config.glossary_path
    _glossary = json.loads(_glossary_path.read_text()) if _glossary_path.exists() else {}
    reviewer = LegalReviewer(config, glossary=_glossary, verification_mode="document")

    t0 = time.time()
    verified_texts = reviewer.verify_batch(orig_texts, trans_texts, batch_size=16)
    elapsed = round(time.time() - t0, 1)

    corrections = sum(1 for t, v in zip(trans_texts, verified_texts, strict=False) if t != v)
    not_verified = sum(1 for v in verified_texts if v.startswith("[NOT VERIFIED"))

    # Merge verified texts back into the full region list
    verified_iter = iter(verified_texts)
    verified_regions = []
    for region in translated_regions:
        if region.get("preserve", False):
            verified_regions.append(region)
        else:
            verified_regions.append({**region, "translated_text": next(verified_iter)})

    _write_step(
        session_id,
        "legal_review",
        "success",
        f"Llama: {corrections} correction(s) on {len(reviewable)} spans in {elapsed}s"
        + (f" · {not_verified} NOT VERIFIED (Vertex unavailable)" if not_verified else ""),
        {
            "corrections_count": corrections,
            "spans_reviewed": len(reviewable),
            "not_verified": not_verified,
            "elapsed_seconds": elapsed,
        },
    )

    path = _dump(meta["work_dir"], "verified_regions", verified_regions)
    summary = {
        "status": "ok",
        "corrections_count": corrections,
        "not_verified": not_verified,
    }
    ti.xcom_push(key="verified_regions_path", value=path)
    ti.xcom_push(key="legal_summary", value=summary)
    return summary


# ══════════════════════════════════════════════════════════════════════════════
# Task 6 — reconstruct_pdf
# ══════════════════════════════════════════════════════════════════════════════


def task_reconstruct_pdf(**context) -> dict:
    """
    Rebuild PDF with translated text at original bounding boxes.

    Matches test script exactly:
        reconstruct_pdf(PDF_PATH, regions, OUTPUT_PATH)
        where each region has 'translated_text' set by legal_review.

    Phase 4: redact original text (DIGITAL=transparent fill, SCANNED=white)
    Phase 5: insert translated text via insert_htmlbox

    XCom → output_path  (str, local path to rebuilt PDF)
    """
    from courtaccess.core.reconstruct_pdf import reconstruct_pdf

    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    verified_regions_path = ti.xcom_pull(task_ids="legal_review", key="verified_regions_path")
    session_id = meta["session_id"]
    target_lang = meta["target_lang"]

    verified_regions = _load(verified_regions_path)
    output_path = str(Path(meta["work_dir"]) / f"output_{target_lang}.pdf")

    _write_step(session_id, "reconstruct_pdf", "running", "Rebuilding PDF with translated text")

    reconstruct_pdf(
        original_path=meta["local_pdf"],
        translated_regions=verified_regions,
        output_path=output_path,
    )

    # Copy output to mounted data dir for inspection (dev only)
    if os.getenv("APP_ENV", "development") == "development":
        shutil.copy2(output_path, f"/opt/airflow/data/output_{target_lang}.pdf")

    size_mb = round(Path(output_path).stat().st_size / 1_048_576, 2)
    _write_step(
        session_id,
        "reconstruct_pdf",
        "success",
        f"PDF rebuilt · {size_mb} MB",
        {"output_size_mb": size_mb},
    )
    ti.xcom_push(key="output_path", value=output_path)
    return {"output_path": output_path, "size_mb": size_mb}


# ══════════════════════════════════════════════════════════════════════════════
# Task 7 — upload_to_gcs
# ══════════════════════════════════════════════════════════════════════════════


def task_upload_to_gcs(**context) -> dict:
    """
    Upload reconstructed PDF to GCS and generate a signed URL.
    GCS path: gs://courtaccess-ai-translated/{session_id}/output_{lang}.pdf

    Writes output_file_gcs_path, signed_url, signed_url_expires_at to
    translation_requests immediately (so the URL is available even if
    finalize later fails for any reason).

    XCom → gcs_result
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    output_path = ti.xcom_pull(task_ids="reconstruct_pdf", key="output_path")
    session_id = meta["session_id"]
    request_id = meta["request_id"]
    target_lang = meta["target_lang"]

    gcs_uri_str = f"gs://{_GCS_BUCKET_TRANSLATED}/{session_id}/output_{target_lang}.pdf"

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
# Task 8 — finalize
# ══════════════════════════════════════════════════════════════════════════════


def task_finalize(**context) -> dict:
    """
    Write final metrics to both tables.

    sessions:
        status       → 'completed'
        completed_at → now()

    translation_requests:
        status                  → 'completed'
        avg_confidence_score    → from ocr_printed_text
        llama_corrections_count → from legal_review
        processing_time_seconds → wall clock from start_time in conf
        completed_at            → now()
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    ocr_summary = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_summary") or {}
    legal_summary = ti.xcom_pull(task_ids="legal_review", key="legal_summary") or {}
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
        avg_confidence_score=ocr_summary.get("avg_confidence"),
        llama_corrections_count=legal_summary.get("corrections_count", 0),
        processing_time_seconds=processing_secs,
        completed_at=now,
    )

    logger.info(
        "Finalized: session=%s lang=%s corrections=%d time=%.1fs",
        session_id,
        meta.get("target_lang"),
        legal_summary.get("corrections_count", 0),
        processing_secs or 0,
    )
    return {"finalized": True, "processing_time_seconds": processing_secs}


# ══════════════════════════════════════════════════════════════════════════════
# Task 9 — log_summary
# ══════════════════════════════════════════════════════════════════════════════


def task_log_summary(**context) -> None:
    """
    Write audit log entry, clean up local work directory.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta") or {}
    legal_summary = ti.xcom_pull(task_ids="legal_review", key="legal_summary") or {}
    gcs = ti.xcom_pull(task_ids="upload_to_gcs", key="gcs_result") or {}
    ocr_summary = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_summary") or {}
    session_id = meta.get("session_id", "unknown")

    logger.info(
        "══ Document Pipeline Summary ══\n"
        "  session_id        : %s\n"
        "  target_lang       : %s\n"
        "  regions_total     : %d\n"
        "  translatable      : %d\n"
        "  avg_confidence    : %.3f\n"
        "  llama_corrections : %d\n"
        "  output_gcs_uri    : %s",
        session_id,
        meta.get("target_lang", "unknown"),
        ocr_summary.get("total_regions", 0),
        ocr_summary.get("translatable", 0),
        ocr_summary.get("avg_confidence", 0.0),
        legal_summary.get("corrections_count", 0),
        gcs.get("gcs_uri", "unknown"),
    )

    _write_step(
        session_id,
        "log_summary",
        "success",
        f"Pipeline complete — {meta.get('target_lang', '').upper()} translation ready",
    )
    _write_audit(
        user_id=meta.get("user_id", ""),
        session_id=session_id,
        request_id=meta.get("request_id", ""),
        action="document_pipeline_completed",
        details={
            "target_lang": meta.get("target_lang"),
            "total_regions": ocr_summary.get("total_regions", 0),
            "avg_confidence": ocr_summary.get("avg_confidence", 0.0),
            "llama_corrections": legal_summary.get("corrections_count", 0),
            "gcs_uri": gcs.get("gcs_uri", ""),
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
    dag_id="document_pipeline_dag",
    description=(
        "Document translation: validate → classify → OCR → translate → "
        "legal review → reconstruct → GCS upload. One language per run."
    ),
    schedule=None,
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    on_failure_callback=_on_dag_failure,
    render_template_as_native_obj=True,
    tags=["courtaccess", "documents", "ocr", "translation", "legal-review"],
) as dag:
    t1 = PythonOperator(task_id="validate_upload", python_callable=task_validate_upload)
    t2 = PythonOperator(task_id="classify_document", python_callable=task_classify_document)
    t3 = PythonOperator(task_id="ocr_printed_text", python_callable=task_ocr_printed_text)
    t4 = PythonOperator(task_id="translate", python_callable=task_translate)
    t5 = PythonOperator(task_id="legal_review", python_callable=task_legal_review)
    t6 = PythonOperator(task_id="reconstruct_pdf", python_callable=task_reconstruct_pdf)
    t7 = PythonOperator(task_id="upload_to_gcs", python_callable=task_upload_to_gcs)
    t8 = PythonOperator(task_id="finalize", python_callable=task_finalize)
    t9 = PythonOperator(task_id="log_summary", python_callable=task_log_summary)

    t1 >> t2 >> t3 >> t4 >> t5 >> t6 >> t7 >> t8 >> t9
