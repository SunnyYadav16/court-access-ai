
"""
=============================================================================
FILE: dags/src/legal_review.py
=============================================================================
Validates legal terminology accuracy in a translation.

STUB IMPLEMENTATION — always returns {"status": "ok", "corrections": []}.

PRODUCTION UPGRADE:
  Replace _stub_review() with a Groq API call (Llama 3.1).
  Set GROQ_API_KEY and USE_REAL_LEGAL_REVIEW=true environment variables.
  The output dict contract must be preserved exactly.
  The DAG's retry logic (_legal_review_with_retry) handles API failures —
  this function should simply raise an exception on network/API errors.

OUTPUT CONTRACT (success):
  {
      "status":      "ok" | "issues_found",
      "corrections": [
          {"term": str, "current": str, "suggested": str, "reason": str}
      ]
  }

RAISE on failure (so the DAG retry logic triggers):
  Any exception — ConnectionError, HTTPError, TimeoutError, etc.
=============================================================================
"""
import logging
import os

logger = logging.getLogger(__name__)

_USE_REAL    = os.getenv("USE_REAL_LEGAL_REVIEW", "false").lower() == "true"
_GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


def review_legal_terms(text: str, lang: str) -> dict:
    """
    Review translated text for legal terminology accuracy.
    NOTE: STUB — always returns OK. Replace with Groq/Llama in production.
    """
    if _USE_REAL and _GROQ_API_KEY:
        return _real_review(text, lang)
    return _stub_review(text, lang)


def _stub_review(text: str, lang: str) -> dict:
    """
    Stub: unconditionally approves translation.
    NOTE: NOT a real legal review — for pipeline testing only.
    """
    logger.debug("[STUB LEGAL REVIEW] lang=%s, text_len=%d — returning OK.", lang, len(text))
    return {"status": "ok", "corrections": []}


def _real_review(text: str, lang: str) -> dict:
    """
    Production legal review via Groq API (Llama 3.1).
    NOTE: NOT active in stub mode.
    RAISES an exception on API failure so the DAG retry logic handles it.
    Enable by setting USE_REAL_LEGAL_REVIEW=true and GROQ_API_KEY.
    """
    import json as _json
    try:
        from groq import Groq

        lang_label = {"spa_Latn": "Spanish", "por_Latn": "Portuguese"}.get(lang, lang)
        client     = Groq(api_key=_GROQ_API_KEY)
        prompt     = (
            f"You are a legal translation reviewer for Massachusetts courts. "
            f"Review this {lang_label} translation for legal accuracy. "
            f"Respond ONLY with JSON: "
            f'{{"status":"ok"|"issues_found","corrections":['
            f'{{"term":"...","current":"...","suggested":"...","reason":"..."}}]}}\n\n'
            f"{text}"
        )
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        raw    = response.choices[0].message.content.strip()
        raw    = raw.replace("```json", "").replace("```", "").strip()
        result = _json.loads(raw)
        logger.info(
            "[REAL LEGAL REVIEW] lang=%s status=%s corrections=%d",
            lang, result.get("status"), len(result.get("corrections", [])),
        )
        return result
    except Exception as exc:
        # Re-raise so the DAG's _legal_review_with_retry() handles it
        logger.error("[REAL LEGAL REVIEW] API call failed: %s", exc)
        raise
