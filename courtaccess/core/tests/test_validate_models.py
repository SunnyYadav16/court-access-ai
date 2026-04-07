"""
Unit tests for courtaccess/core/validate_models.py

Functions under test:
  _run_name       — pure: format a dated MLflow run name
  VALIDATION_SET  — constant: 20 EN→ES reference phrase pairs
  validate        — orchestration: translate 20 phrases, compute metrics

Design notes:
  - _run_name is pure; tested directly with no mocking.
  - validate() has lazy imports inside the function body
    (from courtaccess.core.config import settings, etc.).
    External deps patched at their source module so that the
    function body picks up the mocks:
      patch("courtaccess.core.config.settings", mock_settings)
      patch("courtaccess.core.translation.Translator")
      patch("courtaccess.languages.get_language_config")
      patch("courtaccess.core.legal_review.LegalReviewer")
    MLflow is disabled by injecting None into sys.modules.
  - The `validated` fixture runs validate() once with all translations
    returning non-empty "[ES]{phrase}" at confidence=0.85, and the
    reviewer passing translations through unchanged. This covers the
    base metrics contract.
  - Additional tests swap reviewer behaviour to exercise
    llama_correction_rate and llama_not_verified_rate.
  - courtaccess.core.config requires 5 env vars absent from .env; set via
    os.environ.setdefault at module level so Settings() can be constructed
    when the module is first imported by patch().
"""

import os

# Five required Settings fields absent from .env — must be set before the
# first import of courtaccess.core.config triggers Settings().
os.environ.setdefault("GCS_BUCKET_TRANSCRIPTS", "test-transcripts")
os.environ.setdefault("USE_REAL_SPEECH", "false")
os.environ.setdefault("ROOM_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("ROOM_JWT_EXPIRY_HOURS", "24")
os.environ.setdefault("ROOM_CODE_EXPIRY_MINUTES", "30")

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from courtaccess.core.validate_models import (
    EXPERIMENT_NAME,
    TARGET_LANG,
    VALIDATION_SET,
    _run_name,
    validate,
)

# ─────────────────────────────────────────────────────────────────────────────
# _run_name — pure function
# ─────────────────────────────────────────────────────────────────────────────


class TestRunName:

    def test_stub_mode_contains_stub(self):
        assert "stub" in _run_name(False)

    def test_real_mode_contains_real(self):
        assert "real" in _run_name(True)

    def test_starts_with_validation_prefix(self):
        assert _run_name(False).startswith("validation-")

    def test_contains_todays_date(self):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert today in _run_name(True)

    def test_returns_non_empty_string(self):
        result = _run_name(False)
        assert isinstance(result, str) and len(result) > 0


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION_SET — constant
# ─────────────────────────────────────────────────────────────────────────────


class TestValidationSet:

    def test_has_exactly_20_entries(self):
        assert len(VALIDATION_SET) == 20

    def test_all_entries_are_two_tuples_of_strings(self):
        for entry in VALIDATION_SET:
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], str)

    def test_no_empty_strings(self):
        for en, es in VALIDATION_SET:
            assert en.strip(), f"Empty English phrase found: {en!r}"
            assert es.strip(), f"Empty Spanish phrase found: {es!r}"

    def test_first_entry_is_arraignment(self):
        assert VALIDATION_SET[0] == ("arraignment", "lectura de cargos")

    def test_all_english_phrases_are_unique(self):
        english = [pair[0] for pair in VALIDATION_SET]
        assert len(english) == len(set(english))


# ─────────────────────────────────────────────────────────────────────────────
# validate() — fixtures and helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_settings(**kwargs):
    """Build a MagicMock settings object with sensible defaults."""
    s = MagicMock()
    s.use_real_translation = kwargs.get("use_real_translation", False)
    s.use_vertex_legal_review = kwargs.get("use_vertex_legal_review", False)
    s.nllb_model_path = kwargs.get("nllb_model_path", "/fake/nllb")
    s.validation_confidence_threshold = kwargs.get("validation_confidence_threshold", 0.0)
    return s


def _make_translator_mock(translate_side_effect=None):
    """Return a (class_mock, instance_mock) pair for Translator."""
    instance = MagicMock()
    if translate_side_effect is None:
        instance.translate_text.side_effect = lambda phrase, lang: {
            "translated": f"[ES]{phrase}",
            "confidence": 0.85,
        }
    else:
        instance.translate_text.side_effect = translate_side_effect
    instance.load.return_value = instance
    cls = MagicMock(return_value=instance)
    return cls, instance


def _make_reviewer_mock(verify_side_effect=None):
    """Return a (class_mock, instance_mock) pair for LegalReviewer."""
    instance = MagicMock()
    if verify_side_effect is None:
        instance.verify_batch.side_effect = lambda orig, trans: trans
    else:
        instance.verify_batch.side_effect = verify_side_effect
    cls = MagicMock(return_value=instance)
    return cls, instance


def _run_validate(mock_settings=None, translator_cls=None, reviewer_cls=None):
    """Run validate() with all deps mocked; mlflow is always disabled."""
    if mock_settings is None:
        mock_settings = _make_mock_settings()
    if translator_cls is None:
        translator_cls, _ = _make_translator_mock()
    if reviewer_cls is None:
        reviewer_cls, _ = _make_reviewer_mock()

    with (
        patch("courtaccess.core.config.settings", mock_settings),
        patch("courtaccess.core.translation.Translator", translator_cls),
        patch("courtaccess.languages.get_language_config"),
        patch("courtaccess.core.legal_review.LegalReviewer", reviewer_cls),
        patch.dict("sys.modules", {"mlflow": None}),
    ):
        return validate()


@pytest.fixture()
def validated():
    """Run validate() once with default mocks; return the result dict."""
    return _run_validate()


# ─────────────────────────────────────────────────────────────────────────────
# validate() — output contract
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateOutputContract:

    def test_returns_dict_with_params_key(self, validated):
        assert "params" in validated

    def test_returns_dict_with_metrics_key(self, validated):
        assert "metrics" in validated

    def test_returns_dict_with_threshold_key(self, validated):
        assert "threshold" in validated

    def test_metrics_has_all_five_required_keys(self, validated):
        expected = {
            "nllb_non_empty_rate",
            "nllb_avg_confidence",
            "nllb_changed_rate",
            "llama_correction_rate",
            "llama_not_verified_rate",
        }
        assert expected.issubset(validated["metrics"].keys())

    def test_params_validation_set_size_is_twenty(self, validated):
        assert validated["params"]["validation_set_size"] == "20"

    def test_params_target_language_is_es(self, validated):
        assert validated["params"]["target_language"] == "es"

    def test_threshold_is_float(self, validated):
        assert isinstance(validated["threshold"], float)


# ─────────────────────────────────────────────────────────────────────────────
# validate() — metric computation correctness
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateMetrics:

    def test_nllb_non_empty_rate_is_one_for_all_non_empty(self, validated):
        assert validated["metrics"]["nllb_non_empty_rate"] == pytest.approx(1.0)

    def test_nllb_changed_rate_is_one_when_all_differ_from_input(self, validated):
        # "[ES]{phrase}" != phrase → all changed
        assert validated["metrics"]["nllb_changed_rate"] == pytest.approx(1.0)

    def test_nllb_avg_confidence_computed_from_mock_values(self, validated):
        assert validated["metrics"]["nllb_avg_confidence"] == pytest.approx(0.85)

    def test_llama_correction_rate_zero_when_reviewer_passthrough(self, validated):
        assert validated["metrics"]["llama_correction_rate"] == pytest.approx(0.0)

    def test_llama_not_verified_rate_zero_by_default(self, validated):
        assert validated["metrics"]["llama_not_verified_rate"] == pytest.approx(0.0)

    def test_nllb_non_empty_rate_zero_when_all_empty(self):
        translator_cls, _ = _make_translator_mock(
            translate_side_effect=lambda phrase, lang: {"translated": "", "confidence": 0.5}
        )
        result = _run_validate(translator_cls=translator_cls)
        assert result["metrics"]["nllb_non_empty_rate"] == pytest.approx(0.0)

    def test_llama_correction_rate_one_when_reviewer_changes_all(self):
        reviewer_cls, _ = _make_reviewer_mock(
            verify_side_effect=lambda orig, trans: ["CHANGED"] * len(trans)
        )
        result = _run_validate(reviewer_cls=reviewer_cls)
        assert result["metrics"]["llama_correction_rate"] == pytest.approx(1.0)

    def test_llama_not_verified_rate_one_when_all_prefixed(self):
        reviewer_cls, _ = _make_reviewer_mock(
            verify_side_effect=lambda orig, trans: [f"[NOT VERIFIED] {t}" for t in trans]
        )
        result = _run_validate(reviewer_cls=reviewer_cls)
        assert result["metrics"]["llama_not_verified_rate"] == pytest.approx(1.0)

    def test_nllb_changed_rate_zero_when_translation_equals_input(self):
        # Translator echoes input back → changed_rate = 0
        translator_cls, _ = _make_translator_mock(
            translate_side_effect=lambda phrase, lang: {"translated": phrase, "confidence": 0.9}
        )
        result = _run_validate(translator_cls=translator_cls)
        assert result["metrics"]["nllb_changed_rate"] == pytest.approx(0.0)

    def test_translate_text_called_once_per_phrase(self):
        translator_cls, instance = _make_translator_mock()
        _run_validate(translator_cls=translator_cls)
        assert instance.translate_text.call_count == len(VALIDATION_SET)

    def test_verify_batch_called_once_with_all_phrases(self):
        reviewer_cls, instance = _make_reviewer_mock()
        _run_validate(reviewer_cls=reviewer_cls)
        instance.verify_batch.assert_called_once()
        orig_arg, trans_arg = instance.verify_batch.call_args[0]
        assert len(orig_arg) == len(VALIDATION_SET)
        assert len(trans_arg) == len(VALIDATION_SET)


# ─────────────────────────────────────────────────────────────────────────────
# validate() — MLflow and settings integration
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateIntegration:

    def test_mlflow_unavailable_does_not_crash(self):
        # Already covered by all tests above (mlflow=None), but explicit check
        result = _run_validate()
        assert "metrics" in result

    def test_params_reflect_settings_use_real_translation(self):
        settings = _make_mock_settings(use_real_translation=True)
        result = _run_validate(mock_settings=settings)
        assert result["params"]["use_real_translation"] == "true"

    def test_params_nllb_model_path_from_settings(self):
        settings = _make_mock_settings(nllb_model_path="/custom/nllb")
        result = _run_validate(mock_settings=settings)
        assert result["params"]["nllb_model_path"] == "/custom/nllb"

    def test_threshold_from_settings(self):
        settings = _make_mock_settings(validation_confidence_threshold=0.75)
        result = _run_validate(mock_settings=settings)
        assert result["threshold"] == pytest.approx(0.75)

    def test_module_constants_are_non_empty_strings(self):
        assert isinstance(EXPERIMENT_NAME, str) and EXPERIMENT_NAME
        assert isinstance(TARGET_LANG, str) and TARGET_LANG
