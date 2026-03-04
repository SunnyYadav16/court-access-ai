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

- Python 3.12
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

### Form Scraping (`form_scraper_dag`, weekly Mon 06:00 UTC)

Scrapes mass.gov court form pages, downloads each form PDF, hashes it, and compares against the existing catalog at `courtaccess/data/form_catalog.json`.

Five scenarios handled:
- **New form** → download, catalog entry, trigger pre-translation
- **Updated form** (hash changed) → archive old version, re-translate
- **Deleted form** (confirmed 404 only) → mark archived, retain in system
- **Renamed form** (same hash) → update name, no re-translation
- **No change** → update last-checked timestamp

### Pre-Translation (`form_pretranslation_dag`, triggered by scraper)

Processes one form per DAG run through: Load catalog → OCR → Translate (ES + PT in parallel) → Legal review → Reconstruct PDF → Update catalog → DVC version.

All machine-translated forms are flagged `needs_human_review = True` until a court translator approves them.

### DVC Data Versioning

```
dvc.yaml stages:
  scrape_forms        → writes courtaccess/data/form_catalog.json
  validate_catalog    → writes data/catalog_metrics.json
  pretranslate_forms  → reads courtaccess/data/form_catalog.json
```

Both DAGs call `dvc add` + `dvc push` after updating the catalog.

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
