"""
courtaccess/core/register_models.py

Reads .dvc pointer files from models/ and registers each model version
in MLflow so the deployment registry stays in sync with DVC.

This script is the bridge between DVC (version control for weights)
and MLflow (deployment registry). It answers: "which model versions
are currently tracked, and what are their hashes?"

Run after `dvc pull` or after updating any model:
    python3 -m courtaccess.core.register_models

What it does:
  1. Parses each .dvc pointer file to extract the md5 hash and size
  2. Logs a run in MLflow with model metadata (hash, size, source)
  3. Registers the model version in MLflow Model Registry

If MLflow is unavailable (e.g., local dev without MLflow server),
falls back to logging what would be registered.
"""

import logging
import re
from pathlib import Path

from courtaccess.core.config import settings

logger = logging.getLogger(__name__)

# ── Models tracked by DVC ─────────────────────────────────────────────────────
# Each entry: (dvc_filename, display_name, description)
DVC_MODELS: list[tuple[str, str, str]] = [
    ("whisper-large-v3.dvc", "whisper-large-v3", "Faster-Whisper ASR (CTranslate2)"),
    ("nllb-200-distilled-1.3B-ct2.dvc", "nllb-200-1.3B-ct2", "NLLB-200 Translation (CTranslate2 float16)"),
    ("piper-tts-es.dvc", "piper-tts-es", "Piper TTS Spanish (es_MX ONNX)"),
    ("piper-tts-pt.dvc", "piper-tts-pt", "Piper TTS Portuguese (pt_BR ONNX)"),
    ("spacy-en-core-web-lg.dvc", "spacy-en-core-web-lg", "spaCy NER model for PII detection"),
    ("tfdv-baseline-stats.dvc", "tfdv-baseline-stats", "TFDV monitoring baseline statistics"),
]

# Llama 4 Maverick is API-only (Vertex AI) — no DVC file, registered separately.


def _parse_dvc_file(dvc_path: Path) -> dict | None:
    """
    Extract md5 hash and size from a .dvc pointer file.

    DVC pointer files have YAML-like format:
        outs:
        - md5: abc123...
          size: 612000000
          path: model-dir-name
    """
    if not dvc_path.exists():
        return None

    content = dvc_path.read_text()
    md5_match = re.search(r"md5:\s*([a-f0-9]+)", content)
    size_match = re.search(r"size:\s*(\d+)", content)
    path_match = re.search(r"path:\s*(\S+)", content)

    return {
        "md5": md5_match.group(1) if md5_match else "unknown",
        "size_bytes": int(size_match.group(1)) if size_match else 0,
        "path": path_match.group(1) if path_match else dvc_path.stem,
    }


def register_models(project_root: str = ".") -> list[dict]:
    """
    Register all DVC-tracked models in MLflow.

    Returns:
        List of registration results.
    """
    root = Path(project_root)
    results = []

    # Try to import MLflow — graceful fallback if unavailable
    mlflow = None
    try:
        import mlflow as _mlflow

        _mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        _mlflow.set_experiment("courtaccess-model-registry")
        mlflow = _mlflow
        logger.info("MLflow connected at %s", settings.mlflow_tracking_uri)
    except Exception as exc:
        logger.warning(
            "MLflow unavailable (%s) — running in log-only mode. Models will be listed but not registered.",
            exc,
        )

    # ── Register DVC-tracked models ───────────────────────────────────────────
    for dvc_filename, display_name, description in DVC_MODELS:
        dvc_path = root / "models" / dvc_filename
        parsed = _parse_dvc_file(dvc_path)

        if parsed is None:
            logger.warning("DVC file not found: %s — skipping.", dvc_path)
            results.append(
                {
                    "model_name": display_name,
                    "dvc_file": str(dvc_path),
                    "registered": False,
                    "reason": "dvc_file_missing",
                }
            )
            continue

        model_info = {
            "model_name": display_name,
            "dvc_file": str(dvc_path),
            "md5": parsed["md5"],
            "size_bytes": parsed["size_bytes"],
            "size_mb": round(parsed["size_bytes"] / 1_048_576, 1),
            "description": description,
            "gcs_remote": settings.gcs_bucket_models,
        }

        if mlflow is not None:
            try:
                with mlflow.start_run(run_name=f"register-{display_name}"):
                    mlflow.log_params(
                        {
                            "model_name": display_name,
                            "md5": parsed["md5"],
                            "size_mb": model_info["size_mb"],
                            "dvc_file": dvc_filename,
                            "gcs_bucket": settings.gcs_bucket_models,
                        }
                    )
                    mlflow.log_metrics(
                        {
                            "size_bytes": parsed["size_bytes"],
                        }
                    )
                    mlflow.log_dict(model_info, "model_info.json")

                model_info["registered"] = True
                logger.info(
                    "Registered '%s' in MLflow (md5=%s, size=%sMB).",
                    display_name,
                    parsed["md5"],
                    model_info["size_mb"],
                )
            except Exception as exc:
                model_info["registered"] = False
                model_info["reason"] = str(exc)
                logger.error("Failed to register '%s': %s", display_name, exc)
        else:
            model_info["registered"] = False
            model_info["reason"] = "mlflow_unavailable"
            logger.info(
                "[LOG-ONLY] Model '%s': md5=%s, size=%sMB, dvc=%s",
                display_name,
                parsed["md5"],
                model_info["size_mb"],
                dvc_filename,
            )

        results.append(model_info)

    # ── Register API-only models (Llama 4 Maverick) ───────────────────────────
    llama_info = {
        "model_name": "llama-4-maverick",
        "type": "api_endpoint",
        "provider": "vertex_ai",
        "vertex_legal_llm_model": settings.vertex_legal_llm_model,
        "vertex_project_id": settings.vertex_project_id,
        "vertex_location": settings.vertex_location,
        "description": "Llama 4 Maverick — legal review via Vertex AI API",
    }

    if mlflow is not None:
        try:
            with mlflow.start_run(run_name="register-llama-4-maverick"):
                mlflow.log_params(
                    {
                        "model_name": "llama-4-maverick",
                        "type": "api_endpoint",
                        "provider": "vertex_ai",
                        "vertex_legal_llm_model": settings.vertex_legal_llm_model,
                        "vertex_project_id": settings.vertex_project_id,
                        "vertex_location": settings.vertex_location,
                    }
                )
                mlflow.log_dict(llama_info, "model_info.json")

            llama_info["registered"] = True
            logger.info("Registered 'llama-4-maverick' in MLflow (Vertex AI endpoint).")
        except Exception as exc:
            llama_info["registered"] = False
            llama_info["reason"] = str(exc)
            logger.error("Failed to register llama-4-maverick: %s", exc)
    else:
        llama_info["registered"] = False
        llama_info["reason"] = "mlflow_unavailable"
        logger.info(
            "[LOG-ONLY] Model 'llama-4-maverick': Vertex AI endpoint at %s/%s",
            settings.vertex_project_id,
            settings.vertex_legal_llm_model,
        )

    results.append(llama_info)

    # ── Summary ───────────────────────────────────────────────────────────────
    registered = sum(1 for r in results if r.get("registered"))
    total = len(results)
    logger.info("Registration complete: %d/%d models registered in MLflow.", registered, total)

    return results


def main():
    """CLI entrypoint: `python -m courtaccess.core.register_models`"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    results = register_models()

    # Print summary table
    print("\n" + "=" * 72)  # noqa: T201
    print(f"  {'Model':<30} {'Size':>10} {'MD5':>12} {'Status':>10}")  # noqa: T201
    print("=" * 72)  # noqa: T201
    for r in results:
        name = r.get("model_name", "?")
        size = f"{r.get('size_mb', '-')} MB" if "size_mb" in r else "API"
        md5_raw = r.get("md5", "")
        md5 = md5_raw[:10] + "..." if md5_raw else "n/a"
        status = "✓" if r.get("registered") else "✗"
        print(f"  {name:<30} {size:>10} {md5:>12} {status:>10}")  # noqa: T201


if __name__ == "__main__":
    main()
