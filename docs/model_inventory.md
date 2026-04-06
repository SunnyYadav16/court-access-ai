# CourtAccess AI — Model Inventory

## How Models Are Stored and Served

```
┌─────────────────────┐    dvc push     ┌──────────────────────────┐
│  Developer Laptop   │ ──────────────→ │  GCS Bucket              │
│                     │                 │  gs://courtaccess-ai-    │
│  models/            │    dvc pull     │      models/             │
│    whisper-large-v3/│ ←────────────── │                          │
│    nllb-200-.../    │                 │  (permanent, versioned)  │
│    piper-tts-es/    │                 └──────────┬───────────────┘
│    piper-tts-pt/    │                            │
│    spacy-.../       │                            │ gsutil cp (init container)
│    tfdv-.../        │                            │
└─────────────────────┘                            ▼
                                        ┌──────────────────────────┐
                                        │  GKE Pod                 │
                                        │                          │
                                        │  /opt/models/            │
                                        │    whisper-large-v3/     │
                                        │    nllb-200-.../         │
                                        │    piper-tts-es/         │
                                        │    piper-tts-pt/         │
                                        │    spacy-.../            │
                                        └──────────────────────────┘

Llama 4 Maverick: NO local weights — called via Vertex AI API
```

## Model Details

### 1. Whisper Large V3 (ASR)

| Field | Value |
|---|---|
| **Purpose** | Speech-to-text for real-time courtroom interpretation |
| **Source** | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) |
| **Format** | CTranslate2 (INT8 quantized for faster-whisper) |
| **Size** | ~3 GB |
| **DVC file** | `models/whisper-large-v3.dvc` |
| **Container path** | `/opt/models/whisper-large-v3` |
| **Config env** | `WHISPER_MODEL_PATH` |
| **Used by** | `courtaccess/speech/transcribe.py` |
| **Toggle** | `USE_REAL_TRANSCRIPTION=true` |

### 2. NLLB-200 Distilled 1.3B (Translation)

| Field | Value |
|---|---|
| **Purpose** | English ↔ Spanish/Portuguese translation |
| **Source** | [JustFrederik/nllb-200-distilled-1.3B-ct2-float16](https://huggingface.co/JustFrederik/nllb-200-distilled-1.3B-ct2-float16) |
| **Format** | CTranslate2 float16 |
| **Size** | ~600 MB |
| **DVC file** | `models/nllb-200-distilled-1.3B-ct2.dvc` |
| **Container path** | `/opt/models/nllb-200-distilled-1.3B-ct2` |
| **Config env** | `NLLB_MODEL_PATH` |
| **Used by** | `courtaccess/core/translation.py` |
| **Toggle** | `USE_REAL_TRANSLATION=true` |

### 3. Piper TTS — Spanish (Text-to-Speech)

| Field | Value |
|---|---|
| **Purpose** | Generate spoken Spanish audio from translated text |
| **Source** | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) (es_MX) |
| **Format** | ONNX + JSON config |
| **Size** | ~65 MB |
| **DVC file** | `models/piper-tts-es.dvc` |
| **Container path** | `/opt/models/piper-tts-es` |
| **Config env** | `PIPER_TTS_ES_PATH` |
| **Used by** | `courtaccess/speech/tts.py` |
| **Toggle** | `USE_REAL_TTS=true` |

### 4. Piper TTS — Portuguese (Text-to-Speech)

| Field | Value |
|---|---|
| **Purpose** | Generate spoken Portuguese audio from translated text |
| **Source** | [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) (pt_BR) |
| **Format** | ONNX + JSON config |
| **Size** | ~50 MB |
| **DVC file** | `models/piper-tts-pt.dvc` |
| **Container path** | `/opt/models/piper-tts-pt` |
| **Config env** | `PIPER_TTS_PT_PATH` |
| **Used by** | `courtaccess/speech/tts.py` |
| **Toggle** | `USE_REAL_TTS=true` |

### 5. spaCy en_core_web_lg (NER / PII Detection)

| Field | Value |
|---|---|
| **Purpose** | Named entity recognition for proper noun protection during translation + PII detection |
| **Source** | [explosion/spacy-models](https://github.com/explosion/spacy-models) |
| **Format** | spaCy model package |
| **Size** | ~560 MB |
| **DVC file** | `models/spacy-en-core-web-lg.dvc` |
| **Container path** | pip-installed in container; DVC tracks the version |
| **Used by** | `courtaccess/core/translation.py` (Step 2: NER), `courtaccess/core/pii_scrub.py` |
| **Toggle** | Always loaded (needed for proper noun protection) |

### 6. TFDV Baseline Stats (Monitoring Artifact)

| Field | Value |
|---|---|
| **Purpose** | Reference statistics for drift/anomaly detection |
| **Format** | JSON (schema + thresholds) |
| **Size** | ~50 KB |
| **DVC file** | `models/tfdv-baseline-stats.dvc` |
| **Used by** | `courtaccess/monitoring/drift.py`, `courtaccess/monitoring/anomaly.py` |
| **Regenerated** | After each scraper run when drift is detected |

### 7. Llama 4 Maverick (Legal Review) — API ONLY

| Field | Value |
|---|---|
| **Purpose** | Legal terminology verification + document classification |
| **Served via** | Vertex AI API (Google Cloud) — no local weights |
| **DVC file** | None — API-hosted model |
| **Config env** | `VERTEX_PROJECT_ID`, `VERTEX_LOCATION`, `VERTEX_LEGAL_LLM_MODEL` |
| **Used by** | `courtaccess/core/legal_review.py`, `courtaccess/core/classify_document.py` |
| **Toggle** | `USE_VERTEX_LEGAL_REVIEW=true` |
| **Fallback** | Stub mode returns "OK" with 0.95 confidence |

## Setup Commands

```bash
# First-time setup (download all models + push to GCS)
./scripts/setup_models.sh

# Restore on a fresh machine
dvc pull

# Update a specific model
# (e.g., new Whisper version released)
rm -rf models/whisper-large-v3
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-large-v3', local_dir='models/whisper-large-v3')"
dvc add models/whisper-large-v3
dvc push
git add models/whisper-large-v3.dvc
git commit -m "chore: update whisper to latest version"

# Rollback to previous model version
git log -- models/whisper-large-v3.dvc   # find the commit
git checkout <old-commit> -- models/whisper-large-v3.dvc
dvc checkout models/whisper-large-v3     # restores old weights from cache
```
