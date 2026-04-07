"""
Unit tests for courtaccess/core/config.py

Classes/functions under test:
  Settings         — pydantic-settings model; field types and computed fields
  get_settings()   — returns the module-level singleton

Design notes:
  - Five env vars added to Settings after the .env was last updated are missing
    from .env. They are supplied via os.environ.setdefault() here — at module
    level, before config.py is imported — so the module-level `settings =
    Settings()` succeeds at import time.
  - Individual tests construct Settings(**_BASE) directly, passing all required
    fields as kwargs. This isolates them from the live .env content and lets us
    vary specific fields without side effects.
  - get_settings() is tested against the live singleton; its only contract is
    that it returns the same object as the module-level `settings`.
"""

import os

# Supply defaults for the five fields missing from the project's .env.
# Must be set before courtaccess.core.config is imported (module-level
# `settings = Settings()` runs at import time and reads env vars).
_MISSING = {
    "GCS_BUCKET_TRANSCRIPTS": "test-transcripts",
    "USE_REAL_SPEECH": "false",
    "ROOM_JWT_SECRET": "test-jwt-secret",
    "ROOM_JWT_EXPIRY_HOURS": "24",
    "ROOM_CODE_EXPIRY_MINUTES": "10",
}
for _k, _v in _MISSING.items():
    os.environ.setdefault(_k, _v)


from courtaccess.core.config import Settings, get_settings, settings  # noqa: E402

# ── Minimal kwargs for constructing an isolated Settings instance ─────────────

_BASE: dict = {
    "app_env": "development",
    "debug": False,
    "secret_key": "test-secret",
    "allowed_origins": "http://localhost:3000",
    "postgres_user": "testuser",
    "postgres_password": "testpass",
    "postgres_db": "testdb",
    "postgres_host": "localhost",
    "postgres_port": 5432,
    "gcp_project_id": "test-project",
    "gcp_region": "us-central1",
    "gcs_bucket_uploads": "test-uploads",
    "gcs_bucket_translated": "test-translated",
    "gcs_bucket_forms": "test-forms",
    "gcs_bucket_models": "test-models",
    "gcs_bucket_transcripts": "test-transcripts",
    "gcip_api_key": "test-api-key",
    "gcip_auth_domain": "test.firebaseapp.com",
    "gcip_project_id": "test-project",
    "vertex_project_id": "test-vertex-project",
    "vertex_location": "us-central1",
    "vertex_legal_llm_model": "meta/llama-4-scout",
    "legal_verify_timeout": 30.0,
    "gcp_service_account_json": '{"type": "service_account"}',
    "signed_url_expiry_seconds": 3600,
    "airflow_base_url": None,
    "airflow_username": None,
    "airflow_password": None,
    "redis_url": "redis://localhost:6379",
    "use_real_classification": False,
    "use_real_translation": False,
    "use_vertex_legal_review": False,
    "use_real_ocr": False,
    "nllb_model_path": None,
    "whisper_model_path": None,
    "piper_tts_es_path": None,
    "piper_tts_pt_path": None,
    "use_real_speech": False,
    "access_token_expire_minutes": 60,
    "algorithm": "HS256",
    "room_jwt_secret": "test-room-secret",
    "room_jwt_expiry_hours": 24,
    "room_code_expiry_minutes": 10,
    "bias_underserved_threshold": 0.5,
    "bias_translation_coverage_min": 0.8,
    "bias_language_gap_max": 0.2,
    "ocr_confidence_threshold": 0.7,
    "vertex_max_retries": 3,
    "translation_hallucination_ratio_max": 0.5,
    "translation_hallucination_ratio_min": 0.1,
    "anomaly_form_drop_pct": 0.2,
    "anomaly_mass_new_forms": 100,
    "anomaly_download_fail_pct": 0.1,
    "anomaly_min_pdf_size_bytes": 1024,
    "anomaly_max_pdf_size_bytes": 10_485_760,
    "anomaly_schema_errors": 5,
    "scraper_batch_size": 10,
    "scraper_batch_sleep_sec": 1,
    "scraper_pre_download_sleep": 0,
    "scraper_request_timeout": 30,
    "pdf_render_dpi": 300,
    "validation_confidence_threshold": 0.7,
}


# ─────────────────────────────────────────────────────────────────────────────
# Settings — database_url computed field
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabaseUrl:

    def test_url_uses_asyncpg_driver(self):
        s = Settings(**_BASE)
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_url_contains_user_and_password(self):
        s = Settings(**{**_BASE, "postgres_user": "myuser", "postgres_password": "mypass"})
        assert "myuser:mypass@" in s.database_url

    def test_url_contains_host_and_port(self):
        s = Settings(**{**_BASE, "postgres_host": "db.example.com", "postgres_port": 5433})
        assert "db.example.com:5433" in s.database_url

    def test_url_contains_database_name(self):
        s = Settings(**{**_BASE, "postgres_db": "courtdb"})
        assert s.database_url.endswith("/courtdb")

    def test_url_full_format(self):
        s = Settings(**{
            **_BASE,
            "postgres_user": "user",
            "postgres_password": "pass",
            "postgres_host": "host",
            "postgres_port": 5432,
            "postgres_db": "db",
        })
        assert s.database_url == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_url_changes_when_host_changes(self):
        a = Settings(**{**_BASE, "postgres_host": "host-a"})
        b = Settings(**{**_BASE, "postgres_host": "host-b"})
        assert a.database_url != b.database_url


# ─────────────────────────────────────────────────────────────────────────────
# Settings — field types
# ─────────────────────────────────────────────────────────────────────────────

class TestSettingsFieldTypes:

    def test_debug_is_bool(self):
        s = Settings(**_BASE)
        assert isinstance(s.debug, bool)

    def test_postgres_port_is_int(self):
        s = Settings(**_BASE)
        assert isinstance(s.postgres_port, int)

    def test_use_real_flags_are_bool(self):
        s = Settings(**_BASE)
        assert isinstance(s.use_real_classification, bool)
        assert isinstance(s.use_real_translation, bool)
        assert isinstance(s.use_vertex_legal_review, bool)
        assert isinstance(s.use_real_ocr, bool)

    def test_numeric_thresholds_are_float(self):
        s = Settings(**_BASE)
        assert isinstance(s.bias_underserved_threshold, float)
        assert isinstance(s.ocr_confidence_threshold, float)
        assert isinstance(s.legal_verify_timeout, float)

    def test_optional_fields_accept_none(self):
        s = Settings(**{
            **_BASE,
            "airflow_base_url": None,
            "nllb_model_path": None,
            "whisper_model_path": None,
        })
        assert s.airflow_base_url is None
        assert s.nllb_model_path is None
        assert s.whisper_model_path is None

    def test_optional_mlflow_uri_accepts_none(self):
        # mlflow_tracking_uri has a source-level default of None — it must
        # accept None explicitly even when .env has a different value
        s = Settings(**{**_BASE, "mlflow_tracking_uri": None})
        assert s.mlflow_tracking_uri is None


# ─────────────────────────────────────────────────────────────────────────────
# get_settings — singleton contract
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSettings:

    def test_returns_settings_instance(self):
        result = get_settings()
        assert isinstance(result, Settings)

    def test_returns_module_level_singleton(self):
        # get_settings() must return the same object as the module-level
        # `settings` — it is an accessor, not a factory
        assert get_settings() is settings

    def test_calling_twice_returns_same_object(self):
        a = get_settings()
        b = get_settings()
        assert a is b
