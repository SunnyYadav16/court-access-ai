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

Each task instantiates the classes it needs internally.
Airflow runs each task in its own process — instances are not shared.
"""

import json
import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from courtaccess.core.legal_review import LegalReviewer
from courtaccess.core.ocr_printed import OCREngine
from courtaccess.core.reconstruct_pdf import reconstruct_pdf
from courtaccess.core.translation import Translator
from courtaccess.languages import get_language_config

logger = logging.getLogger(__name__)

# ── Paths (inside Docker container) ──────────────────────────────────────────
CATALOG_PATH = "/opt/airflow/courtaccess/data/form_catalog.json"
FORMS_DIR = "/opt/airflow/forms"
PROJECT_ROOT = "/opt/airflow"

# ── NLLB-200 language codes ───────────────────────────────────────────────────
LANG_EN = "eng_Latn"
LANG_ES = "spa_Latn"
LANG_PT = "por_Latn"

# ── Groq/Llama retry settings ─────────────────────────────────────────────────
GROQ_RETRY_DELAYS = [1, 3, 9]  # seconds — exponential backoff

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
# Catalog helpers — unchanged
# ══════════════════════════════════════════════════════════════════════════════


def _load_catalog() -> list[dict]:
    p = Path(CATALOG_PATH)
    if not p.exists():
        raise FileNotFoundError(f"Catalog not found at {CATALOG_PATH}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_catalog(catalog: list[dict]) -> None:
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def _find_entry(catalog: list[dict], form_id: str) -> tuple[int, dict]:
    for i, entry in enumerate(catalog):
        if entry.get("form_id") == form_id:
            return i, entry
    raise ValueError(f"form_id '{form_id}' not found in catalog.")


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
    Call reviewer.review_legal_terms() up to len(GROQ_RETRY_DELAYS) times.
    On total failure returns a 'skipped' result so the pipeline continues
    and flags the form for mandatory human review.
    """
    last_err = None
    for attempt, delay in enumerate(GROQ_RETRY_DELAYS, start=1):
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
                len(GROQ_RETRY_DELAYS),
                exc,
                delay,
            )
            if attempt < len(GROQ_RETRY_DELAYS):
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

    logger.info("Loading catalog entry for form_id='%s'.", form_id)
    catalog = _load_catalog()
    _, entry = _find_entry(catalog, form_id)

    versions = entry.get("versions", [])
    if not versions:
        raise ValueError(f"Catalog entry '{form_id}' has no version records.")
    latest = versions[0]

    orig_path = latest.get("file_path_original")
    if not orig_path:
        raise ValueError(f"Catalog entry '{form_id}' missing file_path_original.")
    if not Path(orig_path).exists():
        raise FileNotFoundError(f"Original PDF not found: '{orig_path}'.")

    already_has_es = bool(latest.get("file_path_es"))
    already_has_pt = bool(latest.get("file_path_pt"))
    if already_has_es and already_has_pt:
        logger.info("Form '%s' already translated. Skipping.", form_id)
        context["ti"].xcom_push(key="form_meta", value={"skip": True, "form_id": form_id})
        return {"skip": True, "form_id": form_id}

    orig_p = Path(orig_path)
    slug_stem = orig_p.stem
    out_dir = orig_p.parent

    form_meta = {
        "form_id": form_id,
        "form_name": entry.get("form_name", ""),
        "form_slug": entry.get("form_slug", ""),
        "version": latest.get("version", 1),
        "original_path": orig_path,
        "output_es": str(out_dir / f"{slug_stem}_es.pdf"),
        "output_pt": str(out_dir / f"{slug_stem}_pt.pdf"),
        "skip": False,
        "already_has_es": already_has_es,
        "already_has_pt": already_has_pt,
        "existing_es_path": latest.get("file_path_es"),
        "existing_pt_path": latest.get("file_path_pt"),
        "is_mislabeled": "mislabeled" in str(entry.get("preprocessing_flags", [])),
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
    regions_es = _translate_regions(ocr_result["regions"], LANG_ES, translator)

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
    regions_pt = _translate_regions(ocr_result["regions"], LANG_PT, translator)

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
# Tasks 9-11 — store, dvc, summary (unchanged)
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

    catalog = _load_catalog()
    idx, entry = _find_entry(catalog, form_id)
    versions = entry.get("versions", [])

    if versions:
        if path_es:
            versions[0]["file_path_es"] = path_es
        if path_pt:
            versions[0]["file_path_pt"] = path_pt

    langs = []
    if versions and versions[0].get("file_path_es"):
        langs.append("es")
    if versions and versions[0].get("file_path_pt"):
        langs.append("pt")

    entry["languages_available"] = langs
    entry["needs_human_review"] = True
    entry["last_updated_at"] = now

    if audit_notes:
        existing = entry.get("audit_notes", [])
        existing.extend(audit_notes)
        entry["audit_notes"] = existing

    catalog[idx] = entry
    _save_catalog(catalog)

    logger.info(
        "Catalog updated for '%s': ES=%s, PT=%s, langs=%s.",
        form_id,
        path_es,
        path_pt,
        langs,
    )
    for note in audit_notes:
        logger.warning("AUDIT: %s", note)

    result = {
        "form_id": form_id,
        "path_es": path_es,
        "path_pt": path_pt,
        "langs": langs,
        "updated_at": now,
        "audit_notes": audit_notes,
    }
    context["ti"].xcom_push(key="store_result", value=result)
    return result


def task_dvc_version_data(**context) -> None:
    import os as _os

    ti = context["ti"]
    form_meta = ti.xcom_pull(task_ids="load_form_entry", key="form_meta")
    if form_meta.get("skip"):
        logger.info("Skipping DVC versioning — no new files produced.")
        return

    form_id = form_meta["form_id"]
    version = form_meta["version"]
    env = _os.environ.copy()

    def _run(cmd: list[str]) -> bool:
        try:
            res = subprocess.run(  # noqa: S603
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                env=env,
                timeout=120,
            )
            if res.returncode == 0:
                logger.info("DVC OK: %s", " ".join(cmd))
                return True
            logger.warning(
                "DVC failed (rc=%d): %s | stderr: %s",
                res.returncode,
                " ".join(cmd),
                res.stderr.strip(),
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning("DVC timed out: %s", " ".join(cmd))
            return False
        except FileNotFoundError:
            logger.error("DVC not found in container PATH.")
            return False

    c_tracked = _run(["dvc", "add", "courtaccess/data/form_catalog.json"])
    f_tracked = _run(["dvc", "add", f"forms/{form_id}/v{version}"])
    if c_tracked or f_tracked:
        pushed = _run(["dvc", "push"])
        logger.info("DVC push complete." if pushed else "DVC push failed — tracked locally but not pushed.")


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


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition (unchanged)
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
    tags=["courtaccess", "forms", "translation", "ocr"],
) as dag:
    t1_load = PythonOperator(task_id="load_form_entry", python_callable=task_load_form_entry)
    t2_ocr = PythonOperator(task_id="ocr_extract_text", python_callable=task_ocr_extract_text)
    t3_es = PythonOperator(task_id="translate_spanish", python_callable=task_translate_spanish)
    t4_pt = PythonOperator(task_id="translate_portuguese", python_callable=task_translate_portuguese)
    t5_rev_es = PythonOperator(task_id="legal_review_spanish", python_callable=task_legal_review_spanish)
    t6_rev_pt = PythonOperator(task_id="legal_review_portuguese", python_callable=task_legal_review_portuguese)
    t7_rec_es = PythonOperator(task_id="reconstruct_pdf_spanish", python_callable=task_reconstruct_pdf_spanish)
    t8_rec_pt = PythonOperator(task_id="reconstruct_pdf_portuguese", python_callable=task_reconstruct_pdf_portuguese)
    t9_store = PythonOperator(task_id="store_and_update_catalog", python_callable=task_store_and_update_catalog)
    t10_dvc = PythonOperator(task_id="dvc_version_data", python_callable=task_dvc_version_data)
    t11_sum = PythonOperator(task_id="log_summary", python_callable=task_log_summary)

    t1_load >> t2_ocr
    t2_ocr >> [t3_es, t4_pt]
    t3_es >> t5_rev_es
    t4_pt >> t6_rev_pt
    t5_rev_es >> t7_rec_es
    t6_rev_pt >> t8_rec_pt
    [t7_rec_es, t8_rec_pt] >> t9_store >> t10_dvc >> t11_sum
