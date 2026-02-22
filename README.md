# CourtAccess AI

**Real-time speech and document translation system for the Massachusetts Trial Court**

CourtAccess AI is an MLOps-driven platform that provides real-time courtroom interpretation and legal document translation for non-English speakers, primarily Spanish and Portuguese, within the Massachusetts Trial Court system. The system uses pre-trained AI models orchestrated through automated pipelines, with continuous monitoring, drift detection, and version control.

---

## The Problem

Massachusetts courts face a systemic language access crisis. Approximately 45% of scheduled interpreters fail to appear for hearings, causing delays that effectively deny justice to Limited English Proficient (LEP) individuals. The shortage is most acute for non-Spanish languages, and the cost of agency interpreters runs 3x higher than staff interpreters. Court forms, signage, and processes remain largely English-only, creating barriers at every step of the legal process.

## What CourtAccess AI Does

The system provides two core capabilities:

**Real-Time Speech Translation.** Court officials initiate a live session. The system captures audio from the browser microphone, transcribes speech to text, translates between English and the target language, validates legal terminology, and plays back the translated audio, all in near real-time. This runs as a continuous WebSocket stream, not a batch job.

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

The system is built around **3 Airflow DAGs** and a **WebSocket streaming service**:

| Pipeline | Type | Trigger |
|----------|------|---------|
| Real-time speech translation | WebSocket stream (FastAPI) | Court official starts session |
| `document_pipeline_dag` | Airflow DAG | User uploads a PDF |
| `form_scraper_dag` | Airflow DAG (scheduled) | Weekly, every Monday |
| `form_pretranslation_dag` | Airflow DAG | Triggered by scraper when new/updated forms found |

The real-time pipeline is **not** an Airflow DAG. It runs as a continuous WebSocket connection inside FastAPI because real-time audio streaming requires persistent, low-latency connections, not batch orchestration.

### Authentication and Access Control

| Role | Access |
|------|--------|
| `public` | Document translation (upload + government forms) |
| `court_official` | Everything: real-time translation, document translation |
| `interpreter` | Real-time sessions, translation review interface |
| `admin` | Everything + monitoring dashboards, user management |

---

## AI Models

All models are used as pre-trained with no fine-tuning. The MLOps pipeline manages versioning, serving, monitoring, and updates of these models.

| Model | Role | Details |
|-------|------|---------|
| **Faster-Whisper Large V3** | Speech-to-text (ASR) | CTranslate2 INT8 quantization, ~60x realtime |
| **NLLB-200 Distilled 1.3B** | Translation (English ↔ Spanish/Portuguese) | Meta's No Language Left Behind model |
| **Llama 3.1** | Legal term validation + document classification | Via Groq API. Async for real-time, sync for documents |
| **PaddleOCR v3** | Printed text extraction from PDFs | DBNet detection + SVTR recognition, >95% accuracy |
| **Qwen2.5-VL** | Handwritten text extraction | Vision-language model, ~90% accuracy on handwriting |
| **Silero VAD v4** | Voice activity detection | Filters silence before ASR to prevent hallucinations |
| **Piper TTS** | Text-to-speech | Generates spoken audio in Spanish/Portuguese |
| **Microsoft Presidio** | PII detection | Custom recognizers for MA docket patterns, SSN, etc. |

---

## Document Translation Pipeline (document_pipeline_dag)

Step-by-step flow when a user uploads a PDF:

1. **FastAPI** receives upload + target language, creates session and translation request in Cloud SQL, saves PDF to GCS, triggers Airflow DAG via REST API
2. **TFDV** validates the file (format, size, corruption, page count)
3. **Llama 3.1** classifies first 3 pages and hard rejects non-legal documents
4. **PyMuPDF** splits PDF into individual page images
5. **PaddleOCR** extracts printed text with bounding box coordinates
6. **Qwen2.5-VL** extracts handwritten text from low-confidence regions
7. Printed and handwritten results merged by reading order
8. **Presidio** scans for PII (findings logged, not auto-redacted)
9. **NLLB-200** translates each text region independently
10. **Llama 3.1** validates legal terminology (synchronous)
11. **PyMuPDF** reconstructs PDF by redacting original text, inserting translated text, and preserving images/signatures
12. Translated PDF saved to GCS, signed URL generated, user downloads directly from GCS

Users can request a second language translation without re-uploading. The pipeline re-runs from step 4 (skipping validation and classification).

---

## Government Form Management

### Scraping (form_scraper_dag, weekly)

The scraper visits mass.gov court form pages, downloads each form, generates a SHA-256 content hash, and compares against the existing catalog. It handles five scenarios:

- **New form**: download, catalog, trigger translation
- **Updated form** (hash changed): archive old version, re-translate
- **Deleted form** (confirmed 404 only): mark as archived, keep in system with notice
- **Renamed form** (same hash): update name, no re-translation
- **No changes**: update last-checked timestamp

Temporary server errors (5xx, timeouts) do not trigger archival.

### Pre-Translation (form_pretranslation_dag)

New or updated forms are processed through: OCR → translate to Spanish → translate to Portuguese → legal review for each language → PDF reconstruction → store in GCS. All forms are flagged as "Machine-translated, pending human verification" until a court translator reviews and approves.

---

## Data Storage

| Storage | What | Retention |
|---------|------|-----------|
| GCS `courtaccess-uploads/` | User-uploaded PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-translated/` | Translated output PDFs | Auto-deleted after 24 hours |
| GCS `courtaccess-forms/` | Pre-translated government forms (+ archived versions) | Permanent |
| GCS `courtaccess-models/` | Pre-trained model weights (DVC tracked) | Permanent, versioned |
| Cloud SQL (PostgreSQL) | Sessions, translation requests, audit logs, form catalog, user accounts | Permanent (metadata only, no files) |

No raw audio is stored. Real-time sessions retain only session metadata and confidence scores.

All files encrypted at rest with Customer-Managed Encryption Keys (CMEK) via Cloud KMS.

---

## Database Schema

**`sessions`**: One per user interaction. Holds session type (realtime/document), target language, uploaded file GCS path, status, timestamps.

**`translation_requests`**: One per language translation. Links to a session. Holds target language, classification result, output file path, confidence scores, PII count, Llama correction count, processing time, signed URL with expiry, status.

**`audit_logs`**: Every action. User ID, session ID, request ID, action type, details JSON, timestamp. Required for court compliance.

**`form_catalog`**: Government forms library. Form name, source URL, SHA-256 content hash, version number, active/archived status, GCS paths for original + each translated language, human review flag, scrape timestamps.

Key relationship: One session → one uploaded file → multiple translation requests (one per language).

---

## MLOps: Monitoring, Drift Detection, and Versioning

### Monitoring

- **GCP Cloud Logging** captures all API requests, processing steps, errors, and model inference logs.
- **GCP Cloud Monitoring** tracks pod health, CPU/GPU utilization, API latency (p50/p95/p99), error rates, and storage usage. Alerts on pod crashes, latency spikes, high GPU utilization, and disk space.

### Drift Detection

- **Evidently AI** monitors model output quality over time. Tracks ASR confidence trends, translation confidence per language pair, Llama correction rate, and OCR confidence. If scores drift beyond baseline thresholds, alerts are triggered.

### Anomaly Detection

- **TFDV** validates incoming data against expected schemas. Catches corrupted files, empty OCR outputs, suspiciously short translations, malformed API requests, and error rate spikes.

### Model Versioning

- **DVC** tracks pre-trained model weight files in GCS. Each model has a `.dvc` pointer file committed to Git. Rollback: `git checkout <commit>` then `dvc pull`.
- **MLflow** serves as the deployment registry. Logs which model versions are in production, when they were deployed, and their observed performance metrics.

### Update Cycle

When drift is detected: admin investigates → downloads newer model version if needed → tracked in DVC → registered in MLflow → tested via pytest in GitHub Actions → deployed to GKE via Terraform → monitoring continues.

---

## CI/CD

Every code change goes through GitHub Actions:

1. **PR opened** → `test.yml` runs pytest (audio pipeline, document pipeline, classification, API, validation tests)
2. **PR merged** → `build.yml` builds Docker images, tags with Git commit hash, pushes to GCP Artifact Registry
3. **Release** → `deploy.yml` applies Terraform infrastructure changes, runs `kubectl rollout` to GKE with zero-downtime rolling updates. Failed deployments auto-rollback.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React |
| Backend API | FastAPI (REST + WebSocket) |
| Audio Capture | WebRTC |
| Orchestration | Apache Airflow (3 DAGs) |
| Compute | Google Kubernetes Engine (GKE) with GPU node pools |
| File Storage | Google Cloud Storage (GCS) with CMEK encryption |
| Database | Cloud SQL (PostgreSQL) |
| File Delivery | GCS Signed URLs (1-hour expiry) |
| Infrastructure as Code | Terraform |
| Containerization | Docker |
| CI/CD | GitHub Actions |
| Model Versioning | DVC + MLflow |
| Data Validation | TensorFlow Data Validation (TFDV) |
| Drift Detection | Evidently AI |
| PII Detection | Microsoft Presidio |
| Logging | Python logging → GCP Cloud Logging |
| Monitoring | GCP Cloud Monitoring |
| Testing | pytest |
| Form Scraping | Python requests + BeautifulSoup |

---

## Project Structure

```
/CourtAccess-AI
├── app/
│   ├── main.py                    # FastAPI + WebSocket endpoints
│   ├── auth.py                    # Authentication (OAuth2/JWT)
│   ├── models.py                  # SQLAlchemy models
│   ├── routes/
│   │   ├── realtime.py            # WebSocket real-time translation
│   │   ├── documents.py           # Document upload + translation
│   │   └── forms.py               # Government form browsing
│   └── frontend/                  # React app
├── dags/
│   ├── document_pipeline_dag.py   # DAG 1: User document translation
│   ├── form_pretranslation_dag.py # DAG 2: Translate new court forms
│   └── form_scraper_dag.py        # DAG 3: Weekly scrape mass.gov
├── scripts/
│   ├── capture_audio.py           # WebRTC audio handling
│   ├── voice_activity.py          # Silero VAD
│   ├── transcribe.py              # Faster-Whisper ASR
│   ├── translate_text.py          # NLLB-200 translation
│   ├── legal_review.py            # Llama 3.1 via Groq API
│   ├── classify_document.py       # Llama 3.1 document classifier
│   ├── speak_output.py            # Piper TTS
│   ├── ingest_document.py         # PyMuPDF page extraction
│   ├── ocr_printed.py             # PaddleOCR v3
│   ├── ocr_handwritten.py         # Qwen2.5-VL
│   ├── reconstruct_pdf.py         # PyMuPDF layout reconstruction
│   ├── validate_input.py          # TFDV validation
│   ├── pii_scrub.py               # Microsoft Presidio
│   ├── log_metadata.py            # Logging utility
│   └── scrape_forms.py            # mass.gov form scraper
├── monitoring/
│   ├── drift_detect.py            # Evidently AI
│   └── anomaly_detect.py          # TFDV anomaly checks
├── tests/
│   ├── test_audio_pipeline.py
│   ├── test_document_pipeline.py
│   ├── test_classification.py
│   ├── test_api.py
│   └── test_validation.py
├── infra/
│   ├── terraform/                 # GKE, GCS, Cloud SQL, KMS, IAM
│   └── k8s/manifests/             # Deployments, services, GPU configs
├── models/                        # DVC-tracked model weight pointers
│   ├── whisper-large-v3.dvc
│   ├── nllb-200-distilled-1.3b.dvc
│   ├── paddleocr-v3.dvc
│   ├── qwen2.5-vl.dvc
│   ├── silero-vad-v4.dvc
│   ├── piper-tts-es.dvc
│   └── piper-tts-pt.dvc
├── .github/workflows/
│   ├── test.yml                   # PR → pytest
│   ├── build.yml                  # Merge → Docker build → push
│   └── deploy.yml                 # Release → Terraform → GKE
├── Dockerfile
├── docker-compose.yml
├── dvc.yaml
├── requirements.txt
└── README.md
```

---

## Key Design Decisions

**Pre-trained models only, no fine-tuning.** All AI models are used off-the-shelf. The MLOps pipeline manages versioning, deployment, and monitoring, not training. This keeps the system simpler and the focus on pipeline reliability.

**Llama as a validation layer, not a translator.** NLLB-200 handles translation (fast, deterministic, purpose-built). Llama 3.1 reviews translations for legal accuracy after the fact. In real-time mode, Llama runs async so users aren't blocked. In document mode, it runs sync because accuracy matters more than speed.

**PDF-only uploads.** Restricting to PDF simplifies the pipeline with no image-to-PDF conversion needed, providing consistent input for OCR and reconstruction.

**3 Airflow DAGs, not 4.** Real-time speech translation runs as a WebSocket stream inside FastAPI, not as an Airflow DAG. Airflow is for batch workflows with defined start/end, and live audio streaming doesn't fit that model.

**Re-run OCR for second language, don't cache.** When a user requests a second language translation, the pipeline re-runs from ingestion rather than caching OCR output. One code path is simpler than two, and the ~10-15 seconds of extra processing is negligible compared to the complexity of managing intermediate cached files.

**Pre-translated government forms.** Court forms have official legal language that should be translated consistently. Pre-translating and human-verifying once is safer than translating on-the-fly every time, which could produce slightly different results.

**Signed URLs for file delivery.** Translated documents are served via GCS Signed URLs (1-hour expiry) so files are downloaded directly from cloud storage without passing through the API server. Secure, efficient, and stateless.

---
