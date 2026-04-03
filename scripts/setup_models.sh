#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/setup_models.sh — Upload all CourtAccess AI models to GCS via DVC
#
# Run this ONCE (or once per model version update) from the project root
# on a machine with GCS write access.  Teammates never run this script —
# they run `dvc pull` instead.
#
# What this script does, in order:
#   1.  Downloads each model from its canonical source (HuggingFace / GitHub)
#       into the models/ directory.
#   2.  Removes the old placeholder .dvc files (which had fake/stale hashes).
#   3.  Runs `dvc add` on each model directory to compute real md5 hashes
#       and write fresh .dvc pointer files.
#   4.  Runs `dvc push` to upload all model blobs to gs://courtaccess-ai-models.
#
# After this script completes, commit the updated .dvc files:
#   git add models/*.dvc models/.gitignore
#   git commit -m "feat: real DVC pointers for all model weights"
#   git push
#
# ── Models managed by this script (stored in GCS) ────────────────────────────
#   1. Whisper Large V3       ~3 GB    courtaccess/speech/transcribe.py
#   2. NLLB-200 1.3B ct2      ~600 MB  courtaccess/core/translation.py
#   3. Piper TTS Spanish       ~65 MB  courtaccess/speech/tts.py
#   4. Piper TTS Portuguese    ~50 MB  courtaccess/speech/tts.py
#   5. Piper TTS English       ~40 MB  courtaccess/speech/tts.py
#   6. Silero VAD v4           ~2 MB   courtaccess/speech/vad.py
#
# ── Models NOT managed here (not in GCS) ─────────────────────────────────────
#   spaCy en_core_web_lg  — pip-installed in Dockerfile (python -m spacy download)
#   PaddleOCR / Qwen      — pip-installed; weights auto-cached by PaddleOCR
#                           on first inference inside the GPU container
#   Llama 4 Scout         — Vertex AI API; no local weights ever
#   TFDV baseline stats   — generated at runtime by the form scraper DAG
#
# ── Prerequisites ─────────────────────────────────────────────────────────────
#   pip install "dvc[gs]>=3.50.0"
#   gcloud auth application-default login
#   GCS bucket gs://courtaccess-ai-models must already exist
#   .dvc/config already points at that bucket (committed in this repo)
#
# ── Usage ─────────────────────────────────────────────────────────────────────
#   chmod +x scripts/setup_models.sh
#   ./scripts/setup_models.sh               # download + dvc add + dvc push
#   ./scripts/setup_models.sh --skip-push   # download + dvc add only (no GCS)
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Flags ─────────────────────────────────────────────────────────────────────
SKIP_PUSH=false
for arg in "$@"; do
    [[ "$arg" == "--skip-push" ]] && SKIP_PUSH=true
done

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()     { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
err()     { echo -e "${RED}[✗]${NC} $1"; }
section() {
    echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# ── Python interpreter ────────────────────────────────────────────────────────
# Prefer uv-managed Python (project's pinned 3.11 venv) so huggingface_hub
# and torch are available without polluting the system Python.
if command -v uv &>/dev/null; then
    PYTHON="uv run python"
    log "Using uv-managed Python: $(uv run python --version 2>&1)"
elif [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
    log "Using venv Python: $(.venv/bin/python --version 2>&1)"
else
    PYTHON="python3"
    warn "uv and .venv not found — using system python3 ($(python3 --version 2>&1))"
fi

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [[ ! -f "pyproject.toml" ]]; then
    err "Run this script from the project root (directory containing pyproject.toml)."
    exit 1
fi

if ! command -v dvc &>/dev/null; then
    err "dvc not found. Install it: pip install 'dvc[gs]>=3.50.0'"
    exit 1
fi

if [[ "$SKIP_PUSH" == "false" ]]; then
    if ! gcloud auth application-default print-access-token &>/dev/null 2>&1; then
        err "No GCS credentials found. Run: gcloud auth application-default login"
        exit 1
    fi
fi

mkdir -p models

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 1: Whisper Large V3 (ASR)
#
# Source:  Systran/faster-whisper-large-v3 on HuggingFace
#          This is the CTranslate2-converted version required by faster-whisper.
#          The raw OpenAI weights do NOT work — must be the Systran repo.
# Size:    ~3 GB
# Loaded:  courtaccess/speech/transcribe.py  →  WhisperModel(model_size_or_path)
# EnvVar:  WHISPER_MODEL_PATH → /opt/airflow/models/whisper-large-v3
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 1/6: Whisper Large V3 (faster-whisper CTranslate2 format)"

if [[ -d "models/whisper-large-v3" && -f "models/whisper-large-v3/model.bin" ]]; then
    log "Whisper Large V3 already present — skipping download."
else
    log "Downloading Whisper Large V3 from HuggingFace (Systran/faster-whisper-large-v3)..."
    $PYTHON - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="Systran/faster-whisper-large-v3",
    local_dir="models/whisper-large-v3",
    local_dir_use_symlinks=False,
)
print("Whisper Large V3 download complete.")
PYEOF
    log "Whisper Large V3 downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 2: NLLB-200 Distilled 1.3B (Translation)
#
# Source:  JustFrederik/nllb-200-distilled-1.3B-ct2-float16 on HuggingFace
#          CTranslate2 float16 quantized — required by ctranslate2.Translator().
#          The raw facebook/nllb-200-distilled-1.3B weights do NOT work directly.
# Size:    ~600 MB
# Loaded:  courtaccess/core/translation.py  →  ctranslate2.Translator(model_path)
# EnvVar:  NLLB_MODEL_PATH → /opt/airflow/models/nllb-200-distilled-1.3B-ct2
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 2/6: NLLB-200 Distilled 1.3B (CTranslate2 float16)"

if [[ -d "models/nllb-200-distilled-1.3B-ct2" && -f "models/nllb-200-distilled-1.3B-ct2/model.bin" ]]; then
    log "NLLB-200 already present — skipping download."
else
    log "Downloading NLLB-200 Distilled 1.3B ct2 from HuggingFace..."
    $PYTHON - <<'PYEOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="JustFrederik/nllb-200-distilled-1.3B-ct2-float16",
    local_dir="models/nllb-200-distilled-1.3B-ct2",
    local_dir_use_symlinks=False,
)
print("NLLB-200 download complete.")
PYEOF
    log "NLLB-200 downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 3: Piper TTS — Spanish
#
# Source:  rhasspy/piper-voices on HuggingFace (ONNX + JSON config pairs)
#          Tries voices in priority order; first available is used.
# Size:    ~65 MB
# Loaded:  courtaccess/speech/tts.py  →  PiperVoice.load(onnx_path)
# EnvVar:  PIPER_TTS_ES_PATH → /opt/airflow/models/piper-tts-es
#
# Files placed flat in models/piper-tts-es/:
#   <voice_name>.onnx
#   <voice_name>.onnx.json
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 3/6: Piper TTS Spanish"

if [[ -d "models/piper-tts-es" ]] && ls models/piper-tts-es/*.onnx &>/dev/null 2>&1; then
    log "Piper TTS Spanish already present — skipping download."
else
    mkdir -p models/piper-tts-es
    log "Downloading Piper TTS Spanish voice from HuggingFace..."
    $PYTHON - <<'PYEOF'
import os
import shutil
import glob
from huggingface_hub import hf_hub_download

# Priority order — first available wins.
# es_MX-claude-high is highest quality; es_ES-davefx-medium is the reliable fallback.
voices_to_try = [
    ("es/es_MX/claude/high",   "es_MX-claude-high"),
    ("es/es_MX/ald/medium",    "es_MX-ald-medium"),
    ("es/es_ES/davefx/medium", "es_ES-davefx-medium"),
]

dest = "models/piper-tts-es"
downloaded = False

for subdir, name in voices_to_try:
    try:
        for ext in [".onnx", ".onnx.json"]:
            hf_hub_download(
                repo_id="rhasspy/piper-voices",
                filename=f"{subdir}/{name}{ext}",
                local_dir=dest,
                local_dir_use_symlinks=False,
            )
        # Flatten nested HuggingFace subdirectory into dest/
        for f in glob.glob(f"{dest}/{subdir}/{name}*"):
            shutil.move(f, os.path.join(dest, os.path.basename(f)))
        # Remove the now-empty nested dirs
        top = subdir.split("/")[0]
        nested = os.path.join(dest, top)
        if os.path.isdir(nested):
            shutil.rmtree(nested)
        print(f"Downloaded Piper ES voice: {name}")
        downloaded = True
        break
    except Exception as exc:
        print(f"  Voice {name} unavailable ({exc}), trying next...")

if not downloaded:
    raise RuntimeError(
        "No Piper Spanish voice could be downloaded. "
        "Check https://huggingface.co/rhasspy/piper-voices for available es/ voices."
    )
PYEOF
    log "Piper TTS Spanish downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 4: Piper TTS — Portuguese
#
# Source:  rhasspy/piper-voices on HuggingFace
# Size:    ~50 MB
# Loaded:  courtaccess/speech/tts.py  →  PiperVoice.load(onnx_path)
# EnvVar:  PIPER_TTS_PT_PATH → /opt/airflow/models/piper-tts-pt
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 4/6: Piper TTS Portuguese"

if [[ -d "models/piper-tts-pt" ]] && ls models/piper-tts-pt/*.onnx &>/dev/null 2>&1; then
    log "Piper TTS Portuguese already present — skipping download."
else
    mkdir -p models/piper-tts-pt
    log "Downloading Piper TTS Portuguese voice from HuggingFace..."
    $PYTHON - <<'PYEOF'
import os
import shutil
import glob
from huggingface_hub import hf_hub_download

voices_to_try = [
    ("pt/pt_BR/faber/medium", "pt_BR-faber-medium"),
    ("pt/pt_PT/tugao/medium", "pt_PT-tugao-medium"),
]

dest = "models/piper-tts-pt"
downloaded = False

for subdir, name in voices_to_try:
    try:
        for ext in [".onnx", ".onnx.json"]:
            hf_hub_download(
                repo_id="rhasspy/piper-voices",
                filename=f"{subdir}/{name}{ext}",
                local_dir=dest,
                local_dir_use_symlinks=False,
            )
        for f in glob.glob(f"{dest}/{subdir}/{name}*"):
            shutil.move(f, os.path.join(dest, os.path.basename(f)))
        top = subdir.split("/")[0]
        nested = os.path.join(dest, top)
        if os.path.isdir(nested):
            shutil.rmtree(nested)
        print(f"Downloaded Piper PT voice: {name}")
        downloaded = True
        break
    except Exception as exc:
        print(f"  Voice {name} unavailable ({exc}), trying next...")

if not downloaded:
    raise RuntimeError(
        "No Piper Portuguese voice could be downloaded. "
        "Check https://huggingface.co/rhasspy/piper-voices for available pt/ voices."
    )
PYEOF
    log "Piper TTS Portuguese downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 5: Piper TTS — English
#
# Source:  rhasspy/piper-voices on HuggingFace
# Size:    ~40 MB
# Loaded:  courtaccess/speech/tts.py  →  PiperVoice.load(onnx_path)
# EnvVar:  PIPER_TTS_EN_PATH → /opt/airflow/models/piper-tts-en
#
# English voice is needed because TTSService loads all three languages
# (en, es, pt) at startup — missing en would cause startup failure.
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 5/6: Piper TTS English"

if [[ -d "models/piper-tts-en" ]] && ls models/piper-tts-en/*.onnx &>/dev/null 2>&1; then
    log "Piper TTS English already present — skipping download."
else
    mkdir -p models/piper-tts-en
    log "Downloading Piper TTS English voice from HuggingFace..."
    $PYTHON - <<'PYEOF'
import os
import shutil
import glob
from huggingface_hub import hf_hub_download

voices_to_try = [
    ("en/en_US/lessac/medium", "en_US-lessac-medium"),
    ("en/en_US/amy/medium",    "en_US-amy-medium"),
    ("en/en_GB/alan/medium",   "en_GB-alan-medium"),
]

dest = "models/piper-tts-en"
downloaded = False

for subdir, name in voices_to_try:
    try:
        for ext in [".onnx", ".onnx.json"]:
            hf_hub_download(
                repo_id="rhasspy/piper-voices",
                filename=f"{subdir}/{name}{ext}",
                local_dir=dest,
                local_dir_use_symlinks=False,
            )
        for f in glob.glob(f"{dest}/{subdir}/{name}*"):
            shutil.move(f, os.path.join(dest, os.path.basename(f)))
        top = subdir.split("/")[0]
        nested = os.path.join(dest, top)
        if os.path.isdir(nested):
            shutil.rmtree(nested)
        print(f"Downloaded Piper EN voice: {name}")
        downloaded = True
        break
    except Exception as exc:
        print(f"  Voice {name} unavailable ({exc}), trying next...")

if not downloaded:
    raise RuntimeError(
        "No Piper English voice could be downloaded. "
        "Check https://huggingface.co/rhasspy/piper-voices for available en/ voices."
    )
PYEOF
    log "Piper TTS English downloaded."
fi

# ══════════════════════════════════════════════════════════════════════════════
# MODEL 6: Silero VAD v4 (Voice Activity Detection)
#
# Source:  Official Silero release on GitHub
#          https://github.com/snakers4/silero-vad/releases
#          The .pt file is a TorchScript model loaded via torch.jit.load().
#          It is NOT downloaded via torch.hub at runtime — that requires internet
#          access on every cold start. Instead, we download it once here and
#          serve it from GCS.
# Size:    ~2 MB
# Loaded:  courtaccess/speech/vad.py  →  torch.jit.load(path)
# EnvVar:  SILERO_VAD_MODEL_PATH → /opt/airflow/models/silero-vad-v4/silero_vad.jit.pt
#
# Filename convention: silero_vad.jit.pt
#   The upstream file is named silero_vad.pt but we rename it .jit.pt to
#   make explicit that this is a TorchScript artifact, not a state_dict.
# ══════════════════════════════════════════════════════════════════════════════
section "MODEL 6/6: Silero VAD v4"

if [[ -f "models/silero-vad-v4/silero_vad.jit.pt" ]]; then
    log "Silero VAD already present — skipping download."
else
    mkdir -p models/silero-vad-v4
    log "Downloading Silero VAD v4 from GitHub releases..."
$PYTHON - <<'PYEOF'
import os
import shutil
from pathlib import Path

dest_dir = Path("models/silero-vad-v4")
dest_dir.mkdir(parents=True, exist_ok=True)
dest = dest_dir / "silero_vad.jit.pt"

# The silero-vad pip package ships the JIT model file inside its package data.
# This is the correct approach now that the GitHub file structure has changed
# across v4/v5/v6 — importing from the installed package is always version-stable.
try:
    import silero_vad as _sv
    package_dir = Path(_sv.__file__).parent
    # The JIT file is at src/silero_vad/data/silero_vad.jit inside the package
    jit_candidates = list(package_dir.rglob("silero_vad.jit"))
    if not jit_candidates:
        raise FileNotFoundError(f"silero_vad.jit not found inside package at {package_dir}")
    src_file = jit_candidates[0]
    shutil.copy2(src_file, dest)
    print(f"Copied silero_vad.jit from package: {src_file} -> {dest}")
except ImportError:
    raise RuntimeError(
        "silero-vad package not installed. "
        "Add 'silero-vad' to pyproject.toml dependencies or run: pip install silero-vad"
    )

# Verify
import torch
model = torch.jit.load(str(dest), map_location="cpu")
model.eval()
print(f"Silero VAD loaded and verified OK — saved to {dest}")
PYEOF
    log "Silero VAD v4 downloaded and verified."
fi

# ══════════════════════════════════════════════════════════════════════════════
# Llama 4 Scout — no download needed
#
# Runs entirely via the Vertex AI MaaS API (us-east5).
# Configured through env vars: VERTEX_PROJECT_ID, VERTEX_LOCATION,
# VERTEX_LEGAL_LLM_MODEL.  No local weights, no DVC tracking.
# ══════════════════════════════════════════════════════════════════════════════
section "NOTE: Llama 4 Scout — Vertex AI API only, nothing to download"
log "Llama 4 Scout is served via Vertex AI. No local weights to manage."

# ══════════════════════════════════════════════════════════════════════════════
# DVC ADD
#
# Removes the old placeholder .dvc files (fake hashes from before real weights
# existed) and replaces them with real pointer files computed from the
# just-downloaded model directories.
#
# `dvc add <dir>` does three things:
#   1. Computes md5 of every file in the directory.
#   2. Copies the files into the local DVC cache (.dvc/cache/).
#   3. Writes models/<name>.dvc with the root md5, total size, and nfiles.
#   4. Adds models/<name> to models/.gitignore so the weights are never
#      committed to Git.
# ══════════════════════════════════════════════════════════════════════════════
section "DVC ADD — computing hashes and writing pointer files"

log "Removing stale placeholder .dvc files..."
rm -f models/whisper-large-v3.dvc
rm -f models/nllb-200-distilled-1.3B-ct2.dvc
rm -f models/piper-tts-es.dvc
rm -f models/piper-tts-pt.dvc
rm -f models/piper-tts-en.dvc
rm -f models/silero-vad-v4.dvc
# These two are no longer GCS-managed — delete them so dvc pull stops
# trying to fetch them from the bucket.
rm -f models/spacy-en-core-web-lg.dvc
rm -f models/tfdv-baseline-stats.dvc

log "Running dvc add for each model..."
dvc add models/whisper-large-v3
dvc add models/nllb-200-distilled-1.3B-ct2
dvc add models/piper-tts-es
dvc add models/piper-tts-pt
dvc add models/piper-tts-en
dvc add models/silero-vad-v4

log "DVC pointer files written with real hashes."
echo ""
log "Pointer files created:"
for f in models/whisper-large-v3.dvc \
         models/nllb-200-distilled-1.3B-ct2.dvc \
         models/piper-tts-es.dvc \
         models/piper-tts-pt.dvc \
         models/piper-tts-en.dvc \
         models/silero-vad-v4.dvc; do
    if [[ -f "$f" ]]; then
        size=$(grep "size:" "$f" | awk '{print $2}')
        log "  $f  (size: ${size} bytes)"
    else
        warn "  $f — NOT FOUND (dvc add may have failed)"
    fi
done

# ══════════════════════════════════════════════════════════════════════════════
# DVC PUSH
#
# Uploads all locally cached model blobs to gs://courtaccess-ai-models.
# DVC stores blobs content-addressed under files/md5/<ab>/<rest_of_hash>
# so the bucket structure is opaque but fully reproducible from the .dvc files.
#
# Skip with --skip-push if you want to verify locally before uploading.
# ══════════════════════════════════════════════════════════════════════════════
section "DVC PUSH — uploading to gs://courtaccess-ai-models"

if [[ "$SKIP_PUSH" == "true" ]]; then
    warn "--skip-push set: skipping dvc push. Run 'dvc push' manually when ready."
else
    log "Pushing all model blobs to GCS..."
    dvc push
    log "All models pushed to gs://courtaccess-ai-models."
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
section "DONE"
echo ""
echo "  Models now in GCS (tracked by DVC):"
echo "    models/whisper-large-v3.dvc           ~3 GB    ASR"
echo "    models/nllb-200-distilled-1.3B-ct2.dvc ~600 MB  Translation"
echo "    models/piper-tts-es.dvc               ~65 MB   TTS Spanish"
echo "    models/piper-tts-pt.dvc               ~50 MB   TTS Portuguese"
echo "    models/piper-tts-en.dvc               ~40 MB   TTS English"
echo "    models/silero-vad-v4.dvc              ~2 MB    Voice Activity Detection"
echo ""
echo "  Not in GCS (managed differently):"
echo "    spaCy en_core_web_lg  — Dockerfile: python -m spacy download en_core_web_lg"
echo "    PaddleOCR / Qwen      — pip-installed; weights auto-cached on first inference"
echo "    Llama 4 Scout         — Vertex AI API (no local weights)"
echo "    TFDV baseline stats   — generated at runtime by form scraper DAG"
echo ""
echo "  Next steps:"
echo "    git add models/*.dvc models/.gitignore"
echo "    git commit -m 'feat: real DVC pointers for all model weights'"
echo "    git push"
echo ""
echo "  To restore on any machine after this commit:"
echo "    git clone <repo> && cd court-access-ai"
echo "    pip install 'dvc[gs]>=3.50.0'"
echo "    gcloud auth application-default login"
echo "    dvc pull"
echo "    docker compose up"
echo ""
