"""
Unit tests for courtaccess/core/legal_review.py

Class under test: LegalReviewer

Functions under test:
  _cache_key            — deterministic SHA-256 hash
  _redis_key            — namespaced Redis key format
  _build_glossary_snippet — glossary term extraction
  _strip_fences         — @staticmethod, removes markdown fences from LLM output
  _validate_results     — hallucination guard (ratio filter)
  _build_verification_prompt — prompt construction
  review_legal_terms    — stubs in stub mode; routes to Vertex in real mode
  verify_batch          — passthrough in stub mode; batched Vertex in real mode
  _call_llama_cached    — cache-aware Vertex caller (mocked Redis + _call_vertex)
  _get_redis            — lazy connection with graceful degradation

Design notes:
  - .env has USE_VERTEX_LEGAL_REVIEW=true — pytest-dotenv loads this into
    os.environ at session start. All fixtures override it to "false" via
    monkeypatch.setenv so no real Vertex calls are made.
  - LegalReviewer._get_vertex_client and redis are never called in these tests;
    they are replaced by MagicMock where needed.
  - Pure-function static/instance methods are tested without mocking.
"""

from unittest.mock import MagicMock, patch

import pytest

from courtaccess.core.legal_review import _CACHE_VERSION, LegalReviewer
from courtaccess.languages.base import LanguageConfig

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def lang_config():
    return LanguageConfig(
        code="spanish",
        display_name="Spanish (Español)",
        nllb_source="eng_Latn",
        nllb_target="spa_Latn",
        glossary_path="/dev/null",
        llama_lang_label="Spanish",
    )


@pytest.fixture()
def reviewer(lang_config, monkeypatch):
    """Stub-mode LegalReviewer — Vertex disabled, Redis URL cleared."""
    monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "")
    monkeypatch.setenv("REDIS_URL", "")
    return LegalReviewer(lang_config, glossary={"defendant": "acusado", "plaintiff": "demandante"})


@pytest.fixture()
def reviewer_with_glossary(lang_config, monkeypatch):
    """Stub-mode reviewer with a richer glossary for snippet tests."""
    monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
    monkeypatch.setenv("VERTEX_PROJECT_ID", "")
    monkeypatch.setenv("REDIS_URL", "")
    glossary = {
        "defendant": "acusado",
        "plaintiff": "demandante",
        "judgment": "sentencia",
        "motion": "moción",
        "hearing": "audiencia",
    }
    return LegalReviewer(lang_config, glossary=glossary)


# ─────────────────────────────────────────────────────────────────────────────
# Constructor — env var handling
# ─────────────────────────────────────────────────────────────────────────────

class TestConstructor:

    def test_vertex_max_retries_defaults_to_3_when_not_set(self, lang_config, monkeypatch):
        monkeypatch.delenv("VERTEX_MAX_RETRIES", raising=False)
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r._vertex_max_retries == 3

    def test_vertex_max_retries_parsed_from_env(self, lang_config, monkeypatch):
        monkeypatch.setenv("VERTEX_MAX_RETRIES", "5")
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r._vertex_max_retries == 5

    def test_vertex_max_retries_defaults_to_3_on_bad_value(self, lang_config, monkeypatch):
        monkeypatch.setenv("VERTEX_MAX_RETRIES", "not_a_number")
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r._vertex_max_retries == 3

    def test_vertex_max_retries_minimum_is_1(self, lang_config, monkeypatch):
        monkeypatch.setenv("VERTEX_MAX_RETRIES", "0")
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r._vertex_max_retries == 1

    def test_use_vertex_false_when_env_not_true(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r._use_vertex_legal_review is False

    def test_glossary_defaults_to_empty_dict(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        r = LegalReviewer(lang_config)
        assert r.glossary == {}

    def test_verification_mode_defaults_to_document(self, reviewer):
        assert reviewer.verification_mode == "document"

    def test_cache_counters_start_at_zero(self, reviewer):
        assert reviewer._cache_hits == 0
        assert reviewer._cache_misses == 0


# ─────────────────────────────────────────────────────────────────────────────
# _cache_key — deterministic hash
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheKey:

    def test_same_inputs_produce_same_key(self, reviewer):
        k1 = reviewer._cache_key("defendant appeared", "acusado apareció")
        k2 = reviewer._cache_key("defendant appeared", "acusado apareció")
        assert k1 == k2

    def test_different_inputs_produce_different_keys(self, reviewer):
        k1 = reviewer._cache_key("plaintiff filed", "demandante presentó")
        k2 = reviewer._cache_key("defendant fled", "acusado huyó")
        assert k1 != k2

    def test_order_matters(self, reviewer):
        k1 = reviewer._cache_key("original", "translated")
        k2 = reviewer._cache_key("translated", "original")
        assert k1 != k2

    def test_leading_trailing_whitespace_stripped(self, reviewer):
        k1 = reviewer._cache_key("text", "translation")
        k2 = reviewer._cache_key("  text  ", "  translation  ")
        assert k1 == k2

    def test_returns_hex_string(self, reviewer):
        key = reviewer._cache_key("hello", "hola")
        int(key, 16)  # raises ValueError if not valid hex

    def test_is_sha256_length(self, reviewer):
        key = reviewer._cache_key("hello", "hola")
        assert len(key) == 64


# ─────────────────────────────────────────────────────────────────────────────
# _redis_key — key formatting
# ─────────────────────────────────────────────────────────────────────────────

class TestRedisKey:

    def test_key_contains_cache_version(self, reviewer):
        rk = reviewer._redis_key("abc123")
        assert f":{_CACHE_VERSION}:" in rk

    def test_key_contains_language_code(self, reviewer):
        rk = reviewer._redis_key("abc123")
        assert ":spanish:" in rk

    def test_key_contains_cache_hash(self, reviewer):
        sha = "deadbeef1234"
        rk = reviewer._redis_key(sha)
        assert sha in rk

    def test_key_starts_with_namespace(self, reviewer):
        rk = reviewer._redis_key("abc")
        assert rk.startswith("ca:tlcache:")

    def test_full_key_format(self, reviewer):
        sha = "abc123"
        expected = f"ca:tlcache:{_CACHE_VERSION}:spanish:{sha}"
        assert reviewer._redis_key(sha) == expected


# ─────────────────────────────────────────────────────────────────────────────
# _build_glossary_snippet
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildGlossarySnippet:

    def test_matching_term_included_in_snippet(self, reviewer_with_glossary):
        snippet = reviewer_with_glossary._build_glossary_snippet(["The defendant was present."])
        assert "defendant" in snippet
        assert "acusado" in snippet

    def test_non_matching_term_excluded(self, reviewer_with_glossary):
        snippet = reviewer_with_glossary._build_glossary_snippet(["The weather is nice."])
        assert snippet == ""

    def test_case_insensitive_matching(self, reviewer_with_glossary):
        snippet = reviewer_with_glossary._build_glossary_snippet(["DEFENDANT fled the scene."])
        assert "defendant" in snippet

    def test_multiple_matching_terms(self, reviewer_with_glossary):
        snippet = reviewer_with_glossary._build_glossary_snippet(
            ["The plaintiff requested a hearing on the motion."]
        )
        assert "plaintiff" in snippet or "hearing" in snippet or "motion" in snippet

    def test_empty_texts_returns_empty_snippet(self, reviewer_with_glossary):
        snippet = reviewer_with_glossary._build_glossary_snippet([])
        assert snippet == ""

    def test_empty_glossary_returns_empty_snippet(self, reviewer):
        # reviewer fixture has a small glossary but use texts with no matches
        reviewer.glossary = {}
        snippet = reviewer._build_glossary_snippet(["The case was dismissed."])
        assert snippet == ""

    def test_max_15_terms_returned(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "false")
        monkeypatch.setenv("REDIS_URL", "")
        # Glossary with 20 entries, all matching
        glossary = {f"term{i}": f"termino{i}" for i in range(20)}
        text = " ".join(glossary.keys())
        r = LegalReviewer(lang_config, glossary=glossary)
        snippet = r._build_glossary_snippet([text])
        # Each line is "  term → translation" — count lines
        lines = [ln for ln in snippet.splitlines() if ln.strip()]
        assert len(lines) <= 15


# ─────────────────────────────────────────────────────────────────────────────
# _strip_fences — @staticmethod
# ─────────────────────────────────────────────────────────────────────────────

class TestStripFences:

    def test_json_fence_stripped(self):
        fenced = '```json\n["hello", "world"]\n```'
        assert LegalReviewer._strip_fences(fenced) == '["hello", "world"]'

    def test_plain_fence_stripped(self):
        fenced = '```\n["a", "b"]\n```'
        assert LegalReviewer._strip_fences(fenced) == '["a", "b"]'

    def test_plain_json_unchanged(self):
        raw = '["a", "b", "c"]'
        assert LegalReviewer._strip_fences(raw) == raw

    def test_leading_trailing_whitespace_stripped(self):
        raw = '  ["hello"]  '
        assert LegalReviewer._strip_fences(raw) == '["hello"]'

    def test_only_opening_fence_not_fully_stripped(self):
        # No closing ``` → opening stripped, no trailing removal
        fenced = '```json\n["a"]'
        result = LegalReviewer._strip_fences(fenced)
        assert result == '["a"]'


# ─────────────────────────────────────────────────────────────────────────────
# _validate_results — hallucination guard
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateResults:

    def test_normal_ratio_uses_correction(self, reviewer):
        # ratio 1.0 → within [0.2, 5.0]
        result = reviewer._validate_results(["original"], ["translation"], ["corrected"])
        assert result == ["corrected"]

    def test_ratio_below_0_2_uses_original_translation(self, reviewer):
        # corrected is 1 char, translated is 100 chars → ratio 0.01 < 0.2
        long_trans = "a" * 100
        result = reviewer._validate_results(["original"], [long_trans], ["x"])
        assert result == [long_trans]

    def test_ratio_above_5_uses_original_translation(self, reviewer):
        # corrected is 100 chars, translated is 10 chars → ratio 10.0 > 5.0
        result = reviewer._validate_results(["original"], ["1234567890"], ["a" * 100])
        assert result == ["1234567890"]

    def test_empty_correction_uses_original_translation(self, reviewer):
        result = reviewer._validate_results(["original"], ["translation"], [""])
        assert result == ["translation"]

    def test_whitespace_only_correction_uses_original_translation(self, reviewer):
        result = reviewer._validate_results(["original"], ["translation"], ["   "])
        assert result == ["translation"]

    def test_correction_stripped_before_use(self, reviewer):
        result = reviewer._validate_results(["original"], ["translation"], ["  corrected  "])
        assert result == ["corrected"]

    def test_batch_mixed_valid_and_invalid_ratios(self, reviewer):
        original_batch = ["a", "b"]
        translated_batch = ["short", "a" * 100]
        corrected = ["valid_correction", "x"]  # second: ratio 1/100 < 0.2 → keep original
        result = reviewer._validate_results(original_batch, translated_batch, corrected)
        assert result[0] == "valid_correction"
        assert result[1] == "a" * 100


# ─────────────────────────────────────────────────────────────────────────────
# review_legal_terms — routing
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewLegalTerms:

    def test_stub_mode_returns_ok_status(self, reviewer):
        result = reviewer.review_legal_terms("Some translated legal text.")
        assert result["status"] == "ok"

    def test_stub_mode_returns_empty_corrections(self, reviewer):
        result = reviewer.review_legal_terms("Some text.")
        assert result["corrections"] == []

    def test_stub_mode_output_matches_contract(self, reviewer):
        result = reviewer.review_legal_terms("Text.")
        assert set(result.keys()) >= {"status", "corrections"}

    def test_routes_to_stub_when_vertex_project_id_missing(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "true")
        monkeypatch.setenv("VERTEX_PROJECT_ID", "")
        r = LegalReviewer(lang_config)
        result = r.review_legal_terms("Text.")
        assert result["status"] == "ok"


# ─────────────────────────────────────────────────────────────────────────────
# verify_batch — routing and edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyBatch:

    def test_empty_original_returns_translated_unchanged(self, reviewer):
        translated = ["hola", "mundo"]
        result = reviewer.verify_batch([], translated)
        assert result == translated

    def test_stub_mode_returns_translated_spans_unchanged(self, reviewer):
        originals = ["The defendant.", "The plaintiff."]
        translated = ["El acusado.", "El demandante."]
        result = reviewer.verify_batch(originals, translated)
        assert result == translated

    def test_no_vertex_project_id_returns_translated_unchanged(self, lang_config, monkeypatch):
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "true")
        monkeypatch.setenv("VERTEX_PROJECT_ID", "")
        r = LegalReviewer(lang_config)
        originals = ["text"]
        translated = ["texto"]
        result = r.verify_batch(originals, translated)
        assert result == translated

    def test_result_has_same_length_as_input(self, reviewer):
        originals = ["a", "b", "c"]
        translated = ["x", "y", "z"]
        result = reviewer.verify_batch(originals, translated)
        assert len(result) == 3


# ─────────────────────────────────────────────────────────────────────────────
# _build_verification_prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildVerificationPrompt:

    def test_prompt_contains_language_label(self, reviewer):
        prompt = reviewer._build_verification_prompt(["original"], ["translated"], "")
        assert "Spanish" in prompt

    def test_prompt_contains_all_pairs(self, reviewer):
        originals = ["first original", "second original"]
        translated = ["first translated", "second translated"]
        prompt = reviewer._build_verification_prompt(originals, translated, "")
        assert "first original" in prompt
        assert "second original" in prompt
        assert "first translated" in prompt

    def test_prompt_includes_glossary_when_present(self, reviewer):
        snippet = "  defendant → acusado"
        prompt = reviewer._build_verification_prompt(["text"], ["texto"], snippet)
        assert "acusado" in prompt
        assert "REFERENCE GLOSSARY" in prompt

    def test_prompt_omits_glossary_section_when_empty(self, reviewer):
        prompt = reviewer._build_verification_prompt(["text"], ["texto"], "")
        assert "REFERENCE GLOSSARY" not in prompt

    def test_prompt_instructs_json_array_return(self, reviewer):
        prompt = reviewer._build_verification_prompt(["text"], ["texto"], "")
        assert "JSON array" in prompt

    def test_prompt_numbers_pairs_starting_at_1(self, reviewer):
        prompt = reviewer._build_verification_prompt(["a", "b"], ["x", "y"], "")
        assert "1." in prompt
        assert "2." in prompt


# ─────────────────────────────────────────────────────────────────────────────
# _get_redis — lazy connection and graceful degradation
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRedis:

    def test_no_redis_url_returns_none(self, reviewer):
        reviewer._redis_url = None
        assert reviewer._get_redis() is None

    def test_redis_unavailable_flag_returns_none(self, reviewer):
        reviewer._redis_url = "redis://localhost:6379"
        reviewer._redis_available = False
        assert reviewer._get_redis() is None

    def test_failed_connection_sets_unavailable_flag(self, reviewer):
        reviewer._redis_url = "redis://127.0.0.1:19999"  # nothing listening here
        reviewer._redis_available = True
        reviewer._redis = None
        result = reviewer._get_redis()
        assert result is None
        assert reviewer._redis_available is False

    def test_existing_redis_client_returned_without_reconnect(self, reviewer):
        mock_redis = MagicMock()
        reviewer._redis = mock_redis
        reviewer._redis_url = "redis://localhost"
        reviewer._redis_available = True
        result = reviewer._get_redis()
        assert result is mock_redis


# ─────────────────────────────────────────────────────────────────────────────
# _call_llama_cached — cache hit / miss logic (mocked Redis + _call_vertex)
# ─────────────────────────────────────────────────────────────────────────────

class TestCallLlamaCached:

    def _make_reviewer_with_mock_vertex(self, lang_config, monkeypatch):
        """Reviewer with Vertex enabled, real Redis bypassed, _call_vertex mocked."""
        monkeypatch.setenv("USE_VERTEX_LEGAL_REVIEW", "true")
        monkeypatch.setenv("VERTEX_PROJECT_ID", "test-project")
        monkeypatch.setenv("REDIS_URL", "")
        return LegalReviewer(lang_config)

    def test_cache_miss_calls_vertex_and_increments_miss_counter(self, lang_config, monkeypatch):
        r = self._make_reviewer_with_mock_vertex(lang_config, monkeypatch)
        r._redis = None  # no Redis
        with patch.object(r, "_call_vertex", return_value=["resultado"]) as mock_v:
            result = r._call_llama_cached(["original"], ["translated"], "")
        assert result == ["resultado"]
        assert r._cache_misses == 1
        mock_v.assert_called_once()

    def test_cache_hit_returns_cached_value_without_vertex_call(self, lang_config, monkeypatch):
        r = self._make_reviewer_with_mock_vertex(lang_config, monkeypatch)
        # _get_redis() checks _redis_url first — must be non-empty for the path
        # to reach the existing _redis client we inject below.
        mock_redis = MagicMock()
        mock_redis.get.return_value = b"cached_result"
        r._redis = mock_redis
        r._redis_available = True
        r._redis_url = "redis://localhost"

        with patch.object(r, "_call_vertex") as mock_v:
            result = r._call_llama_cached(["original"], ["translated"], "")

        assert result == ["cached_result"]
        assert r._cache_hits == 1
        mock_v.assert_not_called()

    def test_redis_error_disables_cache_and_calls_vertex(self, lang_config, monkeypatch):
        r = self._make_reviewer_with_mock_vertex(lang_config, monkeypatch)
        # Must set _redis_url so _get_redis() returns the mock client and the
        # exception path inside _call_llama_cached is actually reached.
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("connection reset")
        r._redis = mock_redis
        r._redis_available = True
        r._redis_url = "redis://localhost"

        with patch.object(r, "_call_vertex", return_value=["resultado"]) as mock_v:
            result = r._call_llama_cached(["original"], ["translated"], "")

        assert result == ["resultado"]
        assert r._redis_available is False
        mock_v.assert_called_once()
