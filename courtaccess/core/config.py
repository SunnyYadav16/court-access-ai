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
    gcs_bucket_transcripts: str

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

    # ── Groq (Llama fallback — used if Vertex AI is unavailable) ─────────────
    groq_api_key: str 
    groq_legal_llm_model: str 

    # ── Signed URLs ───────────────────────────────────────────────────────────
    signed_url_expiry_seconds: int

    # ── Airflow ───────────────────────────────────────────────────────────────
    airflow_base_url: str | None
    airflow_username: str | None
    airflow_password: str | None

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
    nllb_model_path: str | None
    whisper_model_path: str | None
    piper_tts_es_path: str | None
    piper_tts_pt_path: str | None
    silero_vad_model_path: str | None = None

    # ── Real-Time Speech Pipeline ────────────────────────────────────────────
    # All fields below are only read when use_real_speech=True; they default to
    # None so Settings() can instantiate without them when the speech pipeline
    # is disabled (USE_REAL_SPEECH=false).
    use_real_speech: bool
    whisper_model: str | None = None
    nllb_model: str | None = None
    vad_speech_threshold: float | None = None
    piper_voices_dir: str | None = None
    piper_tts_en_path: str | None = None
    session_recordings_dir: str | None = None
    turn_grace_a_ms: float | None = None
    turn_grace_b_ms: float | None = None
    tts_lockout_buffer_ms: float | None = None

    # ── Auth token ────────────────────────────────────────────────────────────
    access_token_expire_minutes: int
    algorithm: str
    room_jwt_secret: str
    room_jwt_expiry_hours: int
    room_code_expiry_minutes: int

    # ── Monitoring & Bias Thresholds ─────────────────────────────────────────
    bias_underserved_threshold: float
    bias_translation_coverage_min: float
    bias_language_gap_max: float

    # ── Model & Extraction Overrides ──────────────────────────────────────────
    ocr_confidence_threshold: float
    vertex_max_retries: int
    translation_hallucination_ratio_max: float
    translation_hallucination_ratio_min: float

    # ── Anomaly Detection Thresholds ────────────────────────────────────────
    anomaly_form_drop_pct: float
    anomaly_mass_new_forms: int
    anomaly_download_fail_pct: float
    anomaly_min_pdf_size_bytes: int
    anomaly_max_pdf_size_bytes: int
    anomaly_schema_errors: int

    # ── Scraper Tuning ────────────────────────────────────────────────────────
    scraper_batch_size: int
    scraper_batch_sleep_sec: int
    scraper_pre_download_sleep: int
    scraper_request_timeout: int

    # ── Processor Tuning ──────────────────────────────────────────────────────
    pdf_render_dpi: int
    validation_confidence_threshold: float


settings = Settings()


def get_settings() -> Settings:
    """
    Return the global Settings singleton.

    Easy to override in tests:
        app.dependency_overrides[get_settings] = lambda: test_settings

    In non-FastAPI code just import `settings` directly.
    """
    return settings
