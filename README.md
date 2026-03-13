# CourtAccess AI

**Real-time speech and document translation system for the Massachusetts Trial Court**

CourtAccess AI is an MLOps-driven platform that provides real-time courtroom interpretation and legal document translation for non-English speakers, primarily Spanish and Portuguese, within the Massachusetts Trial Court system. The system uses pre-trained AI models orchestrated through automated pipelines, with continuous monitoring, drift detection, and version control.

---

## The Problem

Massachusetts courts face a systemic language access crisis. Approximately 45% of scheduled interpreters fail to appear for hearings, causing delays that effectively deny justice to Limited English Proficient (LEP) individuals. The shortage is most acute for non-Spanish languages, and the cost of agency interpreters runs 3x higher than staff interpreters. Court forms, signage, and processes remain largely English-only, creating barriers at every step of the legal process.

## What CourtAccess AI Does

The system provides two core capabilities:

**Real-Time Speech Translation.** Court officials initiate a live session. The system captures audio from the browser microphone, transcribes speech to text, translates between English and the target language, validates legal terminology, and plays back the translated audio — all in near real-time via a continuous WebSocket stream.

**Document Translation.** Users upload legal PDFs or browse a library of pre-translated Massachusetts court forms. Uploaded documents go through OCR, PII detection, translation, legal term validation, and PDF reconstruction that preserves the original layout. Pre-translated government forms are scraped weekly from mass.gov, translated, and stored for instant access.

---

## Architecture Overview

### User-Facing Paths

```
Home Screen
├── Real-Time Translation (court officials only)
│   Browser mic → VAD → ASR → Translation → Legal Review → TTS → Speaker
│
└── Document Translation (all authenticated users)
    ├── Upload Document
    │   PDF upload → Validate → Classify → OCR → PII Scrub → Translate
    │   → Legal Review → Reconstruct PDF → Signed URL Download
    │
    └── Government Forms
        Browse pre-translated form library → Select language → Download
```

### Pipeline Architecture

| Pipeline | Type | Trigger |
|----------|------|---------|
| Real-time speech translation | WebSocket stream (FastAPI) | Court official starts session |
| `document_pipeline_dag` | Airflow DAG | User uploads a PDF |
| `form_scraper_dag` | Airflow DAG (scheduled) | Weekly, every Monday at 06:00 UTC |
| `form_pretranslation_dag` | Airflow DAG | Triggered by scraper when new/updated forms detected |

### Authentication and Access Control

| Role | Access |
|------|--------|
| `public` | Document translation (upload + government forms) |
| `court_official` | Everything: real-time translation, document translation |
| `interpreter` | Real-time sessions, translation review interface |
| `admin` | Everything + monitoring dashboards, user management |

---

## AI Models

All models are pre-trained with no fine-tuning. The MLOps pipeline manages versioning, serving, monitoring, and updates.

| Model | Role | Details |
|-------|------|---------|
| **Faster-Whisper Large V3** | Speech-to-text (ASR) | CTranslate2 INT8 quantization, ~60x realtime |
| **NLLB-200 Distilled 1.3B** | Translation (English ↔ Spanish/Portuguese) | Meta's No Language Left Behind model |
| **Llama 4 Scout** | Legal term validation + document classification | Via Groq API. Async for real-time, sync for documents |
| **PaddleOCR v3** | Printed text extraction from PDFs | DBNet detection + SVTR recognition, >95% accuracy |
| **Qwen2.5-VL** | Handwritten text extraction | Vision-language model, ~90% accuracy on handwriting |
| **Silero VAD v4** | Voice activity detection | Filters silence before ASR to prevent hallucinations |
| **Piper TTS** | Text-to-speech | Generates spoken audio in Spanish/Portuguese |
| **Microsoft Presidio** | PII detection | Custom recognizers for MA docket patterns, SSN, etc. |

Model weights are tracked via DVC and stored in GCS (`gs://courtaccess-models/`). Each model has a `.dvc` pointer file committed to Git. To pull model weights:

```bash
dvc pull
```

---

## Project Structure

```
court-access-ai/
├── api/                          # FastAPI application
│   ├── main.py                   # App factory, lifespan, health check
│   ├── auth.py                   # JWT token creation/verification
│   ├── dependencies.py           # Shared FastAPI dependencies (CurrentUser, DBSession)
│   ├── routes/
│   │   ├── auth.py               # /auth/register, /login, /me, /refresh, /logout
│   │   ├── documents.py          # /documents/upload, GET, DELETE
│   │   ├── forms.py              # /forms/ — government form catalog
│   │   └── realtime.py           # /ws/session — WebSocket real-time stream
│   ├── schemas/schemas.py        # Pydantic request/response models
│   └── tests/                    # API integration tests (FastAPI TestClient)
│
├── courtaccess/                  # Core Python package
│   ├── core/
│   │   ├── config.py             # Pydantic settings (env-driven)
│   │   ├── logger.py             # Structured logging
│   │   ├── translation.py        # NLLB-200 translation (stub → real)
│   │   ├── legal_review.py       # Llama legal term validation (stub → Groq)
│   │   ├── ocr_printed.py        # PaddleOCR v3 (stub → real)
│   │   ├── ocr_handwritten.py    # Qwen2.5-VL (stub → real)
│   │   ├── reconstruct_pdf.py    # PyMuPDF layout reconstruction
│   │   ├── pii_scrub.py          # Microsoft Presidio
│   │   ├── classify_document.py  # Llama document classifier
│   │   ├── ingest_document.py    # PyMuPDF page splitter
│   │   ├── validation.py         # Form preprocessing + catalog validation
│   │   └── tests/
│   ├── forms/
│   │   ├── scraper.py            # mass.gov scraper (Playwright)
│   │   ├── catalog.py            # Form catalog management
│   │   └── tests/
│   ├── speech/
│   │   ├── vad.py                # Silero VAD (silence filtering)
│   │   ├── transcribe.py         # Faster-Whisper ASR
│   │   ├── tts.py                # Piper TTS
│   │   ├── session.py            # WebSocket session management
│   │   └── tests/
│   └── monitoring/
│       ├── drift.py              # TFDV drift detection + bias analysis
│       ├── anomaly.py            # Anomaly detection (form count, schema, PDF size)
│       └── tests/
│
├── dags/                         # Airflow DAGs
│   ├── form_scraper_dag.py       # Weekly scrape → preprocess → validate → version
│   ├── form_pretranslation_dag.py # OCR → translate → legal review → reconstruct
│   └── document_pipeline_dag.py  # User document translation pipeline
│
├── db/                           # Database layer
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── database.py               # Async engine + session factory
│   └── migrations/               # Alembic migrations
│       └── versions/001_initial_schema.py
│
├── frontend/                     # React + Vite frontend
│   └── src/
│       ├── pages/                # LandingPage, SessionPage, DocumentsPage, FormsPage, ...
│       ├── components/           # Navbar, shared components
│       ├── hooks/                # useAuth, useWebSocket
│       ├── services/api.js       # Axios API client
│       └── store/authStore.js    # Zustand auth state
│
├── models/                       # DVC pointer files (weights stored in GCS)
│   ├── whisper-large-v3.dvc
│   ├── nllb-200-distilled-1.3B-ct2.dvc
│   ├── piper-tts-es.dvc
│   ├── piper-tts-pt.dvc
│   ├── spacy-en-core-web-lg.dvc
│   ├── tfdv-baseline-stats.dvc
│   └── llama4-scout-legal-review.dvc
│
├── data/
│   ├── glossaries/               # Legal term glossaries (ES, PT)
│   └── schemas/                  # TFDV schema definitions
│
├── docs/
│   ├── architecture.md
│   ├── bias_detection_report.md
│   └── contributing/git-push-workflow.md
│
├── .github/workflows/
│   ├── test.yml                  # PR → pytest (204 tests)
│   ├── lint.yml                  # Ruff + Bandit + Gitleaks
│   ├── dependencies.yml          # Trivy filesystem vulnerability scan
│   └── build.yml                 # Docker build + push to GCP Artifact Registry
│
├── Dockerfile                    # Multi-stage: api + airflow targets
├── gpu.Dockerfile                # GPU inference target (CUDA 12, PyTorch)
├── docker-compose.yml            # Local dev: Airflow + API + Postgres + MLflow
├── dvc.yaml                      # DVC pipeline stages
├── pyproject.toml                # Package definition + all dependencies
├── requirements.txt              # Flat mirror of pyproject.toml (CI/local convenience)
├── requirements-dev.txt          # Dev tooling: ruff, bandit, pytest, pre-commit
├── ruff.toml                     # Ruff lint + format config
├── .pre-commit-config.yaml       # Pre-commit hooks
├── .gitleaks.toml                # Secret detection config
└── .env.example                  # Environment variable template
```

---

## Local Setup

### Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/) — fast Python package manager
- Docker + Docker Compose
- DVC (`pip install dvc`)

### 1. Clone and set up the environment

```bash
git clone https://github.com/SunnyYadav16/court-access-ai.git
cd court-access-ai

# Create venv and install all dependencies
uv venv
uv pip install -e .
uv pip install -r requirements-dev.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in all required values (see .env.example for instructions)
```

### 3. Pull model weights from DVC remote

```bash
dvc pull   # Downloads model weights from gs://courtaccess-models/
```

### 4. Start local services

```bash
docker compose up -d
```

This starts:
- **Airflow** (webserver, scheduler, dag-processor, triggerer) → http://localhost:8080
- **FastAPI** → http://localhost:8000
- **PostgreSQL** → port 5432
- **MLflow** (if configured) → http://localhost:5000

### 5. Run tests

```bash
pytest   # runs all 204 tests across api/, courtaccess/, db/
```

---

## CI/CD

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `test.yml` | Every push / PR | `pytest` (204 tests), blocks merge on failure |
| `lint.yml` | Every push / PR | `ruff check`, `ruff format --check`, `bandit`, `gitleaks` |
| `dependencies.yml` | Every push / PR | Trivy filesystem scan → SARIF uploaded to GitHub Security |
| `build.yml` | Merge to `main` | Docker build + push to GCP Artifact Registry |

---

## Data Pipeline

### Pipeline Tasks

#### `form_scraper_dag` — 8 Stages (Scheduled: Monday 06:00 UTC)

Scrapes 11 mass.gov court department pages, downloads PDFs (including existing Spanish/Portuguese translations from mass.gov), and runs preprocessing, validation, anomaly and bias detection.

| # | Task | What It Does |
|---|------|-------------|
| 1 | `scrape_and_classify` | Scrapes mass.gov with Playwright, downloads PDFs, classifies each form into one of 5 scenarios (new/updated/deleted/renamed/no-change), updates `form_catalog.json` |
| 2 | `preprocess_data` | Normalizes names/slugs, detects mislabeled files (HTML/DOCX saved as .pdf), checks PDF integrity, flags empty/tiny files and duplicates |
| 3 | `validate_catalog` | Validates JSON schema, checks for duplicate `form_id`/`source_url`, verifies PDFs exist on disk, generates `catalog_metrics.json` |
| 4 | `detect_anomalies` | Compares against previous run metrics, checks thresholds (form count drop, download failures, schema violations), generates `anomaly_report.json` |
| 5 | `detect_bias` | Slices data by division/language/section, flags underserved divisions and low translation coverage, generates `bias_report.json` |
| 6 | `trigger_pretranslation` | Triggers `form_pretranslation_dag` for any new or updated forms (Scenarios A & B) |
| 7 | `log_summary` | Prints consolidated report (scrape + preprocess + validation + anomaly + bias) to Airflow logs |
| 8 | `dvc_version_data` | Runs `dvc add` + `dvc push` to version the catalog and `forms/` directory |

**5-Scenario Classification:**

| Scenario | Detection | Action |
|----------|-----------|--------|
| **A — New** | URL not in catalog | Create entry, save PDF, queue for translation |
| **B — Updated** | URL exists, hash changed | Save new version, preserve old |
| **C — Deleted** | URL returns 404 (not 5xx) | Mark archived, keep files |
| **D — Renamed** | Same hash, different URL/name | Update name/slug/URL, no re-translation |
| **E — No change** | Hash matches | Update `last_scraped_at` only |

**Court Departments Scraped:** Appeals Court · Boston Municipal Court · District Court · Housing Court · Juvenile Court · Land Court · Superior Court · Attorney Forms · Criminal Matter Forms · Criminal Records Forms · Trial Court eFiling Forms.

> **Dev note:** In `courtaccess/forms/scraper.py`, all departments except Appeals Court are commented out by default to speed up local testing. Uncomment all entries in `COURT_FORM_PAGES` before running in production.

#### `form_pretranslation_dag` — 11 Stages (Triggered by scraper)

Processes **one form per DAG run**: OCR → translate ES + PT in parallel → legal review → reconstruct PDF → update catalog → DVC version.

| # | Task | What It Does |
|---|------|-------------|
| 1 | `load_form_entry` | Loads catalog entry, validates original PDF exists, detects partial translations |
| 2 | `ocr_extract_text` | Extracts text regions with bounding-box coordinates from the PDF |
| 3–4 | `translate_spanish` / `translate_portuguese` | Translates OCR regions per language (skips if translation already exists from mass.gov) |
| 5–6 | `legal_review_spanish` / `legal_review_portuguese` | Validates legal terms via Groq/Llama with 3× exponential-backoff retry (1s, 3s, 9s) |
| 7–8 | `reconstruct_pdf_spanish` / `reconstruct_pdf_portuguese` | Rebuilds PDF with translated text using PyMuPDF |
| 9 | `store_and_update_catalog` | Writes translated PDF paths into catalog, sets `needs_human_review = True` |
| 10 | `dvc_version_data` | Tracks updated catalog + translated PDFs with DVC |
| 11 | `log_summary` | Prints audit-style summary with per-language status |

**Partial Translation Handling** — the scraper may download pre-existing translations from mass.gov:

| Existing Translations | Behaviour |
|-----------------------|-----------|
| Both ES + PT | Entire DAG skips — nothing to translate |
| ES only | Skips Spanish tasks, runs Portuguese pipeline |
| PT only | Skips Portuguese tasks, runs Spanish pipeline |
| Neither | Full parallel translation for both languages |

If legal review fails all retries, the pipeline continues but appends an audit note and leaves `needs_human_review = True` for mandatory human review.

**Stub modules** (swapped for production models later):

| Module | Stub | Production |
|--------|------|------------|
| `courtaccess/core/ocr_printed.py` | PyMuPDF native text extraction | PaddleOCR v3 + Qwen2.5-VL |
| `courtaccess/core/translation.py` | Prefixes text with language tag | NLLB-200 via CTranslate2 |
| `courtaccess/core/legal_review.py` | Always returns OK | Groq API (Llama 4 Scout) |
| `courtaccess/core/reconstruct_pdf.py` | PyMuPDF layout reconstruction | Same (already production-ready) |

### Running the Pipeline

#### Trigger Scraper Manually

```bash
docker compose exec airflow-scheduler airflow dags unpause form_scraper_dag
docker compose exec airflow-scheduler airflow dags trigger form_scraper_dag
```

Or use the Airflow UI (http://localhost:8080): toggle the DAG on → click the play button.

#### Trigger Pre-Translation Manually

```bash
docker compose exec airflow-scheduler airflow dags unpause form_pretranslation_dag
docker compose exec airflow-scheduler airflow dags trigger form_pretranslation_dag \
  --conf '{"form_id": "<uuid-from-catalog>"}'
```

The `form_id` must exist in `courtaccess/data/form_catalog.json` with a valid `file_path_original`.

#### View Pipeline Outputs

```bash
cat courtaccess/data/form_catalog.json | python -m json.tool | head -50
cat courtaccess/data/catalog_metrics.json
cat courtaccess/data/anomaly_report.json
cat courtaccess/data/bias_report.json
ls forms/
```

**Expected runtimes:**
- `scrape_and_classify`: 20–40 min (network I/O + rate-limit sleeps — dominates total runtime)
- All other tasks: 1–15 seconds each

### Form Catalog JSON Schema

```json
{
  "form_id": "a1b2c3d4-...",
  "form_name": "Affidavit of Indigency",
  "form_slug": "affidavit-of-indigency",
  "source_url": "https://www.mass.gov/doc/affidavit-of-indigency/download",
  "status": "active",
  "content_hash": "9f86d081884c7d...",
  "current_version": 1,
  "needs_human_review": true,
  "created_at": "2026-02-21T19:23:45Z",
  "last_scraped_at": "2026-02-21T19:23:45Z",
  "appearances": [
    {"division": "District Court", "section_heading": "Indigency"},
    {"division": "Housing Court", "section_heading": "General Forms"}
  ],
  "versions": [
    {
      "version": 1,
      "content_hash": "9f86d081884c7d...",
      "file_path_original": "forms/a1b2c3d4-.../v1/affidavit-of-indigency.pdf",
      "file_path_es": "forms/a1b2c3d4-.../v1/affidavit-of-indigency_es.pdf",
      "file_path_pt": null,
      "created_at": "2026-02-21T19:23:45Z"
    }
  ]
}
```

This structure maps directly to future SQL tables: top-level fields → `form_catalog`, `appearances[]` → `form_appearances` (many-to-many), `versions[]` → `form_versions` (append-only).

### Anomaly Detection Thresholds

Configurable at the top of `dags/form_scraper_dag.py`:

```python
THRESHOLD_FORM_DROP_PCT      = 20    # % drop in form count → CRITICAL
THRESHOLD_MASS_NEW_FORMS     = 50    # forms added in one run → WARNING
THRESHOLD_DOWNLOAD_FAIL_PCT  = 10    # % missing vs last run → WARNING
THRESHOLD_MIN_PDF_SIZE_BYTES = 1024  # files below 1 KB → WARNING
THRESHOLD_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # files above 50 MB → WARNING
THRESHOLD_SCHEMA_ERRORS      = 0     # any schema errors → CRITICAL
```

Run-over-run comparison: after each run, current metrics are saved as `prev_catalog_metrics.json`. The next run loads this to compute deltas. First run skips comparison checks.

### Bias Detection

`courtaccess/monitoring/drift.py` analyzes the catalog for coverage equity across court divisions and language groups.

| Slice | Bias Flag | Condition |
|-------|-----------|-----------|
| By Division | `underserved_division` | Below 50% of mean form count |
| By Division | `low_translation_coverage` | ES or PT below 20% per division |
| By Language | `language_coverage_gap` | ES vs PT gap exceeds 30% |

Output: `courtaccess/data/bias_report.json`.

### DVC Data Versioning

DVC is initialized automatically by `airflow-init` on first `docker compose up`.

**Tracked files:** `courtaccess/data/form_catalog.json`, `forms/` directory.
**Metrics file:** `courtaccess/data/catalog_metrics.json` (tracked by DVC metrics, committed to Git).

```bash
dvc metrics show          # View current metrics
dvc metrics diff          # Compare metrics between runs
dvc pull                  # Restore data on a new machine
dvc status                # View what DVC is tracking
```

The `dvc_storage/` directory is bind-mounted into all Airflow containers at `/opt/airflow/dvc_storage` — persists across `docker compose down/up` cycles. For production, swap to GCS:

```bash
dvc remote add -d gcs_storage gs://courtaccess-forms
```

---

## Data Storage

| Storage | What | Retention |
|---------|------|-----------|
| GCS `courtaccess-uploads/` | User-uploaded PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-translated/` | Translated output PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-forms/` | Pre-translated government forms + archived versions | Permanent |
| GCS `courtaccess-models/` | Pre-trained model weights (DVC tracked) | Permanent, versioned |
| Cloud SQL (PostgreSQL) | Sessions, translation requests, audit logs, form catalog, user accounts | Permanent (metadata only) |
| `courtaccess/data/` | Local form catalog JSON (DVC tracked) | Version-controlled |

No raw audio is stored. All files encrypted at rest (CMEK via Cloud KMS).

---

## Database Schema

**`users`** — User accounts with roles (public, court_official, interpreter, admin).

**`sessions`** — One per user interaction. Holds session type, target language, uploaded file path, status, timestamps.

**`translation_requests`** — One per language per session. Holds target language, classification result, output path, confidence scores, PII count, Llama correction count, signed URL with expiry.

**`audit_logs`** — Every action logged. Required for court compliance.

**`form_catalog`** (PostgreSQL managed by Alembic migration `001_initial_schema`) — Government forms library mirroring `courtaccess/data/form_catalog.json`.

Key relationship: one session → one uploaded file → multiple translation requests (one per language).

---

## MLOps: Monitoring, Drift, and Versioning

- **TFDV** — validates incoming data, tracks distribution drift vs. the baseline in `models/tfdv-baseline-stats.dvc`
- **Evidently AI** — monitors model output quality over time (ASR confidence, translation confidence, Llama correction rate)
- **DVC** — versions model weights + form catalog. Rollback: `git checkout <commit>` then `dvc pull`
- **MLflow** — deployment registry. Logs which model versions are in production and their observed metrics
- **GCP Cloud Logging / Monitoring** — all API requests, model inference logs, pod health, latency (p50/p95/p99), alerts

---

## Key Design Decisions

**Pre-trained models only.** No fine-tuning. The MLOps pipeline manages versioning, deployment, and monitoring — not training. This keeps the system simpler and focused on pipeline reliability.

**Llama as a validation layer, not a translator.** NLLB-200 handles translation (fast, deterministic, purpose-built). Llama 4 Scout reviews translations for legal accuracy. In real-time mode, Llama runs async so users aren't blocked. In document mode, it runs sync because accuracy matters more than speed.

**Monorepo structure.** The old `data_pipeline/` sub-repo was merged into the root monorepo as `courtaccess/`, `dags/`, `api/`, `db/`, `frontend/`. One repo, one CI pipeline, one `pyproject.toml`.

**PDF-only uploads.** Restricting to PDF simplifies the pipeline — no image-to-PDF conversion needed, consistent input for OCR and reconstruction.

**3 Airflow DAGs, not 4.** Real-time speech translation runs as a WebSocket stream inside FastAPI, not as an Airflow DAG. Live audio streaming requires persistent low-latency connections, not batch orchestration.

**Pre-translated government forms.** Court forms have official legal language. Pre-translating and human-verifying once is safer than translating on-the-fly every time.

**Signed URLs for file delivery.** Translated documents served via GCS Signed URLs (1-hour expiry) — downloaded directly from cloud storage without passing through the API server.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Vite |
| Backend API | FastAPI (REST + WebSocket) |
| Audio Capture | WebRTC |
| Orchestration | Apache Airflow 3.x (3 DAGs) |
| Compute | Google Kubernetes Engine (GKE) with GPU node pools |
| File Storage | Google Cloud Storage (GCS) with CMEK encryption |
| Database | Cloud SQL (PostgreSQL) via SQLAlchemy async + Alembic |
| File Delivery | GCS Signed URLs (1-hour expiry) |
| Infrastructure as Code | Terraform |
| Containerization | Docker (multi-stage: api, airflow, gpu targets) |
| CI/CD | GitHub Actions |
| Model Versioning | DVC + MLflow |
| Data Validation | TensorFlow Data Validation (TFDV) |
| Drift Detection | Evidently AI |
| PII Detection | Microsoft Presidio |
| Logging | Python logging → GCP Cloud Logging |
| Monitoring | GCP Cloud Monitoring |
| Testing | pytest (204 tests) |
| Linting | Ruff (check + format) |
| Security | Bandit, Gitleaks, Trivy |
| Package Manager | uv |
| Form Scraping | Python requests + BeautifulSoup + Playwright |
