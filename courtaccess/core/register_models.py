"""
courtaccess/core/register_models.py

Reads .dvc pointer files from models/ and registers each model version
in MLflow so the deployment registry stays up to date.

Run via:
    python3 -m courtaccess.core.register_models

STUB IMPLEMENTATION — logs what would be registered.
PRODUCTION UPGRADE: replace stub body with real mlflow.register_model() calls.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Models tracked by DVC (relative to project root)
DVC_MODEL_FILES = [
    "models/whisper-large-v3.dvc",
    "models/nllb-200-distilled-1.3b.dvc",
    "models/paddleocr-v3.dvc",
    "models/qwen2.5-vl.dvc",
    "models/silero-vad-v4.dvc",
    "models/piper-tts-es.dvc",
    "models/piper-tts-pt.dvc",
]


def register_models(project_root: str = ".") -> list[dict]:
    """
    Read each .dvc pointer file and register model metadata in MLflow.

    Returns:
        List of dicts: [{"model_name": str, "dvc_path": str, "registered": bool}]

    NOTE: STUB — logs registration intent.
    Replace stub body with mlflow.register_model() in production.
    """
    results = []
    root = Path(project_root)

    for dvc_file in DVC_MODEL_FILES:
        dvc_path = root / dvc_file
        model_name = Path(dvc_file).stem  # e.g. "whisper-large-v3"

        if not dvc_path.exists():
            logger.warning("[STUB] DVC file not found: %s — skipping.", dvc_path)
            results.append({"model_name": model_name, "dvc_path": str(dvc_path), "registered": False})
            continue

        logger.info("[STUB] Would register model '%s' from DVC file '%s' in MLflow.", model_name, dvc_path)
        results.append({"model_name": model_name, "dvc_path": str(dvc_path), "registered": True})

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    register_models()
