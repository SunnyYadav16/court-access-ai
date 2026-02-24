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
             dvc_version_data
                       ▼
               log_summary

NOTE: This is a STUB implementation. OCR, translation, and legal review
use lightweight CPU-friendly methods. These tasks are clearly marked and
will be replaced with production models (PaddleOCR, NLLB-200, Groq/Llama)
before deployment. The DAG architecture, XCom contracts, and catalog update
logic are final.
"""

import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

# NOTE: These src imports follow the same pattern as form_scraper_dag.py.
# The modules live in dags/src/ and PYTHONPATH=/opt/airflow/dags is set
# in docker-compose.yml, so "from src.X import Y" works inside containers.
from src.ocr_printed import extract_text_from_pdf
from src.translate_text import translate_text
from src.legal_review import review_legal_terms
from src.reconstruct_pdf import reconstruct_pdf

logger = logging.getLogger(__name__)

# ── Paths (inside Docker container, mirrors scraper_dag conventions) ──────────
CATALOG_PATH = "/opt/airflow/dags/data/form_catalog.json"
FORMS_DIR    = "/opt/airflow/forms"
PROJECT_ROOT = "/opt/airflow"

# ── NLLB-200 language codes (used by both stub and real translation) ──────────
LANG_EN = "eng_Latn"
LANG_ES = "spa_Latn"
LANG_PT = "por_Latn"

# ── Groq/Llama retry settings ─────────────────────────────────────────────────
# Matches the retry behaviour described in CourtAccess_MLOps_Pipeline_Steps.md
GROQ_RETRY_DELAYS = [1, 3, 9]   # seconds — exponential backoff

# ── DAG default args (mirrors form_scraper_dag.py exactly) ───────────────────
DEFAULT_ARGS = {
    "owner":            "courtaccess",
    "depends_on_past":  False,
    "retries":          1,
    "retry_delay":      60,
    "email_on_failure": False,
    "email_on_retry":   False,
}


# ══════════════════════════════════════════════════════════════════════════════
# Catalog helpers  (mirrors the helper pattern in form_scraper_dag.py)
# ══════════════════════════════════════════════════════════════════════════════

def _load_catalog() -> list[dict]:
    p = Path(CATALOG_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Catalog not found at {CATALOG_PATH}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_catalog(catalog: list[dict]) -> None:
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def _find_entry(catalog: list[dict], form_id: str) -> tuple[int, dict]:
    """Return (index, entry) or raise ValueError."""
    for i, entry in enumerate(catalog):
        if entry.get("form_id") == form_id:
            return i, entry
    raise ValueError(f"form_id '{form_id}' not found in catalog.")


# ══════════════════════════════════════════════════════════════════════════════
# Legal review with retry
# ══════════════════════════════════════════════════════════════════════════════

def _legal_review_with_retry(text: str, lang: str) -> dict:
    """
    Call review_legal_terms() up to len(GROQ_RETRY_DELAYS) times.
    On total failure, returns a 'skipped' result so the pipeline continues
    and flags the form for mandatory human review (per spec in Step 8.8).

    NOTE: review_legal_terms() is a stub. In production it calls Groq/Llama.
    """
    last_err = None
    for attempt, delay in enumerate(GROQ_RETRY_DELAYS, start=1):
        try:
            result = review_legal_terms(text, lang)
            result["skipped"] = False
            logger.info("Legal review (%s) succeeded on attempt %d.", lang, attempt)
            return result
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Legal review (%s) attempt %d/%d failed: %s. "
                "Retrying in %ds.",
                lang, attempt, len(GROQ_RETRY_DELAYS), exc, delay,
            )
            if attempt < len(GROQ_RETRY_DELAYS):
                time.sleep(delay)

    logger.error(
        "Legal review (%s) failed after all retries. "
        "AUDIT: Legal review skipped due to Groq API failure. "
        "Human review is mandatory before removing the review flag. "
        "Last error: %s",
        lang, last_err,
    )
    return {
        "status":      "skipped",
        "corrections": [],
        "skipped":     True,
        "reason":      str(last_err),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Task 1 — load_form_entry
# ══════════════════════════════════════════════════════════════════════════════

def task_load_form_entry(**context) -> dict:
    """
    Read form_id from DAG trigger conf, locate the catalog entry, and
    validate that the original PDF exists on disk.

    Skips forms that already have both file_path_es and file_path_pt set —
    the scraper may have downloaded existing translations from mass.gov,
    so there is nothing for this DAG to do.

    Pushes 'form_meta' to XCom for all downstream tasks.
    """
    conf    = (context["dag_run"].conf or {})
    form_id = conf.get("form_id")
    if not form_id:
        raise ValueError(
            "DAG triggered without 'form_id' in conf. "
            "Expected conf={'form_id': '<uuid>'}."
        )

    logger.info("Loading catalog entry for form_id='%s'.", form_id)
    catalog = _load_catalog()
    _, entry = _find_entry(catalog, form_id)

    versions = entry.get("versions", [])
    if not versions:
        raise ValueError(f"Catalog entry '{form_id}' has no version records.")
    latest = versions[0]  # index 0 = most recent version

    orig_path = latest.get("file_path_original")
    if not orig_path:
        raise ValueError(f"Catalog entry '{form_id}' missing file_path_original.")
    if not Path(orig_path).exists():
        raise FileNotFoundError(
            f"Original PDF not found on disk: '{orig_path}'. "
            "The scraper may not have saved it yet."
        )

    # Check if translations already exist (scraper may have downloaded them)
    already_has_es = bool(latest.get("file_path_es"))
    already_has_pt = bool(latest.get("file_path_pt"))
    if already_has_es and already_has_pt:
        logger.info(
            "Form '%s' already has ES and PT translations from mass.gov. "
            "Skipping — nothing for this DAG to do.",
            form_id,
        )
        # Push a 'skip' flag so downstream tasks can exit gracefully
        context["ti"].xcom_push(key="form_meta", value={"skip": True, "form_id": form_id})
        return {"skip": True, "form_id": form_id}

    # Derive output paths following the catalog convention:
    # forms/{form_id}/v{version}/{slug}_es.pdf
    # forms/{form_id}/v{version}/{slug}_pt.pdf
    orig_p   = Path(orig_path)
    slug_stem = orig_p.stem   # e.g. "notice-of-appearance"
    out_dir   = orig_p.parent  # e.g. /opt/airflow/forms/{id}/v1/

    form_meta = {
        "form_id":       form_id,
        "form_name":     entry.get("form_name", ""),
        "form_slug":     entry.get("form_slug", ""),
        "version":       latest.get("version", 1),
        "original_path": orig_path,
        "output_es":     str(out_dir / f"{slug_stem}_es.pdf"),
        "output_pt":     str(out_dir / f"{slug_stem}_pt.pdf"),
        "skip":          False,
        # Record which translations already exist (partial case)
        "already_has_es": already_has_es,
        "already_has_pt": already_has_pt,
        "existing_es_path": latest.get("file_path_es"),  
        "existing_pt_path": latest.get("file_path_pt"),   
        # Flag mislabeled files so OCR can handle them gracefully
        "is_mislabeled": "mislabeled" in str(entry.get("preprocessing_flags", [])),
    }

    logger.info(
        "Form loaded: '%s' (v%d) | original='%s' | "
        "output_es='%s' | output_pt='%s' | mislabeled=%s",
        form_meta["form_name"], form_meta["version"],
        form_meta["original_path"],
        form_meta["output_es"], form_meta["output_pt"],
        form_meta["is_mislabeled"],
    )

    context["ti"].xcom_push(key="form_meta", value=form_meta)
    return form_meta


# ══════════════════════════════════════════════════════════════════════════════
# Task 2 — ocr_extract_text
# ══════════════════════════════════════════════════════════════════════════════

def task_ocr_extract_text(**context) -> dict:
    """
    Extract text regions from the original PDF.

    NOTE — STUB: uses PyMuPDF native text extraction (CPU, no GPU needed).
    In production this will be replaced with PaddleOCR v3 + Qwen2.5-VL
    (see src/ocr_printed.py for the swap point).

    Output contract (must be preserved when swapping to production OCR):
        {
            "regions": [
                {
                    "text":       str,
                    "bbox":       [x0, y0, x1, y1],   # PDF-space coordinates
                    "confidence": float,               # 0.0–1.0
                    "page":       int,
                    "font_size":  float,
                    "is_bold":    bool,
                }
            ],
            "full_text": str   # all region texts joined by newline
        }
    """
    ti        = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    if form_meta.get("skip"):
        logger.info("Skipping OCR — form already has translations.")
        ti.xcom_push(key="ocr_result", value={"regions": [], "full_text": ""})
        return {}

    logger.info(
        "Running OCR (STUB — PyMuPDF native) on '%s'.",
        form_meta["original_path"],
    )
    result = extract_text_from_pdf(form_meta["original_path"])
    logger.info(
        "OCR complete: %d region(s), %d chars.",
        len(result["regions"]), len(result["full_text"]),
    )
    ti.xcom_push(key="ocr_result", value=result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 3 & 4 — translate_spanish / translate_portuguese
# ══════════════════════════════════════════════════════════════════════════════

def _translate_regions(regions: list[dict], target_lang: str) -> list[dict]:
    """
    Translate each OCR region independently.
    NOTE — STUB: translate_text() prefixes text with a lang tag.
    In production swap translate_text() for NLLB-200 via CTranslate2.
    """
    out = []
    for region in regions:
        src = region.get("text", "").strip()
        if not src:
            out.append({**region, "translated_text": "", "translation_confidence": 1.0})
            continue
        result = translate_text(src, LANG_EN, target_lang)
        out.append({
            **region,
            "translated_text":        result["translated"],
            "translation_confidence": result["confidence"],
        })
    return out


def task_translate_spanish(**context) -> dict:
    """
    Translate OCR regions to Spanish.
    NOTE — STUB: see src/translate_text.py for the production swap point.
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",   key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text",  key="ocr_result")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        logger.info("Skipping Spanish translation — already exists.")
        ti.xcom_push(key="regions_es", value=[])
        return {}

    regions_es = _translate_regions(ocr_result["regions"], LANG_ES)
    logger.info("Spanish translation complete for %d region(s).", len(regions_es))
    ti.xcom_push(key="regions_es", value=regions_es)
    return {"count": len(regions_es)}


def task_translate_portuguese(**context) -> dict:
    """
    Translate OCR regions to Portuguese.
    NOTE — STUB: see src/translate_text.py for the production swap point.
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",   key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text",  key="ocr_result")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        logger.info("Skipping Portuguese translation — already exists.")
        ti.xcom_push(key="regions_pt", value=[])
        return {}

    regions_pt = _translate_regions(ocr_result["regions"], LANG_PT)
    logger.info("Portuguese translation complete for %d region(s).", len(regions_pt))
    ti.xcom_push(key="regions_pt", value=regions_pt)
    return {"count": len(regions_pt)}


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 5 & 6 — legal_review_spanish / legal_review_portuguese
# ══════════════════════════════════════════════════════════════════════════════

def task_legal_review_spanish(**context) -> dict:
    """
    Validate Spanish legal terminology via Llama (Groq API), with 3x retry.
    NOTE — STUB: review_legal_terms() always returns OK. In production
    swap src/legal_review.py with the real Groq API call.
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",  key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text", key="ocr_result")
    regions_es = ti.xcom_pull(task_ids="translate_spanish", key="regions_es")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        ti.xcom_push(key="legal_review_es", value={"status": "skipped_existing", "skipped": False})
        return {}

    translated = "\n".join(r.get("translated_text", "") for r in (regions_es or []))
    review = _legal_review_with_retry(
        text=f"ORIGINAL:\n{ocr_result.get('full_text', '')}\n\nSPANISH:\n{translated}",
        lang=LANG_ES,
    )

    if review["skipped"]:
        logger.warning("Spanish legal review SKIPPED — form flagged for mandatory human review.")
    else:
        logger.info("Spanish legal review: %d correction(s).", len(review.get("corrections", [])))

    ti.xcom_push(key="legal_review_es", value=review)
    return review


def task_legal_review_portuguese(**context) -> dict:
    """
    Validate Portuguese legal terminology via Llama (Groq API), with 3x retry.
    NOTE — STUB: same as above but for Portuguese.
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",    key="form_meta")
    ocr_result = ti.xcom_pull(task_ids="ocr_extract_text",   key="ocr_result")
    regions_pt = ti.xcom_pull(task_ids="translate_portuguese", key="regions_pt")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        ti.xcom_push(key="legal_review_pt", value={"status": "skipped_existing", "skipped": False})
        return {}

    translated = "\n".join(r.get("translated_text", "") for r in (regions_pt or []))
    review = _legal_review_with_retry(
        text=f"ORIGINAL:\n{ocr_result.get('full_text', '')}\n\nPORTUGUESE:\n{translated}",
        lang=LANG_PT,
    )

    if review["skipped"]:
        logger.warning("Portuguese legal review SKIPPED — form flagged for mandatory human review.")
    else:
        logger.info("Portuguese legal review: %d correction(s).", len(review.get("corrections", [])))

    ti.xcom_push(key="legal_review_pt", value=review)
    return review


# ══════════════════════════════════════════════════════════════════════════════
# Tasks 7 & 8 — reconstruct_pdf_spanish / reconstruct_pdf_portuguese
# ══════════════════════════════════════════════════════════════════════════════

def task_reconstruct_pdf_spanish(**context) -> dict:
    """
    Rebuild the PDF with Spanish text using PyMuPDF.
    Output: forms/{form_id}/v{version}/{slug}_es.pdf
    NOTE: PyMuPDF reconstruction is already production-ready (CPU-friendly).
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",   key="form_meta")
    regions_es = ti.xcom_pull(task_ids="translate_spanish", key="regions_es")

    if form_meta.get("skip") or form_meta.get("already_has_es"):
        logger.info("Skipping Spanish PDF reconstruction — already exists.")
        existing_es = form_meta.get("existing_es_path")
        ti.xcom_push(key="path_es", value=form_meta["versions"][0]["file_path_es"]
                     if not form_meta.get("skip") else None)
        return {}

    out_path = form_meta["output_es"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info("Reconstructing Spanish PDF → '%s'.", out_path)
    reconstruct_pdf(
        original_path=form_meta["original_path"],
        translated_regions=regions_es,
        output_path=out_path,
    )
    logger.info("Spanish PDF saved.")
    ti.xcom_push(key="path_es", value=out_path)
    return {"path_es": out_path}


def task_reconstruct_pdf_portuguese(**context) -> dict:
    """
    Rebuild the PDF with Portuguese text using PyMuPDF.
    Output: forms/{form_id}/v{version}/{slug}_pt.pdf
    NOTE: PyMuPDF reconstruction is already production-ready (CPU-friendly).
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",      key="form_meta")
    regions_pt = ti.xcom_pull(task_ids="translate_portuguese", key="regions_pt")

    if form_meta.get("skip") or form_meta.get("already_has_pt"):
        logger.info("Skipping Portuguese PDF reconstruction — already exists.")
        existing_pt = form_meta.get("existing_pt_path")
        ti.xcom_push(key="path_pt", value=None)
        return {}

    out_path = form_meta["output_pt"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    logger.info("Reconstructing Portuguese PDF → '%s'.", out_path)
    reconstruct_pdf(
        original_path=form_meta["original_path"],
        translated_regions=regions_pt,
        output_path=out_path,
    )
    logger.info("Portuguese PDF saved.")
    ti.xcom_push(key="path_pt", value=out_path)
    return {"path_pt": out_path}


# ══════════════════════════════════════════════════════════════════════════════
# Task 9 — store_and_update_catalog
# ══════════════════════════════════════════════════════════════════════════════

def task_store_and_update_catalog(**context) -> dict:
    """
    Write translated PDF paths back into form_catalog.json under
    versions[0]["file_path_es"] and versions[0]["file_path_pt"].
    Also updates languages_available and needs_human_review.

    Appends audit notes when legal review was skipped (per spec).

    NOTE: In production, this task would also upload PDFs to GCS and
    store gs:// URIs. Locally, absolute container paths are used.
    """
    ti         = context["ti"]
    form_meta  = ti.xcom_pull(task_ids="load_form_entry",            key="form_meta")
    path_es    = ti.xcom_pull(task_ids="reconstruct_pdf_spanish",    key="path_es")
    path_pt    = ti.xcom_pull(task_ids="reconstruct_pdf_portuguese", key="path_pt")
    review_es  = ti.xcom_pull(task_ids="legal_review_spanish",       key="legal_review_es")
    review_pt  = ti.xcom_pull(task_ids="legal_review_portuguese",    key="legal_review_pt")

    if form_meta.get("skip"):
        logger.info("Skipping catalog update — form was already fully translated.")
        return {}

    form_id = form_meta["form_id"]
    now     = datetime.utcnow().isoformat() + "Z"

    # Build audit notes for any skipped legal reviews
    audit_notes = []
    if review_es and review_es.get("skipped"):
        audit_notes.append(
            "Legal review skipped due to Groq API failure (Spanish). "
            "Human review is mandatory before removing the review flag."
        )
    if review_pt and review_pt.get("skipped"):
        audit_notes.append(
            "Legal review skipped due to Groq API failure (Portuguese). "
            "Human review is mandatory before removing the review flag."
        )

    catalog = _load_catalog()
    idx, entry = _find_entry(catalog, form_id)
    versions = entry.get("versions", [])

    # Write file paths into versions[0] (latest version record)
    if versions:
        if path_es:
            versions[0]["file_path_es"] = path_es
        if path_pt:
            versions[0]["file_path_pt"] = path_pt

    # Build languages_available list from all non-null paths
    langs = []
    if versions and versions[0].get("file_path_es"):
        langs.append("es")
    if versions and versions[0].get("file_path_pt"):
        langs.append("pt")
    entry["languages_available"] = langs

    # Always set needs_human_review = True (machine-translated, never auto-approve)
    entry["needs_human_review"] = True
    entry["last_updated_at"]    = now

    # Append audit notes if legal review was skipped
    if audit_notes:
        existing = entry.get("audit_notes", [])
        existing.extend(audit_notes)
        entry["audit_notes"] = existing

    catalog[idx] = entry
    _save_catalog(catalog)

    logger.info(
        "Catalog updated for '%s': "
        "file_path_es=%s, file_path_pt=%s, "
        "languages_available=%s, needs_human_review=True.",
        form_id, path_es, path_pt, langs,
    )
    for note in audit_notes:
        logger.warning("AUDIT: %s", note)

    result = {
        "form_id":      form_id,
        "path_es":      path_es,
        "path_pt":      path_pt,
        "langs":        langs,
        "updated_at":   now,
        "audit_notes":  audit_notes,
    }
    context["ti"].xcom_push(key="store_result", value=result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Task 10 — dvc_version_data  (mirrors form_scraper_dag.task_dvc_version_data)
# ══════════════════════════════════════════════════════════════════════════════

def task_dvc_version_data(**context) -> None:
    """
    Version the updated catalog and new translated PDFs with DVC.
    Pattern copied directly from form_scraper_dag.task_dvc_version_data
    to keep DVC usage consistent across both DAGs.
    """
    import os

    ti        = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    if form_meta.get("skip"):
        logger.info("Skipping DVC versioning — no new files were produced.")
        return

    form_id = form_meta["form_id"]
    version = form_meta["version"]
    env     = os.environ.copy()

    def _run(cmd: list[str]) -> bool:
        try:
            res = subprocess.run(
                cmd, cwd=PROJECT_ROOT, capture_output=True,
                text=True, env=env, timeout=120,
            )
            if res.returncode == 0:
                logger.info("DVC OK: %s", " ".join(cmd))
                return True
            logger.warning(
                "DVC failed (rc=%d): %s | stderr: %s",
                res.returncode, " ".join(cmd), res.stderr.strip(),
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning("DVC timed out: %s", " ".join(cmd))
            return False
        except FileNotFoundError:
            logger.error("DVC not found in container PATH.")
            return False

    # Track the catalog and the specific version directory for this form
    c_tracked = _run(["dvc", "add", "dags/data/form_catalog.json"])
    f_tracked = _run(["dvc", "add", f"forms/{form_id}/v{version}"])

    if c_tracked or f_tracked:
        pushed = _run(["dvc", "push"])
        if pushed:
            logger.info("DVC push complete — translations versioned.")
        else:
            logger.warning("DVC push failed — tracked locally but not pushed.")
    else:
        logger.info("No DVC changes to push.")


# ══════════════════════════════════════════════════════════════════════════════
# Task 11 — log_summary  (mirrors form_scraper_dag.task_log_summary style)
# ══════════════════════════════════════════════════════════════════════════════

def task_log_summary(**context) -> None:
    """
    Write a final audit-style summary to the Airflow log.
    Mirrors the log_summary style of form_scraper_dag for consistency.
    """
    ti           = context["ti"]
    form_meta    = ti.xcom_pull(task_ids="load_form_entry",           key="form_meta")
    ocr_result   = ti.xcom_pull(task_ids="ocr_extract_text",          key="ocr_result")
    review_es    = ti.xcom_pull(task_ids="legal_review_spanish",      key="legal_review_es")
    review_pt    = ti.xcom_pull(task_ids="legal_review_portuguese",   key="legal_review_pt")
    store_result = ti.xcom_pull(task_ids="store_and_update_catalog",  key="store_result")

    if form_meta and form_meta.get("skip"):
        logger.info(
            "══ Form Pre-Translation Summary ══\n"
            "  form_id : %s\n"
            "  result  : SKIPPED — translations already existed from mass.gov",
            form_meta.get("form_id"),
        )
        return

    regions = len(ocr_result.get("regions", [])) if ocr_result else 0
    es_skip = review_es.get("skipped", True) if review_es else True
    pt_skip = review_pt.get("skipped", True) if review_pt else True
    es_corr = len(review_es.get("corrections", [])) if review_es and not es_skip else 0
    pt_corr = len(review_pt.get("corrections", [])) if review_pt and not pt_skip else 0

    logger.info(
        "══ Form Pre-Translation Summary ══\n"
        "  form_id           : %s\n"
        "  form_name         : %s\n"
        "  version           : %s\n"
        "  is_mislabeled     : %s\n"
        "  OCR regions       : %d\n"
        "  ES legal review   : %s (%d correction(s))\n"
        "  PT legal review   : %s (%d correction(s))\n"
        "  Spanish PDF       : %s\n"
        "  Portuguese PDF    : %s\n"
        "  languages_avail   : %s\n"
        "  needs_human_review: True\n"
        "  completed_at      : %s",
        form_meta.get("form_id")    if form_meta else "unknown",
        form_meta.get("form_name")  if form_meta else "unknown",
        form_meta.get("version")    if form_meta else "unknown",
        form_meta.get("is_mislabeled") if form_meta else "unknown",
        regions,
        "SKIPPED" if es_skip else "OK", es_corr,
        "SKIPPED" if pt_skip else "OK", pt_corr,
        store_result.get("path_es")   if store_result else "unknown",
        store_result.get("path_pt")   if store_result else "unknown",
        store_result.get("langs")     if store_result else "unknown",
        store_result.get("updated_at") if store_result else "unknown",
    )
    if store_result:
        for note in store_result.get("audit_notes", []):
            logger.warning("AUDIT NOTE: %s", note)


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition
# ══════════════════════════════════════════════════════════════════════════════

with DAG(
    dag_id="form_pretranslation_dag",
    description=(
        "Triggered by form_scraper_dag (Scenarios A & B). "
        "Extracts text, translates to ES+PT, validates legal terms, "
        "reconstructs PDFs, and updates the form catalog. "
        "NOTE: OCR and translation are STUB implementations — "
        "will be upgraded to PaddleOCR + NLLB-200 + Groq before deployment."
    ),
    schedule=None,                     # Externally triggered only
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    tags=["courtaccess", "forms", "translation", "ocr", "stub"],
) as dag:

    t1_load  = PythonOperator(task_id="load_form_entry",            python_callable=task_load_form_entry)
    t2_ocr   = PythonOperator(task_id="ocr_extract_text",           python_callable=task_ocr_extract_text)
    t3_es    = PythonOperator(task_id="translate_spanish",          python_callable=task_translate_spanish)
    t4_pt    = PythonOperator(task_id="translate_portuguese",       python_callable=task_translate_portuguese)
    t5_rev_es= PythonOperator(task_id="legal_review_spanish",       python_callable=task_legal_review_spanish)
    t6_rev_pt= PythonOperator(task_id="legal_review_portuguese",    python_callable=task_legal_review_portuguese)
    t7_rec_es= PythonOperator(task_id="reconstruct_pdf_spanish",    python_callable=task_reconstruct_pdf_spanish)
    t8_rec_pt= PythonOperator(task_id="reconstruct_pdf_portuguese", python_callable=task_reconstruct_pdf_portuguese)
    t9_store = PythonOperator(task_id="store_and_update_catalog",   python_callable=task_store_and_update_catalog)
    t10_dvc  = PythonOperator(task_id="dvc_version_data",           python_callable=task_dvc_version_data)
    t11_sum  = PythonOperator(task_id="log_summary",                python_callable=task_log_summary)

    # ── Dependency graph ──────────────────────────────────────────────────────
    #
    #   load_form_entry
    #          │
    #          ▼
    #   ocr_extract_text
    #       ┌──┴──┐
    #       ▼      ▼
    #   trans_es  trans_pt        (parallel)
    #       │      │
    #       ▼      ▼
    #   rev_es  rev_pt            (parallel)
    #       │      │
    #       ▼      ▼
    #   rec_es  rec_pt            (parallel)
    #       └──┬──┘
    #          ▼
    #   store_and_update_catalog
    #          ▼
    #   dvc_version_data
    #          ▼
    #   log_summary
    #
    t1_load  >> t2_ocr
    t2_ocr   >> [t3_es,    t4_pt]
    t3_es    >> t5_rev_es
    t4_pt    >> t6_rev_pt
    t5_rev_es >> t7_rec_es
    t6_rev_pt >> t8_rec_pt
    [t7_rec_es, t8_rec_pt] >> t9_store
    t9_store >> t10_dvc >> t11_sum