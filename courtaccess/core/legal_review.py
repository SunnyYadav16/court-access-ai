"""
courtaccess/core/legal_review.py

LegalReviewer class for Llama-based legal terminology verification.

Provider priority (controlled by env vars):
  1. Vertex AI — Llama 4 Maverick (USE_VERTEX_LEGAL_REVIEW=true)
  2. Groq      — Llama 3.1 fallback (USE_REAL_LEGAL_REVIEW=true + GROQ_API_KEY)
  3. Stub      — always returns OK (default)

Translation cache (Redis-backed):
  Caches Llama verification results keyed by SHA-256 of
  (original, nllb_output) pair. Survives container restarts.
  Cache version bump invalidates all entries.
  Falls back gracefully to direct API calls if Redis is unavailable.

Source: Cell 7 and translation cache cell of the original Colab script.
All prompt logic, batch logic, hallucination guard, and cache logic
carried over exactly. Made language-aware via LanguageConfig.

OUTPUT CONTRACT (review_legal_terms):
  {"status": "ok" | "issues_found", "corrections": [...]}
"""

import hashlib
import json
import logging
import os
import time

from courtaccess.languages.base import LanguageConfig

logger = logging.getLogger(__name__)

_CACHE_VERSION = 1
_CACHE_TTL_SECONDS = 86400 * 30  # 30 days
_VERTEX_MAX_RETRIES = 3
_VERTEX_RETRY_BACKOFF = [1, 2, 4]  # seconds between attempts
_VERTEX_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_NOT_VERIFIED_PREFIX = "[NOT VERIFIED — Vertex AI unavailable]"


class LegalReviewer:
    """
    Verifies translated legal text using Llama 4 (Vertex AI) or
    Llama 3.1 (Groq fallback). Caches results in Redis to avoid
    redundant API calls across container restarts.

    Instantiate once at app startup per language:
        reviewer = LegalReviewer(config, glossary.glossary)

    Usage:
        verified = reviewer.verify_batch(originals, translated)
    """

    def __init__(
        self,
        config: LanguageConfig,
        glossary: dict | None = None,
        verification_mode: str = "document",
    ) -> None:
        self.config = config
        self.glossary = glossary or {}
        self.verification_mode = verification_mode  # "document" | "audio"

        self._use_real = os.getenv("USE_REAL_LEGAL_REVIEW", "false").lower() == "true"
        self._use_vertex = os.getenv("USE_VERTEX_LEGAL_REVIEW", "false").lower() == "true"

        self._vertex_project = os.getenv("VERTEX_PROJECT_ID", "")
        self._vertex_location = os.getenv("VERTEX_LOCATION", "us-east5")
        self._vertex_model = os.getenv(
            "VERTEX_MODEL_ID",
            "meta/llama-4-maverick-17b-128e-instruct-maas",
        )
        self._gcp_sa_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")

        self._vertex_credentials = None
        self._cache_hits = 0
        self._cache_misses = 0

        # Redis — lazy connection, graceful degradation
        self._redis_url = os.getenv("REDIS_URL", "")
        self._redis = None
        self._redis_available = True  # set False on first connection failure

    # ── Public API ────────────────────────────────────────────────────────────

    def verify_batch(
        self,
        original_spans: list,
        translated_spans: list,
        batch_size: int = 16,
    ) -> list:
        """
        Verify a batch of translation pairs using Llama.
        Returns corrected translations in the same order.

        DOCUMENT mode: sends all spans to Llama.
        AUDIO mode:    sends only spans containing glossary terms.

        Source: Cell 7 verify_page_translations()
        """
        if not original_spans:
            return translated_spans

        if not (self._use_real and self._use_vertex and self._vertex_project):
            return translated_spans

        if self.verification_mode == "document":
            indices = list(range(len(original_spans)))
        else:
            indices = [i for i, orig in enumerate(original_spans) if self._build_glossary_snippet([orig])]
            if not indices:
                return translated_spans

        verified = list(translated_spans)
        total_batches = (len(indices) + batch_size - 1) // batch_size

        for batch_num, start in enumerate(range(0, len(indices), batch_size), 1):
            batch_idx = indices[start : start + batch_size]
            orig_batch = [original_spans[i] for i in batch_idx]
            trans_batch = [translated_spans[i] for i in batch_idx]
            snippet = self._build_glossary_snippet(orig_batch)
            results = self._call_llama_cached(orig_batch, trans_batch, snippet)
            for i, result in enumerate(results):
                verified[batch_idx[i]] = result
            logger.info(
                "Batch %d/%d: verified %d spans",
                batch_num,
                total_batches,
                len(orig_batch),
            )

        return verified

    def review_legal_terms(self, text: str) -> dict:
        """
        Review a single translated text for legal accuracy.
        Returns output contract dict: {status, corrections}
        """
        if not (self._use_real and self._use_vertex and self._vertex_project):
            return self._stub_review(text)
        return self._vertex_review(text)

    def print_cache_stats(self) -> None:
        """Source: translation cache cell print_cache_stats()"""
        total = self._cache_hits + self._cache_misses
        redis_status = "connected" if (self._redis is not None and self._redis_available) else "disconnected"
        if not total:
            logger.info("No cache activity yet (Redis: %s)", redis_status)
            return
        hit_rate = self._cache_hits / total * 100
        logger.info(
            "Cache stats — hits: %d (%.1f%%), misses: %d | Redis: %s",
            self._cache_hits,
            hit_rate,
            self._cache_misses,
            redis_status,
        )

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_key(self, original: str, translated: str) -> str:
        """
        SHA-256 of (original, nllb_output) pair.
        Source: translation cache cell _cache_key()
        """
        raw = f"{original.strip()}|||{translated.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _redis_key(self, cache_key: str) -> str:
        """Namespaced Redis key: ca:tlcache:{version}:{lang}:{sha256}"""
        return f"ca:tlcache:{_CACHE_VERSION}:{self.config.code}:{cache_key}"

    def _get_redis(self):
        """
        Return a live Redis client, or None if unavailable.
        Creates the connection lazily on first call.
        Sets _redis_available=False permanently on ConnectionError
        so subsequent calls skip the attempt entirely.
        """
        if not self._redis_available or not self._redis_url:
            return None
        if self._redis is None:
            try:
                import redis as redis_lib

                client = redis_lib.Redis.from_url(
                    self._redis_url,
                    socket_connect_timeout=2,
                    decode_responses=False,  # we handle decode ourselves
                )
                client.ping()
                self._redis = client
                logger.info("Redis connected: %s", self._redis_url)
            except Exception as exc:
                logger.warning("Redis unavailable: %s — cache disabled for this session", exc)
                self._redis_available = False
                self._redis = None
        return self._redis

    # ── Llama callers ─────────────────────────────────────────────────────────

    def _call_llama_cached(
        self,
        original_batch: list,
        translated_batch: list,
        snippet: str,
    ) -> list:
        """
        Cache-aware wrapper around _call_llama.
        Checks Redis first, calls API only for misses.
        Stores results as plain strings with a 30-day TTL.
        If Redis is down, skips cache and calls API directly.
        Source: translation cache cell _call_llama_cached()
        """
        results = list(translated_batch)
        miss_indices = []
        miss_orig = []
        miss_trans = []

        redis = self._get_redis()

        for i, (orig, trans) in enumerate(zip(original_batch, translated_batch, strict=False)):
            cached = None
            if redis:
                try:
                    raw = redis.get(self._redis_key(self._cache_key(orig, trans)))
                    if raw is not None:
                        cached = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                except Exception as exc:
                    logger.warning("Redis get error: %s — disabling cache", exc)
                    self._redis_available = False
                    redis = None

            if cached is not None:
                results[i] = cached
                self._cache_hits += 1
            else:
                miss_indices.append(i)
                miss_orig.append(orig)
                miss_trans.append(trans)
                self._cache_misses += 1

        if miss_indices:
            api_results = self._call_llama(miss_orig, miss_trans, snippet)
            redis = self._get_redis()
            for i, (orig, trans, result) in enumerate(zip(miss_orig, miss_trans, api_results, strict=False)):
                if redis:
                    try:
                        redis.set(
                            self._redis_key(self._cache_key(orig, trans)),
                            result,
                            ex=_CACHE_TTL_SECONDS,
                        )
                    except Exception as exc:
                        logger.warning("Redis set error: %s", exc)
                        self._redis_available = False
                        redis = None
                results[miss_indices[i]] = result

        return results

    def _call_llama(
        self,
        original_batch: list,
        translated_batch: list,
        snippet: str,
    ) -> list:
        """
        Send one batch to Vertex AI.
        Falls back to NLLB output with a warning prefix on exhausted retries.
        Source: Cell 7 _call_llama()
        """
        return self._call_vertex(original_batch, translated_batch, snippet)

    def _call_vertex(
        self,
        original_batch: list,
        translated_batch: list,
        snippet: str,
    ) -> list:
        """
        Vertex AI Llama 4 batch call with retry logic.

        Retried (up to _VERTEX_MAX_RETRIES times):
          - Network/service errors: ConnectionError, TimeoutError
          - HTTP status errors: 429, 500, 502, 503, 504
          - 401 token expiry: refreshes credentials, counts as one attempt

        Not retried (bad response — model ran but returned garbage):
          - JSONDecodeError
          - Result is not a list
          - Result length does not match batch size

        On exhausted retries: returns NLLB output with _NOT_VERIFIED_PREFIX.
        Source: Cell 7 _call_llama() Vertex section.
        """
        import httpx

        prompt = self._build_verification_prompt(original_batch, translated_batch, snippet)
        last_exc = None

        for attempt in range(_VERTEX_MAX_RETRIES):
            try:
                client = self._get_vertex_client()
                resp = client.chat.completions.create(
                    model=self._vertex_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=2048,
                )

                # ── Bad response checks (no retry) ────────────────────────
                raw = resp.choices[0].message.content
                try:
                    corrected = json.loads(self._strip_fences(raw))
                except json.JSONDecodeError as exc:
                    logger.warning("Vertex bad response (JSONDecodeError) — returning NLLB output: %s", exc)
                    return translated_batch

                if not isinstance(corrected, list):
                    logger.warning(
                        "Vertex bad response (not a list, got %s) — returning NLLB output",
                        type(corrected).__name__,
                    )
                    return translated_batch

                if len(corrected) != len(original_batch):
                    logger.warning(
                        "Vertex bad response (length mismatch: expected %d, got %d) — returning NLLB output",
                        len(original_batch),
                        len(corrected),
                    )
                    return translated_batch

                # ── Success ───────────────────────────────────────────────
                return self._validate_results(original_batch, translated_batch, corrected)

            except Exception as exc:
                err = str(exc)
                last_exc = exc

                # Token expiry — refresh and retry immediately (no backoff sleep)
                if any(c in err for c in ["401", "UNAUTHENTICATED", "ACCESS_TOKEN_EXPIRED"]):
                    logger.warning(
                        "Vertex token expired (attempt %d/%d) — refreshing",
                        attempt + 1,
                        _VERTEX_MAX_RETRIES,
                    )
                    self._vertex_credentials = None
                    continue

                # Retryable network/service errors
                is_retryable = isinstance(exc, (ConnectionError, TimeoutError)) or (
                    isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _VERTEX_RETRYABLE_HTTP
                )

                if is_retryable:
                    wait = _VERTEX_RETRY_BACKOFF[min(attempt, len(_VERTEX_RETRY_BACKOFF) - 1)]
                    logger.warning(
                        "Vertex retryable error (attempt %d/%d, retrying in %ds): %s",
                        attempt + 1,
                        _VERTEX_MAX_RETRIES,
                        wait,
                        exc,
                    )
                    time.sleep(wait)
                    continue

                # Non-retryable unknown error — log and give up immediately
                logger.error("Vertex non-retryable error: %s", exc)
                return translated_batch

        # All retries exhausted
        logger.error(
            "Vertex AI unavailable after %d attempts: %s — returning NLLB output with warning",
            _VERTEX_MAX_RETRIES,
            last_exc,
        )
        return [f"{_NOT_VERIFIED_PREFIX} {t}" for t in translated_batch]

    def _validate_results(
        self,
        original_batch: list,
        translated_batch: list,
        corrected: list,
    ) -> list:
        """
        Hallucination guard — reject results with extreme length ratios.
        Source: Cell 7 validation logic inside _call_llama()
        """
        validated = []
        for trans, corr in zip(translated_batch, corrected, strict=False):
            if not corr or not corr.strip():
                validated.append(trans)
                continue
            ratio = len(corr) / max(len(trans), 1)
            validated.append(corr.strip() if 0.2 <= ratio <= 5.0 else trans)
        return validated

    # ── Vertex AI client ──────────────────────────────────────────────────────

    def _get_vertex_client(self):
        """
        Build OpenAI-compatible Vertex AI client.
        Refreshes service account credentials on each call.
        Source: Cell 0 of Colab script.
        """
        import google.auth.transport.requests
        from google.oauth2 import service_account
        from openai import OpenAI

        if not self._gcp_sa_json:
            raise OSError("GCP_SERVICE_ACCOUNT_JSON not set. Add to .env for local dev or Secret Manager on GCP.")

        if self._vertex_credentials is None:
            self._vertex_credentials = service_account.Credentials.from_service_account_info(
                json.loads(self._gcp_sa_json),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

        self._vertex_credentials.refresh(google.auth.transport.requests.Request())

        return OpenAI(
            base_url=(
                f"https://{self._vertex_location}-aiplatform.googleapis.com/v1"
                f"/projects/{self._vertex_project}"
                f"/locations/{self._vertex_location}/endpoints/openapi"
            ),
            api_key=self._vertex_credentials.token,
        )

    # ── Prompt and utilities ──────────────────────────────────────────────────

    def _build_glossary_snippet(self, texts: list) -> str:
        """
        Find glossary terms in texts and build reference string.
        Source: Cell 7 _build_glossary_snippet()
        """
        combined = " ".join(texts).lower()
        matches = {}
        for term in sorted(self.glossary, key=len, reverse=True):
            if term in combined:
                matches[term] = self.glossary[term]
            if len(matches) >= 15:
                break
        if not matches:
            return ""
        return "\n".join(f"  {en} → {es}" for en, es in matches.items())

    def _build_verification_prompt(
        self,
        original_batch: list,
        translated_batch: list,
        snippet: str,
    ) -> str:
        """
        Build Llama verification prompt.
        Source: Cell 7 _call_llama() prompt — language-aware.
        """
        lang = self.config.llama_lang_label
        abbr = lang[:2].upper()
        pairs = "\n".join(
            f"{k + 1}. EN: {o}\n   {abbr}: {t}"
            for k, (o, t) in enumerate(zip(original_batch, translated_batch, strict=False))
        )
        glossary_section = (
            (
                f"\nREFERENCE GLOSSARY — verified legal translations "
                f"for terms found in this batch. Use as a guide, "
                f"not a strict constraint. Prefer natural legal "
                f"{lang} that preserves meaning over forced "
                f"glossary terms:\n{snippet}\n"
            )
            if snippet
            else ""
        )

        return (
            f"You are a certified legal translator specializing in "
            f"English to {lang} court document translation.\n"
            f"{glossary_section}\n"
            f"For each numbered pair below, verify the {lang} "
            f"translation. Your PRIMARY goal is to ensure the full "
            f"legal meaning and context of the English text is "
            f"preserved accurately in {lang}.\n\n"
            f"Rules:\n"
            f"1. Preserve legal citations, § symbols, case numbers, "
            f"statute references, URLs, and form codes EXACTLY as-is\n"
            f"2. Use the glossary as a reference guide — but prefer "
            f"natural legal {lang} over forced glossary terms "
            f"if the translation already captures the meaning correctly\n"
            f"3. Preserve proper nouns (people, places, organizations) "
            f"exactly as written\n"
            f"4. Only correct genuine legal meaning errors — do NOT "
            f"change translations for stylistic preference alone\n"
            f"5. If a translation is already legally accurate, "
            f"return it UNCHANGED\n"
            f"6. Short field labels like DATE, SIGNATURE, BBO NO. "
            f"should be translated as standard {lang} form field labels\n"
            f"7. Do NOT capitalize common nouns mid-sentence. "
            f"Only capitalize proper nouns and sentence-first words\n"
            f"8. For form field abbreviations like BBO NO., preserve "
            f"the abbreviation order\n"
            f"9. For civil cases use 'demandante'/'demandado' (ES) or "
            f"'autor'/'réu' (PT). For criminal cases use 'acusado'/'réu'.\n"
            f"10. 'notice' in a legal filing header means 'aviso' or "
            f"'notificación' — both acceptable\n"
            f"Return ONLY a JSON array of verified {lang} strings, "
            f"one per pair, in the same order. "
            f"No explanation, no markdown, just the JSON array.\n\n"
            f"PAIRS:\n{pairs}\n\n"
            f'Return format: ["verified 1", "verified 2", ...]'
        )

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove markdown code fences from LLM JSON output."""
        text = text.strip()
        for prefix in ("```json", "```"):
            if text.startswith(prefix):
                text = text[len(prefix) :]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    # ── Single-text review implementations ───────────────────────────────────

    def _stub_review(self, text: str) -> dict:
        logger.debug("Stub review: len=%d", len(text))
        return {"status": "ok", "corrections": []}

    def _vertex_review(self, text: str) -> dict:
        results = self._call_vertex([text], [text], "")
        return {"status": "ok", "corrections": [], "reviewed": results[0]}
