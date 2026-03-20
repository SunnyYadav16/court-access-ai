"""
courtaccess/core/config.py

Centralised settings — reads from .env via pydantic-settings.
All environment variables used anywhere in the project are defined here.

PRODUCTION UPGRADE:
  Set each variable in the GKE secret / Cloud Run env config.
  .env is for local development only. Never commit .env to git.
"""

import logging

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Application ───────────────────────────────────────────────────────────
    app_env: str = "development"  # development | staging | production
    debug: bool = True
    allowed_origins: str = "http://localhost:3000,http://localhost:8000"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://courtaccess:courtaccess@localhost:5432/courtaccess"

    # ── Google Cloud ──────────────────────────────────────────────────────────
    gcs_bucket_uploads: str = "courtaccess-ai-uploads"
    gcs_bucket_translated: str = "courtaccess-ai-translated"
    gcs_bucket_forms: str = "courtaccess-ai-forms"
    gcs_bucket_models: str = "courtaccess-ai-models"
    gcp_project_id: str = "courtaccess-ai"
    gcp_region: str = "us-east1"

    # ── API keys ──────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"
    secret_key: str = "change-me-in-production"  # noqa: S105

    # ── Vertex AI (Llama 4 — primary legal review provider) ──────────────────
    vertex_project_id: str = ""
    vertex_location: str = "us-east5"
    vertex_model_id: str = "meta/llama-4-maverick-17b-128e-instruct-maas"
    gcp_service_account_json: str = ""

    # ── Signed URLs ───────────────────────────────────────────────────────────
    signed_url_expiry_seconds: int = 3600

    # ── Airflow ───────────────────────────────────────────────────────────────
    airflow_base_url: str = "http://airflow-webserver:8080"
    airflow_username: str = "airflow"
    airflow_password: str = "airflow"  # noqa: S105

    # ── MLflow ────────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "http://mlflow:5000"

    # ── Redis (translation cache) ─────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Model toggles (set to true in prod to use real models) ───────────────
    use_real_translation: bool = False
    use_real_legal_review: bool = False
    use_vertex_legal_review: bool = False  # True = Vertex AI, False = Groq fallback
    use_real_ocr: bool = False

    # ── Model paths (inside container) ───────────────────────────────────────
    nllb_model_path: str = "/opt/models/nllb-200-distilled-1.3B-ct2"
    whisper_model_path: str = "/opt/models/whisper-large-v3"
    piper_tts_es_path: str = "/opt/models/piper-tts-es"
    piper_tts_pt_path: str = "/opt/models/piper-tts-pt"

    # ── Auth ──────────────────────────────────────────────────────────────────
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


def get_settings() -> Settings:
    """
    Return the global Settings singleton.

    This thin wrapper makes it easy to override in tests:
        app.dependency_overrides[get_settings] = lambda: test_settings

    In non-FastAPI code just import `settings` directly.
    """
    return settings
