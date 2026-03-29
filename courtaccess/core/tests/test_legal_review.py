"""
courtaccess/core/tests/test_legal_review.py

Tests for courtaccess.core.legal_review.LegalReviewer.

Test classes:
  TestReviewLegalTermsContract  — output contract shape (stub mode)
  TestVerifyBatch               — verify_batch behaviour (stub mode)
  TestBuildGlossarySnippet      — glossary matching logic
  TestStripFences               — JSON fence removal
  TestBuildVerificationPrompt   — prompt construction
  TestValidateResults           — hallucination guard
  TestCacheHelpers              — SHA-256 key + Redis key helpers
  TestRedisCache                — Redis hit / miss / degradation
  TestVertexRetry               — retry logic and bad-response handling

Integration tests (require real credentials) are marked:
  @pytest.mark.integration_vertex
"""

import json
from unittest.mock import MagicMock, patch

import httpx

from courtaccess.core.legal_review import (
    _NOT_VERIFIED_PREFIX,
    _VERTEX_MAX_RETRIES,
    LegalReviewer,
)
from courtaccess.languages import get_language_config

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_reviewer(glossary: dict | None = None) -> LegalReviewer:
    return LegalReviewer(get_language_config("spanish"), glossary or {})


def _make_real_reviewer(
    glossary: dict | None = None,
    redis_url: str = "redis://localhost:6379",
) -> LegalReviewer:
    """
    Reviewer with USE_VERTEX_LEGAL_REVIEW
    set via monkeypatching env vars. Used by Redis and retry tests
    so they exercise the real code paths without real credentials.
    """
    r = LegalReviewer(get_language_config("spanish"), glossary or {})
    r._use_real = True
    r._use_vertex = True
    r._vertex_project = "test-project"
    r._redis_url = redis_url
    return r


# ── review_legal_terms output contract ───────────────────────────────────────


class TestReviewLegalTermsContract:
    def test_returns_required_keys(self):
        result = _make_reviewer().review_legal_terms("El acusado se declara no culpable.")
        assert "status" in result
        assert "corrections" in result
        assert isinstance(result["corrections"], list)

    def test_stub_always_ok(self):
        result = _make_reviewer().review_legal_terms("Any text.")
        assert result["status"] == "ok"
        assert result["corrections"] == []

    def test_empty_text(self):
        result = _make_reviewer().review_legal_terms("")
        assert "status" in result

    def test_portuguese_config(self):
        reviewer = LegalReviewer(get_language_config("portuguese"), {})
        result = reviewer.review_legal_terms("O réu se declara inocente.")
        assert result["status"] in ("ok", "issues_found")


# ── verify_batch — stub mode ──────────────────────────────────────────────────


class TestVerifyBatch:
    def test_stub_returns_unchanged(self):
        r = _make_reviewer()
        originals = ["The defendant", "The plaintiff"]
        translated = ["El acusado", "El demandante"]
        assert r.verify_batch(originals, translated) == translated

    def test_empty_returns_empty(self):
        assert _make_reviewer().verify_batch([], []) == []

    def test_returns_same_length(self):
        r = _make_reviewer()
        result = r.verify_batch(["A", "B", "C"], ["X", "Y", "Z"])
        assert len(result) == 3

    def test_with_glossary(self):
        r = _make_reviewer({"defendant": "acusado"})
        originals = ["The defendant"]
        translated = ["El acusado"]
        assert r.verify_batch(originals, translated) == translated

    def test_stub_mode_skips_redis(self):
        """Stub mode must never touch Redis even if REDIS_URL is set."""
        r = _make_reviewer()
        r._redis_url = "redis://localhost:6379"
        with patch.object(r, "_get_redis") as mock_get:
            r.verify_batch(["The court"], ["El tribunal"])
            mock_get.assert_not_called()


# ── _build_glossary_snippet ───────────────────────────────────────────────────


class TestBuildGlossarySnippet:
    def test_finds_matching_term(self):
        r = _make_reviewer({"defendant": "acusado"})
        result = r._build_glossary_snippet(["The defendant pleads."])
        assert "defendant" in result
        assert "acusado" in result

    def test_no_match_returns_empty(self):
        r = _make_reviewer({"arraignment": "lectura de cargos"})
        result = r._build_glossary_snippet(["The weather is nice."])
        assert result == ""

    def test_empty_glossary_returns_empty(self):
        assert _make_reviewer()._build_glossary_snippet(["Hello"]) == ""

    def test_max_15_terms(self):
        glossary = {f"term{i}": f"valor{i}" for i in range(20)}
        r = _make_reviewer(glossary)
        result = r._build_glossary_snippet([f"term{i} " for i in range(20)])
        assert len([line for line in result.splitlines() if line.strip()]) <= 15

    def test_longer_terms_first(self):
        r = _make_reviewer(
            {
                "right to counsel": "derecho a la asistencia letrada",
                "right": "derecho",
            }
        )
        result = r._build_glossary_snippet(["The right to counsel is guaranteed."])
        assert "right to counsel" in result


# ── _strip_fences ─────────────────────────────────────────────────────────────


class TestStripFences:
    def test_strips_json_fence(self):
        assert LegalReviewer._strip_fences('```json\n["hi"]\n```') == '["hi"]'

    def test_strips_plain_fence(self):
        assert LegalReviewer._strip_fences('```\n["hi"]\n```') == '["hi"]'

    def test_no_fence_unchanged(self):
        assert LegalReviewer._strip_fences('["hi"]') == '["hi"]'

    def test_strips_whitespace(self):
        assert LegalReviewer._strip_fences('  ["hi"]  ') == '["hi"]'


# ── _build_verification_prompt ────────────────────────────────────────────────


class TestBuildVerificationPrompt:
    def setup_method(self):
        self.r = _make_reviewer()

    def test_contains_language_label(self):
        prompt = self.r._build_verification_prompt(["The defendant"], ["El acusado"], "")
        assert "Spanish" in prompt

    def test_contains_pair_numbers(self):
        prompt = self.r._build_verification_prompt(["Text 1", "Text 2"], ["Texto 1", "Texto 2"], "")
        assert "1." in prompt
        assert "2." in prompt

    def test_contains_glossary_when_provided(self):
        prompt = self.r._build_verification_prompt(["The defendant"], ["El acusado"], "  defendant → acusado")
        assert "defendant → acusado" in prompt

    def test_no_glossary_section_when_empty(self):
        prompt = self.r._build_verification_prompt(["The defendant"], ["El acusado"], "")
        assert "REFERENCE GLOSSARY" not in prompt

    def test_json_array_instruction(self):
        prompt = self.r._build_verification_prompt(["Text"], ["Texto"], "")
        assert "JSON array" in prompt


# ── _validate_results ─────────────────────────────────────────────────────────


class TestValidateResults:
    def setup_method(self):
        self.r = _make_reviewer()

    def test_accepts_valid_result(self):
        result = self.r._validate_results(
            ["The defendant"],
            ["El acusado"],
            ["El acusado principal"],
        )
        assert result == ["El acusado principal"]

    def test_rejects_empty_correction(self):
        result = self.r._validate_results(["The defendant"], ["El acusado"], [""])
        assert result == ["El acusado"]

    def test_rejects_extreme_ratio_too_long(self):
        result = self.r._validate_results(["Hi"], ["Hola"], ["Hola " * 100])
        assert result == ["Hola"]

    def test_rejects_extreme_ratio_too_short(self):
        result = self.r._validate_results(
            ["The defendant pleads not guilty today in court"],
            ["El acusado se declara no culpable hoy en el tribunal"],
            ["X"],
        )
        assert result == ["El acusado se declara no culpable hoy en el tribunal"]

    def test_whitespace_only_correction_falls_back(self):
        """Whitespace-only Llama output must fall back to NLLB — not treated as valid."""
        result = self.r._validate_results(
            ["The court shall decide."],
            ["El tribunal decidirá."],
            ["   "],
        )
        assert result == ["El tribunal decidirá."]


# ── cache helpers ─────────────────────────────────────────────────────────────


class TestCacheHelpers:
    def setup_method(self):
        self.r = _make_reviewer()

    def test_cache_key_is_sha256(self):
        key = self.r._cache_key("original", "translated")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_inputs_same_key(self):
        assert self.r._cache_key("a", "b") == self.r._cache_key("a", "b")

    def test_different_inputs_different_key(self):
        assert self.r._cache_key("a", "b") != self.r._cache_key("a", "c")

    def test_strips_whitespace_before_hashing(self):
        assert self.r._cache_key("a", "b") == self.r._cache_key("a ", " b")

    def test_redis_key_format(self):
        """Redis key must include version, language code, and SHA-256."""
        from courtaccess.core.legal_review import _CACHE_VERSION

        r = _make_reviewer()
        sha = r._cache_key("orig", "trans")
        rkey = r._redis_key(sha)
        assert str(_CACHE_VERSION) in rkey
        assert r.config.code in rkey
        assert sha in rkey
        assert rkey.startswith("ca:tlcache:")

    def test_redis_key_different_languages(self):
        """Same content in different languages must produce different Redis keys."""
        r_es = LegalReviewer(get_language_config("spanish"), {})
        r_pt = LegalReviewer(get_language_config("portuguese"), {})
        sha = r_es._cache_key("the court", "el tribunal")
        assert r_es._redis_key(sha) != r_pt._redis_key(sha)


# ── Redis cache ───────────────────────────────────────────────────────────────


class TestRedisCache:
    """
    All tests patch redis.Redis.from_url to avoid needing a real instance.
    _call_llama is also patched so no Vertex credentials are required.
    """

    def _mock_vertex_response(self, reviewer, results: list):
        """Patch _call_llama to return controlled results."""
        reviewer._call_llama = MagicMock(return_value=results)

    # ── Scenario A: Redis unavailable from the start ──────────────────────────

    def test_redis_connection_failure_degrades_gracefully(self):
        """If Redis refuses connection, _redis_available is set False and
        verify_batch still returns Llama results without crashing."""
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El tribunal decidirá."])

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", side_effect=ConnectionError("refused")):
            result = r.verify_batch(["The court shall decide."], ["El tribunal."])

        assert result == ["El tribunal decidirá."]
        assert r._redis_available is False

    # ── Scenario B: Redis up, cache miss → API called → stored ───────────────

    def test_cache_miss_calls_api_and_stores_result(self):
        """On a cache miss, _call_llama is called and result is stored in Redis."""
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El acusado se declara no culpable."])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None  # cache miss

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            result = r.verify_batch(["The defendant pleads not guilty."], ["El acusado."])

        assert result == ["El acusado se declara no culpable."]
        mock_redis.get.assert_called_once()
        mock_redis.set.assert_called_once()

        # Confirm the stored value is a plain string (not JSON-wrapped)
        stored_value = mock_redis.set.call_args[0][1]
        assert isinstance(stored_value, str)
        assert stored_value == "El acusado se declara no culpable."

    # ── Scenario C: Redis up, cache hit → API not called ─────────────────────

    def test_cache_hit_skips_api(self):
        """On a cache hit, _call_llama must never be called."""
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["SHOULD NOT BE RETURNED"])

        cached_translation = "El acusado se declara no culpable."
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = cached_translation.encode("utf-8")

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            result = r.verify_batch(["The defendant pleads not guilty."], ["El acusado."])

        assert result == [cached_translation]
        r._call_llama.assert_not_called()
        mock_redis.set.assert_not_called()

    def test_cache_hit_increments_hit_counter(self):
        r = _make_real_reviewer()
        self._mock_vertex_response(r, [])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = b"El tribunal."

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            r.verify_batch(["The court."], ["El tribunal."])

        assert r._cache_hits == 1
        assert r._cache_misses == 0

    def test_cache_miss_increments_miss_counter(self):
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El tribunal decidirá."])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            r.verify_batch(["The court shall decide."], ["El tribunal."])

        assert r._cache_hits == 0
        assert r._cache_misses == 1

    # ── Scenario D: Redis fails mid-job on get ────────────────────────────────

    def test_redis_get_failure_mid_job_disables_cache(self):
        """If Redis.get raises mid-job, _redis_available is set False
        and Llama is called directly for remaining spans."""
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El tribunal decidirá."])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.side_effect = ConnectionError("lost connection")

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            result = r.verify_batch(["The court shall decide."], ["El tribunal."])

        assert result == ["El tribunal decidirá."]
        assert r._redis_available is False

    # ── Scenario E: Redis fails mid-job on set ────────────────────────────────

    def test_redis_set_failure_mid_job_disables_cache(self):
        """If Redis.set raises after an API call, _redis_available becomes False
        but the Llama result is still returned correctly."""
        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El tribunal decidirá."])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None  # cache miss
        mock_redis.set.side_effect = ConnectionError("lost on write")

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            result = r.verify_batch(["The court shall decide."], ["El tribunal."])

        assert result == ["El tribunal decidirá."]
        assert r._redis_available is False

    # ── TTL is set on store ───────────────────────────────────────────────────

    def test_redis_set_includes_ttl(self):
        """Stored entries must have an expiry (ex=) set."""
        from courtaccess.core.legal_review import _CACHE_TTL_SECONDS

        r = _make_real_reviewer()
        self._mock_vertex_response(r, ["El acusado."])

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.get.return_value = None

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url", return_value=mock_redis):
            r.verify_batch(["The defendant."], ["El acusado."])

        call_kwargs = mock_redis.set.call_args[1]
        assert "ex" in call_kwargs
        assert call_kwargs["ex"] == _CACHE_TTL_SECONDS

    # ── No REDIS_URL → Redis is never attempted ───────────────────────────────

    def test_no_redis_url_skips_redis_entirely(self):
        """If REDIS_URL is empty, _get_redis must return None without trying."""
        r = _make_real_reviewer(redis_url="")
        self._mock_vertex_response(r, ["El tribunal."])

        import redis as redis_lib

        with patch.object(redis_lib.Redis, "from_url") as mock_from_url:
            r.verify_batch(["The court."], ["El tribunal."])
            mock_from_url.assert_not_called()


# ── Vertex AI retry logic ─────────────────────────────────────────────────────


class TestVertexRetry:
    """
    Tests for _call_vertex retry and bad-response handling.
    _get_vertex_client is patched so no GCP credentials are needed.
    """

    def _make_vertex_reviewer(self) -> LegalReviewer:
        r = _make_reviewer()
        r._use_real = True
        r._use_vertex = True
        r._vertex_project = "test-project"
        return r

    def _fake_client(self, content: str):
        """Build a mock OpenAI-compatible client returning `content`."""
        choice = MagicMock()
        choice.message.content = content
        resp = MagicMock()
        resp.choices = [choice]
        client = MagicMock()
        client.chat.completions.create.return_value = resp
        return client

    # ── Bad response: JSON error → immediate return, no retry ────────────────

    def test_json_decode_error_returns_nllb_immediately(self):
        r = self._make_vertex_reviewer()
        with patch.object(r, "_get_vertex_client", return_value=self._fake_client("not valid json")):
            result = r._call_vertex(["The court."], ["El tribunal."], "")
        assert result == ["El tribunal."]

    def test_json_error_does_not_retry(self):
        """JSONDecodeError is a bad response — _get_vertex_client called exactly once."""
        r = self._make_vertex_reviewer()
        mock_client = self._fake_client("not valid json")
        with patch.object(r, "_get_vertex_client", return_value=mock_client) as mock_get:
            r._call_vertex(["The court."], ["El tribunal."], "")
        assert mock_get.call_count == 1

    # ── Bad response: result is not a list → immediate return ────────────────

    def test_non_list_response_returns_nllb_immediately(self):
        r = self._make_vertex_reviewer()
        with patch.object(r, "_get_vertex_client", return_value=self._fake_client('{"key": "value"}')):
            result = r._call_vertex(["The court."], ["El tribunal."], "")
        assert result == ["El tribunal."]

    # ── Bad response: length mismatch → immediate return ─────────────────────

    def test_length_mismatch_returns_nllb_immediately(self):
        r = self._make_vertex_reviewer()
        # Send 2 spans but Llama returns only 1
        with patch.object(r, "_get_vertex_client", return_value=self._fake_client('["only one item"]')):
            result = r._call_vertex(
                ["The court.", "The defendant."],
                ["El tribunal.", "El acusado."],
                "",
            )
        assert result == ["El tribunal.", "El acusado."]

    def test_length_mismatch_does_not_retry(self):
        r = self._make_vertex_reviewer()
        with patch.object(r, "_get_vertex_client", return_value=self._fake_client('["only one item"]')) as mock_get:
            r._call_vertex(["A.", "B."], ["X.", "Y."], "")
        assert mock_get.call_count == 1

    # ── Retryable: connection error ───────────────────────────────────────────

    def test_connection_error_retries_up_to_max(self):
        r = self._make_vertex_reviewer()
        with (
            patch.object(r, "_get_vertex_client", side_effect=ConnectionError("timeout")) as mock_get,
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            result = r._call_vertex(["The court."], ["El tribunal."], "")
        assert mock_get.call_count == _VERTEX_MAX_RETRIES
        assert result == [f"{_NOT_VERIFIED_PREFIX} El tribunal."]

    def test_connection_error_result_has_not_verified_prefix(self):
        r = self._make_vertex_reviewer()
        with (
            patch.object(r, "_get_vertex_client", side_effect=ConnectionError("down")),
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            result = r._call_vertex(["The court."], ["El tribunal."], "")
        assert result[0].startswith(_NOT_VERIFIED_PREFIX)

    def test_not_verified_prefix_applied_to_all_spans_in_batch(self):
        """Every span in the batch must get the warning prefix on exhausted retries."""
        r = self._make_vertex_reviewer()
        originals = ["The court.", "The defendant.", "The plaintiff."]
        translated = ["El tribunal.", "El acusado.", "El demandante."]
        with (
            patch.object(r, "_get_vertex_client", side_effect=ConnectionError("down")),
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            result = r._call_vertex(originals, translated, "")
        assert len(result) == 3
        assert all(r.startswith(_NOT_VERIFIED_PREFIX) for r in result)

    # ── Retryable: HTTP 503 ───────────────────────────────────────────────────

    def test_http_503_retries_up_to_max(self):
        r = self._make_vertex_reviewer()
        http_resp = MagicMock()
        http_resp.status_code = 503
        with (
            patch.object(
                r,
                "_get_vertex_client",
                side_effect=httpx.HTTPStatusError("503", request=MagicMock(), response=http_resp),
            ) as mock_get,
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            r._call_vertex(["The court."], ["El tribunal."], "")
        assert mock_get.call_count == _VERTEX_MAX_RETRIES

    # ── Retryable: 401 token expiry → refresh + retry ─────────────────────────

    def test_401_triggers_credential_refresh(self):
        """On 401, _vertex_credentials is cleared so _get_vertex_client
        rebuilds them on the next attempt."""
        r = self._make_vertex_reviewer()
        r._vertex_credentials = MagicMock()  # pre-set so we can check it's cleared

        call_count = 0

        def _side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("401 UNAUTHENTICATED")
            return self._fake_client('["El tribunal decidirá."]')

        with (
            patch.object(r, "_get_vertex_client", side_effect=_side_effect),
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            result = r._call_vertex(["The court shall decide."], ["El tribunal."], "")

        assert result == ["El tribunal decidirá."]
        assert r._vertex_credentials is None  # cleared on token error

    # ── Success path still works ──────────────────────────────────────────────

    def test_successful_response_returned_correctly(self):
        r = self._make_vertex_reviewer()
        with patch.object(
            r, "_get_vertex_client", return_value=self._fake_client('["El acusado se declara no culpable."]')
        ):
            result = r._call_vertex(
                ["The defendant pleads not guilty."],
                ["El acusado."],
                "",
            )
        assert result == ["El acusado se declara no culpable."]

    def test_successful_response_goes_through_validate_results(self):
        """Results still pass through the hallucination guard even on success."""
        r = self._make_vertex_reviewer()
        # Llama returns a ridiculously long string — should be rejected
        long_resp = json.dumps(["word " * 200])
        with patch.object(r, "_get_vertex_client", return_value=self._fake_client(long_resp)):
            result = r._call_vertex(["Hi."], ["Hola."], "")
        assert result == ["Hola."]  # hallucination guard kicked in

    # ── Non-retryable unknown error → immediate return ────────────────────────

    def test_unknown_error_does_not_retry(self):
        r = self._make_vertex_reviewer()
        with (
            patch.object(r, "_get_vertex_client", side_effect=ValueError("unexpected")) as mock_get,
            patch("courtaccess.core.legal_review.time.sleep"),
        ):
            result = r._call_vertex(["The court."], ["El tribunal."], "")
        assert mock_get.call_count == 1
        assert result == ["El tribunal."]
