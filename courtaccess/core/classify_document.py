"""
courtaccess/core/classify_document.py

Document classifier: determines if an uploaded PDF is a legal document
or an irrelevant file that should be rejected.

Uses Llama 4 via Vertex AI (first 3 pages only — fast and cost-effective).
Same auth pattern as legal_review.py — service account JSON from env.

STUB/REAL HYBRID:
  - Stub: always returns "legal" to allow pipeline testing end-to-end.
  - Real: calls Vertex AI with Llama 4. Enabled with USE_REAL_CLASSIFICATION=true.

PRODUCTION NOTES:
  - Hard-rejects non-legal docs — the pipeline stops here for invalid uploads.
  - Only reads first 3 pages to minimise token usage and latency.

OUTPUT CONTRACT (success):
  {
      "classification": "legal" | "non_legal",
      "confidence":     float,      # 0.0-1.0
      "reason":         str,        # brief explanation
      "pages_reviewed": int,
  }

RAISES:
  ValueError if classification == "non_legal" and caller should hard-reject.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_USE_REAL = os.getenv("USE_REAL_CLASSIFICATION", "false").lower() == "true"
_VERTEX_PROJECT = os.getenv("VERTEX_PROJECT_ID", "")
_VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-east5")
_VERTEX_MODEL = os.getenv(
    "VERTEX_MODEL_ID",
    "meta/llama-4-maverick-17b-128e-instruct-maas",
)
_GCP_SA_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
_MAX_PAGES = 3  # only classify first 3 pages


def classify_document(pdf_path: str) -> dict:
    """
    Classify a PDF as legal or non-legal.

    Args:
        pdf_path: Absolute path to the uploaded PDF.

    Returns:
        Dict matching OUTPUT CONTRACT above.

    Raises:
        FileNotFoundError: if pdf_path does not exist.
    """
    from pathlib import Path

    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if _USE_REAL and _VERTEX_PROJECT and _GCP_SA_JSON:
        return _real_classify(pdf_path)
    return _stub_classify(pdf_path)


def _stub_classify(pdf_path: str) -> dict:
    """
    Stub: unconditionally classifies every document as legal.
    NOT a real classifier — for pipeline testing only.
    """
    logger.debug("[STUB CLASSIFY] '%s' → legal (stub always passes).", pdf_path)
    return {
        "classification": "legal",
        "confidence": 1.0,
        "reason": "Stub classifier: all documents accepted.",
        "pages_reviewed": 0,
    }


def _get_vertex_client():
    """
    Build OpenAI-compatible Vertex AI client.
    Same auth pattern as LegalReviewer._get_vertex_client().
    """
    import google.auth.transport.requests
    from google.oauth2 import service_account
    from openai import OpenAI

    credentials = service_account.Credentials.from_service_account_info(
        json.loads(_GCP_SA_JSON),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    credentials.refresh(google.auth.transport.requests.Request())

    return OpenAI(
        base_url=(
            f"https://{_VERTEX_LOCATION}-aiplatform.googleapis.com/v1"
            f"/projects/{_VERTEX_PROJECT}"
            f"/locations/{_VERTEX_LOCATION}/endpoints/openapi"
        ),
        api_key=credentials.token,
    )


def _real_classify(pdf_path: str) -> dict:
    """
    Production classifier via Vertex AI (Llama 4 Maverick).
    Reads first 3 pages via PyMuPDF, sends text to Llama for classification.

    Bad response (non-JSON, missing keys) → falls back to stub result
    rather than crashing the pipeline, since classification is a gate
    check and a false positive is safer than a pipeline crash.

    RAISES:
        RuntimeError on Vertex auth or network failure.
    """
    import pymupdf

    # ── Extract text from first N pages ──────────────────────────────────────
    doc = pymupdf.open(pdf_path)
    pages_text = []
    pages_read = min(_MAX_PAGES, len(doc))
    for i in range(pages_read):
        pages_text.append(doc[i].get_text("text"))
    doc.close()

    excerpt = "\n\n".join(pages_text)[:4000]  # cap tokens

    prompt = (
        "You are a document classifier for Massachusetts courts. "
        "Determine if the following document excerpt is a legal document "
        "(court forms, legal filings, affidavits, motions, orders, etc.) "
        "or a non-legal document. "
        "Respond ONLY with JSON: "
        '{"classification":"legal"|"non_legal","confidence":0.0-1.0,"reason":"..."}\n\n'
        f"DOCUMENT EXCERPT:\n{excerpt}"
    )

    try:
        client = _get_vertex_client()
        response = client.chat.completions.create(
            model=_VERTEX_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        # ── Bad response guard — fall back to stub rather than crash ─────────
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("[REAL CLASSIFY] Bad JSON from Vertex (%s) — falling back to stub", exc)
            return _stub_classify(pdf_path)

        if "classification" not in result or "confidence" not in result:
            logger.warning("[REAL CLASSIFY] Missing keys in Vertex response — falling back to stub")
            return _stub_classify(pdf_path)

        result["pages_reviewed"] = pages_read
        logger.info(
            "[REAL CLASSIFY] '%s' → %s (confidence=%.2f)",
            pdf_path,
            result["classification"],
            result["confidence"],
        )
        return result

    except Exception as exc:
        logger.error("[REAL CLASSIFY] Vertex AI failed: %s", exc)
        raise RuntimeError(f"Document classification failed: {exc}") from exc
