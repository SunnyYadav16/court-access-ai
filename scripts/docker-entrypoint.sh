#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/docker-entrypoint.sh — CourtAccess AI container startup
#
# Runs BEFORE the main process (API, Airflow, or GPU inference) starts.
# Handles:
#   1. Pull model weights from GCS via DVC (if GCS remote is configured)
#      OR copy from local DVC storage (for local dev via docker-compose)
#   2. Register models in MLflow (non-blocking, best-effort)
#   3. Exec the main CMD
#
# This script is idempotent — safe to run on every container start.
# Models are pulled into /opt/models/ (shared volume in compose).
# If models are already present, DVC skips the download.
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[entrypoint]${NC} $1"; }
warn() { echo -e "${YELLOW}[entrypoint]${NC} $1"; }

# ── Step 1: Pull model weights ────────────────────────────────────────────────
# Three modes:
#   A) GCS remote configured → dvc pull from gs://courtaccess-ai-models
#   B) Local DVC storage mounted → dvc checkout from local cache
#   C) Neither → skip (models must be mounted manually or baked into image)

pull_models() {
    # Skip if DVC is not installed (e.g., lightweight API container in stub mode)
    if ! command -v dvc &>/dev/null; then
        warn "DVC not installed — skipping model pull. Models must be provided externally."
        return 0
    fi

    # Check if we're in a DVC-tracked repo
    if [[ ! -d ".dvc" && ! -d "/opt/airflow/.dvc" ]]; then
        warn "No .dvc directory found — skipping model pull."
        return 0
    fi

    # Try to move to the directory that has .dvc
    local dvc_root="."
    if [[ -d "/opt/airflow/.dvc" ]]; then
        dvc_root="/opt/airflow"
    fi

    cd "$dvc_root"

    # Git safe directory (needed when host UID != container UID)
    git config --global --add safe.directory "$dvc_root" 2>/dev/null || true

    # Check if models are already present (any .dvc file has a matching directory)
    local models_present=true
    for dvc_file in models/*.dvc; do
        [[ -f "$dvc_file" ]] || continue
        local model_dir="models/$(basename "${dvc_file}" .dvc)"
        if [[ ! -d "$model_dir" ]] || [[ -z "$(ls -A "$model_dir" 2>/dev/null)" ]]; then
            models_present=false
            break
        fi
    done

    if [[ "$models_present" == "true" ]]; then
        log "All models already present — skipping DVC pull."
        return 0
    fi

    # Attempt DVC pull with retries to handle concurrent startup locks
    log "Pulling models via DVC..."
    local attempts=0
    local max_attempts=30
    local success=false

    while [ $attempts -lt $max_attempts ]; do
        set +e
        local dvc_output
        dvc_output=$(dvc pull --allow-missing 2>&1)
        local dvc_status=$?
        set -e

        if [ $dvc_status -eq 0 ]; then
            log "DVC pull complete."
            success=true
            break
        elif echo "$dvc_output" | grep -qi "Unable to acquire lock"; then
            attempts=$((attempts + 1))
            warn "DVC pull is locked by another process. Waiting ($attempts/$max_attempts)..."
            sleep $(( 3 + RANDOM % 4 ))
        else
            warn "DVC pull failed (auth or config): $dvc_output"
            break
        fi
    done

    if [ "$success" = false ]; then
        warn "Trying DVC checkout from local cache..."
        attempts=0
        while [ $attempts -lt $max_attempts ]; do
            set +e
            local checkout_output
            checkout_output=$(dvc checkout 2>&1)
            local checkout_status=$?
            set -e

            if [ $checkout_status -eq 0 ]; then
                log "DVC checkout complete."
                break
            elif echo "$checkout_output" | grep -qi "Unable to acquire lock"; then
                attempts=$((attempts + 1))
                warn "DVC checkout is locked by another process. Waiting ($attempts/$max_attempts)..."
                sleep $(( 3 + RANDOM % 4 ))
            else
                warn "DVC checkout failed: $checkout_output"
                break
            fi
        done
    fi

    cd - >/dev/null
}

# ── Step 2: Register models in MLflow (best-effort) ──────────────────────────
register_models() {
    # Only run if MLFLOW_TRACKING_URI is set and reachable
    if [[ -z "${MLFLOW_TRACKING_URI:-}" ]]; then
        return 0
    fi

    log "Registering models in MLflow..."
    python3 -m courtaccess.core.register_models 2>&1 || warn "MLflow registration failed (non-blocking)."
}

# ── Step 3: Run ───────────────────────────────────────────────────────────────
pull_models
register_models

# If running inside an Airflow container, chain into Airflow's entrypoint.
# Airflow commands (scheduler, api-server, triggerer, dag-processor) need
# Airflow's /entrypoint to set up env, run DB checks, etc.
if [[ -f "/entrypoint" && "${1:-}" =~ ^(scheduler|api-server|triggerer|dag-processor|airflow|celery|flower)$ ]]; then
    log "Chaining into Airflow entrypoint: /entrypoint $*"
    exec /entrypoint "$@"
fi

log "Starting: $*"

# ── Database migrations ───────────────────────────────────────────────────────
# Skip entirely when SKIP_API_MIGRATIONS=true.  Set this in environments where
# another process (e.g. a dedicated init container or CI step) owns the schema.
#
# When migrations are enabled, wait briefly for Postgres to be ready before
# running alembic — the api container may start before airflow-init completes.
if [[ "${SKIP_API_MIGRATIONS:-false}" == "true" ]]; then
    warn "SKIP_API_MIGRATIONS=true — skipping alembic upgrade."
else
    # Resolve connection details from individual env vars (same pattern as the app).
    _PG_HOST="${POSTGRES_HOST:-localhost}"
    _PG_PORT="${POSTGRES_PORT:-5432}"
    _PG_USER="${POSTGRES_USER:-}"
    _RETRIES=15
    _WAIT=2

    log "Waiting for Postgres at ${_PG_HOST}:${_PG_PORT} (up to $((_RETRIES * _WAIT))s)..."
    for i in $(seq 1 "$_RETRIES"); do
        if pg_isready -h "$_PG_HOST" -p "$_PG_PORT" -U "$_PG_USER" -q 2>/dev/null; then
            log "Postgres is ready."
            break
        fi
        if [[ "$i" -eq "$_RETRIES" ]]; then
            warn "Postgres not ready after $((_RETRIES * _WAIT))s — proceeding anyway (alembic may fail)."
        else
            log "Postgres not ready yet (attempt $i/$_RETRIES) — retrying in ${_WAIT}s..."
            sleep "$_WAIT"
        fi
    done

    log "Running: alembic --config db/migrations/alembic.ini upgrade head"
    alembic --config db/migrations/alembic.ini upgrade head
fi

exec "$@"
