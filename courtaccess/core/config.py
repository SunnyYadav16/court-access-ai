"""
courtaccess/core/config.py

Centralised settings — reads from .env via pydantic-settings.
All environment variables used anywhere in the project are defined here.

PRODUCTION UPGRADE:
  Set each variable in the Cloud Run env config (or GCP Secret Manager).
  .env is for local development only. Never commit .env to git.
"""

import logging

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_env: str  # development | staging | production
    debug: bool
    secret_key: str
    allowed_origins: str

    # ── Database ──────────────────────────────────────────────────────────────
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str
    postgres_port: int

    @computed_field  # type: ignore[misc]
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Google Cloud ──────────────────────────────────────────────────────────
    gcp_project_id: str
    gcp_region: str
    gcs_bucket_uploads: str
    gcs_bucket_translated: str
    gcs_bucket_forms: str
    gcs_bucket_models: str

    # ── Auth (GCIP / Firebase) ────────────────────────────────────────────────
    gcip_api_key: str
    gcip_auth_domain: str
    gcip_project_id: str

    # ── Vertex AI (Llama 4 — primary legal review provider) ──────────────────
    vertex_project: str
    vertex_location: str
    legal_llm_model: str
    legal_verify_timeout: float
    gcp_service_account_json: str = ""  # optional: inline SA JSON

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

    # ── Model toggles (feature flags — safe to leave False locally) ───────────
    use_real_classification: bool = False
    use_real_translation: bool = False
    use_real_legal_review: bool = False
    use_vertex_legal_review: bool = False
    use_real_ocr: bool = False

    # ── Model paths (inside container) ───────────────────────────────────────
    nllb_model_path: str = "/opt/models/nllb-200-distilled-1.3B-ct2"
    whisper_model_path: str = "/opt/models/whisper-large-v3"
    piper_tts_es_path: str = "/opt/models/piper-tts-es"
    piper_tts_pt_path: str = "/opt/models/piper-tts-pt"

    # ── Auth token ────────────────────────────────────────────────────────────
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"


settings = Settings()


def get_settings() -> Settings:
    """
    Return the global Settings singleton.

    Easy to override in tests:
        app.dependency_overrides[get_settings] = lambda: test_settings

    In non-FastAPI code just import `settings` directly.
    """
    return settings
