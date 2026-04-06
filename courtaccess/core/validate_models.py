"""
courtaccess/core/validate_models.py

Translation pipeline quality validation against a fixed reference dataset.

Runnable as:
    python -m courtaccess.core.validate_models
    validate-models   (pyproject.toml [project.scripts] entry point)

Two execution contexts:
  CI (test.yml)         — MLFLOW_TRACKING_URI=file:///tmp/mlflow (local FS, no server)
  Pre-deploy (deploy.yml) — MLFLOW_TRACKING_URI=http://mlflow:5000 (real server, visible in UI)

Metrics logged per run:
  nllb_non_empty_rate   — fraction of 20 phrases with non-empty output  (should be 1.0)
  nllb_avg_confidence   — average translate_text()[\"confidence\"] across all phrases
  nllb_changed_rate     — fraction where output ≠ input (NLLB actually translated)
  llama_correction_rate — fraction of spans where Llama changed the NLLB output
  llama_not_verified_rate — fraction of outputs starting with [NOT VERIFIED …]

Params logged (configuration snapshot, not numeric metrics):
  use_real_translation
  use_vertex_legal_review
  nllb_model_path
  target_language
  validation_set_size
  confidence_threshold

Threshold gate:
  Read VALIDATION_CONFIDENCE_THRESHOLD from env (default 0.0).
  If nllb_avg_confidence < threshold → exit(1), blocking CI/CD job.

MLflow experiment: courtaccess-model-validation  (separate from model-registry)
Run name:         validation-{YYYY-MM-DD}-{stub|real}
"""

import logging
import os
import sys
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ── Ground-truth validation set (EN → ES) ─────────────────────────────────────
# Sourced from the NJ Courts legal glossary already parsed in this project.
# These are fixed reference translations, NOT generated or approximate.
# DO NOT modify without a corresponding note in the PR — they are the gate.
VALIDATION_SET: list[tuple[str, str]] = [
    ("arraignment", "lectura de cargos"),
    ("bail", "fianza"),
    ("contempt of court", "desacato al tribunal"),
    ("defendant", "acusado"),
    ("plaintiff", "demandante"),
    ("subpoena", "citación"),
    ("affidavit", "declaración jurada"),
    ("continuance", "aplazamiento"),
    ("custody", "custodia"),
    ("indictment", "acusación formal"),
    ("injunction", "interdicto"),
    ("jurisdiction", "jurisdicción"),
    ("parole", "libertad condicional"),
    ("probation", "libertad supervisada"),
    ("summons", "citación judicial"),
    ("verdict", "veredicto"),
    ("warrant", "orden judicial"),
    ("deposition", "declaración bajo juramento"),
    ("felony", "delito grave"),
    ("misdemeanor", "delito menor"),
]

EXPERIMENT_NAME = "courtaccess-model-validation"
TARGET_LANG = "spa_Latn"


def _run_name(use_real: bool) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    mode = "real" if use_real else "stub"
    return f"validation-{date}-{mode}"


def validate(project_root: str = ".") -> dict:
    """
    Run the validation against the 20-phrase reference set.

    Returns a dict with all computed metrics and params so callers
    (tests, CI scripts) can inspect values without re-parsing MLflow.
    """
    from courtaccess.core.config import settings

    use_real_translation = settings.use_real_translation
    use_vertex_legal_review = settings.use_vertex_legal_review
    nllb_model_path = settings.nllb_model_path or "/opt/airflow/models/nllb-200-distilled-1.3B-ct2"
    threshold = settings.validation_confidence_threshold

    # ── Params (logged as MLflow params — strings, not floats) ───────────────
    params = {
        "use_real_translation": str(use_real_translation).lower(),
        "use_vertex_legal_review": str(use_vertex_legal_review).lower(),
        "nllb_model_path": nllb_model_path,
        "target_language": "es",
        "validation_set_size": str(len(VALIDATION_SET)),
        "confidence_threshold": str(threshold),
    }

    # ── Build translator ──────────────────────────────────────────────────────
    from courtaccess.core.translation import Translator
    from courtaccess.languages import get_language_config

    config = get_language_config("spanish")
    translator = Translator(config).load()

    phrases_en = [pair[0] for pair in VALIDATION_SET]

    # ── NLLB metrics ─────────────────────────────────────────────────────────
    nllb_outputs: list[str] = []
    confidences: list[float] = []
    non_empty_count = 0
    changed_count = 0

    for phrase in phrases_en:
        result = translator.translate_text(phrase, TARGET_LANG)
        translated = result.get("translated", "") or ""
        confidence = float(result.get("confidence", 0.0))

        nllb_outputs.append(translated)
        confidences.append(confidence)

        if translated and translated.strip():
            non_empty_count += 1

        if translated.strip() != phrase.strip():
            changed_count += 1

    n = len(VALIDATION_SET)
    nllb_non_empty_rate = non_empty_count / n
    nllb_avg_confidence = sum(confidences) / n if confidences else 0.0
    nllb_changed_rate = changed_count / n

    # ── Llama legal review metrics ────────────────────────────────────────────
    from courtaccess.core.legal_review import LegalReviewer

    reviewer = LegalReviewer(config)
    verified_outputs = reviewer.verify_batch(phrases_en, nllb_outputs)

    _not_verified_prefix = "[NOT VERIFIED"
    correction_count = 0
    not_verified_count = 0

    for nllb_out, verified in zip(nllb_outputs, verified_outputs, strict=False):
        if verified != nllb_out:
            correction_count += 1
        if verified.startswith(_not_verified_prefix):
            not_verified_count += 1

    llama_correction_rate = correction_count / n
    llama_not_verified_rate = not_verified_count / n

    # ── Log to MLflow ─────────────────────────────────────────────────────────
    mlflow = None
    try:
        import mlflow as _mlflow

        tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
        _mlflow.set_tracking_uri(tracking_uri)
        _mlflow.set_experiment(EXPERIMENT_NAME)
        mlflow = _mlflow
        logger.info("MLflow connected at %s", tracking_uri)
    except Exception as exc:
        logger.warning("MLflow unavailable (%s) — results will not be persisted.", exc)

    metrics = {
        "nllb_non_empty_rate": nllb_non_empty_rate,
        "nllb_avg_confidence": nllb_avg_confidence,
        "nllb_changed_rate": nllb_changed_rate,
        "llama_correction_rate": llama_correction_rate,
        "llama_not_verified_rate": llama_not_verified_rate,
    }

    if mlflow is not None:
        try:
            with mlflow.start_run(run_name=_run_name(use_real_translation)):
                mlflow.log_params(params)
                mlflow.log_metrics(metrics)
            logger.info("Metrics logged to MLflow experiment '%s'.", EXPERIMENT_NAME)
        except Exception as exc:
            logger.error("Failed to log metrics to MLflow: %s", exc)

    return {"params": params, "metrics": metrics, "threshold": threshold}


def main() -> None:
    """CLI / module entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    result = validate()
    metrics = result["metrics"]
    threshold = result["threshold"]

    # ── Print summary table ───────────────────────────────────────────────────
    print("\n" + "=" * 68)  # noqa: T201
    print("  Metric                         Value")  # noqa: T201
    print("=" * 68)  # noqa: T201
    for name, value in metrics.items():
        print(f"  {name:<32} {value:.4f}")  # noqa: T201
    print("=" * 68)  # noqa: T201

    # ── Per-phrase detail ─────────────────────────────────────────────────────
    print("\n  Phrase-level results (EN → NLLB output):")  # noqa: T201
    from courtaccess.core.translation import Translator
    from courtaccess.languages import get_language_config

    config = get_language_config("spanish")
    translator = Translator(config).load()

    for en, _expected_es in VALIDATION_SET:
        result_dict = translator.translate_text(en, TARGET_LANG)
        translated = result_dict.get("translated", "")
        conf = result_dict.get("confidence", 0.0)
        print(f"  [{conf:.2f}] {en!r:30} → {translated!r}")  # noqa: T201

    # ── Threshold gate ────────────────────────────────────────────────────────
    avg_conf = metrics["nllb_avg_confidence"]
    print(f"\n  Average confidence: {avg_conf:.4f} (threshold: {threshold})")  # noqa: T201

    if avg_conf < threshold:
        print(  # noqa: T201
            f"\n❌ Validation FAILED — nllb_avg_confidence {avg_conf:.4f} "
            f"is below threshold {threshold}. Blocking deployment."
        )
        sys.exit(1)

    print(  # noqa: T201
        f"\n✅ Validation PASSED — "
        f"non_empty={metrics['nllb_non_empty_rate']:.2f} "
        f"avg_conf={avg_conf:.4f} "
        f"changed={metrics['nllb_changed_rate']:.2f}"
    )


if __name__ == "__main__":
    main()
