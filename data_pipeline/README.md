# CourtAccess AI — Data Pipeline

**MLOps Data Pipeline for Massachusetts Trial Court Language Access**

Part of the CourtAccess AI system — an AI-driven platform providing real-time courtroom interpretation and legal document translation for non-English speakers in the Massachusetts Trial Court system.

This pipeline consists of **two Airflow DAGs**:

1. **`form_scraper_dag`** (scheduled weekly) — Scrapes Massachusetts court forms from mass.gov, downloads PDFs (including existing Spanish and Portuguese translations), tracks changes with 5-scenario classification, preprocesses data, validates schema, detects anomalies and coverage bias, and versions everything using DVC.

2. **`form_pretranslation_dag`** (triggered by scraper) — Translates new or updated court forms to Spanish and Portuguese via OCR → translation → legal review → PDF reconstruction, then updates the form catalog and versions the output with DVC.

---

## Table of Contents

- [Pipeline Overview](#pipeline-overview)
- [Project Structure](#project-structure)
- [Setup Instructions](#setup-instructions)
- [Running the Pipeline](#running-the-pipeline)
- [Pipeline Tasks (8 Stages)](#pipeline-tasks-8-stages)
- [Pre-Translation Pipeline](#pre-translation-pipeline-form_pretranslation_dag)
- [Data Acquisition](#data-acquisition)
- [Data Preprocessing](#data-preprocessing)
- [Data Schema & Validation](#data-schema--validation)
- [Anomaly Detection & Alerts](#anomaly-detection--alerts)
- [Bias Detection & Data Slicing](#bias-detection--data-slicing)
- [Data Versioning (DVC)](#data-versioning-dvc)
- [Testing](#testing)
- [Pipeline Flow Optimization](#pipeline-flow-optimization)
- [JSON Catalog Schema](#json-catalog-schema)
- [Court Departments Scraped](#court-departments-scraped)
- [Error Handling & Logging](#error-handling--logging)
- [Reproducibility](#reproducibility)

---

## Pipeline Overview

```
form_scraper_dag (Airflow DAG — Scheduled Every Monday 06:00 UTC)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  scrape_and_classify                                                     │
│  │  Scrape 11 mass.gov department pages using Playwright                │
│  │  Download PDFs + existing ES/PT translations                         │
│  │  Classify each form into 5 scenarios (new/updated/deleted/           │
│  │  renamed/no-change)                                                  │
│  │  Update form_catalog.json                                            │
│  ▼                                                                      │
│  preprocess_data                                                         │
│  │  Normalize form names and slugs                                      │
│  │  Detect mislabeled files (HTML/DOCX saved as .pdf)                   │
│  │  Check PDF integrity (truncated downloads)                           │
│  │  Flag empty/tiny files, detect duplicate content                     │
│  ▼                                                                      │
│  validate_catalog                                                        │
│  │  Validate JSON schema (required fields, types, values)               │
│  │  Check for duplicate form_ids and source_urls                        │
│  │  Verify referenced PDFs exist on disk                                │
│  │  Generate catalog_metrics.json                                       │
│  ▼                                                                      │
│  detect_anomalies                                                        │
│  │  Compare current metrics against previous run                        │
│  │  Check for form count drops, mass new forms, download failures       │
│  │  Scan for tiny/huge PDFs, schema violations, missing files           │
│  │  Generate anomaly_report.json                                        │
│  ▼                                                                      │
│  detect_bias                                                             │
│  │  Slice data by division, language, section heading, version          │
│  │  Flag underserved divisions and low translation coverage             │
│  │  Analyze ES vs PT coverage gap                                       │
│  │  Generate bias_report.json                                           │
│  ▼                                                                      │
│  trigger_pretranslation                                                  │
│  │  Queue new/updated forms for AI translation (placeholder)            │
│  ▼                                                                      │
│  log_summary                                                             │
│  │  Print consolidated report to Airflow logs                           │
│  │  (scrape + preprocess + validation + anomaly + bias)                 │
│  ▼                                                                      │
│  dvc_version_data                                                        │
│     Run 'dvc add' on catalog + forms directory                          │
│     Push to DVC remote storage                                          │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
data_pipeline/
├── dags/                                  # Airflow DAGs and source code
│   ├── form_scraper_dag.py                # Scraper DAG — 8 tasks (weekly)
│   ├── form_pretranslation_dag.py         # Pre-translation DAG — 11 tasks (triggered)
│   ├── src/                               # Modular pipeline source code
│   │   ├── __init__.py
│   │   ├── scrape_forms.py                # Core scraping logic + 5 scenario handlers
│   │   ├── preprocess_forms.py            # Data cleaning, normalization, file validation
│   │   ├── bias_detection.py              # Language and division coverage checks
│   │   ├── ocr_printed.py                 # OCR text extraction (stub → PaddleOCR v3)
│   │   ├── translate_text.py              # Translation (stub → NLLB-200)
│   │   ├── legal_review.py                # Legal term validation (stub → Groq/Llama)
│   │   └── reconstruct_pdf.py             # PDF reconstruction with PyMuPDF
│   └── data/                              # Pipeline outputs (generated at runtime)
│       ├── form_catalog.json              # Form metadata catalog (DVC tracked)
│       ├── catalog_metrics.json           # Validation metrics (DVC metrics)
│       ├── preprocess_report.json         # Preprocessing results
│       ├── anomaly_report.json            # Anomaly detection results
│       ├── prev_catalog_metrics.json      # Previous run metrics (for comparison)
│       └── bias_report.json               # Bias detection results
├── scripts/
│   └── validate_catalog.py                # Standalone validation (used by dvc.yaml)
├── tests/
│   ├── __init__.py
│   └── test_form_scraper.py               # 66 unit tests
├── forms/                                 # Downloaded PDFs (DVC tracked, gitignored)
├── Dockerfile                             # Airflow + Playwright + DVC image
├── docker-compose.yml                     # PostgreSQL + 5 Airflow services
├── dvc.yaml                               # DVC pipeline definition and metrics
├── requirements.txt                       # Python dependencies
├── .env.example                           # Environment variable template
├── .gitignore                             # Git ignores (forms/, logs/, .env, etc.)
└── README.md                              # This file
```

---

## Setup Instructions

### Prerequisites

- Docker and Docker Compose (v2+)
- Git
- Python 3.10+ (for running tests locally)

### Step 1 — Clone the Repository

```bash
git clone https://github.com/SunnyYadav16/court-access-ai.git
cd court-access-ai/data_pipeline
```

### Step 2 — Create the Environment File

```bash
cp .env.example .env
```

Generate the required keys and add them to `.env`:

```bash
# Generate Fernet key (using Docker to avoid needing local python packages)
docker run --rm apache/airflow:3.1.7 python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Generate secret key
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the outputs into `.env`:

```
AIRFLOW_UID=50000
AIRFLOW_FERNET_KEY=<paste fernet key>
AIRFLOW_SECRET_KEY=<paste secret key>
_AIRFLOW_WWW_USER_USERNAME=airflow
_AIRFLOW_WWW_USER_PASSWORD=airflow
POSTGRES_USER=airflow
POSTGRES_PASSWORD=airflow
POSTGRES_DB=airflow
```

### Step 3 — Build and Start

```bash
docker compose build
docker compose up -d
```

This automatically:
- Starts PostgreSQL database
- Initializes DVC with local remote storage (via `airflow-init`)
- Migrates Airflow database and creates admin user
- Starts Airflow API server, scheduler, DAG processor, and triggerer

### Step 4 — Access Airflow UI

Open `http://localhost:8080` and log in with `airflow` / `airflow`.

### Step 5 — Verify DAGs are Visible

```bash
docker compose exec airflow-scheduler airflow dags list
```

You should see both `form_scraper_dag` and `form_pretranslation_dag` in the output.

---

## Running the Pipeline

### Trigger the Scraper Manually

```bash
docker compose exec airflow-scheduler airflow dags unpause form_scraper_dag
docker compose exec airflow-scheduler airflow dags trigger form_scraper_dag
```

Or use the Airflow UI: toggle the DAG on → click the play button.

The scraper's `trigger_pretranslation` task automatically triggers `form_pretranslation_dag` for any new or updated forms (Scenarios A & B).

### Trigger Pre-Translation Manually

To translate a specific form without running the full scraper:

```bash
docker compose exec airflow-scheduler airflow dags unpause form_pretranslation_dag
docker compose exec airflow-scheduler airflow dags trigger form_pretranslation_dag \
  --conf '{"form_id": "<uuid-from-catalog>"}'
```

The `form_id` must exist in `dags/data/form_catalog.json` with a valid `file_path_original`.

### Automatic Schedule

The scraper DAG runs every Monday at 06:00 UTC automatically. The pretranslation DAG has no schedule — it is only triggered by the scraper or manually.

### Monitor Progress

In the Airflow UI: click the DAG name → click the running DAG run → click any task → **Logs** tab.

- **Scraper** runs take approximately 20-40 minutes (scraping 11 departments with rate-limit sleeps between batches).
- **Pre-translation** runs take approximately 1-5 minutes per form (depending on PDF size and page count).

### View Outputs

```bash
# Catalog JSON
cat dags/data/form_catalog.json | python -m json.tool | head -50

# Validation metrics
cat dags/data/catalog_metrics.json

# Anomaly report
cat dags/data/anomaly_report.json

# Bias report
cat dags/data/bias_report.json

# Downloaded and translated PDFs
ls forms/
```

---

## Pipeline Tasks (8 Stages)

| # | Task ID | Module | What It Does |
|---|---------|--------|-------------|
| 1 | `scrape_and_classify` | `src/scrape_forms.py` | Scrapes mass.gov, downloads PDFs + translations, classifies into 5 scenarios |
| 2 | `preprocess_data` | `src/preprocess_forms.py` | Normalizes names/slugs, detects mislabeled files, checks PDF integrity |
| 3 | `validate_catalog` | Inline in DAG | Validates JSON schema, checks duplicates, verifies PDFs exist, generates metrics |
| 4 | `detect_anomalies` | Inline in DAG | Compares against previous run, checks thresholds, generates anomaly report |
| 5 | `detect_bias` | `src/bias_detection.py` | Data slicing by division/language/section, flags coverage imbalances |
| 6 | `trigger_pretranslation` | Inline in DAG | Triggers `form_pretranslation_dag` for new/updated forms (Scenarios A & B) |
| 7 | `log_summary` | Inline in DAG | Prints consolidated report to Airflow logs |
| 8 | `dvc_version_data` | Inline in DAG | Runs `dvc add` + `dvc push` to version data |

---

## Pre-Translation Pipeline (form_pretranslation_dag)

Triggered by `form_scraper_dag` when Scenario A (new form) or Scenario B (updated form) is detected. Processes **one form per DAG run**.

### Pipeline Flow

```
form_pretranslation_dag (Airflow DAG — Triggered, no schedule)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  load_form_entry                                                         │
│  │  Read form_id from trigger conf, locate catalog entry                │
│  │  Validate original PDF exists, detect partial translations           │
│  │  Skip form if ES + PT already exist from mass.gov                    │
│  ▼                                                                      │
│  ocr_extract_text                                                        │
│  │  Extract text regions with bounding boxes from original PDF          │
│  │  (Stub: PyMuPDF native. Production: PaddleOCR v3 + Qwen2.5-VL)      │
│  ▼                                                                      │
│  ┌─────────────────────────┬─────────────────────────┐                   │
│  │  translate_spanish      │  translate_portuguese    │  (parallel)      │
│  │  → legal_review_spanish │  → legal_review_portuguese│ (parallel)      │
│  │  → reconstruct_pdf_es   │  → reconstruct_pdf_pt    │  (parallel)      │
│  └─────────────┬───────────┴───────────┬─────────────┘                   │
│                ▼                       ▼                                 │
│  store_and_update_catalog                                                │
│  │  Write translated PDF paths into form_catalog.json                   │
│  │  Update languages_available, set needs_human_review=True             │
│  │  Append audit notes if legal review was skipped                      │
│  ▼                                                                      │
│  dvc_version_data                                                        │
│  │  Track updated catalog + translated PDFs with DVC                    │
│  ▼                                                                      │
│  log_summary                                                             │
│     Print audit-style summary to Airflow logs                           │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Trigger Configuration

The DAG expects a trigger conf with the `form_id` to translate:

```json
{"form_id": "<uuid-from-catalog>"}
```

### Tasks (11 Stages)

| # | Task ID | Module | What It Does |
|---|---------|--------|-------------|
| 1 | `load_form_entry` | Inline in DAG | Loads catalog entry, validates original PDF exists, detects partial translations |
| 2 | `ocr_extract_text` | `src/ocr_printed.py` | Extracts text regions with bbox coordinates from PDF |
| 3 | `translate_spanish` | `src/translate_text.py` | Translates OCR regions to Spanish (skips if ES already exists) |
| 4 | `translate_portuguese` | `src/translate_text.py` | Translates OCR regions to Portuguese (skips if PT already exists) |
| 5 | `legal_review_spanish` | `src/legal_review.py` | Validates Spanish legal terms via Llama/Groq with 3x retry |
| 6 | `legal_review_portuguese` | `src/legal_review.py` | Validates Portuguese legal terms via Llama/Groq with 3x retry |
| 7 | `reconstruct_pdf_spanish` | `src/reconstruct_pdf.py` | Rebuilds PDF with Spanish text using PyMuPDF |
| 8 | `reconstruct_pdf_portuguese` | `src/reconstruct_pdf.py` | Rebuilds PDF with Portuguese text using PyMuPDF |
| 9 | `store_and_update_catalog` | Inline in DAG | Updates catalog with translated paths and audit notes |
| 10 | `dvc_version_data` | Inline in DAG | Runs `dvc add` + `dvc push` to version translations |
| 11 | `log_summary` | Inline in DAG | Prints audit-style summary with per-language status |

### Partial Translation Handling

The scraper may download existing Spanish or Portuguese translations from mass.gov. The pretranslation DAG handles this:

- **Both ES + PT exist** → Entire DAG skips (nothing to do)
- **Only ES exists** → Skips Spanish tasks, runs Portuguese pipeline only
- **Only PT exists** → Skips Portuguese tasks, runs Spanish pipeline only
- **Neither exists** → Runs full parallel translation for both languages

### Legal Review Retry

Legal review calls Groq/Llama with exponential backoff (1s, 3s, 9s). If all retries fail, the pipeline **continues** but appends an audit note and leaves `needs_human_review = True` so the form is flagged for mandatory human review.

### Stub Modules

Four `src/` modules are stub implementations that will be swapped for production models:

| Module | Stub Behaviour | Production Replacement |
|--------|---------------|------------------------|
| `src/ocr_printed.py` | PyMuPDF native text extraction | PaddleOCR v3 + Qwen2.5-VL |
| `src/translate_text.py` | Prefixes text with language tag | NLLB-200 via CTranslate2 |
| `src/legal_review.py` | Always returns OK | Groq API (Llama 3.1) |
| `src/reconstruct_pdf.py` | PyMuPDF layout reconstruction | Same (already production-ready) |

---

## Data Acquisition

**Source:** 11 Massachusetts court department pages on mass.gov.

**Tool:** Playwright (headless Chromium) — mass.gov renders forms dynamically via JavaScript and blocks plain HTTP requests with 403 errors.

**Process:**
1. Open each department page in headless browser
2. Scroll to trigger lazy-loaded content
3. Extract form links with section headings via DOM traversal
4. Detect existing Spanish/Portuguese translation links
5. Download PDFs in batches of 10 with 15-second sleeps (rate limiting)
6. Deduplicate across departments (same URL = same form)

**5-Scenario Classification:**

| Scenario | Detection | Action |
|----------|-----------|--------|
| **A — New** | URL not in catalog | Create entry, save PDF, queue for translation |
| **B — Updated** | URL exists, hash changed | Save new version, old version preserved |
| **C — Deleted** | URL returns 404 (not 5xx) | Mark archived, keep files |
| **D — Renamed** | Same hash, different URL/name | Update name/slug/URL |
| **E — No change** | Hash matches | Update `last_scraped_at` |

**Departments Scraped:** Appeals Court, Boston Municipal Court, District Court, Housing Court, Juvenile Court, Land Court, Superior Court, Attorney Forms, Criminal Matter Forms, Criminal Records Forms, Trial Court eFiling Forms.

> **Dev note:** In `src/scrape_forms.py`, all departments except Appeals Court are commented out by default to speed up local testing. Uncomment all entries in `COURT_FORM_PAGES` before running in production or staging.

---

## Data Preprocessing

**Module:** `dags/src/preprocess_forms.py`

| Check | What It Does | Modifies Catalog? |
|-------|-------------|-------------------|
| Name normalization | Trims whitespace, collapses spaces, strips leaked file extensions | Yes — `form_name` |
| Slug normalization | Lowercases, replaces underscores, removes special characters | Yes — `form_slug` |
| Empty file detection | Flags 0-byte downloads | Yes — adds `preprocessing_flags` |
| Tiny file detection | Flags files under 1KB (likely error pages) | Yes — adds flag |
| File type detection | Reads magic bytes to catch HTML/DOCX mislabeled as .pdf | Yes — adds flag |
| PDF integrity | Checks for `%%EOF` marker (missing = truncated) | Yes — adds flag |
| Duplicate content | Finds different form_ids sharing same content_hash | Report only |

**Output:** `dags/data/preprocess_report.json`

---

## Data Schema & Validation

**Task:** `validate_catalog` (inline in DAG)

Validates every catalog entry against the required schema:

**Required top-level fields:** `form_id`, `form_name`, `form_slug`, `source_url`, `status`, `content_hash`, `current_version`, `needs_human_review`, `created_at`, `last_scraped_at`, `appearances`, `versions`

**Checks performed:**
- Missing required fields
- Duplicate `form_id` values
- Duplicate `source_url` values
- Invalid `status` values (must be `active` or `archived`)
- Invalid `current_version` (must be positive integer)
- Empty `versions` array
- Missing appearance/version sub-fields
- Referenced PDFs not found on disk

**Output:** `dags/data/catalog_metrics.json` — tracked by DVC as a metrics file.

```bash
# View current metrics
dvc metrics show
```

---

## Anomaly Detection & Alerts

**Task:** `detect_anomalies` (inline in DAG)

Compares current run metrics against configurable thresholds and previous run data.

| Check | Threshold | Severity | What It Catches |
|-------|-----------|----------|----------------|
| Form count drop | >20% decrease | CRITICAL | mass.gov outage or scraper breaking |
| Mass new forms | >50 in one run | WARNING | Scraper bug or site restructure |
| Download failure rate | >10% missing vs last run | WARNING | Network issues, rate limiting |
| Tiny PDFs | <1KB | WARNING | HTML error pages saved as .pdf |
| Huge PDFs | >50MB | WARNING | Wrong files downloaded |
| Schema violations | Any errors | CRITICAL | Broken catalog entries |
| Missing PDFs | Any on disk | WARNING | Failed writes or deletions |

**Run-over-run comparison:** After each run, current metrics are saved as `prev_catalog_metrics.json`. Next run loads this to compute deltas. First run skips comparison checks.

**Alert mechanism:** Anomalies are logged at `CRITICAL` or `WARNING` level in Airflow logs and written to `dags/data/anomaly_report.json`.

**Thresholds are configurable** at the top of `form_scraper_dag.py`:

```python
THRESHOLD_FORM_DROP_PCT      = 20
THRESHOLD_MASS_NEW_FORMS     = 50
THRESHOLD_DOWNLOAD_FAIL_PCT  = 10
THRESHOLD_MIN_PDF_SIZE_BYTES = 1024
THRESHOLD_MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024
THRESHOLD_SCHEMA_ERRORS      = 0
```

---

## Bias Detection & Data Slicing

**Module:** `dags/src/bias_detection.py`

Analyzes the form catalog for coverage equity — ensuring all court divisions and language groups have equitable access to translated forms.

### Slicing Dimensions

| Slice | What It Analyzes | Bias Flags |
|-------|-----------------|------------|
| **By Division** | Form count + ES/PT coverage per department | `underserved_division` — below 50% of mean form count |
| | | `low_translation_coverage` — ES or PT below 20% per division |
| **By Language** | Overall Spanish vs Portuguese coverage | `language_coverage_gap` — if gap exceeds 30% |
| **By Section Heading** | Forms per section, translation availability | Informational (stats only) |
| **By Version** | Update frequency distribution | Stats only (mean, median, std_dev) |

### Why This Matters

If Housing Court has 14 forms with 0 translations while District Court has 42 forms with 30 translations, LEP individuals in Housing Court get significantly worse service. The bias detection flags these imbalances so they can be prioritized for translation.

**Output:** `dags/data/bias_report.json`

---

## Data Versioning (DVC)

### How It Works

DVC is initialized automatically by `airflow-init` on first `docker compose up`. No manual setup required.

**Tracked files:**
- `dags/data/form_catalog.json` — form metadata catalog
- `forms/` — downloaded PDF directory

**Metrics file:**
- `dags/data/catalog_metrics.json` — tracked by DVC metrics (not cached, committed to Git)

**Pipeline definition:** `dvc.yaml` documents two stages matching the Airflow DAG.

### Automatic Versioning

The `dvc_version_data` DAG task (Task 8) runs `dvc add` and `dvc push` automatically after every scraper run. Data is versioned without manual intervention.

### DVC Commands

```bash
# View current metrics
dvc metrics show

# Compare metrics between runs
dvc metrics diff

# Pull data from remote (on a new machine after cloning)
dvc pull

# View DVC-tracked files
dvc status
```

### Storage

Development uses a local DVC remote. The `dvc_storage/` directory in your project is bind-mounted into all Airflow containers at `/opt/airflow/dvc_storage` — this is where `dvc push` writes, and it persists across `docker compose down/up` cycles.

For production, swap to GCS:

```bash
dvc remote add -d gcs_storage gs://courtaccess-forms
```

---

## Testing

**66 unit tests** across 12 test classes, all using mocked network calls (no real HTTP requests).

### Run Tests

```bash
uv pip install pytest requests playwright
uv run pytest tests/ -v
```

### Test Coverage

| Test Class | Tests | What It Covers |
|-----------|-------|---------------|
| `TestCatalogHelpers` | 7 | Load/save roundtrip, find by URL/hash |
| `TestSlugFromUrl` | 4 | URL slug extraction edge cases |
| `TestSha256` | 3 | Hash correctness and determinism |
| `TestFileHelpers` | 6 | Save original/translation, path conventions |
| `TestMergeAppearances` | 4 | Division deduplication, multi-division merge |
| `TestScenarioA` | 8 | New form: catalog entry, versions, appearances, translations, disk write |
| `TestScenarioB` | 7 | Updated form: version increment, old preserved, translations |
| `TestScenarioC` | 4 | Deleted form: archived status, versions/appearances preserved |
| `TestScenarioD` | 5 | Renamed form: name/URL/slug updated, no pretranslation |
| `TestScenarioE` | 4 | No change: timestamp only, version/status unchanged |
| `TestDownloadPdf` | 5 | 200/404/500/network error/403 Playwright fallback |
| `TestRunScrape` | 9 | Integration: counts, appearances merge, translations, empty scrape |

---

## Pipeline Flow Optimization

### Optimizations Implemented

1. **Single browser session per department** — Playwright opens one browser per department page and downloads all PDFs within that session, instead of launching a new browser for each PDF.

2. **Batch downloading with rate limiting** — PDFs are downloaded in batches of 10 with 15-second sleeps between batches, preventing mass.gov rate limiting.

3. **URL deduplication before processing** — The same form URL appearing on multiple department pages is only downloaded once. Appearances are tracked separately.

4. **Lightweight intermediate tasks** — Preprocessing, validation, anomaly detection, and bias detection are fast tasks (~seconds) that don't block the pipeline. The bottleneck is the scraping task (~20-40 min).

5. **Version-based storage** — Each version gets its own directory (`forms/{id}/v{n}/`). No file copying or archiving needed on updates — old versions stay untouched.

6. **DVC persist flag** — The `forms/` directory uses `persist: true` in `dvc.yaml`, so DVC doesn't delete existing PDFs before re-running the pipeline.

### Gantt Chart Analysis

After running the DAG, view the Gantt chart in the Airflow UI:

**DAG run → Gantt tab**

*(Add screenshot here after running the DAG)*

**Expected distribution:**
- `scrape_and_classify`: ~20-40 minutes (95%+ of total runtime — network I/O bound)
- `preprocess_data`: ~2-5 seconds
- `validate_catalog`: ~1-3 seconds
- `detect_anomalies`: ~1-2 seconds
- `detect_bias`: ~1-2 seconds
- `trigger_pretranslation`: <1 second
- `log_summary`: <1 second
- `dvc_version_data`: ~5-15 seconds

The scraping task dominates because of rate-limit sleeps (60s before downloading each department + 15s between batches). This is intentional — aggressive scraping would get blocked by mass.gov.

---

## JSON Catalog Schema

Each form in `form_catalog.json` follows this structure:

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

This structure maps directly to SQL tables for future database migration (currently everything is running locally using JSON files):
- Top-level fields → `form_catalog` table
- `appearances[]` → `form_appearances` table (many-to-many with divisions)
- `versions[]` → `form_versions` table (append-only version history)

---

## Court Departments Scraped

| Department | Source URL |
|-----------|-----------|
| Appeals Court | mass.gov/lists/appeals-court-forms |
| Boston Municipal Court | mass.gov/lists/boston-municipal-court-forms |
| District Court | mass.gov/lists/district-court-forms |
| Housing Court | mass.gov/lists/housing-court-forms |
| Juvenile Court | mass.gov/lists/juvenile-court-forms |
| Land Court | mass.gov/lists/land-court-forms |
| Superior Court | mass.gov/lists/superior-court-forms |
| Attorney Forms | mass.gov/lists/attorney-court-forms |
| Criminal Matter Forms | mass.gov/lists/court-forms-for-criminal-matters |
| Criminal Records Forms | mass.gov/lists/court-forms-for-criminal-records |
| Trial Court eFiling Forms | mass.gov/lists/trial-court-efiling-forms |

---

## Error Handling & Logging

**Logging:** Python's `logging` module throughout all modules, routed through Airflow's built-in logging system. Visible in the Airflow UI (task → Logs tab).

**Error handling by layer:**

| Layer | How Errors Are Handled |
|-------|----------------------|
| **Network** | `requests` failures caught, 403 falls back to Playwright, transient errors do NOT archive forms |
| **Download** | Individual PDF failures logged and skipped — one bad download doesn't stop the batch |
| **Scraping** | Per-department try/except — one department failing doesn't stop the others |
| **Preprocessing** | Per-file checks — issues flagged but processing continues |
| **Validation** | Errors counted and reported — pipeline continues to generate metrics |
| **Anomaly detection** | Missing previous metrics handled gracefully (first run) |
| **DVC** | Command failures logged as warnings — data is still saved locally even if push fails |
| **Airflow** | DAG retries once on failure (60s delay), configurable via `DEFAULT_ARGS` |

---

## Reproducibility

### On Any Machine

```bash
git clone https://github.com/SunnyYadav16/court-access-ai.git
cd court-access-ai/data_pipeline
cp .env.example .env
# Add keys to .env (see Setup Instructions)
docker compose build
docker compose up -d
```

DVC is initialized automatically. All dependencies are in the Docker image. No local Python environment needed to run the pipeline.

### Restore Previous Data

```bash
# Pull the latest versioned data
dvc pull

# Or checkout a specific historical version
git log --oneline                    # Find the commit
git checkout <commit-hash>
dvc pull                             # Restores that version's data
```

### Run Tests Without Docker

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv run pytest tests/ -v
```
