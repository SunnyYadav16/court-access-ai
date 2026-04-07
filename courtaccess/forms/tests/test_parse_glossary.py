"""
Tests for courtaccess/forms/parse_glossary.py

Covers Glossary.load(), get_matching_terms(), and _should_skip().
PDF parsing (_parse_blocks) requires a real PDF so it is integration-tested
with a minimal synthetic PDF using pymupdf.
"""

import json

import pytest

from courtaccess.forms.parse_glossary import Glossary
from courtaccess.languages.portuguese import PORTUGUESE_CONFIG
from courtaccess.languages.spanish import SPANISH_CONFIG

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_glossary_dir(tmp_path):
    """Return a tmp dir acting as the glossary directory."""
    return tmp_path


@pytest.fixture
def spanish_glossary_with_tmp_dir(tmp_path):
    """
    Glossary instance whose json_path points inside tmp_path so we can
    create/read JSON without touching the real data/glossaries directory.
    """
    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = tmp_path / "glossary_es.json"
    return glossary


@pytest.fixture
def populated_glossary(tmp_path):
    """Glossary with a pre-written JSON file containing known terms."""
    data = {
        "defendant": "acusado",
        "beyond a reasonable doubt": "más allá de una duda razonable",
        "plea": "declaración",
        "verdict": "veredicto",
        "affidavit": "declaración jurada",
    }
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    glossary.load()
    return glossary


# ══════════════════════════════════════════════════════════════════════════════
# Glossary.load()
# ══════════════════════════════════════════════════════════════════════════════


def test_load_success(tmp_path):
    data = {"acquit": "absolver", "bail": "fianza"}
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    result = glossary.load()

    assert result is glossary  # returns self
    assert glossary.glossary == data


def test_load_returns_self(tmp_path):
    data = {"term": "traducción"}
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file

    assert glossary.load() is glossary


def test_load_file_not_found_raises(tmp_path):
    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = tmp_path / "does_not_exist.json"

    with pytest.raises(FileNotFoundError) as exc_info:
        glossary.load()

    assert "does_not_exist.json" in str(exc_info.value)


def test_load_file_not_found_message_contains_command(tmp_path):
    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError) as exc_info:
        glossary.load()

    assert "parse_glossary.py" in str(exc_info.value) or "Generate" in str(exc_info.value)


def test_load_populates_glossary_dict(tmp_path):
    data = {"a": "b", "c": "d", "e": "f"}
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    glossary.load()

    assert len(glossary.glossary) == 3


def test_load_portuguese_glossary(tmp_path):
    data = {"defendant": "réu", "verdict": "veredito"}
    json_file = tmp_path / "glossary_pt.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(PORTUGUESE_CONFIG)
    glossary.json_path = json_file
    glossary.load()

    assert glossary.glossary["defendant"] == "réu"


def test_load_real_spanish_glossary():
    """Integration: load the actual committed glossary_es.json."""
    glossary = Glossary(SPANISH_CONFIG)
    glossary.load()
    assert len(glossary.glossary) > 0


def test_load_real_portuguese_glossary():
    """Integration: load the actual committed glossary_pt.json."""
    glossary = Glossary(PORTUGUESE_CONFIG)
    glossary.load()
    assert len(glossary.glossary) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Glossary.get_matching_terms()
# ══════════════════════════════════════════════════════════════════════════════


def test_get_matching_terms_basic(populated_glossary):
    result = populated_glossary.get_matching_terms("The defendant entered a plea.")
    assert "defendant" in result
    assert "plea" in result


def test_get_matching_terms_case_insensitive(populated_glossary):
    result = populated_glossary.get_matching_terms("The DEFENDANT was found not guilty.")
    assert "defendant" in result


def test_get_matching_terms_no_match(populated_glossary):
    result = populated_glossary.get_matching_terms("The weather is nice today.")
    assert result == {}


def test_get_matching_terms_empty_text(populated_glossary):
    result = populated_glossary.get_matching_terms("")
    assert result == {}


def test_get_matching_terms_max_terms_respected(tmp_path):
    # 10 distinct terms, but max_terms=3
    data = {f"term{i}": f"trans{i}" for i in range(10)}
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    glossary.load()

    text = " ".join(f"term{i}" for i in range(10))
    result = glossary.get_matching_terms(text, max_terms=3)
    assert len(result) <= 3


def test_get_matching_terms_default_max_is_8(tmp_path):
    data = {f"term{i}": f"trans{i}" for i in range(20)}
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    glossary.load()

    text = " ".join(f"term{i}" for i in range(20))
    result = glossary.get_matching_terms(text)
    assert len(result) <= 8


def test_get_matching_terms_longer_terms_first(tmp_path):
    """'beyond a reasonable doubt' should match before 'doubt' alone."""
    data = {
        "beyond a reasonable doubt": "más allá de una duda razonable",
        "doubt": "duda",
    }
    json_file = tmp_path / "glossary_es.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = json_file
    glossary.load()

    result = glossary.get_matching_terms("beyond a reasonable doubt", max_terms=1)
    # With max_terms=1, the longer term wins
    assert "beyond a reasonable doubt" in result


def test_get_matching_terms_returns_correct_translations(populated_glossary):
    result = populated_glossary.get_matching_terms("verdict was read")
    assert result.get("verdict") == "veredicto"


def test_get_matching_terms_partial_word_matches(populated_glossary):
    """Substring matching — 'affidavit' matches if in text."""
    result = populated_glossary.get_matching_terms("please sign this affidavit form")
    assert "affidavit" in result


def test_get_matching_terms_empty_glossary():
    glossary = Glossary(SPANISH_CONFIG)
    glossary.glossary = {}
    result = glossary.get_matching_terms("the defendant")
    assert result == {}


# ══════════════════════════════════════════════════════════════════════════════
# Glossary._should_skip()
# ══════════════════════════════════════════════════════════════════════════════


def test_should_skip_y_too_low():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("Valid Term", y0=30.0) is True


def test_should_skip_y_too_high():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("Valid Term", y0=800.0) is True


def test_should_skip_y_at_lower_boundary():
    glossary = Glossary(SPANISH_CONFIG)
    # y0 == 55 is NOT skipped (condition is y0 < 55)
    assert glossary._should_skip("Some term", y0=55.0) is False


def test_should_skip_y_at_upper_boundary():
    glossary = Glossary(SPANISH_CONFIG)
    # y0 == 725 is NOT skipped (condition is y0 > 725)
    assert glossary._should_skip("Some term", y0=725.0) is False


def test_should_skip_empty_text():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("", y0=300.0) is True


def test_should_skip_whitespace_only():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("   ", y0=300.0) is True


def test_should_skip_single_letter():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("A", y0=300.0) is True


def test_should_skip_two_letter_alpha():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("ab", y0=300.0) is True


def test_should_skip_two_digit_string():
    """Two-character string with digits should NOT be skipped (not isalpha)."""
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("42", y0=300.0) is False


def test_should_skip_known_header_line():
    glossary = Glossary(SPANISH_CONFIG)
    # "glossary of legal" is in glossary_skip_lines for Spanish
    assert glossary._should_skip("Glossary of Legal Terms", y0=300.0) is True


def test_should_skip_known_header_revised():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("Revised 2022", y0=300.0) is True


def test_should_not_skip_valid_term():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("defendant", y0=300.0) is False


def test_should_not_skip_multiword_term():
    glossary = Glossary(SPANISH_CONFIG)
    assert glossary._should_skip("beyond a reasonable doubt", y0=300.0) is False


# ══════════════════════════════════════════════════════════════════════════════
# Glossary.parse_pdf() — file-not-found path
# ══════════════════════════════════════════════════════════════════════════════


def test_parse_pdf_raises_on_missing_pdf(tmp_path):
    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = tmp_path / "glossary_es.json"

    with pytest.raises(FileNotFoundError):
        glossary.parse_pdf(str(tmp_path / "nonexistent.pdf"))


def test_parse_pdf_applies_legal_overrides(tmp_path, monkeypatch):
    """parse_pdf() should merge legal_overrides on top of parsed terms."""
    glossary = Glossary(SPANISH_CONFIG)
    glossary.json_path = tmp_path / "glossary_es.json"

    # Stub _parse_blocks to return a minimal dict
    monkeypatch.setattr(glossary, "_parse_blocks", lambda _path: {"acquit": "absolver"})

    # Create a dummy file so the existence check passes
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    glossary.parse_pdf(str(fake_pdf))

    # legal_overrides from SPANISH_CONFIG should be present
    assert "defendant" in glossary.glossary
    assert glossary.glossary["defendant"] == "acusado"
    # Original parsed term preserved
    assert glossary.glossary["acquit"] == "absolver"


def test_parse_pdf_saves_json(tmp_path, monkeypatch):
    glossary = Glossary(SPANISH_CONFIG)
    json_path = tmp_path / "glossary_es.json"
    glossary.json_path = json_path

    monkeypatch.setattr(glossary, "_parse_blocks", lambda _path: {"term": "término"})

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    glossary.parse_pdf(str(fake_pdf))

    assert json_path.exists()
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert "term" in saved
