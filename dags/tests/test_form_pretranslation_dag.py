"""
dags/tests/test_form_pretranslation_dag.py

Unit tests for dags/form_pretranslation_dag.py.

Covers:
  - _translate_regions: empty text → translated_text="", confidence=1.0;
      non-empty text → calls translator.translate_text and propagates result
  - _legal_review_with_retry: success on first attempt → returns result with
      skipped=False; all attempts fail → returns status="skipped", skipped=True;
      retries after failure before giving up (sleep mocked to 0)
  - task_load_form_entry: missing form_id → raises ValueError; form_id not in
      DB → raises ValueError; already has ES and PT → returns skip=True
  - task_translate_spanish: already_has_es flag → pushes empty list, returns {}
  - task_translate_portuguese: already_has_pt flag → pushes empty list, returns {}
  - task_legal_review_spanish: already_has_es → pushes skipped status
  - task_legal_review_portuguese: already_has_pt → pushes skipped status
  - task_reconstruct_pdf_spanish: already_has_es → pushes path_es=None, returns {}
  - task_ocr_extract_text: skip flag → pushes empty regions
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
import dags.form_pretranslation_dag as dag_mod
from dags.tests.conftest import _make_context

_FORM_ID = str(uuid.uuid4())
_PATCH_BASE = "dags.form_pretranslation_dag"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form_meta(
    skip: bool = False,
    already_has_es: bool = False,
    already_has_pt: bool = False,
    form_id: str | None = None,
) -> dict:
    fid = form_id or _FORM_ID
    return {
        "form_id": fid,
        "form_name": "Test Form",
        "form_slug": "test-form",
        "version": 1,
        "original_gcs_uri": f"gs://forms/{fid}/original.pdf",
        "original_path": f"/tmp/courtaccess/form_pretranslation/test/{fid}_original.pdf",
        "output_es": f"/tmp/courtaccess/form_pretranslation/test/{fid}_es.pdf",
        "output_pt": f"/tmp/courtaccess/form_pretranslation/test/{fid}_pt.pdf",
        "skip": skip,
        "already_has_es": already_has_es,
        "already_has_pt": already_has_pt,
        "existing_es_path": None,
        "existing_pt_path": None,
        "is_mislabeled": False,
    }


def _make_ocr_result(regions: list | None = None) -> dict:
    return {
        "regions": regions or [{"text": "The defendant shall appear", "confidence": 0.9}],
        "full_text": "The defendant shall appear",
    }


# ===========================================================================
# _translate_regions
# ===========================================================================


def test_translate_regions_empty_text_returns_confidence_one() -> None:
    """Regions with empty text must get translated_text='' and confidence=1.0."""
    translator = MagicMock()
    regions = [{"text": "", "page": 1}]
    result = dag_mod._translate_regions(regions, dag_mod.LANG_ES, translator)
    assert len(result) == 1
    assert result[0]["translated_text"] == ""
    assert result[0]["translation_confidence"] == 1.0


def test_translate_regions_whitespace_text_returns_confidence_one() -> None:
    """Regions with whitespace-only text must get translated_text='' and confidence=1.0."""
    translator = MagicMock()
    regions = [{"text": "   ", "page": 1}]
    result = dag_mod._translate_regions(regions, dag_mod.LANG_ES, translator)
    assert result[0]["translated_text"] == ""
    assert result[0]["translation_confidence"] == 1.0
    translator.translate_text.assert_not_called()


def test_translate_regions_calls_translate_text() -> None:
    """Non-empty regions must call translator.translate_text."""
    translator = MagicMock()
    translator.translate_text.return_value = {"translated": "El acusado deberá comparecer", "confidence": 0.95}
    regions = [{"text": "The defendant shall appear", "page": 1}]
    result = dag_mod._translate_regions(regions, dag_mod.LANG_ES, translator)
    translator.translate_text.assert_called_once_with("The defendant shall appear", dag_mod.LANG_ES)
    assert result[0]["translated_text"] == "El acusado deberá comparecer"
    assert result[0]["translation_confidence"] == pytest.approx(0.95)


def test_translate_regions_preserves_original_fields() -> None:
    """All original region fields must be preserved in output."""
    translator = MagicMock()
    translator.translate_text.return_value = {"translated": "Hola", "confidence": 0.9}
    regions = [{"text": "Hello", "page": 2, "bbox": [0, 0, 100, 20], "font_size": 12}]
    result = dag_mod._translate_regions(regions, dag_mod.LANG_ES, translator)
    assert result[0]["page"] == 2
    assert result[0]["bbox"] == [0, 0, 100, 20]
    assert result[0]["font_size"] == 12


def test_translate_regions_multiple_regions() -> None:
    """All regions in a list must be translated."""
    translator = MagicMock()
    translator.translate_text.side_effect = [
        {"translated": "Hola", "confidence": 0.9},
        {"translated": "Mundo", "confidence": 0.85},
    ]
    regions = [{"text": "Hello", "page": 1}, {"text": "World", "page": 1}]
    result = dag_mod._translate_regions(regions, dag_mod.LANG_ES, translator)
    assert len(result) == 2
    assert result[0]["translated_text"] == "Hola"
    assert result[1]["translated_text"] == "Mundo"


# ===========================================================================
# _legal_review_with_retry
# ===========================================================================


def test_legal_review_with_retry_success_on_first_attempt() -> None:
    """Successful first attempt must return result with skipped=False."""
    reviewer = MagicMock()
    reviewer.review_legal_terms.return_value = {"status": "ok", "corrections": []}
    result = dag_mod._legal_review_with_retry("some legal text", reviewer)
    assert result["skipped"] is False
    assert result["status"] == "ok"
    reviewer.review_legal_terms.assert_called_once()


def test_legal_review_with_retry_all_fail_returns_skipped() -> None:
    """All retry attempts failing must return status='skipped', skipped=True."""
    reviewer = MagicMock()
    reviewer.review_legal_terms.side_effect = Exception("Vertex unavailable")
    with patch("dags.form_pretranslation_dag.time.sleep"):
        result = dag_mod._legal_review_with_retry("text", reviewer)
    assert result["skipped"] is True
    assert result["status"] == "skipped"
    assert "corrections" in result


def test_legal_review_with_retry_retries_correct_number_of_times() -> None:
    """Must retry exactly len(Vertex_RETRY_DELAYS) times before giving up."""
    reviewer = MagicMock()
    reviewer.review_legal_terms.side_effect = Exception("always fails")
    with patch("dags.form_pretranslation_dag.time.sleep"):
        dag_mod._legal_review_with_retry("text", reviewer)
    assert reviewer.review_legal_terms.call_count == len(dag_mod.Vertex_RETRY_DELAYS)


def test_legal_review_with_retry_succeeds_on_second_attempt() -> None:
    """Success on second attempt must return the successful result."""
    reviewer = MagicMock()
    reviewer.review_legal_terms.side_effect = [
        Exception("first attempt fails"),
        {"status": "ok", "corrections": ["fix1"]},
    ]
    with patch("dags.form_pretranslation_dag.time.sleep"):
        result = dag_mod._legal_review_with_retry("text", reviewer)
    assert result["skipped"] is False
    assert result["corrections"] == ["fix1"]
    assert reviewer.review_legal_terms.call_count == 2


def test_legal_review_with_retry_includes_reason_on_failure() -> None:
    """Failed result must include the reason string from the last exception."""
    reviewer = MagicMock()
    reviewer.review_legal_terms.side_effect = Exception("connection timeout")
    with patch("dags.form_pretranslation_dag.time.sleep"):
        result = dag_mod._legal_review_with_retry("text", reviewer)
    assert "connection timeout" in result.get("reason", "")


# ===========================================================================
# task_load_form_entry
# ===========================================================================


def test_task_load_form_entry_missing_form_id_raises() -> None:
    """Missing form_id in conf must raise ValueError."""
    ctx = _make_context(conf={})
    with pytest.raises(ValueError, match="form_id"):
        dag_mod.task_load_form_entry(**ctx)


@patch(f"{_PATCH_BASE}.get_sync_engine")
def test_task_load_form_entry_not_in_db_raises(mock_engine) -> None:
    """form_id not found in DB must raise ValueError."""
    mock_engine.return_value = MagicMock()
    with patch(f"{_PATCH_BASE}.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session
        with patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=None):
            ctx = _make_context(conf={"form_id": _FORM_ID})
            with pytest.raises(ValueError, match="not found"):
                dag_mod.task_load_form_entry(**ctx)


@patch(f"{_PATCH_BASE}.get_sync_engine")
@patch(f"{_PATCH_BASE}.gcs.parse_gcs_uri")
@patch(f"{_PATCH_BASE}.gcs.download_file")
def test_task_load_form_entry_already_has_both_returns_skip(mock_dl, mock_parse, mock_engine) -> None:
    """Form with both ES and PT already → must return skip=True without downloading."""
    mock_engine.return_value = MagicMock()
    mock_parse.return_value = ("bucket", "blob")

    # Build a mock ORM form with both translations
    mock_form = MagicMock()
    mock_form.form_name = "Test Form"
    mock_form.form_slug = "test-form"
    mock_form.preprocessing_flags = []

    mock_version = MagicMock()
    mock_version.version = 1
    mock_version.file_path_original = "gs://bucket/original.pdf"
    mock_version.file_path_es = "gs://bucket/es.pdf"
    mock_version.file_path_pt = "gs://bucket/pt.pdf"
    mock_form.versions = [mock_version]

    with patch(f"{_PATCH_BASE}.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session
        with patch(f"{_PATCH_BASE}.form_queries.get_form_by_id_sync", return_value=mock_form):
            ctx = _make_context(conf={"form_id": _FORM_ID})
            result = dag_mod.task_load_form_entry(**ctx)

    assert result["skip"] is True
    assert result["form_id"] == _FORM_ID
    mock_dl.assert_not_called()


# ===========================================================================
# task_translate_spanish (skip paths)
# ===========================================================================


def test_translate_spanish_skips_when_already_has_es() -> None:
    """already_has_es=True → must push empty regions and return {} without translating."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(already_has_es=True)
        if key == "ocr_result":
            return _make_ocr_result()
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.Translator"):
        result = dag_mod.task_translate_spanish(**ctx)
    assert result == {}
    ctx["ti"].xcom_push.assert_called_once_with(key="regions_es", value=[])


def test_translate_spanish_skips_when_skip_flag_set() -> None:
    """skip=True → must push empty regions without loading Translator."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(skip=True)
        if key == "ocr_result":
            return _make_ocr_result()
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.Translator") as mock_translator:
        dag_mod.task_translate_spanish(**ctx)
    mock_translator.assert_not_called()


# ===========================================================================
# task_translate_portuguese (skip path)
# ===========================================================================


def test_translate_portuguese_skips_when_already_has_pt() -> None:
    """already_has_pt=True → must push empty regions and return {}."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(already_has_pt=True)
        if key == "ocr_result":
            return _make_ocr_result()
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.Translator"):
        result = dag_mod.task_translate_portuguese(**ctx)
    assert result == {}
    ctx["ti"].xcom_push.assert_called_once_with(key="regions_pt", value=[])


# ===========================================================================
# task_legal_review_spanish / portuguese (skip paths)
# ===========================================================================


def test_legal_review_spanish_skips_when_already_has_es() -> None:
    """already_has_es=True → must push skipped status without calling LegalReviewer."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(already_has_es=True)
        if key == "ocr_result":
            return _make_ocr_result()
        if key == "regions_es":
            return []
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.LegalReviewer") as mock_lr:
        result = dag_mod.task_legal_review_spanish(**ctx)
    mock_lr.assert_not_called()
    assert result == {}
    pushed = ctx["ti"].xcom_push.call_args.kwargs
    assert pushed["key"] == "legal_review_es"
    assert pushed["value"]["status"] == "skipped_existing"


def test_legal_review_portuguese_skips_when_already_has_pt() -> None:
    """already_has_pt=True → must push skipped status without calling LegalReviewer."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(already_has_pt=True)
        if key == "ocr_result":
            return _make_ocr_result()
        if key == "regions_pt":
            return []
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.LegalReviewer") as mock_lr:
        result = dag_mod.task_legal_review_portuguese(**ctx)
    mock_lr.assert_not_called()
    assert result == {}
    pushed = ctx["ti"].xcom_push.call_args.kwargs
    assert pushed["key"] == "legal_review_pt"
    assert pushed["value"]["status"] == "skipped_existing"


# ===========================================================================
# task_reconstruct_pdf_spanish (skip path)
# ===========================================================================


def test_reconstruct_pdf_spanish_skips_when_already_has_es() -> None:
    """already_has_es=True → must push path_es=None and return {} immediately."""
    ctx = _make_context()

    def _pull(task_ids, key):
        if key == "form_meta":
            return _make_form_meta(already_has_es=True)
        if key == "regions_es":
            return []
        return None

    ctx["ti"].xcom_pull = MagicMock(side_effect=_pull)
    with patch(f"{_PATCH_BASE}.reconstruct_pdf") as mock_recon:
        result = dag_mod.task_reconstruct_pdf_spanish(**ctx)
    mock_recon.assert_not_called()
    assert result == {}
    ctx["ti"].xcom_push.assert_called_once_with(key="path_es", value=None)


# ===========================================================================
# task_ocr_extract_text (skip path)
# ===========================================================================


def test_ocr_extract_text_skips_when_skip_flag_set() -> None:
    """skip=True → must push empty regions without loading OCREngine."""
    ctx = _make_context()
    ctx["ti"].xcom_pull = MagicMock(return_value=_make_form_meta(skip=True))

    with patch(f"{_PATCH_BASE}.OCREngine") as mock_ocr:
        dag_mod.task_ocr_extract_text(**ctx)
    mock_ocr.assert_not_called()
    ctx["ti"].xcom_push.assert_called_once_with(key="ocr_result", value={"regions": [], "full_text": ""})
