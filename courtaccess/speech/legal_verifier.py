"""
courtaccess/speech/legal_verifier.py

Legal Context Verification Service — LLaMA 4 via Vertex AI MaaS.

Verifies that NLLB machine translations preserve legal meaning in real-time
courtroom speech.  Designed for short utterances with a strict 5 s timeout.

Note: this is separate from courtaccess.core.legal_review, which handles
batch document-level verification.  They serve different use cases and coexist.

Provides a singleton LegalVerifierService that:
  1. Calls LLaMA 4 (Scout or Maverick) on Vertex AI via the OpenAI-compatible
     endpoint.
  2. Returns a VerificationResult with a refined translation, accuracy score,
     and a one-sentence note.

Returns None from get_legal_verifier() if VERTEX_PROJECT_ID is not set, which
silently disables the feature throughout the speech pipeline.

Config (via courtaccess.core.config.Settings):
  VERTEX_PROJECT_ID       — GCP project ID (required; feature disabled if absent)
  VERTEX_LOCATION         — Vertex AI region (default: us-east5)
  VERTEX_LEGAL_LLM_MODEL  — model name (default: meta/llama-4-maverick-17b-128e-instruct-maas)
  LEGAL_VERIFY_TIMEOUT    — timeout in seconds (default: 5.0)
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
    Verifies machine-translated legal speech using LLaMA 4 on Vertex AI.

    Vertex AI exposes an OpenAI-compatible REST endpoint, so we use the
    standard `openai` Python SDK pointed at the Vertex base URL.  Auth is
    handled via Google Application Default Credentials (ADC).
    """

    _instance: Optional["LegalVerifierService"] = None
    _client = None
    _model: str = ""

    def __new__(cls) -> "LegalVerifierService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if LegalVerifierService._client is None:
            self._load_client()

    # ------------------------------------------------------------------ #
    #  Setup                                                              #
    # ------------------------------------------------------------------ #

    def _load_client(self) -> None:
        """Initialise the OpenAI client pointed at the Vertex AI endpoint.

        Auth strategy (matches legal_review.py _get_vertex_client):
          - Local dev: GCP_SERVICE_ACCOUNT_JSON contains the raw JSON of a
            service account key. Parsed via from_service_account_info().
          - Production (GCE / Cloud Run VM): GCP_SERVICE_ACCOUNT_JSON is empty
            or unset. Falls back to Application Default Credentials (ADC)
            provided by the attached compute service account automatically.
        """
        try:
            import google.auth
            import google.auth.transport.requests
            import openai

            s = get_settings()
            project = s.vertex_project_id
            location = s.vertex_location

            # Two auth modes:
            #   Local dev  — GCP_SERVICE_ACCOUNT_JSON is a path to a key file.
            #   Production — GCP_SERVICE_ACCOUNT_JSON is empty; ADC from VM SA.
            import os as _os

            sa_key_path = (s.gcp_service_account_json or "").strip()

            if sa_key_path and _os.path.isfile(sa_key_path):
                # Local dev — read the service-account key file from disk.
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
                # Production — use GCE metadata server (ADC).
                #
                # docker-compose builds GOOGLE_APPLICATION_CREDENTIALS as
                # '/app/${GOOGLE_APPLICATION_CREDENTIALS}'. When the env var is
                # empty in .env.production this expands to '/app/' — a directory,
                # not a file. google.auth.default() reads that env var first and
                # crashes with IsADirectoryError before reaching the metadata server.
                # Temporarily clear any invalid path so ADC falls through correctly.
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
                    # Restore env var so other components are unaffected
                    if _cleared_gac:
                        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gac

            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)

            base_url = (
                f"https://{location}-aiplatform.googleapis.com/v1beta1/"
                f"projects/{project}/locations/{location}/endpoints/openapi"
            )

            LegalVerifierService._client = openai.OpenAI(
                base_url=base_url,
                api_key=credentials.token,
            )

            model = s.vertex_legal_llm_model
            LegalVerifierService._model = model
            logger.info(
                "Client initialised (project=%s, location=%s, model=%s)",
                project,
                location,
                model,
            )

        except (KeyError, AttributeError):
            raise RuntimeError("[LegalVerifier] VERTEX_PROJECT_ID setting is required.") from None
        except Exception as exc:
            raise RuntimeError(f"[LegalVerifier] Failed to initialise Vertex AI client: {exc}") from exc

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

        try:
            client = LegalVerifierService._client
            model = LegalVerifierService._model

            response = client.chat.completions.create(
                model=model,
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
            logger.warning("API call failed (%s): %s", type(exc).__name__, exc)
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

    Returns None if:
      - USE_VERTEX_LEGAL_REVIEW is not set to "true", OR
      - VERTEX_PROJECT_ID is not set.

    Logs the real exception at ERROR level on init failure so it is
    visible in production logs instead of being silently swallowed.
    The permanent _init_attempted lock has been removed so that
    transient startup failures do not permanently disable the service.
    """
    global _legal_verifier

    s = get_settings()

    # Respect the feature flag — if disabled, skip entirely.
    if not s.use_vertex_legal_review:
        return None

    # Require the project ID to be configured.
    if not s.vertex_project_id:
        logger.warning("[LegalVerifier] VERTEX_PROJECT_ID is not set — Vertex legal review disabled.")
        return None

    # Return cached singleton if already initialised successfully.
    if _legal_verifier is not None:
        return _legal_verifier

    # Attempt initialisation — log the real error so it is visible in prod logs.
    try:
        _legal_verifier = LegalVerifierService()
        logger.info("[LegalVerifier] Vertex AI client initialised successfully.")
    except Exception as exc:
        logger.error(
            "[LegalVerifier] Failed to initialise Vertex AI client — falling back to stub. Error: %s",
            exc,
            exc_info=True,
        )
        return None

    return _legal_verifier
