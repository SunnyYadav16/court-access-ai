"""
dags/document_pipeline_dag.py

Airflow DAG — document_pipeline_dag
Triggered manually or by the API when a user uploads a document.

Pipeline (one document per DAG run):
    validate_upload
        → classify_document
        → ingest_pages
        → ocr_printed_text
        → ocr_handwritten_text           (only on low-confidence regions)
        → pii_scan
        ┌────────────────────┐
        ▼                    ▼
    translate_spanish   translate_portuguese   (parallel)
        │                    │
        ▼                    ▼
    legal_review_es    legal_review_pt        (parallel)
        └────────┬───────────┘
                 ▼
        reconstruct_pdfs
                 ▼
        store_outputs
                 ▼
        log_summary

NOTE: All task functions are STUBS. They log what they *would* do and push
expected XCom shapes. Replace each stub with the real courtaccess.* calls
when the corresponding module is production-ready.

Trigger conf:
    {
        "document_id":  "<uuid>",
        "user_id":      "<user-id>",
        "upload_path":  "/opt/airflow/uploads/<uuid>/<filename>.pdf",
        "target_langs": ["es", "pt"]   # optional; defaults to both
    }
"""

import logging
from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

logger = logging.getLogger(__name__)

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
# Task stubs
# ══════════════════════════════════════════════════════════════════════════════


def task_validate_upload(**context) -> dict:
    """
    STUB — Task 1.
    Validates that the uploaded file exists, is a valid PDF (magic bytes),
    and does not exceed the max size limit.

    Production: calls courtaccess.core.validation helpers.
    """
    conf = context["dag_run"].conf or {}
    doc_id = conf.get("document_id", "unknown")
    upload_path = conf.get("upload_path", "")
    logger.info("[STUB] validate_upload: doc_id=%s path=%s", doc_id, upload_path)
    result = {"document_id": doc_id, "upload_path": upload_path, "valid": True}
    context["ti"].xcom_push(key="upload_meta", value=result)
    return result


def task_classify_document(**context) -> dict:
    """
    STUB — Task 2.
    Classifies the document as a legal form (pass) or irrelevant (reject).

    Production: calls courtaccess.core.classify_document.classify()
    which uses Vertex/Llama on the first 3 pages.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    logger.info("[STUB] classify_document: doc_id=%s", meta.get("document_id"))
    result = {"document_id": meta["document_id"], "is_legal": True, "confidence": 1.0}
    ti.xcom_push(key="classification", value=result)
    return result


def task_ingest_pages(**context) -> dict:
    """
    STUB — Task 3.
    Splits the PDF into per-page PNG images at 300 DPI.

    Production: calls courtaccess.core.ingest_document.ingest()
    which uses PyMuPDF (fitz) to render each page.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    doc_id = meta["document_id"]
    logger.info("[STUB] ingest_pages: doc_id=%s", doc_id)
    result = {"document_id": doc_id, "page_count": 1, "pages": []}
    ti.xcom_push(key="pages", value=result)
    return result


def task_ocr_printed_text(**context) -> dict:
    """
    STUB — Task 4.
    Extracts printed text regions from each page using PaddleOCR.

    Production: calls courtaccess.core.ocr_printed.extract_text_from_pdf()
    on the original upload path.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    logger.info("[STUB] ocr_printed_text: doc_id=%s", meta["document_id"])
    result = {"regions": [], "full_text": "", "low_confidence_regions": []}
    ti.xcom_push(key="ocr_result", value=result)
    return result


def task_ocr_handwritten_text(**context) -> dict:
    """
    STUB — Task 5.
    Processes low-confidence OCR regions with Qwen2.5-VL (GPU).
    Skipped when there are no low-confidence regions.

    Production: calls courtaccess.core.ocr_handwritten.extract_handwritten()
    """
    ti = context["ti"]
    ocr_result = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_result")
    low_conf = ocr_result.get("low_confidence_regions", [])
    if not low_conf:
        logger.info("[STUB] ocr_handwritten_text: no low-confidence regions, skipping.")
        ti.xcom_push(key="handwritten_regions", value=[])
        return {}
    logger.info("[STUB] ocr_handwritten_text: %d low-confidence region(s) to process.", len(low_conf))
    ti.xcom_push(key="handwritten_regions", value=[])
    return {"processed": len(low_conf)}


def task_pii_scan(**context) -> dict:
    """
    STUB — Task 6.
    Scans OCR output for PII (names, SSNs, DOBs, docket numbers).
    Does NOT redact — logs findings for human review only.

    Production: calls courtaccess.core.pii_scrub.scan_text()
    using Microsoft Presidio + custom MA court recognizers.
    """
    ti = context["ti"]
    ocr_result = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_result")
    text = ocr_result.get("full_text", "")
    logger.info("[STUB] pii_scan: scanning %d chars", len(text))
    result = {"pii_found": [], "pii_count": 0, "human_review_required": False}
    ti.xcom_push(key="pii_report", value=result)
    return result


def task_translate_spanish(**context) -> dict:
    """
    STUB — Task 7a.
    Translates OCR regions to Spanish using NLLB-200 via CTranslate2.

    Production: calls courtaccess.core.translation.translate_text()
    per region, target_lang="spa_Latn".
    """
    ti = context["ti"]
    ocr_result = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_result")
    regions = ocr_result.get("regions", [])
    logger.info("[STUB] translate_spanish: %d region(s)", len(regions))
    regions_es = [
        {**r, "translated_text": f"[ES] {r.get('text', '')}", "translation_confidence": 0.85} for r in regions
    ]
    ti.xcom_push(key="regions_es", value=regions_es)
    return {"count": len(regions_es)}


def task_translate_portuguese(**context) -> dict:
    """
    STUB — Task 7b.
    Translates OCR regions to Portuguese using NLLB-200 via CTranslate2.

    Production: calls courtaccess.core.translation.translate_text()
    per region, target_lang="por_Latn".
    """
    ti = context["ti"]
    ocr_result = ti.xcom_pull(task_ids="ocr_printed_text", key="ocr_result")
    regions = ocr_result.get("regions", [])
    logger.info("[STUB] translate_portuguese: %d region(s)", len(regions))
    regions_pt = [
        {**r, "translated_text": f"[PT] {r.get('text', '')}", "translation_confidence": 0.85} for r in regions
    ]
    ti.xcom_push(key="regions_pt", value=regions_pt)
    return {"count": len(regions_pt)}


def task_legal_review_es(**context) -> dict:
    """
    STUB — Task 8a.
    Validates Spanish legal terminology via Vertex/Llama. 3x retry with backoff.

    Production: calls courtaccess.core.legal_review.review_legal_terms()
    """
    ti = context["ti"]
    regions_es = ti.xcom_pull(task_ids="translate_spanish", key="regions_es")
    es_text = "\n".join(r.get("translated_text", "") for r in (regions_es or []))
    logger.info("[STUB] legal_review_es: reviewing %d chars", len(es_text))
    result = {"status": "ok", "corrections": [], "skipped": False}
    ti.xcom_push(key="legal_review_es", value=result)
    return result


def task_legal_review_pt(**context) -> dict:
    """
    STUB — Task 8b.
    Validates Portuguese legal terminology via Vertex/Llama. 3x retry with backoff.

    Production: calls courtaccess.core.legal_review.review_legal_terms()
    """
    ti = context["ti"]
    regions_pt = ti.xcom_pull(task_ids="translate_portuguese", key="regions_pt")
    pt_text = "\n".join(r.get("translated_text", "") for r in (regions_pt or []))
    logger.info("[STUB] legal_review_pt: reviewing %d chars", len(pt_text))
    result = {"status": "ok", "corrections": [], "skipped": False}
    ti.xcom_push(key="legal_review_pt", value=result)
    return result


def task_reconstruct_pdfs(**context) -> dict:
    """
    STUB — Task 9.
    Rebuilds ES and PT PDFs with translated text overlaid using PyMuPDF.

    Production: calls courtaccess.core.reconstruct_pdf.reconstruct_pdf()
    twice (once per language).
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    doc_id = meta["document_id"]
    logger.info("[STUB] reconstruct_pdfs: doc_id=%s", doc_id)
    result = {"path_es": None, "path_pt": None}
    ti.xcom_push(key="output_paths", value=result)
    return result


def task_store_outputs(**context) -> dict:
    """
    STUB — Task 10.
    Uploads output PDFs to GCS and writes metadata to the database.
    Updates document status to 'translated' in PostgreSQL.

    Production: calls GCS client + SQLAlchemy models from db/models.py.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    output_paths = ti.xcom_pull(task_ids="reconstruct_pdfs", key="output_paths")
    doc_id = meta["document_id"]
    logger.info("[STUB] store_outputs: doc_id=%s paths=%s", doc_id, output_paths)
    result = {"document_id": doc_id, "stored": True, "gcs_uris": {}}
    ti.xcom_push(key="store_result", value=result)
    return result


def task_log_summary(**context) -> None:
    """
    STUB — Task 11.
    Writes final audit log entry for this document run.
    """
    ti = context["ti"]
    meta = ti.xcom_pull(task_ids="validate_upload", key="upload_meta")
    pii = ti.xcom_pull(task_ids="pii_scan", key="pii_report")
    review_es = ti.xcom_pull(task_ids="legal_review_es", key="legal_review_es")
    review_pt = ti.xcom_pull(task_ids="legal_review_pt", key="legal_review_pt")
    store_result = ti.xcom_pull(task_ids="store_outputs", key="store_result")

    logger.info(
        "══ Document Pipeline Summary ══\n"
        "  document_id       : %s\n"
        "  pii_found         : %d\n"
        "  ES legal status   : %s\n"
        "  PT legal status   : %s\n"
        "  stored            : %s",
        meta.get("document_id") if meta else "unknown",
        pii.get("pii_count", 0) if pii else 0,
        review_es.get("status", "unknown") if review_es else "unknown",
        review_pt.get("status", "unknown") if review_pt else "unknown",
        store_result.get("stored", False) if store_result else False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# DAG definition
# ══════════════════════════════════════════════════════════════════════════════

with DAG(
    dag_id="document_pipeline_dag",
    description=(
        "On-demand document processing: validate → classify → OCR → PII scan "
        "→ translate (ES+PT in parallel) → legal review → reconstruct → store."
    ),
    schedule=None,  # Triggered via API or Airflow REST
    start_date=datetime(2024, 1, 1),
    default_args=DEFAULT_ARGS,
    catchup=False,
    tags=["courtaccess", "documents", "ocr", "translation", "legal-review", "stub"],
) as dag:
    t1_validate = PythonOperator(task_id="validate_upload", python_callable=task_validate_upload)
    t2_classify = PythonOperator(task_id="classify_document", python_callable=task_classify_document)
    t3_ingest = PythonOperator(task_id="ingest_pages", python_callable=task_ingest_pages)
    t4_ocr = PythonOperator(task_id="ocr_printed_text", python_callable=task_ocr_printed_text)
    t5_hw = PythonOperator(task_id="ocr_handwritten_text", python_callable=task_ocr_handwritten_text)
    t6_pii = PythonOperator(task_id="pii_scan", python_callable=task_pii_scan)
    t7_es = PythonOperator(task_id="translate_spanish", python_callable=task_translate_spanish)
    t7_pt = PythonOperator(task_id="translate_portuguese", python_callable=task_translate_portuguese)
    t8_rev_es = PythonOperator(task_id="legal_review_es", python_callable=task_legal_review_es)
    t8_rev_pt = PythonOperator(task_id="legal_review_pt", python_callable=task_legal_review_pt)
    t9_recon = PythonOperator(task_id="reconstruct_pdfs", python_callable=task_reconstruct_pdfs)
    t10_store = PythonOperator(task_id="store_outputs", python_callable=task_store_outputs)
    t11_log = PythonOperator(task_id="log_summary", python_callable=task_log_summary)

    # ── Dependency graph ──────────────────────────────────────────────────────
    #
    #   validate_upload
    #         │
    #         ▼
    #   classify_document
    #         │
    #         ▼
    #   ingest_pages
    #         │
    #         ▼
    #   ocr_printed_text
    #         │
    #         ▼
    #   ocr_handwritten_text
    #         │
    #         ▼
    #   pii_scan
    #       ┌──┴──┐
    #       ▼      ▼
    #   trans_es  trans_pt          (parallel)
    #       │      │
    #       ▼      ▼
    #   rev_es   rev_pt            (parallel)
    #       └──┬──┘
    #          ▼
    #   reconstruct_pdfs
    #          ▼
    #   store_outputs
    #          ▼
    #   log_summary
    #
    t1_validate >> t2_classify >> t3_ingest >> t4_ocr >> t5_hw >> t6_pii
    t6_pii >> [t7_es, t7_pt]
    t7_es >> t8_rev_es
    t7_pt >> t8_rev_pt
    [t8_rev_es, t8_rev_pt] >> t9_recon >> t10_store >> t11_log
