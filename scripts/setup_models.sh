#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/setup_models.sh — Download all models and track with DVC
#
# This script downloads every model used by CourtAccess AI, places them
# in models/<name>/, runs `dvc add` to create real pointer files, and
# pushes weights to GCS via `dvc push`.
#
# Prerequisites:
#   - Python 3.11+ with pip
#   - dvc[gs] installed:  pip install "dvc[gs]"
#   - gcloud CLI authenticated:  gcloud auth application-default login
#   - GCS bucket exists:  gs://courtaccess-ai-models
#   - .dvc/config points at that bucket (already configured)
#
# Usage:
#   chmod +x scripts/setup_models.sh
#   ./scripts/setup_models.sh          # download all + dvc add + dvc push
#   ./scripts/setup_models.sh --skip-push   # download + dvc add only (no GCS upload)
#
# After running:
#   git add models/*.dvc models/.gitignore
#   git commit -m "feat: add real DVC pointers for all model weights"
#   git push
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

SKIP_PUSH=false
if [[ "${1:-}" == "--skip-push" ]]; then
    SKIP_PUSH=true
fi

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }

# ── Python interpreter ────────────────────────────────────────────────────────
# Use `uv run python` to ensure we always use the project's Python 3.11 venv,
# not the system python3 (which may be 3.12/3.13 and can't build blis/spaCy).
if command -v uv &>/dev/null; then
    PYTHON="uv run python"
    log "Using uv-managed Python: $(uv run python --version)"
elif [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
    log "Using venv Python: $(.venv/bin/python --version)"
else
    PYTHON="python3"
    warn "uv and .venv not found — using system python3 ($(python3 --version)). spaCy may fail on Python 3.13."
fi

# ── Ensure we're in project root ──────────────────────────────────────────────
if [[ ! -f "pyproject.toml" ]]; then
    err "Run this from the project root (where pyproject.toml lives)."
    exit 1
fi

# ── Check prerequisites ───────────────────────────────────────────────────────
command -v dvc >/dev/null 2>&1 || { err "dvc not found. Install: pip install 'dvc[gs]'"; exit 1; }
command -v python3 >/dev/null 2>&1 || { err "python3 not found."; exit 1; }

mkdir -p models

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 1: Whisper Large V3 (ASR — speech-to-text)
# Size: ~3 GB (CTranslate2 format for faster-whisper)
# Used by: courtaccess/speech/transcribe.py
# Container path: /opt/models/whisper-large-v3
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 1/6: Whisper Large V3 (faster-whisper CTranslate2 format)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "models/whisper-large-v3" && -f "models/whisper-large-v3/model.bin" ]]; then
    log "Whisper already downloaded — skipping."
else
    log "Downloading Whisper Large V3 (CTranslate2 format)..."
    $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'Systran/faster-whisper-large-v3',
    local_dir='models/whisper-large-v3',
    local_dir_use_symlinks=False,
)
print('Done.')
"
    log "Whisper Large V3 downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 2: NLLB-200 Distilled 1.3B (Translation)
# Size: ~600 MB (CTranslate2 float16 quantized)
# Used by: courtaccess/core/translation.py
# Container path: /opt/models/nllb-200-distilled-1.3B-ct2
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 2/6: NLLB-200 Distilled 1.3B (CTranslate2 float16)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "models/nllb-200-distilled-1.3B-ct2" && -f "models/nllb-200-distilled-1.3B-ct2/model.bin" ]]; then
    log "NLLB already downloaded — skipping."
else
    log "Downloading NLLB-200 Distilled 1.3B (CTranslate2)..."
    $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'JustFrederik/nllb-200-distilled-1.3B-ct2-float16',
    local_dir='models/nllb-200-distilled-1.3B-ct2',
    local_dir_use_symlinks=False,
)
print('Done.')
"
    log "NLLB-200 downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 3: Piper TTS — Spanish (es_MX)
# Size: ~65 MB (ONNX voice model + JSON config)
# Used by: courtaccess/speech/tts.py
# Container path: /opt/models/piper-tts-es
#
# Piper voices are distributed as .onnx + .onnx.json pairs.
# Browse available voices: https://huggingface.co/rhasspy/piper-voices/tree/main/es/es_MX
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 3/6: Piper TTS Spanish (es_MX-claude-high)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "models/piper-tts-es" && $(ls models/piper-tts-es/*.onnx 2>/dev/null | wc -l) -gt 0 ]]; then
    log "Piper TTS Spanish already downloaded — skipping."
else
    mkdir -p models/piper-tts-es
    log "Downloading Piper TTS Spanish voice..."
    $PYTHON -c "
from huggingface_hub import hf_hub_download
import os

# Download the ONNX model + config for es_MX claude high quality voice
# If this specific voice is unavailable, fall back to es_MX-ald-medium
voices_to_try = [
    ('es/es_MX/claude/high', 'es_MX-claude-high'),
    ('es/es_MX/ald/medium', 'es_MX-ald-medium'),
    ('es/es_ES/davefx/medium', 'es_ES-davefx-medium'),
]

downloaded = False
for subdir, name in voices_to_try:
    try:
        for ext in ['.onnx', '.onnx.json']:
            hf_hub_download(
                'rhasspy/piper-voices',
                filename=f'{subdir}/{name}{ext}',
                local_dir='models/piper-tts-es',
                local_dir_use_symlinks=False,
            )
        # Flatten: move files from nested subdirectory to models/piper-tts-es/
        import shutil, glob
        for f in glob.glob(f'models/piper-tts-es/{subdir}/{name}*'):
            shutil.move(f, f'models/piper-tts-es/{os.path.basename(f)}')
        # Clean up nested dirs
        top = subdir.split('/')[0]
        if os.path.isdir(f'models/piper-tts-es/{top}'):
            shutil.rmtree(f'models/piper-tts-es/{top}')
        print(f'Downloaded voice: {name}')
        downloaded = True
        break
    except Exception as e:
        print(f'Voice {name} not available: {e}, trying next...')

if not downloaded:
    print('WARNING: No Piper ES voice found. Create a placeholder.')
    with open('models/piper-tts-es/README.md', 'w') as f:
        f.write('# Placeholder — download Piper ES voice manually\n')
"
    log "Piper TTS Spanish done."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 4: Piper TTS — Portuguese (pt_BR)
# Size: ~50 MB
# Used by: courtaccess/speech/tts.py
# Container path: /opt/models/piper-tts-pt
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 4/6: Piper TTS Portuguese (pt_BR-faber-medium)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "models/piper-tts-pt" && $(ls models/piper-tts-pt/*.onnx 2>/dev/null | wc -l) -gt 0 ]]; then
    log "Piper TTS Portuguese already downloaded — skipping."
else
    mkdir -p models/piper-tts-pt
    log "Downloading Piper TTS Portuguese voice..."
    $PYTHON -c "
from huggingface_hub import hf_hub_download
import os, shutil, glob

voices_to_try = [
    ('pt/pt_BR/faber/medium', 'pt_BR-faber-medium'),
    ('pt/pt_PT/tugao/medium', 'pt_PT-tugao-medium'),
]

downloaded = False
for subdir, name in voices_to_try:
    try:
        for ext in ['.onnx', '.onnx.json']:
            hf_hub_download(
                'rhasspy/piper-voices',
                filename=f'{subdir}/{name}{ext}',
                local_dir='models/piper-tts-pt',
                local_dir_use_symlinks=False,
            )
        for f in glob.glob(f'models/piper-tts-pt/{subdir}/{name}*'):
            shutil.move(f, f'models/piper-tts-pt/{os.path.basename(f)}')
        top = subdir.split('/')[0]
        if os.path.isdir(f'models/piper-tts-pt/{top}'):
            shutil.rmtree(f'models/piper-tts-pt/{top}')
        print(f'Downloaded voice: {name}')
        downloaded = True
        break
    except Exception as e:
        print(f'Voice {name} not available: {e}, trying next...')

if not downloaded:
    print('WARNING: No Piper PT voice found. Create a placeholder.')
    with open('models/piper-tts-pt/README.md', 'w') as f:
        f.write('# Placeholder — download Piper PT voice manually\n')
"
    log "Piper TTS Portuguese done."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 5: spaCy en_core_web_lg (NER for PII + proper noun protection)
# Size: ~560 MB
# Used by: courtaccess/core/translation.py (Step 2: proper noun protection)
# Install method: pip install + copy to models/ for DVC tracking
#
# NOTE: spaCy models are normally pip-installed. We ALSO track the
# downloaded wheel in models/ so DVC versions it alongside other weights.
# The container pip-installs it at build time from the local copy.
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 5/6: spaCy en_core_web_lg"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ -d "models/spacy-en-core-web-lg" && $(ls models/spacy-en-core-web-lg/ 2>/dev/null | wc -l) -gt 2 ]]; then
    log "spaCy en_core_web_lg already downloaded — skipping."
else
    log "Downloading spaCy en_core_web_lg..."
    # Install the model into the current Python env
    # Try spacy download first; fall back to direct wheel install via uv pip
    # NEVER use bare `pip` here — it routes to the system Python, not the uv venv.
    $PYTHON -m spacy download en_core_web_lg 2>/dev/null \
        || uv pip install "https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl"

    # Copy the installed model data to models/ for DVC tracking
    $PYTHON -c "
import spacy
import shutil
import os

nlp = spacy.load('en_core_web_lg')
model_path = os.path.dirname(nlp.path)

# Copy the entire model directory
dest = 'models/spacy-en-core-web-lg'
if os.path.exists(dest):
    shutil.rmtree(dest)
shutil.copytree(str(nlp.path), dest)
print(f'Copied spaCy model from {nlp.path} to {dest}')
"
    log "spaCy en_core_web_lg done."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 6: TFDV Baseline Stats (monitoring reference statistics)
# Size: ~50 KB (generated, not downloaded)
# Used by: courtaccess/monitoring/drift.py
#
# This is NOT a model download — it's a generated artifact.
# We generate baseline statistics from the current form catalog
# using TFDV, then DVC-track the output so it's versioned.
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  MODEL 6/6: TFDV Baseline Stats (generated artifact)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

mkdir -p models/tfdv-baseline-stats
if [[ -f "models/tfdv-baseline-stats/baseline_stats.json" ]]; then
    log "TFDV baseline stats already exist — skipping."
else
    log "Generating TFDV baseline statistics..."
    $PYTHON -c "
import json
import os
from datetime import datetime

# Generate baseline statistics structure
# In production, this would use tensorflow_data_validation to compute
# real statistics from the form catalog. For now, we create the schema
# that drift.py and anomaly.py will validate against.

baseline = {
    'generated_at': datetime.utcnow().isoformat() + 'Z',
    'generator': 'scripts/setup_models.sh',
    'dataset': 'form_catalog',
    'num_examples': 0,  # populated after first real scraper run
    'features': {
        'form_id': {'type': 'STRING', 'presence': {'min_fraction': 1.0}},
        'form_name': {'type': 'STRING', 'presence': {'min_fraction': 1.0}},
        'source_url': {'type': 'STRING', 'presence': {'min_fraction': 1.0}},
        'content_hash': {'type': 'STRING', 'presence': {'min_fraction': 1.0}},
        'status': {
            'type': 'STRING',
            'presence': {'min_fraction': 1.0},
            'domain': {'value': ['active', 'archived']},
        },
        'version': {
            'type': 'INT',
            'presence': {'min_fraction': 1.0},
            'int_domain': {'min': 1},
        },
        'last_checked': {'type': 'STRING', 'presence': {'min_fraction': 1.0}},
    },
    'thresholds': {
        'jensen_shannon_divergence': 0.1,
        'z_score_numeric_features': 3.0,
        'min_active_forms': 10,
        'max_form_drop_pct': 20,
    },
}

os.makedirs('models/tfdv-baseline-stats', exist_ok=True)
with open('models/tfdv-baseline-stats/baseline_stats.json', 'w') as f:
    json.dump(baseline, f, indent=2)

print('Baseline stats generated.')
"
    log "TFDV baseline done."
fi

# ══════════════════════════════════════════════════════════════════════════════
# NOTE ON LLAMA 4 MAVERICK
#
# Llama 4 Maverick is called via Vertex AI API — no local weights.
# It does NOT need a DVC-tracked directory or model download.
# The model endpoint is configured via env vars in config.py:
#   VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_MODEL_ID
#
# We remove the old llama4-scout-legal-review.dvc placeholder since
# it tracked prompt templates that don't need DVC versioning — they
# live in legal_review.py as code.
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  NOTE: Llama 4 Maverick — API only, no DVC tracking needed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log "Llama 4 Maverick runs via Vertex AI API (env: VERTEX_PROJECT_ID, VERTEX_MODEL_ID)."
log "No local weights to download or DVC-track."

if [[ -f "models/llama4-scout-legal-review.dvc" ]]; then
    warn "Removing old placeholder: models/llama4-scout-legal-review.dvc"
    rm -f models/llama4-scout-legal-review.dvc
fi

# ══════════════════════════════════════════════════════════════════════════════
# DVC ADD — Create real pointer files for all models
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DVC ADD — Creating real pointer files"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Remove old placeholder .dvc files (they have fake md5 hashes)
log "Removing old placeholder .dvc files..."
rm -f models/whisper-large-v3.dvc
rm -f models/nllb-200-distilled-1.3B-ct2.dvc
rm -f models/piper-tts-es.dvc
rm -f models/piper-tts-pt.dvc
rm -f models/spacy-en-core-web-lg.dvc
rm -f models/tfdv-baseline-stats.dvc

# DVC add each model directory — this computes real hashes
log "Running dvc add for each model..."
dvc add models/whisper-large-v3
dvc add models/nllb-200-distilled-1.3B-ct2
dvc add models/piper-tts-es
dvc add models/piper-tts-pt
dvc add models/spacy-en-core-web-lg
dvc add models/tfdv-baseline-stats

log "DVC pointer files created with real hashes."

# ══════════════════════════════════════════════════════════════════════════════
# DVC PUSH — Upload weights to GCS
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_PUSH" == "true" ]]; then
    warn "Skipping dvc push (--skip-push flag). Run 'dvc push' manually when ready."
else
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  DVC PUSH — Uploading to gs://courtaccess-ai-models"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    dvc push
    log "All model weights pushed to GCS."
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DONE — Model Setup Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Models tracked by DVC:"
echo "  models/whisper-large-v3.dvc          (~3 GB)   — ASR"
echo "  models/nllb-200-distilled-1.3B-ct2.dvc (~600 MB) — Translation"
echo "  models/piper-tts-es.dvc             (~65 MB)  — TTS Spanish"
echo "  models/piper-tts-pt.dvc             (~50 MB)  — TTS Portuguese"
echo "  models/spacy-en-core-web-lg.dvc     (~560 MB) — NER / PII"
echo "  models/tfdv-baseline-stats.dvc      (~50 KB)  — Monitoring baseline"
echo ""
echo "NOT tracked by DVC (API-only, no local weights):"
echo "  Llama 4 Maverick — via Vertex AI (VERTEX_PROJECT_ID env var)"
echo ""
echo "Next steps:"
echo "  git add models/*.dvc models/.gitignore"
echo "  git commit -m 'feat: add real DVC pointers for all model weights'"
echo "  git push"
echo ""
echo "To restore on a fresh machine:"
echo "  git clone <repo> && cd court-access-ai"
echo "  pip install 'dvc[gs]'"
echo "  dvc pull   # downloads all weights from GCS"
echo ""
