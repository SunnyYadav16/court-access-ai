"""
courtaccess/core/sensitivity_analysis.py

Sensitivity analysis for the CourtAccess AI system.
Maps to Section 5 of the submission PDF:
  "how the model's performance changes with respect to different
   input features or hyperparameters."

Two sub-analyses in one script:

Sub-analysis A - Threshold sensitivity (hyperparameter sensitivity)
  Sweeps UNDERSERVED_THRESHOLD (0.1-0.9) and TRANSLATION_COVERAGE_THRESHOLD
  (10-40) across all combinations, re-running run_bias_detection() for each
  pair.  Each sweep point is a separate MLflow run so the full grid is
  visible in the UI.  Also computes threshold_sensitivity_score
  (std-dev of bias_flags_count across all sweep points) to quantify
  how much the flag count depends on threshold choice.

Sub-analysis B — Input characteristic analysis (feature correlations)
  Queries the PostgreSQL translation_requests and pipeline_steps tables for
  completed document sessions and computes:
    • Pearson correlation between processing_time_seconds and avg_confidence_score
    • Average avg_confidence_score per target_language
    • Average llama_corrections_count per target_language
    • Per-language correction_rate = llama_corrections_count / total_regions
      (total_regions comes from pipeline_steps.metadata for step ocr_printed_text)
  Graceful DB fallback: if the DB is unreachable (CI, no DATABASE_URL), logs a
  warning and skips Sub-analysis B without failing the process.

MLflow experiment: courtaccess-sensitivity-analysis
Run names:
  threshold-sweep-u{U_VAL}-t{T_VAL}     (one per grid cell)
  threshold-sweep-summary                (std-dev summary run)
  input-characteristics-{YYYY-MM-DD}     (Sub-analysis B)

Runnable as:
    python -m courtaccess.core.sensitivity_analysis
    sensitivity-analysis   (pyproject.toml [project.scripts] entry point)
"""

import logging
import math
import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Experiment name ───────────────────────────────────────────────────────────
EXPERIMENT_NAME = "courtaccess-sensitivity-analysis"

# ── Sub-analysis A sweep ranges ───────────────────────────────────────────────
# UNDERSERVED_THRESHOLD: fraction of mean below which a division is flagged
UNDERSERVED_SWEEP = [round(v * 0.1, 1) for v in range(1, 10)]  # 0.1 … 0.9
# TRANSLATION_COVERAGE_THRESHOLD: min % coverage below which a language is flagged
COVERAGE_SWEEP = list(range(10, 45, 5))  # 10, 15, 20 … 40

# ── Catalog path (DVC-tracked) ────────────────────────────────────────────────
DEFAULT_CATALOG_PATH = Path("courtaccess/data/form_catalog.json")

# ── Sub-analysis B: OCR step name whose metadata holds total_regions ──────────
OCR_STEP_NAME = "ocr_printed_text"


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _load_catalog(catalog_path: Path) -> list[dict]:
    """Load catalog from JSON file.  Returns [] if file does not exist."""
    if not catalog_path.exists():
        logger.warning("Catalog file not found at %s — Sub-analysis A will use an empty set.", catalog_path)
        return []
    import json

    return json.loads(catalog_path.read_text(encoding="utf-8"))


def _stdev(values: list[float]) -> float:
    """Population standard deviation (returns 0.0 for < 2 values)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((x - mean) ** 2 for x in values) / n)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient.  Returns None if not computable."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=False))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


# ══════════════════════════════════════════════════════════════════════════════
# Sub-analysis A — Threshold sensitivity
# ══════════════════════════════════════════════════════════════════════════════


def run_threshold_sweep(
    catalog: list[dict],
    mlflow,  # may be None (graceful fallback)
) -> dict[str, Any]:
    """
    Grid-sweep UNDERSERVED_THRESHOLD x TRANSLATION_COVERAGE_THRESHOLD.

    For each pair, calls run_bias_detection(catalog, underserved_threshold=u_thresh,
    translation_coverage_min=t_thresh) using the optional override parameters,
    and records bias_count + critical_flags_count.

    Returns:
        {
          "grid": [{u, t, bias_flags_count, critical_flags_count}, ...],
          "threshold_sensitivity_score": float,  # std-dev of bias_flags_count
        }
    """
    from courtaccess.monitoring.drift import run_bias_detection

    grid: list[dict] = []

    logger.info(
        "Starting threshold sweep: %d x %d = %d combinations",
        len(UNDERSERVED_SWEEP),
        len(COVERAGE_SWEEP),
        len(UNDERSERVED_SWEEP) * len(COVERAGE_SWEEP),
    )

    for u_thresh in UNDERSERVED_SWEEP:
        for t_thresh in COVERAGE_SWEEP:
            report = run_bias_detection(
                catalog,
                underserved_threshold=u_thresh,
                translation_coverage_min=t_thresh,
            )

            bias_count = report.get("bias_count", 0)
            critical_count = sum(1 for f in report.get("bias_flags", []) if f.get("severity", "").upper() == "CRITICAL")

            grid.append(
                {
                    "underserved_threshold": u_thresh,
                    "translation_coverage_threshold": t_thresh,
                    "bias_flags_count": bias_count,
                    "critical_flags_count": critical_count,
                }
            )

            logger.debug(
                "  u=%.1f t=%d → bias_flags=%d critical=%d",
                u_thresh,
                t_thresh,
                bias_count,
                critical_count,
            )

            # Log to MLflow — one run per grid cell
            if mlflow is not None:
                try:
                    run_name = f"threshold-sweep-u{u_thresh}-t{t_thresh}"
                    with mlflow.start_run(run_name=run_name, nested=False):
                        mlflow.log_params(
                            {
                                "underserved_threshold": str(u_thresh),
                                "translation_coverage_threshold": str(t_thresh),
                            }
                        )
                        mlflow.log_metrics(
                            {
                                "bias_flags_count": float(bias_count),
                                "critical_flags_count": float(critical_count),
                            }
                        )
                except Exception as exc:
                    logger.warning("MLflow run logging failed for u=%.1f t=%d: %s", u_thresh, t_thresh, exc)

    # ── Summary metric: std-dev of bias_flags_count across all cells ──────────
    bias_counts = [g["bias_flags_count"] for g in grid]
    sensitivity_score = _stdev(bias_counts)
    logger.info(
        "Threshold sweep complete. bias_flags_count range: [%d, %d], std-dev=%.3f",
        int(min(bias_counts)) if bias_counts else 0,
        int(max(bias_counts)) if bias_counts else 0,
        sensitivity_score,
    )

    if mlflow is not None:
        with suppress(Exception), mlflow.start_run(run_name="threshold-sweep-summary"):
            mlflow.log_metric("threshold_sensitivity_score", sensitivity_score)
            mlflow.log_metric("sweep_points_total", float(len(grid)))
            mlflow.log_metric("bias_flags_min", float(min(bias_counts)) if bias_counts else 0.0)
            mlflow.log_metric("bias_flags_max", float(max(bias_counts)) if bias_counts else 0.0)

    return {
        "grid": grid,
        "threshold_sensitivity_score": sensitivity_score,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Sub-analysis B — Input characteristic analysis
# ══════════════════════════════════════════════════════════════════════════════


def run_input_characteristics(mlflow) -> dict[str, Any] | None:
    """
    Query translation_requests + pipeline_steps and compute feature correlations.

    Returns the computed metrics dict, or None if the DB is unavailable.
    Graceful: DB errors are caught and logged; Sub-analysis A is unaffected.
    """
    database_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not database_url:
        logger.warning(
            "DATABASE_URL not set — skipping Sub-analysis B (input characteristics). "
            "Set DATABASE_URL=postgresql+psycopg2://... to enable."
        )
        return None

    try:
        import sqlalchemy as sa

        from db.database import get_sync_engine

        engine = get_sync_engine()

        # ── Query completed document translation requests ─────────────────────
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT
                        tr.target_language,
                        tr.avg_confidence_score,
                        tr.llama_corrections_count,
                        tr.processing_time_seconds
                    FROM translation_requests tr
                    JOIN sessions s ON s.session_id = tr.session_id
                    WHERE s.type = 'document'
                      AND tr.status = 'completed'
                      AND tr.avg_confidence_score IS NOT NULL
                      AND tr.processing_time_seconds IS NOT NULL
                    """
                )
            ).fetchall()

        if not rows:
            logger.warning(
                "No completed document translation_requests with confidence scores found — "
                "Sub-analysis B metrics will be empty."
            )
            return {
                "row_count": 0,
                "time_confidence_correlation": None,
                "avg_confidence_by_language": {},
                "avg_corrections_by_language": {},
                "correction_rate_by_language": {},
            }

        # ── Organise by language ──────────────────────────────────────────────
        data_by_lang: dict[str, dict[str, list]] = {}
        all_times: list[float] = []
        all_confs: list[float] = []

        for row in rows:
            lang = row[0]  # spa_Latn | por_Latn
            conf = float(row[1])
            corrections = int(row[2] or 0)
            proc_time = float(row[3])

            all_times.append(proc_time)
            all_confs.append(conf)

            if lang not in data_by_lang:
                data_by_lang[lang] = {"conf": [], "corrections": [], "times": []}
            data_by_lang[lang]["conf"].append(conf)
            data_by_lang[lang]["corrections"].append(corrections)
            data_by_lang[lang]["times"].append(proc_time)

        # ── Fetch total_regions per session from pipeline_steps ───────────────
        with engine.connect() as conn:
            ocr_rows = conn.execute(
                sa.text(
                    """
                    SELECT
                        s.target_language,
                        COALESCE((ps.metadata->>'total_regions')::int, 0) AS total_regions,
                        tr.llama_corrections_count
                    FROM pipeline_steps ps
                    JOIN sessions s ON s.session_id = ps.session_id
                    JOIN translation_requests tr ON tr.session_id = s.session_id
                    WHERE ps.step_name = :step_name
                      AND s.type = 'document'
                      AND tr.status = 'completed'
                    """
                ),
                {"step_name": OCR_STEP_NAME},
            ).fetchall()

        # ── Compute correction_rate per language ──────────────────────────────
        lang_regions: dict[str, list[int]] = {}
        lang_corrections_ocr: dict[str, list[int]] = {}
        for row in ocr_rows:
            lang = row[0]
            regions = int(row[1])
            corrections = int(row[2] or 0)
            lang_regions.setdefault(lang, []).append(regions)
            lang_corrections_ocr.setdefault(lang, []).append(corrections)

        correction_rate_by_language: dict[str, float] = {}
        for lang in lang_regions:
            total_regions = sum(lang_regions[lang])
            total_corrections = sum(lang_corrections_ocr[lang])
            correction_rate_by_language[lang] = (
                round(total_corrections / total_regions, 4) if total_regions > 0 else 0.0
            )

        # ── Core metrics ──────────────────────────────────────────────────────
        time_conf_corr = _pearson(all_times, all_confs)

        avg_confidence_by_language = {
            lang: round(sum(d["conf"]) / len(d["conf"]), 4) for lang, d in data_by_lang.items()
        }
        avg_corrections_by_language = {
            lang: round(sum(d["corrections"]) / len(d["corrections"]), 4) for lang, d in data_by_lang.items()
        }

        metrics = {
            "row_count": len(rows),
            "time_confidence_correlation": round(time_conf_corr, 4) if time_conf_corr is not None else None,
            "avg_confidence_by_language": avg_confidence_by_language,
            "avg_corrections_by_language": avg_corrections_by_language,
            "correction_rate_by_language": correction_rate_by_language,
        }

        logger.info("Input characteristic analysis computed on %d rows.", len(rows))
        for lang, conf in avg_confidence_by_language.items():
            logger.info(
                "  %s: avg_confidence=%.4f corrections_per_request=%.4f",
                lang,
                conf,
                avg_corrections_by_language.get(lang, 0.0),
            )
        if time_conf_corr is not None:
            logger.info("  time↔confidence Pearson r=%.4f", time_conf_corr)

        # ── Log to MLflow ─────────────────────────────────────────────────────
        if mlflow is not None:
            try:
                date = datetime.now(UTC).strftime("%Y-%m-%d")
                flat_metrics: dict[str, float] = {
                    "row_count": float(len(rows)),
                    "time_confidence_correlation": float(time_conf_corr) if time_conf_corr is not None else 0.0,
                }
                for lang, val in avg_confidence_by_language.items():
                    safe = lang.replace("_", ".")
                    flat_metrics[f"avg_confidence_{safe}"] = val
                for lang, val in avg_corrections_by_language.items():
                    safe = lang.replace("_", ".")
                    flat_metrics[f"avg_corrections_{safe}"] = val
                for lang, val in correction_rate_by_language.items():
                    safe = lang.replace("_", ".")
                    flat_metrics[f"correction_rate_{safe}"] = val

                with mlflow.start_run(run_name=f"input-characteristics-{date}"):
                    mlflow.log_metrics(flat_metrics)
                    mlflow.log_params(
                        {
                            "ocr_step_name": OCR_STEP_NAME,
                            "session_type": "document",
                            "status_filter": "completed",
                        }
                    )
            except Exception as exc:
                logger.warning("MLflow logging failed for input characteristics: %s", exc)

        return metrics

    except Exception as exc:
        logger.warning(
            "Sub-analysis B skipped — DB query failed (%s: %s). "
            "Ensure DATABASE_URL is set and the PostgreSQL instance is reachable.",
            type(exc).__name__,
            exc,
        )
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════


def run_sensitivity_analysis(catalog_path: Path | None = None) -> dict[str, Any]:
    """
    Run both sub-analyses and return their results.

    Args:
        catalog_path: Path to form_catalog.json.  Defaults to
                      courtaccess/data/form_catalog.json relative to cwd.
    """
    if catalog_path is None:
        catalog_path = DEFAULT_CATALOG_PATH

    # ── Connect to MLflow (graceful fallback) ─────────────────────────────────
    mlflow = None
    try:
        import mlflow as _mlflow

        from courtaccess.core.config import settings

        tracking_uri = settings.mlflow_tracking_uri or os.getenv("MLFLOW_TRACKING_URI")
        _mlflow.set_tracking_uri(tracking_uri)
        _mlflow.set_experiment(EXPERIMENT_NAME)
        mlflow = _mlflow
        logger.info("MLflow connected at %s (experiment: %s)", tracking_uri, EXPERIMENT_NAME)
    except Exception as exc:
        logger.warning("MLflow unavailable (%s) — results will not be persisted.", exc)

    # ── Load catalog ──────────────────────────────────────────────────────────
    catalog = _load_catalog(catalog_path)
    logger.info(
        "Catalog loaded: %d entries (%d active).", len(catalog), sum(1 for f in catalog if f.get("status") == "active")
    )

    # ── Sub-analysis A ────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Sub-analysis A: Threshold Sensitivity Sweep")
    logger.info("=" * 60)
    sweep_result = run_threshold_sweep(catalog, mlflow)

    # ── Sub-analysis B ────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Sub-analysis B: Input Characteristic Analysis")
    logger.info("=" * 60)
    input_result = run_input_characteristics(mlflow)

    return {
        "threshold_sweep": sweep_result,
        "input_characteristics": input_result,
    }


def main() -> None:
    """CLI / module entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )

    result = run_sensitivity_analysis()
    sweep = result["threshold_sweep"]
    chars = result["input_characteristics"]

    # ── Print Sub-analysis A summary ──────────────────────────────────────────
    print("\n" + "=" * 70)  # noqa: T201
    print("  Sub-analysis A — Threshold Sensitivity")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print(f"  Sweep points computed : {len(sweep['grid'])}")  # noqa: T201
    print(f"  sensitivity_score     : {sweep['threshold_sensitivity_score']:.4f}  (std-dev of bias_flags_count)")  # noqa: T201

    if sweep["grid"]:
        max_point = max(sweep["grid"], key=lambda g: g["bias_flags_count"])
        min_point = min(sweep["grid"], key=lambda g: g["bias_flags_count"])
        print(  # noqa: T201
            f"  Most sensitive cell   : u={max_point['underserved_threshold']}  t={max_point['translation_coverage_threshold']}  → {max_point['bias_flags_count']} flags"
        )
        print(  # noqa: T201
            f"  Least sensitive cell  : u={min_point['underserved_threshold']}  t={min_point['translation_coverage_threshold']}  → {min_point['bias_flags_count']} flags"
        )

    # ── Print Sub-analysis B summary ──────────────────────────────────────────
    print("\n" + "=" * 70)  # noqa: T201
    print("  Sub-analysis B — Input Characteristics")  # noqa: T201
    print("=" * 70)  # noqa: T201

    if chars is None:
        print("  ⚠  Skipped — DB unreachable or DATABASE_URL not set.")  # noqa: T201
    else:
        print(f"  Rows analysed                   : {chars['row_count']}")  # noqa: T201
        corr = chars["time_confidence_correlation"]
        print(  # noqa: T201
            f"  time↔confidence Pearson r       : {corr:.4f}"
            if corr is not None
            else "  time↔confidence Pearson r       : N/A"
        )
        for lang, conf in chars["avg_confidence_by_language"].items():
            corr_rate = chars["correction_rate_by_language"].get(lang, "N/A")
            print(f"  [{lang}] avg_confidence={conf:.4f}  correction_rate={corr_rate}")  # noqa: T201

    print("\n✅ Sensitivity analysis complete.")  # noqa: T201


if __name__ == "__main__":
    main()
