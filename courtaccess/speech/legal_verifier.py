"""
courtaccess/speech/legal_verifier.py

Legal Context Verification Service — LLaMA 4 via Vertex AI or Groq.

Verifies that NLLB machine translations preserve legal meaning in real-time
courtroom speech.  Designed for short utterances with a strict 5 s timeout.

Note: this is separate from courtaccess.core.legal_review, which handles
batch document-level verification.  They serve different use cases and coexist.

Provides a singleton LegalVerifierService that:
  1. Calls LLaMA 4 on Vertex AI (primary) or Groq (fallback) via
     OpenAI-compatible endpoints.
  2. Returns a VerificationResult with a refined translation, accuracy score,
     and a one-sentence note.

Provider priority:
  1. Vertex AI — if VERTEX_PROJECT_ID and USE_VERTEX_LEGAL_REVIEW are set
  2. Groq     — if GROQ_API_KEY is set (fallback on Vertex failure, or
                primary when Vertex is not configured)

Returns None from get_legal_verifier() if neither provider is configured.

Config (via courtaccess.core.config.Settings):
  VERTEX_PROJECT_ID       — GCP project ID (Vertex disabled if absent)
  VERTEX_LOCATION         — Vertex AI region (default: us-east5)
  VERTEX_LEGAL_LLM_MODEL  — model name
  LEGAL_VERIFY_TIMEOUT    — timeout in seconds (default: 5.0)
  GROQ_API_KEY            — Groq API key (Groq disabled if absent)
  GROQ_LEGAL_LLM_MODEL    — Groq model name
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

LANG_LABELS = {
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
}

# ---------------------------------------------------------------------------
#  Result type
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    """Result of a single legal-context verification call."""

    verified_translation: str  # LLM-refined translation
    accuracy_score: float  # 0.0-1.0  (1.0 = identical to raw NLLB output)
    accuracy_note: str  # human-readable explanation of the score
    raw_translation: str  # original NLLB output (passthrough)
    used_fallback: bool  # True if the LLM call failed or timed out


# ---------------------------------------------------------------------------
#  LegalVerifierService (singleton)
# ---------------------------------------------------------------------------


class LegalVerifierService:
    """
    Verifies machine-translated legal speech using LLaMA 4 on Vertex AI
    (primary) or Groq (fallback).

    Vertex AI exposes an OpenAI-compatible REST endpoint, so we use the
    standard ``openai`` Python SDK pointed at the Vertex base URL.  Groq
    also uses an OpenAI-compatible SDK.  Auth for Vertex is handled via
    Google Application Default Credentials (ADC).
    """

    _instance: Optional["LegalVerifierService"] = None

    # Vertex AI state
    _client = None
    _model: str = ""
    _credentials = None  # google.auth credentials object — stored for refresh
    _base_url: str = ""  # Vertex AI OpenAI-compat base URL — stored for client rebuild

    # Groq state
    _groq_client = None
    _groq_model: str = ""

    def __new__(cls) -> "LegalVerifierService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if LegalVerifierService._client is None and LegalVerifierService._groq_client is None:
            self._load_clients()

    # ------------------------------------------------------------------ #
    #  Setup                                                              #
    # ------------------------------------------------------------------ #

    def _load_clients(self) -> None:
        """Initialise Vertex AI and/or Groq clients based on available config."""
        s = get_settings()

        # ── Vertex AI (primary) ──────────────────────────────────────────
        if s.use_vertex_legal_review and s.vertex_project_id:
            try:
                self._load_vertex_client(s)
            except Exception as exc:
                logger.warning(
                    "[LegalVerifier] Vertex AI client init failed: %s — will use Groq if available",
                    exc,
                )

        # ── Groq (fallback) ──────────────────────────────────────────────
        if s.groq_api_key:
            try:
                self._load_groq_client(s)
            except Exception as exc:
                logger.warning("[LegalVerifier] Groq client init failed: %s", exc)

        if LegalVerifierService._client is None and LegalVerifierService._groq_client is None:
            raise RuntimeError("[LegalVerifier] No LLM provider available. Set VERTEX_PROJECT_ID or GROQ_API_KEY.")

    def _load_vertex_client(self, s) -> None:
        """Initialise the OpenAI client pointed at the Vertex AI endpoint.

        Auth strategy (matches legal_review.py _get_vertex_client):
          - Local dev: GCP_SERVICE_ACCOUNT_JSON contains the raw JSON of a
            service account key. Parsed via from_service_account_info().
          - Production (GCE / Cloud Run VM): GCP_SERVICE_ACCOUNT_JSON is empty
            or unset. Falls back to Application Default Credentials (ADC)
            provided by the attached compute service account automatically.
        """
        import google.auth
        import google.auth.transport.requests
        import openai

        project = s.vertex_project_id
        location = s.vertex_location

        import os as _os

        sa_key_path = (s.gcp_service_account_json or "").strip()

        if sa_key_path and _os.path.isfile(sa_key_path):
            from google.oauth2 import service_account

            with open(sa_key_path) as _f:
                sa_info = json.load(_f)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            logger.info("[LegalVerifier] Using service account key file: %s", sa_key_path)
        elif sa_key_path:
            logger.warning(
                "[LegalVerifier] GCP_SERVICE_ACCOUNT_JSON='%s' is not a readable file — falling through to ADC.",
                sa_key_path,
            )
            sa_key_path = ""  # force ADC path below

        if not sa_key_path:
            import os

            gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
            _cleared_gac = False
            if gac and not os.path.isfile(gac):
                logger.info(
                    "[LegalVerifier] GOOGLE_APPLICATION_CREDENTIALS='%s' is not a valid file "
                    "(likely an empty template expansion) — clearing so ADC uses GCE metadata server.",
                    gac,
                )
                del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
                _cleared_gac = True

            try:
                credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                logger.info("[LegalVerifier] Using Application Default Credentials (ADC).")
            finally:
                if _cleared_gac:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gac

        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)

        base_url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{location}/endpoints/openapi"
        )

        LegalVerifierService._credentials = credentials
        LegalVerifierService._base_url = base_url
        LegalVerifierService._client = openai.OpenAI(
            base_url=base_url,
            api_key=credentials.token,
        )

        model = s.vertex_legal_llm_model
        LegalVerifierService._model = model
        logger.info(
            "[LegalVerifier] Vertex client initialised (project=%s, location=%s, model=%s)",
            project,
            location,
            model,
        )

    def _load_groq_client(self, s) -> None:
        """Initialise the Groq client."""
        try:
            from groq import Groq
        except ImportError:
            logger.warning("[LegalVerifier] groq package not installed — Groq fallback disabled")
            return

        LegalVerifierService._groq_client = Groq(api_key=s.groq_api_key)
        LegalVerifierService._groq_model = s.groq_legal_llm_model or "meta-llama/llama-4-scout-17b-16e-instruct"
        logger.info("[LegalVerifier] Groq client initialised (model=%s)", LegalVerifierService._groq_model)

    # ------------------------------------------------------------------ #
    #  Token refresh                                                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def _ensure_client_fresh(cls) -> None:
        """Refresh the Vertex AI token and rebuild the OpenAI client if expired.

        Google OAuth2 tokens expire after ~1 hour.  Calling this before every
        verify() call ensures long-running sessions never hit a 401.
        """
        creds = cls._credentials
        if creds is None:
            return
        if not creds.valid:
            import google.auth.transport.requests

            creds.refresh(google.auth.transport.requests.Request())
            import openai

            cls._client = openai.OpenAI(
                base_url=cls._base_url,
                api_key=creds.token,
            )
            logger.debug("[LegalVerifier] Credentials refreshed; OpenAI client rebuilt.")

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def verify(
        self,
        original_text: str,
        raw_translation: str,
        source_lang: str,
        target_lang: str,
    ) -> VerificationResult:
        """
        Verify that *raw_translation* preserves the legal meaning of
        *original_text*.

        This is a synchronous, blocking call — callers should run it in
        ``asyncio.to_thread`` to avoid blocking the event loop.

        Provider order: Vertex AI → Groq → raw NLLB fallback.

        Args:
            original_text:   Utterance in *source_lang* as transcribed by Whisper.
            raw_translation: NLLB-200 machine translation in *target_lang*.
            source_lang:     Short ISO code: "en", "es", or "pt".
            target_lang:     Short ISO code: "en", "es", or "pt".

        Returns:
            VerificationResult — never raises; falls back gracefully on error.
        """
        timeout = get_settings().legal_verify_timeout
        src_label = LANG_LABELS.get(source_lang, source_lang)
        tgt_label = LANG_LABELS.get(target_lang, target_lang)

        system_prompt = (
            "You are a certified legal interpreter assistant specialising in "
            "courtroom proceedings. Your task is to verify that a machine "
            "translation preserves the precise legal meaning of the original "
            "utterance. You must respond with ONLY a single valid JSON object "
            "-- no markdown, no commentary, no extra text.\n\n"
            "JSON schema:\n"
            '{"verified_translation": "<string>", "accuracy_score": <float 0.0-1.0>, '
            '"accuracy_note": "<one sentence>"}\n\n'
            "Guidelines:\n"
            "- accuracy_score of 1.0 means the machine translation is legally "
            "precise and no changes are needed.\n"
            "- accuracy_score between 0.8-0.99 means minor rewording for legal "
            "clarity.\n"
            "- accuracy_score below 0.8 means substantial rephrasing was "
            "required to preserve legal meaning.\n"
            "- Never invent facts. Never add or remove legal claims.\n"
            "- If the original is informal speech, preserve its informal register "
            "in the verified translation."
        )

        user_message = (
            f"Original ({src_label}):\n{original_text}\n\n"
            f"Machine translation ({tgt_label}):\n{raw_translation}\n\n"
            "Please verify the translation and return the JSON result."
        )

        # ── Try Vertex AI (primary) ──────────────────────────────────────
        if LegalVerifierService._client is not None:
            try:
                LegalVerifierService._ensure_client_fresh()
                response = LegalVerifierService._client.chat.completions.create(
                    model=LegalVerifierService._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.1,
                    max_tokens=512,
                    timeout=timeout,
                )
                raw_json = response.choices[0].message.content or ""
                return self._parse_response(raw_json, raw_translation)
            except Exception as exc:
                logger.warning(
                    "Vertex API call failed (%s): %s — trying Groq fallback",
                    type(exc).__name__,
                    exc,
                )

        # ── Try Groq (fallback) ──────────────────────────────────────────
        if LegalVerifierService._groq_client is not None:
            try:
                response = LegalVerifierService._groq_client.chat.completions.create(
                    model=LegalVerifierService._groq_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.1,
                    max_tokens=512,
                    timeout=timeout,
                )
                raw_json = response.choices[0].message.content or ""
                return self._parse_response(raw_json, raw_translation)
            except Exception as exc:
                logger.warning(
                    "Groq API call also failed (%s): %s",
                    type(exc).__name__,
                    exc,
                )

        # ── Both providers failed ────────────────────────────────────────
        return self._fallback(raw_translation)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _parse_response(self, raw_json: str, raw_translation: str) -> VerificationResult:
        """Parse the LLM JSON response; return a fallback on any parse error."""
        try:
            clean = re.sub(r"```(?:json)?|```", "", raw_json).strip()
            data = json.loads(clean)

            verified = str(data.get("verified_translation", raw_translation)).strip()
            score = float(data.get("accuracy_score", 1.0))
            score = max(0.0, min(1.0, score))
            note = str(data.get("accuracy_note", "")).strip()

            if not verified:
                verified = raw_translation
            if not note:
                note = "No additional notes from verifier."

            return VerificationResult(
                verified_translation=verified,
                accuracy_score=round(score, 3),
                accuracy_note=note,
                raw_translation=raw_translation,
                used_fallback=False,
            )

        except Exception as exc:
            logger.warning("JSON parse failed: %s — raw: %r", exc, raw_json)
            return self._fallback(raw_translation)

    @staticmethod
    def _fallback(raw_translation: str) -> VerificationResult:
        """Return the raw NLLB translation unchanged when the LLM call fails."""
        return VerificationResult(
            verified_translation=raw_translation,
            accuracy_score=1.0,
            accuracy_note="Verification unavailable -- showing machine translation.",
            raw_translation=raw_translation,
            used_fallback=True,
        )


# ---------------------------------------------------------------------------
#  Module-level accessor
# ---------------------------------------------------------------------------

_legal_verifier: LegalVerifierService | None = None


def get_legal_verifier() -> LegalVerifierService | None:
    """
    Get (or create) the global LegalVerifierService instance.

    Returns None if neither Vertex AI nor Groq is configured:
      - Vertex requires USE_VERTEX_LEGAL_REVIEW=true AND VERTEX_PROJECT_ID
      - Groq requires GROQ_API_KEY

    Logs the real exception at ERROR level on init failure so it is
    visible in production logs instead of being silently swallowed.
    """
    global _legal_verifier

    s = get_settings()

    # Check if at least one provider is available.
    vertex_available = s.use_vertex_legal_review and s.vertex_project_id
    groq_available = bool(s.groq_api_key)

    if not vertex_available and not groq_available:
        return None

    # Return cached singleton if already initialised successfully.
    if _legal_verifier is not None:
        return _legal_verifier

    # Attempt initialisation — log the real error so it is visible in prod logs.
    try:
        _legal_verifier = LegalVerifierService()
        logger.info("[LegalVerifier] Service initialised successfully.")
    except Exception as exc:
        logger.error(
            "[LegalVerifier] Failed to initialise — falling back to stub. Error: %s",
            exc,
            exc_info=True,
        )
        return None

    return _legal_verifier
