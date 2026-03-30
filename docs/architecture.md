# CourtAccess AI — Architecture Documentation

> **Version:** 1.0.0 | **Last Updated:** 2024-01-01 | **Authors:** CourtAccess AI Engineering Team

## 1. System Overview

CourtAccess AI is an on-premise AI platform designed to provide real-time multilingual court interpretation and document translation for Limited English Proficiency (LEP) individuals in Massachusetts courthouses. The system is optimised for Spanish and Portuguese — the two largest LEP language groups in the MA court system — while being architecturally extensible to 200+ languages via NLLB-200.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CourtAccess AI Platform                         │
│                                                                         │
│   ┌─────────────┐    ┌──────────────────┐    ┌──────────────────────┐  │
│   │  React SPA  │ ── │  FastAPI Backend  │ ── │  PostgreSQL (async)  │  │
│   │  (Vite 7)   │    │  (api/main.py)   │    │  (SQLAlchemy 2.x)   │  │
│   └─────────────┘    └──────────────────┘    └──────────────────────┘  │
│          │                    │                                         │
│          │             ┌──────┴──────┐                                   │
│          │             │ ML Services  │                                   │
│          │             │  (on-prem)  │                                   │
│          │             └──────┬──────┘                                   │
│          │                    │                                         │
│   WebSocket            ┌──────┴──────────────────────────────────┐     │
│   (real-time)          │  Whisper ASR → NLLB-200 → Piper TTS    │     │
│                        │  spaCy PII  → LLaMA 4 legal review      │     │
│                        └──────────────────────────────────────────┘     │
│                                                                         │
│   ┌─────────────────────────────────┐  ┌──────────────────────────┐    │
│   │  Apache Airflow (DAG pipeline)  │  │  TFDV Drift Monitoring   │    │
│   │  - Document pipeline DAG        │  │  - Weekly baseline check │    │
│   │  - Form scraper DAG             │  │  - Bias alerts           │    │
│   └─────────────────────────────────┘  └──────────────────────────┘    │
│                                                                         │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  Google Cloud Storage (GCS) — model cache & translated PDFs   │   │
│   └────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Architecture

### 2.1 API Layer (`api/`)

| File | Responsibility |
|---|---|
| `api/main.py` | FastAPI app factory with lifespan for DB init/close, CORS, GZip, Request-ID middleware, and exception handlers |
| `api/auth.py` | JWT (HS256) token creation/validation, bcrypt password hashing |
| `api/dependencies.py` | `get_db`, `get_current_user`, `require_role` dependency injection |
| `api/routes/auth.py` | Register, login, token refresh, logout, profile endpoints |
| `api/routes/realtime.py` | REST session management + WebSocket endpoint for live interpretation |
| `api/routes/documents.py` | PDF upload, translation status polling, list, delete |
| `api/routes/forms.py` | Court form catalog search, form detail, human review submission |
| `api/schemas/schemas.py` | Pydantic v2 request/response models |

**Authentication flow:**
1. `POST /auth/login` → issues `access_token` (30 min) + `refresh_token` (7 days)
2. All protected routes require `Authorization: Bearer <access_token>`
3. `POST /auth/refresh` renews the access token silently (handled by Axios interceptor in frontend)
4. `POST /auth/logout` invalidates the refresh token server-side

**WebSocket protocol (`/sessions/{id}/ws`):**
- Client authenticates via `?token=<jwt>`
- Messages are JSON: `{ "type": "audio_chunk|ping|transcript|error", "payload": {...}, "timestamp_ms": int }`
- Server pushes `{ "type": "transcript", "payload": { "segment_id", "original_text", "translated_text", "is_interim", "speaker" } }`

---

### 2.2 Database Layer (`db/`)

**Database:** PostgreSQL 15 with `asyncpg` (async operations) and `psycopg2` (Alembic migrations)

| Table | Purpose |
|---|---|
| `users` | Account management, roles (`user`, `admin`, `court_official`, `interpreter`) |
| `sessions` | Real-time interpretation session metadata, JSONB `participants` |
| `translation_requests` | Document translation lifecycle (6-state FSM: pending → processing → translated → approved/rejected → error) |
| `audit_logs` | Immutable security event log — FK uses `ON DELETE SET NULL` for 7-year retention |
| `form_catalog` | DB mirror of Massachusetts court form scraper output, GIN index on `divisions[]` |

**Migration strategy:** Alembic with offline + online support. Only `SYNC_DATABASE_URL` (psycopg2) is used for migrations; async connections use asyncpg at runtime.

**Key design decisions:**
- UUID primary keys (`gen_random_uuid()`) to prevent enumeration attacks
- All timestamps in UTC with `timezone=True`
- JSONB for flexible semistructured data (session participants, translated URIs, legal review status)
- `ARRAY(String)` for multi-value enumerations (target_languages, divisions)
- GIN index on `form_catalog.divisions` for fast `@>` array containment queries

---

### 2.3 ML Pipeline (`courtaccess/`)

**Speech pipeline (real-time):**
```
Microphone → WebSocket audio_chunk → Whisper Large-v3 (ASR)
    → spaCy PII masking → NLLB-200 translation → Piper TTS synthesis
    → WebSocket transcript segment
```

**Document pipeline (async, Airflow DAG):**
```
PDF upload → text extraction (pdfplumber) → PII detection (spaCy)
    → chunking (512 token max) → NLLB-200 batch translation
    → LLaMA 4 Scout legal review → PDF reconstruction
    → GCS upload → DB status update → user notification
```

**Model registry:**

| Model | Purpose | Size | Tracking |
|---|---|---|---|
| `nllb-200-distilled-1.3B-ct2` | Translation (200 langs) | 612 MB | DVC |
| `whisper-large-v3` | ASR (en/es/pt) | 3.1 GB | DVC |
| `piper-tts-es` | Spanish TTS | 65 MB | DVC |
| `piper-tts-pt` | Portuguese TTS | 50 MB | DVC |
| `spacy-en-core-web-lg` | PII detection | 562 MB | DVC |
| `llama4-scout-legal-review` | Legal context QA | API | DVC (prompts only) |
| `tfdv-baseline-stats` | Drift monitoring | 280 KB | DVC |

---

### 2.4 Data Pipeline (`dags/`)

Apache Airflow DAG `document_pipeline_dag` with 11 tasks:

```
extract_text → detect_pii → mask_pii → chunk_text → translate_chunks
→ unmask_translation → legal_review → reconstruct_pdf → upload_to_gcs
→ update_db_status → notify_user
```

**DAG configuration:**
- Scheduler: daily at 00:00 UTC with 3 retries + exponential backoff
- Parallelism: 4 workers (machine-dependent)
- GCS bucket: `AIRFLOW_GCS_BUCKET` env var
- Failure alerting: email via `SMTP_CONN_ID`

---

### 2.5 Form Scraper (`courtaccess/forms/`)

Weekly scraper for the Massachusetts court system form catalog (`mass.gov/courts/forms`):
- Fetches form index HTML, extracts form links + metadata via BeautifulSoup
- Detects Spanish/Portuguese availability from URL patterns and PDF metadata
- Hashes form content to detect version changes
- Writes to PostgreSQL `form_catalog` table via Alembic-managed schema
- Triggers TFDV drift comparison after every successful run

---

### 2.6 Monitoring (`courtaccess/monitoring/`)

**Drift detection (`drift.py`):**
- Runs weekly via Airflow after each form scraper execution
- Compares current form catalog statistics against TFDV baseline
- Alerts on Jensen-Shannon divergence > 0.1 or z-score > 3.0 for numeric features
- Logs anomalies to `audit_logs` table with `action="drift_alert"`

**Bias detection:**
- Analyses translation quality and legal review scores sliced by `division` and `target_language`
- Flags if any slice shows `translation_confidence` > 0.1 below the overall mean
- Report output: `docs/bias_detection_report.md` (regenerated after each pipeline run)

---

## 3. Security Architecture

| Layer | Control |
|---|---|
| Authentication | JWT HS256 (30 min access + 7 day refresh) |
| Authorisation | Role-based (`user`, `interpreter`, `court_official`, `admin`) on every protected route |
| Password storage | bcrypt (12 rounds) |
| PII handling | spaCy NER masking before any external API call |
| Audit logging | Immutable `audit_logs` table, 7-year retention policy |
| Transport | HTTPS (TLS 1.3) + WSS for WebSocket |
| Secrets management | Environment variables via `.env` / Docker secrets — never hardcoded |
| Database | Parameterised queries via SQLAlchemy ORM (no raw SQL string formatting) |

---

## 4. Deployment Architecture

```
┌─────────────────────────────────────────┐
│  courthouse-server (on-premise Linux)   │
│                                         │
│  Docker Compose services:               │
│  ├── nginx (TLS termination + SPA)      │
│  ├── api (uvicorn, 4 workers)           │
│  ├── postgres (TimescaleDB extension)   │
│  ├── airflow-scheduler                  │
│  ├── airflow-worker (Celery)            │
│  ├── redis (Celery broker)              │
│  └── mlflow (model experiment tracking) │
│                                         │
│  Volumes:                               │
│  ├── /opt/models/    (7 ML models)      │
│  ├── /opt/airflow/   (DAG files)        │
│  └── /var/pgdata/    (PostgreSQL)       │
└─────────────────────────────────────────┘
         │  GCS egress (translated PDFs)
         ▼
┌───────────────────────────┐
│  Google Cloud Storage     │
│  gs://courtaccess-prod/   │
│  - translated_docs/       │
│  - model_cache/           │
└───────────────────────────┘
```

**Environment variables (see `.env.example`):**
- `DATABASE_URL` — asyncpg connection string
- `SECRET_KEY` — JWT signing key (≥32 random bytes)
- `GCP_PROJECT_ID`, `GCS_BUCKET_NAME` — Cloud Storage
- `AIRFLOW_CONN_*` — Airflow connection strings

---

## 5. Configuration & Environment

All settings are centralised in `courtaccess/core/config.py` as a Pydantic `BaseSettings` class loaded from `.env`. Settings are immutable at runtime and cached via `@lru_cache` (`get_settings()`).

---

## 6. Testing Strategy

| Layer | Tool | Location |
|---|---|---|
| DB models (unit) | pytest | `db/tests/test_models.py` (45 tests) |
| API auth logic (unit) | pytest | `api/tests/test_auth.py` (35 tests) |
| API routes (integration) | pytest + TestClient | `api/tests/test_routes.py` (59 tests) |
| Core modules | pytest | `courtaccess/**/test_*.py` |
| E2E (future) | Playwright | `frontend/tests/` (planned) |

Run all tests:
```bash
cd /Users/sunnyyadav/PycharmProjects/court-access-ai
python3 -m pytest courtaccess/ api/ db/ -v --tb=short
```
