"""
courtaccess/core/tests/test_pii_scrub.py

Unit tests for courtaccess.core.pii_scrub.
Tests the stub (Presidio) detection logic without the real Vertex API.
"""

from unittest.mock import MagicMock, patch

from courtaccess.core.pii_scrub import scrub_pii


def test_scrub_empty_text():
    result = scrub_pii("")
    assert result == {"findings": [], "finding_count": 0, "has_pii": False}


def test_scrub_returns_contract():
    """Even mocked results must match OUTPUT CONTRACT."""
    mock_result = MagicMock()
    mock_result.entity_type = "PERSON"
    mock_result.start = 4
    mock_result.end = 12
    mock_result.score = 0.85

    with patch("courtaccess.core.pii_scrub._get_analyzer") as mock_get:
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = [mock_result]
        mock_get.return_value = mock_analyzer

        result = scrub_pii("The John Smith appeared in court.")

    assert result["has_pii"] is True
    assert result["finding_count"] == 1
    assert result["findings"][0]["entity_type"] == "PERSON"
    assert "score" in result["findings"][0]


def test_scrub_no_pii_clean_text():
    with patch("courtaccess.core.pii_scrub._get_analyzer") as mock_get:
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = []
        mock_get.return_value = mock_analyzer

        result = scrub_pii("Motion to suppress evidence filed.")

    assert result["has_pii"] is False
    assert result["finding_count"] == 0
