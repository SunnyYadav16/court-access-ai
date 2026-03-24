# CourtAccess AI

> Real-time speech and document translation for the Massachusetts Trial Court

CourtAccess AI is an MLOps-driven platform delivering real-time courtroom interpretation and legal document translation for Limited English Proficient (LEP) individuals — primarily Spanish and Portuguese speakers — within the Massachusetts Trial Court system. The platform orchestrates pre-trained AI models through automated pipelines, with continuous monitoring, drift detection, and version control built in from the ground up.

---

## The Problem

Massachusetts courts face a systemic language access crisis. Approximately **45% of scheduled interpreters fail to appear** for hearings, causing delays that effectively deny justice to LEP individuals. The shortage is most acute for non-Spanish languages, and agency interpreters cost **3× more** than staff interpreters. Court forms, signage, and processes remain largely English-only — barriers at every step of the legal process.

---

## What CourtAccess AI Does

**Real-Time Speech Translation.** Court officials start a live session. The system captures audio from the browser microphone, runs voice activity detection to filter silence, transcribes speech with Faster-Whisper, translates with NLLB-200, validates legal terminology with Llama 4, and plays back translated audio — all over a persistent WebSocket stream.

**Document Translation.** Users upload legal PDFs or browse a library of pre-translated Massachusetts court forms. Uploaded documents are OCR'd, scrubbed for PII, translated, legally reviewed, and reconstructed into a layout-preserving PDF served via a signed GCS URL. Government forms are scraped weekly from mass.gov, pre-translated, and stored for instant access.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   React + Vite Frontend                      │
└──────────────────────────┬──────────────────────────────────┘
                           │  REST / WebSocket
┌──────────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend (GKE)                      │
│  ┌─────────────────────┐   ┌──────────────────────────────┐  │
│  │  /ws/session        │   │  /documents  /forms  /auth   │  │
│  │  WebSocket stream   │   │  REST endpoints              │  │
│  └─────────┬───────────┘   └─────────────┬────────────────┘  │
└────────────┼─────────────────────────────┼──────────────────┘
             │                             │
    ┌────────▼────────┐          ┌─────────▼──────────┐
    │  Speech Pipeline│          │  Document Pipeline  │
    │  VAD → ASR      │          │  Airflow DAG        │
    │  → NLLB-200     │          │  OCR → PII Scrub    │
    │  → Llama 4      │          │  → NLLB-200         │
    │  → Piper TTS    │          │  → Llama 4          │
    └─────────────────┘          │  → Reconstruct PDF  │
                                 └─────────────────────┘
                                          │
                             ┌────────────▼────────────┐
                             │  GCS (uploads/translated)│
                             │  Cloud SQL (PostgreSQL)  │
                             │  DVC + MLflow (models)   │
                             └─────────────────────────┘
```

### Pipeline Overview

| Pipeline | Type | Trigger |
|---|---|---|
| Real-time speech translation | WebSocket stream (FastAPI) | Court official starts session |
| `document_pipeline_dag` | Airflow DAG | User uploads a PDF |
| `form_scraper_dag` | Airflow DAG (scheduled) | Weekly, every Monday at 06:00 UTC |
| `form_pretranslation_dag` | Airflow DAG | Triggered by scraper on new/updated forms |

### Access Control

| Role | Access |
|---|---|
| `public` | Document translation (upload + government forms) |
| `court_official` | Everything: real-time translation + document translation |
| `interpreter` | Real-time sessions, translation review interface |
| `admin` | Everything + monitoring dashboards, user management |

---

## AI Models

All models are pre-trained — no fine-tuning. The MLOps pipeline handles versioning, serving, monitoring, and updates.

| Model | Role | Details |
|---|---|---|
| **Faster-Whisper Large V3** | Speech-to-text | CTranslate2 INT8 quantization, ~60× realtime |
| **NLLB-200 Distilled 1.3B** | Translation (EN ↔ ES/PT) | Meta's No Language Left Behind |
| **Llama 4 Maverick** | Legal validation + doc classification | Via Vertex API — async for real-time, sync for documents |
| **PaddleOCR v3** | Printed text extraction | DBNet + SVTR recognition, >95% accuracy |
| **Qwen2.5-VL** | Handwritten text extraction | Vision-language model, ~90% accuracy |
| **Silero VAD v4** | Voice activity detection | Filters silence before ASR |
| **Piper TTS** | Text-to-speech | Spoken output in Spanish and Portuguese |
| **Microsoft Presidio** | PII detection | Custom recognizers for MA docket patterns, SSN, etc. |

Model weights are tracked via DVC and stored in GCS (`gs://courtaccess-models/`):

```bash
dvc pull   # downloads model weights from GCS
```

---

## Project Structure

```
court-access-ai/
├── api/                          # FastAPI application
│   ├── main.py                   # App factory, lifespan, health check
│   ├── auth.py                   # JWT token creation/verification
│   ├── dependencies.py           # Shared FastAPI dependencies
│   ├── routes/
│   │   ├── auth.py               # /auth/register, /login, /me, /refresh, /logout
│   │   ├── documents.py          # /documents/upload, GET, DELETE
│   │   ├── forms.py              # /forms/ — government form catalog
│   │   └── realtime.py           # /ws/session — WebSocket real-time stream
│   ├── schemas/schemas.py        # Pydantic request/response models
│   └── tests/
│
├── courtaccess/                  # Core Python package
│   ├── core/
│   │   ├── translation.py        # NLLB-200 (stub → real)
│   │   ├── legal_review.py       # Llama validation (stub → Vertex)
│   │   ├── ocr_printed.py        # PaddleOCR v3 (stub → real)
│   │   ├── ocr_handwritten.py    # Qwen2.5-VL (stub → real)
│   │   ├── reconstruct_pdf.py    # PyMuPDF layout reconstruction
│   │   ├── pii_scrub.py          # Microsoft Presidio
│   │   └── ...
│   ├── languages/
│   │   ├── base.py               # LanguageConfig dataclass
│   │   ├── spanish.py            # Spanish configuration + glossary (700+ terms)
│   │   ├── portuguese.py         # Portuguese configuration + glossary (700+ terms)
│   │   └── tests/
│   ├── forms/
│   │   ├── scraper.py            # mass.gov scraper (Playwright)
│   │   ├── catalog.py            # Form catalog management
│   │   └── tests/
│   ├── speech/
│   │   ├── vad.py                # Silero VAD
│   │   ├── transcribe.py         # Faster-Whisper ASR
│   │   ├── tts.py                # Piper TTS
│   │   ├── session.py            # WebSocket session management
│   │   └── tests/
│   └── monitoring/
│       ├── drift.py              # TFDV drift detection + bias analysis
│       ├── anomaly.py            # Anomaly detection
│       └── tests/
│
├── dags/
│   ├── form_scraper_dag.py       # Weekly scrape → preprocess → validate → version
│   ├── form_pretranslation_dag.py
│   └── document_pipeline_dag.py
│
├── db/
│   ├── models.py                 # SQLAlchemy ORM models
│   ├── database.py               # Async engine + session factory
│   └── migrations/versions/001_initial_schema.py
│
├── frontend/src/
│   ├── pages/                    # LandingPage, SessionPage, DocumentsPage, FormsPage
│   ├── hooks/                    # useAuth, useWebSocket
│   └── store/authStore.js        # Zustand auth state
│
├── data/glossaries/              # Legal term glossaries — 700+ terms each (ES, PT)
├── models/                       # DVC pointer files (weights stored in GCS)
├── docs/                         # Architecture docs, bias reports, contributing guides
├── .github/workflows/            # CI/CD: test, lint, dependencies, build
├── Dockerfile                    # Multi-stage: api + airflow targets
├── gpu.Dockerfile                # GPU inference (CUDA 12, PyTorch)
├── docker-compose.yml            # Local dev stack
└── pyproject.toml                # Package + all dependencies
```

---

## Local Setup

### Prerequisites

- Python 3.11
- [uv](https://docs.astral.sh/uv/) — fast Python package manager
- Docker + Docker Compose
- DVC (`pip install dvc`)

### 1. Clone and install

```bash
git clone https://github.com/SunnyYadav16/court-access-ai.git
cd court-access-ai

# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc   # or restart your terminal

# Create venv and install
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install -r requirements-dev.txt 2>/dev/null || true
```

### 2. Install additional dependencies

```bash
# spaCy model (not in pyproject.toml)
python -m spacy download en_core_web_lg

# PyTorch
uv pip install torch
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env — see .env.example for all required values
```

### 4. Pull model weights

```bash
dvc pull   # downloads from gs://courtaccess-models/
```

### 5. Start local services

```bash
docker compose up -d
```

| Service | URL |
|---|---|
| Airflow | http://localhost:8080 |
| FastAPI | http://localhost:8000 |
| PostgreSQL | port 5432 |
| MLflow | http://localhost:5000 |

### 6. Run tests

```bash
pytest   # 204 tests across api/, courtaccess/, db/
```

---

## CI/CD

| Workflow | Trigger | What it does |
|---|---|---|
| `test.yml` | Every push / PR | `pytest` — 204 tests, blocks merge on failure |
| `lint.yml` | Every push / PR | `ruff check`, `ruff format --check`, `bandit`, `gitleaks` |
| `dependencies.yml` | Every push / PR | Trivy filesystem scan → SARIF to GitHub Security |
| `build.yml` | Merge to `main` | Docker build + push to GCP Artifact Registry |

---

## Data Pipeline

### `form_scraper_dag` — 8 stages, scheduled Monday 06:00 UTC

Scrapes 11 mass.gov court department pages, downloads PDFs, and runs preprocessing, validation, anomaly detection, and bias analysis.

| Stage | Task | What it does |
|---|---|---|
| 1 | `scrape_and_classify` | Playwright scrape → classify into 5 scenarios → update `form_catalog.json` |
| 2 | `preprocess_data` | Normalize slugs, detect mislabeled files, check PDF integrity, flag duplicates |
| 3 | `validate_catalog` | Validate JSON schema, check duplicate IDs/URLs, generate `catalog_metrics.json` |
| 4 | `detect_anomalies` | Compare to previous run, check thresholds, generate `anomaly_report.json` |
| 5 | `detect_bias` | Slice by division/language, flag low coverage, generate `bias_report.json` |
| 6 | `trigger_pretranslation` | Trigger `form_pretranslation_dag` for scenarios A and B |
| 7 | `log_summary` | Print consolidated report to Airflow logs |
| 8 | `dvc_version_data` | `dvc add` + `dvc push` the catalog and `forms/` directory |

**5-scenario classification:**

| Scenario | Detection | Action |
|---|---|---|
| A — New | URL not in catalog | Create entry, save PDF, queue for translation |
| B — Updated | URL exists, hash changed | Save new version, preserve old |
| C — Deleted | URL returns 404 | Mark archived, keep files |
| D — Renamed | Same hash, different URL/name | Update metadata, no re-translation |
| E — No change | Hash matches | Update `last_scraped_at` only |

> **Dev note:** In `courtaccess/forms/scraper.py`, all departments except Appeals Court are commented out by default for faster local testing. Uncomment all entries in `COURT_FORM_PAGES` before running in production.

### `form_pretranslation_dag` — 11 stages, triggered by scraper

Processes one form per DAG run: OCR → translate ES + PT in parallel → legal review → reconstruct PDF → update catalog → DVC version.

**Partial translation handling:**

| Existing translations | Behaviour |
|---|---|
| Both ES + PT | Entire DAG skips |
| ES only | Skips Spanish tasks, runs Portuguese pipeline |
| PT only | Skips Portuguese tasks, runs Spanish pipeline |
| Neither | Full parallel translation for both languages |

**Stub modules** (replaced in production):

| Module | Stub | Production |
|---|---|---|
| `courtaccess/core/ocr_printed.py` | PyMuPDF native text | PaddleOCR v3 + Qwen2.5-VL |
| `courtaccess/core/translation.py` | Language-tag prefix | NLLB-200 via CTranslate2 |
| `courtaccess/core/legal_review.py` | Always returns OK | Vertex API (Llama 4 Maverick) |
| `courtaccess/core/reconstruct_pdf.py` | PyMuPDF reconstruction | Same — already production-ready |

### Running pipelines manually

```bash
# Trigger scraper
docker compose exec airflow-scheduler airflow dags unpause form_scraper_dag
docker compose exec airflow-scheduler airflow dags trigger form_scraper_dag

# Trigger pre-translation
docker compose exec airflow-scheduler airflow dags unpause form_pretranslation_dag
docker compose exec airflow-scheduler airflow dags trigger form_pretranslation_dag \
  --conf '{"form_id": "<uuid-from-catalog>"}'

# View outputs
cat courtaccess/data/form_catalog.json | python -m json.tool | head -50
cat courtaccess/data/anomaly_report.json
cat courtaccess/data/bias_report.json
```

**Expected runtimes:**
- `scrape_and_classify`: 20–40 min (network I/O dominates)
- All other stages: 1–15 seconds each

### Anomaly detection thresholds

Configurable at the top of `dags/form_scraper_dag.py`:

```python
THRESHOLD_FORM_DROP_PCT      = 20    # % drop in form count → CRITICAL
THRESHOLD_MASS_NEW_FORMS     = 50    # forms added in one run → WARNING
THRESHOLD_DOWNLOAD_FAIL_PCT  = 10    # % missing vs last run → WARNING
THRESHOLD_MIN_PDF_SIZE_BYTES = 1024  # files below 1 KB → WARNING
THRESHOLD_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # files above 50 MB → WARNING
THRESHOLD_SCHEMA_ERRORS      = 0     # any schema errors → CRITICAL
```

### Bias detection

`courtaccess/monitoring/drift.py` analyzes coverage equity across court divisions and language groups.

| Slice | Flag | Condition |
|---|---|---|
| By division | `underserved_division` | Below 50% of mean form count |
| By division | `low_translation_coverage` | ES or PT below 20% per division |
| By language | `language_coverage_gap` | ES vs PT gap exceeds 30% |

Output: `courtaccess/data/bias_report.json`

---

## Data Storage

| Storage | What | Retention |
|---|---|---|
| GCS `courtaccess-uploads/` | User-uploaded PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-translated/` | Translated output PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-forms/` | Pre-translated government forms | Permanent |
| GCS `courtaccess-models/` | Model weights (DVC tracked) | Permanent, versioned |
| Cloud SQL (PostgreSQL) | Sessions, requests, audit logs, form catalog | Permanent (metadata only) |
| `courtaccess/data/` | Local form catalog JSON | Version-controlled via DVC |

No raw audio is ever stored. All files are encrypted at rest (CMEK via Cloud KMS).

---

## Database Schema

- `users` — accounts with roles: `public`, `court_official`, `interpreter`, `admin`
- `sessions` — one per user interaction: type, target language, file path, status, timestamps
- `translation_requests` — one per language per session: output path, confidence scores, PII count, Llama correction count, signed URL with expiry
- `audit_logs` — every action logged; required for court compliance
- `form_catalog` — government forms library, mirrors `courtaccess/data/form_catalog.json`

One session → one uploaded file → multiple translation requests (one per language).

---

## MLOps: Monitoring, Drift, and Versioning

- **TFDV** — validates incoming data, tracks distribution drift against the baseline in `models/tfdv-baseline-stats.dvc`
- **Evidently AI** — monitors model output quality over time (ASR confidence, translation confidence, Llama correction rate)
- **DVC** — versions model weights and the form catalog; to roll back: `git checkout <commit>` then `dvc pull`
- **MLflow** — deployment registry; logs which model versions are in production and their observed metrics
- **GCP Cloud Logging / Monitoring** — API requests, model inference logs, pod health, latency at p50/p95/p99

---

## Key Design Decisions

**Pre-trained models only.** No fine-tuning. The MLOps pipeline manages versioning, deployment, and monitoring — keeping the system focused on reliability rather than training infrastructure.

**Llama as a validation layer, not a translator.** NLLB-200 handles translation — fast, deterministic, purpose-built. Llama 4 Maverick reviews the output for legal accuracy. In real-time mode it runs async so users aren't blocked; in document mode it runs sync because accuracy matters more than latency.

**Monorepo.** One repo, one CI pipeline, one `pyproject.toml`. The previous `data_pipeline/` sub-repo is merged into `courtaccess/`, `dags/`, `api/`, `db/`, `frontend/`.

**PDF-only uploads.** Restricting input to PDF eliminates image-to-PDF conversion, keeps the OCR and reconstruction pipeline consistent, and simplifies validation.

**3 Airflow DAGs, not 4.** Real-time speech translation lives as a WebSocket stream inside FastAPI — not a DAG. Live audio requires persistent low-latency connections, not batch orchestration.

**Pre-translated government forms.** Court forms carry official legal language. Pre-translating once and having humans verify is safer than on-the-fly translation at request time.

**Signed URLs for file delivery.** Translated documents are served via GCS Signed URLs (1-hour expiry), downloaded directly from cloud storage without the API server acting as a proxy.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite |
| Backend API | FastAPI (REST + WebSocket) |
| Audio capture | WebRTC |
| Orchestration | Apache Airflow 3.x |
| Compute | Google Kubernetes Engine (GKE) with GPU node pools |
| File storage | Google Cloud Storage (GCS) with CMEK encryption |
| Database | Cloud SQL (PostgreSQL) via SQLAlchemy async + Alembic |
| File delivery | GCS Signed URLs (1-hour expiry) |
| Infrastructure | Terraform |
| Containers | Docker — multi-stage: api, airflow, gpu |
| CI/CD | GitHub Actions |
| Model versioning | DVC + MLflow |
| Data validation | TensorFlow Data Validation (TFDV) |
| Drift detection | Evidently AI |
| PII detection | Microsoft Presidio |
| Logging | Python → GCP Cloud Logging |
| Monitoring | GCP Cloud Monitoring |
| Testing | pytest (204 tests) |
| Linting | Ruff (check + format) |
| Security | Bandit, Gitleaks, Trivy |
| Package manager | uv |
| Form scraping | requests + BeautifulSoup + Playwright |

