"""
courtaccess/core/tests/test_legal_review.py

Unit tests for courtaccess.core.legal_review.
Stub mode tests — real Groq API tests gated behind GROQ_API_KEY env var.
"""

from courtaccess.core.legal_review import _stub_review, review_legal_terms


def test_review_returns_contract():
    result = review_legal_terms("El acusado se declara no culpable.", "spa_Latn")
    assert "status" in result
    assert "corrections" in result
    assert isinstance(result["corrections"], list)


def test_stub_review_always_ok():
    result = _stub_review("Any text.", "spa_Latn")
    assert result["status"] == "ok"
    assert result["corrections"] == []


def test_review_portuguese():
    result = review_legal_terms("O réu se declara inocente.", "por_Latn")
    assert result["status"] in ("ok", "issues_found")


def test_review_empty_text():
    result = review_legal_terms("", "spa_Latn")
    assert "status" in result
