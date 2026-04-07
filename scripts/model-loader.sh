#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/model-loader.sh — CourtAccess AI model loader (one-shot service)
#
# Runs as a dedicated Docker service that completes before any model-consuming
# service (api, airflow-scheduler, etc.) starts. Separates model loading from
# Airflow DB init so a model update never requires restarting the full stack.
#
# Modes (set via MODEL_LOADER_MODE env var):
#
#   local  (docker-compose.yml)
#     - .git / .dvc / models / dvc_storage are host bind mounts
#     - Configures a local fallback remote (writes to .dvc/config.local only,
#       never clobbers the committed .dvc/config GCS remote)
#     - Authenticates via GCP_DVC_CREDENTIALS file if present, else ADC
#     - Falls back to `dvc checkout` if `dvc pull` fails (uses local cache)
#
#   prod   (docker-compose.prod.yml)
#     - models/ is a named Docker volume (persists across restarts)
#     - Copies authoritative .dvc pointer files from /opt/airflow/dvc-pointers/
#       (image layer, never a volume mount) into the models/ volume to overwrite
#       any stale hashes from a previous image version
#     - Authenticates via VM service account ADC — no credentials file needed
#     - Runs `dvc pull --allow-missing`
#
# Targeted single-model update (prod):
#   docker compose -f docker-compose.prod.yml up model-loader --force-recreate
#   This re-runs the full pull. For a single model, pass its name as $1:
#   MODEL_TARGET=whisper-large-v3 docker compose ... up model-loader
#
# Sentinel file:
#   Writes models/.models-ready on success. docker-entrypoint.sh checks for
#   this file and skips its own DVC logic if found.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[model-loader]${NC} $1"; }
warn() { echo -e "${YELLOW}[model-loader]${NC} $1"; }
err()  { echo -e "${RED}[model-loader]${NC} $1"; }

MODE="${MODEL_LOADER_MODE:-local}"
DVC_ROOT="/opt/airflow"
SENTINEL="${DVC_ROOT}/models/.models-ready"
TARGET="${MODEL_TARGET:-}"   # optional: single model dir name (e.g. whisper-large-v3)

# ── Sentinel guarantee ────────────────────────────────────────────────────────
# Runs on ANY exit — normal completion, explicit `exit N`, or an unexpected
# `set -e` kill (permission error, dvc init failure, etc.).
# Guarantees the sentinel is always written so Docker marks the service as
# service_completed_successfully and dependent services are never left hanging.
# Model pull errors are degraded-mode (services start with existing volume
# contents), never fatal to the overall stack.
_ensure_sentinel() {
    local code=$?
    if [[ ! -f "$SENTINEL" ]]; then
        if [[ $code -ne 0 ]]; then
            warn "Exiting with code ${code} before sentinel was written — writing now to unblock dependent services."
        fi
        touch "$SENTINEL" 2>/dev/null || true
        chown "${AIRFLOW_UID:-50000}:0" "$SENTINEL" 2>/dev/null || true
    fi
    # Always exit 0: model pull errors are non-fatal to the stack.
    exit 0
}
trap _ensure_sentinel EXIT

log "Starting in mode=${MODE}"

cd "$DVC_ROOT"

# ── Git safe.directory ────────────────────────────────────────────────────────
# Required when host UID != container UID (airflow user is 50000, host is typically 1000).
git config --global --add safe.directory "$DVC_ROOT" 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL MODE
# ══════════════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "local" ]]; then

    # Initialize DVC if not already done (bind mount may be a fresh clone).
    if [[ ! -d ".dvc" ]]; then
        log "Initializing DVC..."
        dvc init
    fi

    # Configure the local fallback remote. --local writes to .dvc/config.local
    # (gitignored), so the committed GCS remote in .dvc/config is never touched.
    dvc remote add --local local_storage "${DVC_ROOT}/dvc_storage" 2>/dev/null || \
        dvc remote modify --local local_storage url "${DVC_ROOT}/dvc_storage"
    chown -R "${AIRFLOW_UID:-50000}:0" "${DVC_ROOT}/.dvc"
    log "DVC local remote configured: $(dvc remote list)"

    # Resolve credentials: use GCP_DVC_CREDENTIALS if it points to a real file.
    # If it's unset, empty, or a directory, let DVC use ADC unobstructed.
    resolved_creds="${GCP_DVC_CREDENTIALS:-}"
    if [[ -n "$resolved_creds" && -f "$resolved_creds" ]]; then
        log "Using DVC credentials: ${resolved_creds}"
        export GOOGLE_APPLICATION_CREDENTIALS="$resolved_creds"
    else
        warn "GCP_DVC_CREDENTIALS not set or not a file — using ADC / local cache."
        unset GOOGLE_APPLICATION_CREDENTIALS 2>/dev/null || true
    fi

    # Build dvc pull target list.
    if [[ -n "$TARGET" ]]; then
        DVC_TARGETS="models/${TARGET}.dvc"
        log "Targeted pull: ${DVC_TARGETS}"
    else
        DVC_TARGETS=""
    fi

    # Attempt dvc pull, fall back to dvc checkout from local cache.
    log "Running dvc pull..."
    # shellcheck disable=SC2086
    if dvc pull --allow-missing $DVC_TARGETS 2>&1; then
        log "dvc pull complete."
    else
        warn "dvc pull failed — falling back to dvc checkout (local cache)."
        # shellcheck disable=SC2086
        dvc checkout $DVC_TARGETS 2>&1 || \
            warn "dvc checkout also failed — models must be provided via volume mount."
    fi

    chown -R "${AIRFLOW_UID:-50000}:0" "${DVC_ROOT}/models" 2>/dev/null || true

# ══════════════════════════════════════════════════════════════════════════════
# PROD MODE
# ══════════════════════════════════════════════════════════════════════════════
elif [[ "$MODE" == "prod" ]]; then

    POINTERS_DIR="${DVC_ROOT}/dvc-pointers"

    # Overwrite any stale .dvc pointer files in the named volume with the
    # authoritative hashes baked into the current image. This is the key step
    # that prevents a persistent volume from shadowing a newer image's pointers.
    if [[ -d "$POINTERS_DIR" ]]; then
        log "Copying authoritative .dvc pointer files from image layer..."
        cp -v "${POINTERS_DIR}"/*.dvc "${DVC_ROOT}/models/" 2>/dev/null || \
            warn "No .dvc files found in ${POINTERS_DIR} — skipping pointer copy."
    else
        warn "dvc-pointers dir not found at ${POINTERS_DIR} — image may be stale."
    fi

    # Initialize DVC (no-scm because there is no .git in prod).
    if [[ ! -d ".dvc" ]]; then
        log "Initializing DVC (no-scm)..."
        dvc init --no-scm
    fi

    # Configure GCS remote from env var.
    if [[ -z "${GCS_BUCKET_MODELS:-}" ]]; then
        warn "GCS_BUCKET_MODELS is not set — cannot configure DVC GCS remote. Skipping pull; services will start with existing volume contents."
        exit 0  # _ensure_sentinel trap writes sentinel and exits 0
    fi
    dvc remote add -d gcs_remote "gs://${GCS_BUCKET_MODELS}" 2>/dev/null || \
        dvc remote modify gcs_remote url "gs://${GCS_BUCKET_MODELS}"
    log "DVC GCS remote configured: gs://${GCS_BUCKET_MODELS}"

    # ADC handles auth via VM service account — no credentials file needed.
    # Build target list for optional single-model update.
    if [[ -n "$TARGET" ]]; then
        DVC_TARGETS="models/${TARGET}.dvc"
        log "Targeted pull: ${DVC_TARGETS}"
    else
        DVC_TARGETS=""
    fi

    log "Running dvc pull..."
    # shellcheck disable=SC2086
    dvc pull --allow-missing $DVC_TARGETS 2>&1 || \
        warn "dvc pull failed — models must be pre-loaded into the models volume."

    chown -R "${AIRFLOW_UID:-50000}:0" "${DVC_ROOT}/models" 2>/dev/null || true

else
    warn "Unknown MODEL_LOADER_MODE='${MODE}'. Must be 'local' or 'prod'. Skipping model load."
    exit 0  # _ensure_sentinel trap writes sentinel and exits 0
fi

# ── Write sentinel ────────────────────────────────────────────────────────────
touch "$SENTINEL"
chown "${AIRFLOW_UID:-50000}:0" "$SENTINEL" 2>/dev/null || true
log "Sentinel written: ${SENTINEL}"
log "Model loader complete."
