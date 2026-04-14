"""
Shared setup for courtaccess/monitoring/tests.

Sets env vars that anomaly.py reads at call time via os.getenv().
drift.py (bias detection) accepts explicit threshold params so it
needs no env vars for most tests, but we set them anyway as fallbacks.
"""

import os

_MONITORING_ENV = {
    # Anomaly detection thresholds
    "ANOMALY_FORM_DROP_PCT": "20.0",
    "ANOMALY_MASS_NEW_FORMS": "50",
    "ANOMALY_DOWNLOAD_FAIL_PCT": "10.0",
    "ANOMALY_MIN_PDF_SIZE_BYTES": "1024",
    "ANOMALY_MAX_PDF_SIZE_BYTES": "52428800",
    "ANOMALY_SCHEMA_ERRORS": "0",
    # Bias / drift thresholds
    "BIAS_UNDERSERVED_THRESHOLD": "0.5",
    "BIAS_TRANSLATION_COVERAGE_MIN": "20.0",
    "BIAS_LANGUAGE_GAP_MAX": "30.0",
}

for _key, _val in _MONITORING_ENV.items():
    os.environ.setdefault(_key, _val)
