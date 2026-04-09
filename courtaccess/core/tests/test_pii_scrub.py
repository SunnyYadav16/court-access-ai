"""
Tests for courtaccess/core/pii_scrub.py

Coverage:
  - scrub_pii: empty / whitespace-only text → early return without calling analyzer
  - scrub_pii: output contract (findings, finding_count, has_pii)
  - scrub_pii: each finding has entity_type, start, end, score, text_excerpt
  - scrub_pii: text_excerpt is redacted ("[ENTITY_TYPE]")
  - scrub_pii: score rounded to 3 decimal places
  - scrub_pii: has_pii=True when findings present, False when empty
  - scrub_pii: multiple findings counted correctly
  - _get_analyzer: singleton caching (second call returns same object)
  - _get_analyzer: initialised lazily (None → populated after first call)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ── fixture: reset the global _analyzer cache between every test ──────────────


@pytest.fixture(autouse=True)
def reset_analyzer_cache():
    import courtaccess.core.pii_scrub as pii_mod

    original = pii_mod._analyzer
    pii_mod._analyzer = None
    yield
    pii_mod._analyzer = original


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_result(entity_type: str, start: int, end: int, score: float) -> MagicMock:
    """Simulate a Presidio RecognizerResult."""
    r = MagicMock()
    r.entity_type = entity_type
    r.start = start
    r.end = end
    r.score = score
    return r


def _mock_analyzer(results: list) -> MagicMock:
    analyzer = MagicMock()
    analyzer.analyze.return_value = results
    return analyzer


# ══════════════════════════════════════════════════════════════════════════════
# Empty / whitespace input — early return (no analyzer call)
# ══════════════════════════════════════════════════════════════════════════════


class TestEmptyInput:
    def test_empty_string_returns_empty_findings(self):
        from courtaccess.core.pii_scrub import scrub_pii

        result = scrub_pii("")
        assert result == {"findings": [], "finding_count": 0, "has_pii": False}

    def test_whitespace_only_returns_empty_findings(self):
        from courtaccess.core.pii_scrub import scrub_pii

        result = scrub_pii("   \t\n  ")
        assert result == {"findings": [], "finding_count": 0, "has_pii": False}

    def test_empty_string_does_not_call_get_analyzer(self):
        from courtaccess.core.pii_scrub import scrub_pii

        with patch("courtaccess.core.pii_scrub._get_analyzer") as mock_get:
            scrub_pii("")
        mock_get.assert_not_called()

    def test_whitespace_does_not_call_get_analyzer(self):
        from courtaccess.core.pii_scrub import scrub_pii

        with patch("courtaccess.core.pii_scrub._get_analyzer") as mock_get:
            scrub_pii("   ")
        mock_get.assert_not_called()

    def test_single_newline_returns_empty(self):
        from courtaccess.core.pii_scrub import scrub_pii

        result = scrub_pii("\n")
        assert result["findings"] == []
        assert result["has_pii"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Output contract
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputContract:
    def _run(self, text: str, analyzer_results: list) -> dict:
        from courtaccess.core.pii_scrub import scrub_pii

        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer(analyzer_results)):
            return scrub_pii(text)

    def test_output_has_findings_key(self):
        result = self._run("John Smith", [])
        assert "findings" in result

    def test_output_has_finding_count_key(self):
        result = self._run("John Smith", [])
        assert "finding_count" in result

    def test_output_has_has_pii_key(self):
        result = self._run("John Smith", [])
        assert "has_pii" in result

    def test_findings_is_a_list(self):
        result = self._run("John Smith", [])
        assert isinstance(result["findings"], list)

    def test_no_findings_has_pii_false(self):
        result = self._run("Court form 1A", [])
        assert result["has_pii"] is False
        assert result["finding_count"] == 0

    def test_findings_present_has_pii_true(self):
        presidio_result = _make_result("PERSON", 0, 10, 0.85)
        result = self._run("John Smith applied", [presidio_result])
        assert result["has_pii"] is True
        assert result["finding_count"] == 1

    def test_finding_count_matches_len_findings(self):
        r1 = _make_result("PERSON", 0, 4, 0.9)
        r2 = _make_result("PHONE_NUMBER", 10, 22, 0.8)
        result = self._run("John 617-555-1234", [r1, r2])
        assert result["finding_count"] == len(result["findings"])
        assert result["finding_count"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# Finding shape
# ══════════════════════════════════════════════════════════════════════════════


class TestFindingShape:
    def _single_finding(self, entity_type="PERSON", start=0, end=4, score=0.9) -> dict:
        from courtaccess.core.pii_scrub import scrub_pii

        r = _make_result(entity_type, start, end, score)
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer([r])):
            result = scrub_pii("some text with PII")
        return result["findings"][0]

    def test_finding_has_entity_type(self):
        f = self._single_finding(entity_type="PERSON")
        assert f["entity_type"] == "PERSON"

    def test_finding_has_start(self):
        f = self._single_finding(start=5)
        assert f["start"] == 5

    def test_finding_has_end(self):
        f = self._single_finding(end=12)
        assert f["end"] == 12

    def test_finding_has_score(self):
        f = self._single_finding(score=0.9)
        assert f["score"] == pytest.approx(0.9, abs=0.001)

    def test_finding_has_text_excerpt(self):
        f = self._single_finding()
        assert "text_excerpt" in f

    def test_text_excerpt_is_redacted_entity_type(self):
        f = self._single_finding(entity_type="PHONE_NUMBER")
        assert f["text_excerpt"] == "[PHONE_NUMBER]"

    def test_text_excerpt_does_not_contain_raw_text(self):
        from courtaccess.core.pii_scrub import scrub_pii

        r = _make_result("EMAIL_ADDRESS", 0, 20, 0.95)
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer([r])):
            result = scrub_pii("user@example.com sent mail")
        excerpt = result["findings"][0]["text_excerpt"]
        assert "user@example.com" not in excerpt

    def test_score_rounded_to_3_decimal_places(self):
        from courtaccess.core.pii_scrub import scrub_pii

        # score with many decimal places: 0.8765432 → rounded to 0.877
        r = _make_result("PERSON", 0, 4, 0.8765432)
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer([r])):
            result = scrub_pii("John is here")
        assert result["findings"][0]["score"] == 0.877

    def test_score_not_higher_than_3_decimal_places(self):
        from courtaccess.core.pii_scrub import scrub_pii

        r = _make_result("PERSON", 0, 4, 0.123456789)
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer([r])):
            result = scrub_pii("Jane is here")
        score_str = str(result["findings"][0]["score"])
        decimal_part = score_str.split(".")[-1] if "." in score_str else ""
        assert len(decimal_part) <= 3


# ══════════════════════════════════════════════════════════════════════════════
# Multiple finding types
# ══════════════════════════════════════════════════════════════════════════════


class TestMultipleFindings:
    def test_multiple_findings_all_returned(self):
        from courtaccess.core.pii_scrub import scrub_pii

        results = [
            _make_result("PERSON", 0, 4, 0.9),
            _make_result("PHONE_NUMBER", 10, 22, 0.8),
            _make_result("EMAIL_ADDRESS", 30, 50, 0.95),
        ]
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer(results)):
            result = scrub_pii("Some text with multiple PII entities")

        assert result["finding_count"] == 3
        assert result["has_pii"] is True

    def test_multiple_entity_types_preserved(self):
        from courtaccess.core.pii_scrub import scrub_pii

        results = [
            _make_result("PERSON", 0, 4, 0.9),
            _make_result("MA_DOCKET_NUMBER", 10, 22, 0.85),
        ]
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer(results)):
            result = scrub_pii("John filed docket 23CR0045")

        types = {f["entity_type"] for f in result["findings"]}
        assert "PERSON" in types
        assert "MA_DOCKET_NUMBER" in types

    def test_custom_ma_entity_types_in_excerpts(self):
        from courtaccess.core.pii_scrub import scrub_pii

        results = [_make_result("MA_COURT_FILE_NUMBER", 5, 14, 0.7)]
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=_mock_analyzer(results)):
            result = scrub_pii("case SJC-12345 was filed")

        assert result["findings"][0]["text_excerpt"] == "[MA_COURT_FILE_NUMBER]"


# ══════════════════════════════════════════════════════════════════════════════
# Analyzer call arguments
# ══════════════════════════════════════════════════════════════════════════════


class TestAnalyzerCallArgs:
    def test_analyzer_called_with_text(self):
        from courtaccess.core.pii_scrub import scrub_pii

        mock_analyzer = _mock_analyzer([])
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=mock_analyzer):
            scrub_pii("Hello world")

        mock_analyzer.analyze.assert_called_once()
        kwargs = mock_analyzer.analyze.call_args[1]
        assert kwargs["text"] == "Hello world"

    def test_default_language_is_en(self):
        from courtaccess.core.pii_scrub import scrub_pii

        mock_analyzer = _mock_analyzer([])
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=mock_analyzer):
            scrub_pii("Hello world")

        kwargs = mock_analyzer.analyze.call_args[1]
        assert kwargs["language"] == "en"

    def test_custom_language_forwarded(self):
        from courtaccess.core.pii_scrub import scrub_pii

        mock_analyzer = _mock_analyzer([])
        with patch("courtaccess.core.pii_scrub._get_analyzer", return_value=mock_analyzer):
            scrub_pii("Hola mundo", language="es")

        kwargs = mock_analyzer.analyze.call_args[1]
        assert kwargs["language"] == "es"


# ══════════════════════════════════════════════════════════════════════════════
# _get_analyzer — singleton / lazy loading
# ══════════════════════════════════════════════════════════════════════════════


class TestGetAnalyzerSingleton:
    def test_returns_non_none_object(self):
        import courtaccess.core.pii_scrub as pii_mod

        mock_engine = MagicMock()
        mock_presidio = MagicMock()
        mock_presidio.AnalyzerEngine.return_value = mock_engine
        mock_presidio.PatternRecognizer = MagicMock
        mock_presidio.Pattern = MagicMock
        mock_presidio.RecognizerRegistry.return_value = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "presidio_analyzer": mock_presidio,
            },
        ):
            result = pii_mod._get_analyzer()

        assert result is not None

    def test_second_call_returns_same_object(self):
        import courtaccess.core.pii_scrub as pii_mod

        mock_engine = MagicMock()
        mock_presidio = MagicMock()
        mock_presidio.AnalyzerEngine.return_value = mock_engine
        mock_presidio.PatternRecognizer = MagicMock
        mock_presidio.Pattern = MagicMock
        mock_presidio.RecognizerRegistry.return_value = MagicMock()

        with patch.dict("sys.modules", {"presidio_analyzer": mock_presidio}):
            first = pii_mod._get_analyzer()
            second = pii_mod._get_analyzer()

        assert first is second

    def test_analyzer_engine_created_only_once(self):
        import courtaccess.core.pii_scrub as pii_mod

        mock_presidio = MagicMock()
        mock_presidio.RecognizerRegistry.return_value = MagicMock()

        with patch.dict("sys.modules", {"presidio_analyzer": mock_presidio}):
            pii_mod._get_analyzer()
            pii_mod._get_analyzer()
            pii_mod._get_analyzer()

        assert mock_presidio.AnalyzerEngine.call_count == 1

    def test_module_global_set_after_first_call(self):
        import courtaccess.core.pii_scrub as pii_mod

        assert pii_mod._analyzer is None  # reset by autouse fixture

        mock_presidio = MagicMock()
        mock_presidio.RecognizerRegistry.return_value = MagicMock()

        with patch.dict("sys.modules", {"presidio_analyzer": mock_presidio}):
            pii_mod._get_analyzer()

        assert pii_mod._analyzer is not None
