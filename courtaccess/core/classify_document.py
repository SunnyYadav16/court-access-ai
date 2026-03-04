"""
courtaccess/core/classify_document.py

Document classifier: determines if an uploaded PDF is a legal document
or an irrelevant file that should be rejected.

Uses Llama 3.1 via Groq API (first 3 pages only — fast and cost-effective).

STUB/REAL HYBRID:
  - Stub: always returns "legal" to allow pipeline testing end-to-end.
  - Real: calls Groq API with Llama 3.1. Enabled with USE_REAL_CLASSIFICATION=true.

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

import os

from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

_USE_REAL = os.getenv("USE_REAL_CLASSIFICATION", "false").lower() == "true"
_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
_MAX_PAGES = 3  # Only classify the first 3 pages


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

    if _USE_REAL and _GROQ_API_KEY:
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


def _real_classify(pdf_path: str) -> dict:
    """
    Production classifier via Groq API (Llama 3.1).
    Reads first 3 pages via PyMuPDF, sends text to Llama for classification.

    RAISES:
        RuntimeError on Groq API failure (caller should surface error to user).
    """
    import json as _json

    import fitz  # PyMuPDF

    # Extract text from first N pages
    doc = fitz.open(pdf_path)
    pages_text = []
    pages_read = min(_MAX_PAGES, len(doc))
    for i in range(pages_read):
        pages_text.append(doc[i].get_text("text"))
    doc.close()

    excerpt = "\n\n".join(pages_text)[:4000]  # cap tokens

    try:
        from groq import Groq

        client = Groq(api_key=_GROQ_API_KEY)
        prompt = (
            "You are a document classifier for Massachusetts courts. "
            "Determine if the following document excerpt is a legal document "
            "(court forms, legal filings, affidavits, motions, orders, etc.) "
            "or a non-legal document. "
            'Respond ONLY with JSON: {"classification":"legal"|"non_legal","confidence":0.0-1.0,"reason":"..."}\n\n'
            f"DOCUMENT EXCERPT:\n{excerpt}"
        )
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        result = _json.loads(raw)
        result["pages_reviewed"] = pages_read
        logger.info(
            "[REAL CLASSIFY] '%s' → %s (confidence=%.2f)",
            pdf_path,
            result["classification"],
            result["confidence"],
        )
        return result

    except Exception as exc:
        logger.error("[REAL CLASSIFY] Groq API failed: %s", exc)
        raise RuntimeError(f"Document classification failed: {exc}") from exc
