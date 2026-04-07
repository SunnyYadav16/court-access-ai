"""
Unit tests for courtaccess/core/classify_document.py

Functions under test:
  classify_document   — routing: stub vs real, FileNotFoundError, auth checks
  _stub_classify      — output contract, always-legal guarantee
  _real_classify      — fail-closed guards, markdown stripping, pages_reviewed,
                        ClassificationError vs RuntimeError distinction

Design notes:
  - No real Vertex AI calls are made. _get_vertex_client and pymupdf.open are
    patched at the boundary so tests are fast and hermetic.
  - Module-level flags (_USE_REAL, _VERTEX_PROJECT_ID, _GCP_SA_JSON) are set
    at import time from os.environ. We patch them directly on the module to
    control routing without reloading the module.
  - All tests that exercise _real_classify patch both pymupdf.open (PDF text
    extraction) and _get_vertex_client (Vertex API) so neither the filesystem
    nor the network is touched.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import courtaccess.core.classify_document as classify_mod
from courtaccess.core.classify_document import (
    ClassificationError,
    _stub_classify,
    classify_document,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vertex_response(payload: dict) -> MagicMock:
    """
    Build a mock that mimics the shape of an OpenAI chat completion response:
      response.choices[0].message.content
    """
    msg = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=msg)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_raw_vertex_response(raw_text: str) -> MagicMock:
    """Same but with arbitrary raw text as content (for error-path tests)."""
    msg = SimpleNamespace(content=raw_text)
    choice = SimpleNamespace(message=msg)
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_mock_pdf(num_pages: int, page_text: str = "Legal document text."):
    """
    Build a mock pymupdf document with num_pages pages each returning page_text.
    """
    page = MagicMock()
    page.get_text.return_value = page_text
    doc = MagicMock()
    doc.__len__.return_value = num_pages
    doc.__getitem__.return_value = page
    return doc


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def pdf_file(tmp_path):
    """A real file on disk so Path.exists() passes in classify_document()."""
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4\nfake content\n%%EOF")
    return str(f)


@pytest.fixture()
def real_classify_patches(pdf_file):
    """
    Patch the three things _real_classify touches externally:
      1. classify_mod._USE_REAL       — force real path
      2. classify_mod._VERTEX_PROJECT_ID — must be truthy
      3. classify_mod._GCP_SA_JSON    — truthy → skips ADC check, has_auth=True
      4. pymupdf.open                 — avoid real PDF parsing
      5. classify_mod._get_vertex_client — avoid real Vertex auth

    Yields a dict so individual tests can customise the mock client response.
    """
    mock_doc = _make_mock_pdf(num_pages=3)
    mock_client = MagicMock()

    with (
        patch.object(classify_mod, "_USE_REAL", True),
        patch.object(classify_mod, "_VERTEX_PROJECT_ID", "test-project"),
        patch.object(classify_mod, "_GCP_SA_JSON", "fake-sa-json"),
        patch("pymupdf.open", return_value=mock_doc),
        patch("courtaccess.core.classify_document._get_vertex_client", return_value=mock_client),
    ):
        yield {"client": mock_client, "doc": mock_doc, "pdf_file": pdf_file}


# ─────────────────────────────────────────────────────────────────────────────
# _stub_classify
# ─────────────────────────────────────────────────────────────────────────────

class TestStubClassify:

    def test_returns_legal_classification(self, tmp_path):
        f = tmp_path / "any.pdf"
        f.write_bytes(b"content")
        result = _stub_classify(str(f))
        assert result["classification"] == "legal"

    def test_returns_full_confidence(self, tmp_path):
        f = tmp_path / "any.pdf"
        f.write_bytes(b"content")
        result = _stub_classify(str(f))
        assert result["confidence"] == 1.0

    def test_output_matches_contract(self, tmp_path):
        # Verify all four required keys are present
        f = tmp_path / "any.pdf"
        f.write_bytes(b"content")
        result = _stub_classify(str(f))
        assert set(result.keys()) == {"classification", "confidence", "reason", "pages_reviewed"}

    def test_pages_reviewed_is_zero(self, tmp_path):
        # Stub never opens the file — pages_reviewed is always 0
        f = tmp_path / "any.pdf"
        f.write_bytes(b"content")
        result = _stub_classify(str(f))
        assert result["pages_reviewed"] == 0

    def test_classifies_every_document_as_legal(self, tmp_path):
        # The stub must never return "non_legal" — it exists solely to pass
        # all documents through for pipeline testing
        for name in ("form.pdf", "image.pdf", "gibberish.pdf"):
            f = tmp_path / name
            f.write_bytes(b"content")
            assert _stub_classify(str(f))["classification"] == "legal"


# ─────────────────────────────────────────────────────────────────────────────
# classify_document — routing
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyDocumentRouting:

    def test_raises_file_not_found_for_missing_pdf(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            classify_document(str(tmp_path / "ghost.pdf"))

    def test_routes_to_stub_when_use_real_is_false(self, pdf_file):
        with (
            patch.object(classify_mod, "_USE_REAL", False),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", "sa"),
        ):
            result = classify_document(pdf_file)
        # Stub always returns legal with confidence 1.0
        assert result["classification"] == "legal"
        assert result["confidence"] == 1.0

    def test_routes_to_stub_when_vertex_project_id_missing(self, pdf_file):
        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", None),
            patch.object(classify_mod, "_GCP_SA_JSON", "sa"),
        ):
            result = classify_document(pdf_file)
        assert result["classification"] == "legal"
        assert result["confidence"] == 1.0

    def test_routes_to_stub_when_no_auth_available(self, pdf_file):
        # _GCP_SA_JSON absent and ADC fails → has_auth stays False → stub
        import google.auth.exceptions

        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", None),
            patch(
                "google.auth.default",
                side_effect=google.auth.exceptions.DefaultCredentialsError(),
            ),
        ):
            result = classify_document(pdf_file)
        assert result["classification"] == "legal"
        assert result["confidence"] == 1.0

    def test_routes_to_real_when_sa_json_present(self, pdf_file):
        # _GCP_SA_JSON set → skips ADC, has_auth=True → real path taken
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "confidence": 0.95, "reason": "looks legal"}
        )
        mock_doc = _make_mock_pdf(num_pages=1)

        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", "sa-json"),
            patch("pymupdf.open", return_value=mock_doc),
            patch("courtaccess.core.classify_document._get_vertex_client", return_value=mock_client),
        ):
            result = classify_document(pdf_file)
        # Real classifier adds pages_reviewed from actual doc length
        assert result["pages_reviewed"] == 1

    def test_routes_to_real_when_adc_succeeds(self, pdf_file):
        # No SA JSON, but ADC check succeeds → has_auth=True → real path taken
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_vertex_response(
            {"classification": "non_legal", "confidence": 0.88, "reason": "not a court form"}
        )
        mock_doc = _make_mock_pdf(num_pages=2)

        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", None),
            patch("google.auth.default"),
            patch("pymupdf.open", return_value=mock_doc),
            patch("courtaccess.core.classify_document._get_vertex_client", return_value=mock_client),
        ):
            result = classify_document(pdf_file)
        assert result["classification"] == "non_legal"


# ─────────────────────────────────────────────────────────────────────────────
# _real_classify — output contract
# ─────────────────────────────────────────────────────────────────────────────

class TestRealClassifyContract:

    def test_returns_all_required_keys(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "confidence": 0.97, "reason": "court filing"}
        )
        result = classify_document(patches["pdf_file"])
        assert set(result.keys()) >= {"classification", "confidence", "reason", "pages_reviewed"}

    def test_pages_reviewed_set_from_actual_page_count(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "confidence": 0.9, "reason": "ok"}
        )
        # mock_doc has 3 pages (set in fixture)
        result = classify_document(patches["pdf_file"])
        assert result["pages_reviewed"] == 3

    def test_pdf_with_fewer_than_3_pages_reviewed_correctly(self, pdf_file):
        # A 1-page PDF should report pages_reviewed=1, not 3
        mock_doc = _make_mock_pdf(num_pages=1)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "confidence": 0.9, "reason": "ok"}
        )
        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", "sa"),
            patch("pymupdf.open", return_value=mock_doc),
            patch("courtaccess.core.classify_document._get_vertex_client", return_value=mock_client),
        ):
            result = classify_document(pdf_file)
        assert result["pages_reviewed"] == 1

    def test_pdf_with_more_than_3_pages_only_reads_3(self, pdf_file):
        # _MAX_PAGES = 3 — a 10-page PDF should still report pages_reviewed=3
        mock_doc = _make_mock_pdf(num_pages=10)
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "confidence": 0.9, "reason": "ok"}
        )
        with (
            patch.object(classify_mod, "_USE_REAL", True),
            patch.object(classify_mod, "_VERTEX_PROJECT_ID", "proj"),
            patch.object(classify_mod, "_GCP_SA_JSON", "sa"),
            patch("pymupdf.open", return_value=mock_doc),
            patch("courtaccess.core.classify_document._get_vertex_client", return_value=mock_client),
        ):
            result = classify_document(pdf_file)
        assert result["pages_reviewed"] == 3

    def test_non_legal_classification_returned_as_is(self, real_classify_patches):
        # _real_classify does not raise on non_legal — that is the caller's job
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"classification": "non_legal", "confidence": 0.82, "reason": "not a form"}
        )
        result = classify_document(patches["pdf_file"])
        assert result["classification"] == "non_legal"


# ─────────────────────────────────────────────────────────────────────────────
# _real_classify — fail-closed guards
# ─────────────────────────────────────────────────────────────────────────────

class TestRealClassifyFailClosed:

    def test_non_json_response_raises_classification_error(self, real_classify_patches):
        # A plain-text response must raise ClassificationError, not be silently
        # accepted or fall back to stub — fail closed is non-negotiable here
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_raw_vertex_response(
            "I think this is a legal document."
        )
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])

    def test_non_json_does_not_raise_runtime_error(self, real_classify_patches):
        # ClassificationError and RuntimeError must be kept distinct.
        # A bad AI response is NOT a transport/auth failure.
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_raw_vertex_response(
            "This document appears legal."
        )
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])
        # If we reach here, RuntimeError was not raised — the distinction holds

    def test_missing_classification_key_raises_classification_error(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"confidence": 0.9, "reason": "looks ok"}  # classification missing
        )
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])

    def test_missing_confidence_key_raises_classification_error(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"classification": "legal", "reason": "court form"}  # confidence missing
        )
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])

    def test_missing_both_required_keys_raises_classification_error(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response(
            {"reason": "something"}  # neither classification nor confidence
        )
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])

    def test_empty_json_object_raises_classification_error(self, real_classify_patches):
        patches = real_classify_patches
        patches["client"].chat.completions.create.return_value = _make_vertex_response({})
        with pytest.raises(ClassificationError):
            classify_document(patches["pdf_file"])

    def test_vertex_network_failure_raises_runtime_error(self, real_classify_patches):
        # A transport/auth exception must surface as RuntimeError, not
        # ClassificationError — callers handle these two cases differently
        patches = real_classify_patches
        patches["client"].chat.completions.create.side_effect = Exception("connection timeout")
        with pytest.raises(RuntimeError):
            classify_document(patches["pdf_file"])

    def test_runtime_error_is_not_classification_error(self, real_classify_patches):
        # Confirm the two exception types don't overlap
        patches = real_classify_patches
        patches["client"].chat.completions.create.side_effect = Exception("network down")
        with pytest.raises(RuntimeError) as exc_info:
            classify_document(patches["pdf_file"])
        assert not isinstance(exc_info.value, ClassificationError)

    def test_markdown_fences_stripped_before_json_parse(self, real_classify_patches):
        # Vertex sometimes wraps JSON in ```json ... ``` — must be stripped
        patches = real_classify_patches
        fenced = '```json\n{"classification":"legal","confidence":0.95,"reason":"ok"}\n```'
        patches["client"].chat.completions.create.return_value = _make_raw_vertex_response(fenced)
        # Should parse successfully, not raise ClassificationError
        result = classify_document(patches["pdf_file"])
        assert result["classification"] == "legal"

    def test_markdown_fence_without_json_label_stripped(self, real_classify_patches):
        # Plain ``` fences (without 'json' label) also stripped
        patches = real_classify_patches
        fenced = '```\n{"classification":"non_legal","confidence":0.7,"reason":"not a form"}\n```'
        patches["client"].chat.completions.create.return_value = _make_raw_vertex_response(fenced)
        result = classify_document(patches["pdf_file"])
        assert result["classification"] == "non_legal"
