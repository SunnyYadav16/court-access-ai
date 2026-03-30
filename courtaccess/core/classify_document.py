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
  ClassificationError if the AI response cannot be parsed or is missing required
    keys — callers must treat this as a hard-reject (fail closed).
  RuntimeError on Vertex auth or network failure.
  ValueError if classification == "non_legal" and caller should hard-reject.
"""

import json
import logging

from courtaccess.core.config import settings

logger = logging.getLogger(__name__)

_USE_REAL = settings.use_real_classification
_VERTEX_PROJECT = settings.vertex_project_id
_VERTEX_LOCATION = settings.vertex_location
_VERTEX_MODEL = settings.vertex_model_id
_GCP_SA_JSON = settings.gcp_service_account_json
_MAX_PAGES = 3  # only classify first 3 pages


class ClassificationError(Exception):
    """
    Raised when the AI classifier returns a response that cannot be used:
      - Non-JSON output
      - JSON missing required keys ('classification' or 'confidence')

    Callers must treat this as a hard-reject (fail closed) — do not
    silently pass the document through.
    """


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

    Fail-closed on bad AI responses: a non-JSON reply or a response missing
    required keys raises ClassificationError rather than falling back to a
    stub that unconditionally approves documents.

    RAISES:
        ClassificationError: AI response is unparseable or missing required keys.
        RuntimeError: Vertex auth or network failure.
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

        # ── Fail-closed response guard ────────────────────────────────────────
        # A bad AI response must never silently approve a document.
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "[REAL CLASSIFY] Vertex returned non-JSON for '%s' — failing closed. raw=%r error=%s",
                pdf_path,
                raw[:200],
                exc,
            )
            raise ClassificationError(f"Vertex AI returned unparseable JSON for '{pdf_path}': {exc}") from exc

        missing = [k for k in ("classification", "confidence") if k not in result]
        if missing:
            logger.error(
                "[REAL CLASSIFY] Vertex response missing keys %s for '%s' — failing closed. result=%r",
                missing,
                pdf_path,
                result,
            )
            raise ClassificationError(f"Vertex AI response missing required keys {missing} for '{pdf_path}'")

        result["pages_reviewed"] = pages_read
        logger.info(
            "[REAL CLASSIFY] '%s' → %s (confidence=%.2f)",
            pdf_path,
            result["classification"],
            result["confidence"],
        )
        return result

    except ClassificationError:
        raise  # propagate as-is — distinct from a transport/auth failure
    except Exception as exc:
        logger.error("[REAL CLASSIFY] Vertex AI failed: %s", exc)
        raise RuntimeError(f"Document classification failed: {exc}") from exc
