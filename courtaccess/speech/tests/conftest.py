"""
Shared test setup for courtaccess/speech/tests.

Sets all required env vars at module-import time (before pydantic-settings
calls Settings()) and stubs out heavy optional dependencies (piper) that
are not installed in the test environment.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock

# ── 1. Stub piper before any speech module imports it at module level ─────────
# tts.py does `from piper import PiperVoice` at module level.
# piper is not installed in the test venv, so we stub it here.
_piper_stub = MagicMock()
_piper_config_stub = MagicMock()
sys.modules.setdefault("piper", _piper_stub)
sys.modules.setdefault("piper.config", _piper_config_stub)

# ── 2. Set every required env var before courtaccess.core.config is imported ──
# pydantic-settings reads these at Settings() instantiation time.
# All values are test-safe dummies — no real credentials needed.
_TEST_ENV = {
    # Application
    "APP_ENV": "test",
    "DEBUG": "false",
    "SECRET_KEY": "test-secret-key-32-chars-xxxxxxxxxx",
    "ALLOWED_ORIGINS": "http://localhost:3000",
    "SIGNED_URL_EXPIRY_SECONDS": "3600",
    # Database
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "test",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    # GCP
    "GCP_PROJECT_ID": "test-project",
    "GCP_REGION": "us-east1",
    "GCS_BUCKET_UPLOADS": "test-uploads",
    "GCS_BUCKET_TRANSLATED": "test-translated",
    "GCS_BUCKET_FORMS": "test-forms",
    "GCS_BUCKET_MODELS": "test-models",
    "GCS_BUCKET_TRANSCRIPTS": "test-transcripts",
    # Auth
    "GCIP_API_KEY": "test-api-key",
    "GCIP_AUTH_DOMAIN": "test.firebaseapp.com",
    "GCIP_PROJECT_ID": "test-project",
    # Vertex AI
    "VERTEX_PROJECT_ID": "test-project",
    "VERTEX_LOCATION": "us-east5",
    "VERTEX_LEGAL_LLM_MODEL": "test-model",
    "LEGAL_VERIFY_TIMEOUT": "5.0",
    "GCP_SERVICE_ACCOUNT_JSON": "",
    # Airflow
    "AIRFLOW_BASE_URL": "http://localhost:8080",
    "AIRFLOW_USERNAME": "airflow",
    "AIRFLOW_PASSWORD": "airflow",
    # Redis
    "REDIS_URL": "redis://localhost:6379",
    # Feature flags
    "USE_REAL_CLASSIFICATION": "false",
    "USE_REAL_TRANSLATION": "false",
    "USE_VERTEX_LEGAL_REVIEW": "false",
    "USE_REAL_OCR": "false",
    "USE_REAL_SPEECH": "false",
    # Model paths (str | None required fields)
    "NLLB_MODEL_PATH": "",
    "WHISPER_MODEL_PATH": "",
    "PIPER_TTS_ES_PATH": "",
    "PIPER_TTS_PT_PATH": "",
    # Speech pipeline
    "WHISPER_MODEL": "small",
    "NLLB_MODEL": "facebook/nllb-200-distilled-1.3B",
    "VAD_SPEECH_THRESHOLD": "0.5",
    "TURN_GRACE_A_MS": "2000",
    "TURN_GRACE_B_MS": "1000",
    "TTS_LOCKOUT_BUFFER_MS": "200",
    "SESSION_RECORDINGS_DIR": str(tempfile.gettempdir()),
    "PIPER_TTS_EN_PATH": "",
    "SILERO_VAD_MODEL_PATH": "",
    # JWT
    "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
    "ALGORITHM": "HS256",
    "ROOM_JWT_SECRET": "test-room-jwt-secret-32-chars-xxx",
    "ROOM_JWT_EXPIRY_HOURS": "4",
    "ROOM_CODE_EXPIRY_MINUTES": "60",
    # Monitoring thresholds
    "BIAS_UNDERSERVED_THRESHOLD": "0.5",
    "BIAS_TRANSLATION_COVERAGE_MIN": "20.0",
    "BIAS_LANGUAGE_GAP_MAX": "30.0",
    # Model overrides
    "OCR_CONFIDENCE_THRESHOLD": "0.35",
    "VERTEX_MAX_RETRIES": "3",
    "TRANSLATION_HALLUCINATION_RATIO_MAX": "2.5",
    "TRANSLATION_HALLUCINATION_RATIO_MIN": "0.1",
    # Anomaly thresholds
    "ANOMALY_FORM_DROP_PCT": "20.0",
    "ANOMALY_MASS_NEW_FORMS": "50",
    "ANOMALY_DOWNLOAD_FAIL_PCT": "10.0",
    "ANOMALY_MIN_PDF_SIZE_BYTES": "1024",
    "ANOMALY_MAX_PDF_SIZE_BYTES": "52428800",
    "ANOMALY_SCHEMA_ERRORS": "0",
    # Scraper tuning
    "SCRAPER_BATCH_SIZE": "10",
    "SCRAPER_BATCH_SLEEP_SEC": "5",
    "SCRAPER_PRE_DOWNLOAD_SLEEP": "2",
    "SCRAPER_REQUEST_TIMEOUT": "30",
    # Processor tuning
    "PDF_RENDER_DPI": "300",
    "VALIDATION_CONFIDENCE_THRESHOLD": "0.85",
}

for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

