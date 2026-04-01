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
    app_env: str  # development | production
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
    vertex_project_id: str
    vertex_location: str
    vertex_legal_llm_model: str
    legal_verify_timeout: float
    gcp_service_account_json: str

    # ── Signed URLs ───────────────────────────────────────────────────────────
    signed_url_expiry_seconds: int

    # ── Airflow ───────────────────────────────────────────────────────────────
    airflow_base_url: str | None = None
    airflow_username: str | None = None
    airflow_password: str | None = None

    # ── MLflow ────────────────────────────────────────────────────────────────
    mlflow_tracking_uri: str | None = None

    # ── Redis (translation cache) ─────────────────────────────────────────────
    redis_url: str

    # ── Model toggles (feature flags — safe to leave False locally) ───────────
    use_real_classification: bool
    use_real_translation: bool
    use_vertex_legal_review: bool
    use_real_ocr: bool

    # ── Model paths (inside container) ───────────────────────────────────────
    nllb_model_path: str | None = None
    whisper_model_path: str | None = None
    piper_tts_es_path: str | None = None
    piper_tts_pt_path: str | None = None

    # ── Auth token ────────────────────────────────────────────────────────────
    access_token_expire_minutes: int
    algorithm: str

    # ── Monitoring & Bias Thresholds ─────────────────────────────────────────
    bias_underserved_threshold: float = 0.5
    bias_translation_coverage_min: float = 20.0
    bias_language_gap_max: float = 30.0

    # ── Model & Extraction Overrides ──────────────────────────────────────────
    ocr_confidence_threshold: float = 0.35
    vertex_max_retries: int = 3
    translation_hallucination_ratio_max: float = 2.5
    translation_hallucination_ratio_min: float = 0.1

    # ── Anomaly Detection Thresholds ────────────────────────────────────────
    anomaly_form_drop_pct: float = 20.0
    anomaly_mass_new_forms: int = 50
    anomaly_download_fail_pct: float = 10.0
    anomaly_min_pdf_size_bytes: int = 1024
    anomaly_max_pdf_size_bytes: int = 50 * 1024 * 1024
    anomaly_schema_errors: int = 0

    # ── Scraper Tuning ────────────────────────────────────────────────────────
    scraper_batch_size: int = 10
    scraper_batch_sleep_sec: int = 15
    scraper_pre_download_sleep: int = 60
    scraper_request_timeout: int = 30

    # ── Processor Tuning ──────────────────────────────────────────────────────
    pdf_render_dpi: int = 300
    validation_confidence_threshold: float = 0.85


settings = Settings()


def get_settings() -> Settings:
    """
    Return the global Settings singleton.

    Easy to override in tests:
        app.dependency_overrides[get_settings] = lambda: test_settings

    In non-FastAPI code just import `settings` directly.
    """
    return settings
