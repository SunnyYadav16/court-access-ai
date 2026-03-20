"""
Tests for courtaccess.forms.parse_glossary.Glossary

Real glossary data used where available (glossary_es.json must exist).
PDF parse tests use minimal in-memory PDFs — no real glossary PDF required.
"""

import json
from pathlib import Path

import pymupdf
import pytest

from courtaccess.forms.parse_glossary import Glossary
from courtaccess.languages import get_language_config

_GLOSSARY_DIR = Path(__file__).parent.parent.parent.parent / "data" / "glossaries"
_ES_JSON      = _GLOSSARY_DIR / "glossary_es.json"
_REAL_DATA_AVAILABLE = _ES_JSON.exists() and _ES_JSON.stat().st_size > 1000


def _spanish_config():
    return get_language_config("spanish")


def _portuguese_config():
    return get_language_config("portuguese")


def _make_glossary_with_entries(entries: dict) -> Glossary:
    g           = Glossary.__new__(Glossary)
    g.config    = _spanish_config()
    g.json_path = _ES_JSON
    g.glossary  = entries
    return g


# ── Glossary.load() ───────────────────────────────────────────────────────────

class TestGlossaryLoad:

    def test_load_raises_file_not_found_with_instructions(self, tmp_path):
        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "nonexistent.json"
        g.glossary  = {}
        with pytest.raises(FileNotFoundError, match=r"parse_glossary\.py"):
            g.load()

    def test_load_raises_includes_language_code(self, tmp_path):
        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "nonexistent.json"
        g.glossary  = {}
        with pytest.raises(FileNotFoundError, match="spanish"):
            g.load()

    def test_load_returns_self_for_chaining(self, tmp_path):
        json_file = tmp_path / "glossary_es.json"
        with open(json_file, "w") as f:
            json.dump({"bail": "fianza"}, f)
        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = json_file
        g.glossary  = {}
        assert g.load() is g

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_load_real_glossary_has_738_terms(self):
        g = Glossary(_spanish_config()).load()
        assert len(g.glossary) == 738

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_load_real_glossary_is_flat_dict(self):
        g = Glossary(_spanish_config()).load()
        assert isinstance(g.glossary, dict)
        for key, val in list(g.glossary.items())[:10]:
            assert isinstance(key, str)
            assert isinstance(val, str)

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_load_real_glossary_keys_are_lowercase(self):
        g = Glossary(_spanish_config()).load()
        for key in g.glossary:
            assert key == key.lower(), f"Key not lowercase: '{key}'"

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_load_real_glossary_contains_critical_terms(self):
        g = Glossary(_spanish_config()).load()
        critical = [
            "arraignment", "bail", "defendant", "waiver",
            "affidavit", "bench warrant",
            "beyond a reasonable doubt", "plea",
            "probation", "trial court",
        ]
        missing = [t for t in critical if t not in g.glossary]
        assert not missing, f"Missing critical terms: {missing}"

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_load_real_glossary_legal_overrides_present(self):
        config = _spanish_config()
        g      = Glossary(config).load()
        for term, translation in config.legal_overrides.items():
            assert term.lower() in g.glossary, (
                f"Override term '{term}' missing from glossary"
            )
            assert g.glossary[term.lower()] == translation, (
                f"Override term '{term}' has wrong translation: "
                f"expected '{translation}', "
                f"got '{g.glossary[term.lower()]}'"
            )


# ── Glossary.get_matching_terms() ─────────────────────────────────────────────

class TestGetMatchingTerms:

    def test_finds_single_term(self):
        g = _make_glossary_with_entries({"defendant": "acusado"})
        assert g.get_matching_terms("The defendant pleads.") == {
            "defendant": "acusado"
        }

    def test_returns_empty_when_no_match(self):
        g = _make_glossary_with_entries({"arraignment": "lectura de cargos"})
        assert g.get_matching_terms("The weather is nice.") == {}

    def test_longer_terms_matched_first(self):
        g = _make_glossary_with_entries({
            "right to counsel": "derecho a la asistencia letrada",
            "right":            "derecho",
        })
        result = g.get_matching_terms("The right to counsel is guaranteed.")
        assert "right to counsel" in result
        assert result["right to counsel"] == "derecho a la asistencia letrada"

    def test_max_terms_respected(self):
        entries = {f"term_{i}": f"valor_{i}" for i in range(20)}
        g       = _make_glossary_with_entries(entries)
        result  = g.get_matching_terms(" ".join(entries.keys()), max_terms=5)
        assert len(result) <= 5

    def test_case_insensitive_match(self):
        g = _make_glossary_with_entries({"defendant": "acusado"})
        assert g.get_matching_terms("THE DEFENDANT PLEADS.") == {
            "defendant": "acusado"
        }

    def test_default_max_terms_is_8(self):
        entries = {f"word_{i}": f"palabra_{i}" for i in range(20)}
        g       = _make_glossary_with_entries(entries)
        result  = g.get_matching_terms(" ".join(entries.keys()))
        assert len(result) <= 8

    def test_empty_glossary_returns_empty(self):
        assert _make_glossary_with_entries({}).get_matching_terms(
            "The defendant."
        ) == {}

    def test_empty_text_returns_empty(self):
        assert _make_glossary_with_entries(
            {"defendant": "acusado"}
        ).get_matching_terms("") == {}

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_real_glossary_matches_defendant(self):
        g = Glossary(_spanish_config()).load()
        result = g.get_matching_terms(
            "The defendant waived their right to counsel."
        )
        assert "defendant" in result
        assert "right to counsel" in result

    @pytest.mark.skipif(
        not _REAL_DATA_AVAILABLE,
        reason="glossary_es.json not present"
    )
    def test_real_glossary_legal_overrides_matched(self):
        g = Glossary(_spanish_config()).load()
        result = g.get_matching_terms(
            "The Commonwealth proved beyond a reasonable doubt."
        )
        assert "beyond a reasonable doubt" in result
        assert result["beyond a reasonable doubt"] == "más allá de una duda razonable"


# ── Glossary._should_skip() ───────────────────────────────────────────────────

class TestShouldSkip:

    def _make_glossary(self) -> Glossary:
        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = _ES_JSON
        g.glossary  = {}
        return g

    def test_skips_above_top_margin(self):
        assert self._make_glossary()._should_skip("some text", y0=30.0)

    def test_skips_below_bottom_margin(self):
        assert self._make_glossary()._should_skip("some text", y0=730.0)

    def test_skips_empty_text(self):
        assert self._make_glossary()._should_skip("", y0=100.0)

    def test_skips_single_letter(self):
        assert self._make_glossary()._should_skip("A", y0=100.0)

    def test_skips_known_header(self):
        assert self._make_glossary()._should_skip(
            "glossary of legal terms", y0=100.0
        )

    def test_skips_revised_header(self):
        assert self._make_glossary()._should_skip("revised 2023", y0=100.0)

    def test_does_not_skip_valid_term(self):
        assert not self._make_glossary()._should_skip("arraignment", y0=100.0)

    def test_does_not_skip_valid_term_in_margin(self):
        assert not self._make_glossary()._should_skip("bail", y0=200.0)


# ── Glossary.parse_pdf() ─────────────────────────────────────────────────────

class TestParsePdf:

    def test_raises_if_pdf_missing(self, tmp_path):
        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "glossary_es.json"
        g.glossary  = {}
        with pytest.raises(FileNotFoundError):
            g.parse_pdf(str(tmp_path / "nonexistent.pdf"))

    def test_returns_self(self, tmp_path):
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page()
        pdf_path = str(tmp_path / "glossary.pdf")
        doc.save(pdf_path)
        doc.close()

        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "glossary_es.json"
        g.glossary  = {}
        assert g.parse_pdf(pdf_path) is g

    def test_saves_json_to_disk(self, tmp_path):
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page()
        pdf_path = str(tmp_path / "glossary.pdf")
        doc.save(pdf_path)
        doc.close()

        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "glossary_es.json"
        g.glossary  = {}
        g.parse_pdf(pdf_path)
        assert g.json_path.exists()

    def test_legal_overrides_applied_after_parse(self, tmp_path):
        """
        Verifies config.legal_overrides are applied as the final
        authoritative override layer — matching Cell 7a behavior
        where MA_OVERRIDES_ES.update() runs after PDF parsing.
        """
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page()
        pdf_path = str(tmp_path / "glossary.pdf")
        doc.save(pdf_path)
        doc.close()

        config      = _spanish_config()
        g           = Glossary.__new__(Glossary)
        g.config    = config
        g.json_path = tmp_path / "glossary_es.json"
        g.glossary  = {}
        g.parse_pdf(pdf_path)

        for en_term, es_term in config.legal_overrides.items():
            assert en_term.lower() in g.glossary, (
                f"Override '{en_term}' missing after parse"
            )
            assert g.glossary[en_term.lower()] == es_term

    def test_saved_json_is_valid_flat_dict(self, tmp_path):
        doc = pymupdf.open()
        for _ in range(3):
            doc.new_page()
        pdf_path = str(tmp_path / "glossary.pdf")
        doc.save(pdf_path)
        doc.close()

        g           = Glossary.__new__(Glossary)
        g.config    = _spanish_config()
        g.json_path = tmp_path / "glossary_es.json"
        g.glossary  = {}
        g.parse_pdf(pdf_path)

        with open(g.json_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert isinstance(saved, dict)
        for k, v in saved.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
