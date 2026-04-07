#!/usr/bin/env bash
# scripts/deploy.sh — called by the deploy-to-vm SSH action in deploy.yml.
#
# Usage (on the VM):
#   bash ~/app/scripts/deploy.sh <github_sha>
#
# The CI workflow passes ${{ github.sha }} as $1.
# All docker compose commands assume the working directory is ~/app.
#
# Sequence:
#   1. git fetch + reset  — pins repo to the exact deployed SHA (not branch HEAD)
#   2. export APP_VERSION — pins every docker compose command to the new SHA
#   3. docker compose pull — downloads all new images while old containers serve
#   3b. build + recreate mlflow — mlflow uses build: not image:, pull skips it
#   4. model-loader       — syncs model weights into shared-models volume
#   5. airflow-init       — runs DB migrations
#   6. airflow services   — restart with new image
#   7. api                — restarts last (~5-10 s gap)
#   8. health check       — blocks until API is ready; fails the CI step on timeout
#   9. .deploy_state      — records deployed SHA for rollback reference

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE="docker compose -f ${APP_DIR}/docker-compose.prod.yml"
STATE_FILE="${APP_DIR}/.deploy_state"

# ── 1. Argument validation ─────────────────────────────────────────────────────
if [ -z "${1:-}" ]; then
  echo "❌ Usage: deploy.sh <github_sha>" >&2
  exit 1
fi

# ── 1b. Seed manifest if this is the very first deploy (scraper hasn't run yet) ──
# deploy.yml's validate-before-deploy gate requires the manifest to exist.
# On a fresh project the scraper DAG hasn't fired yet, so we seed an empty
# manifest so the first tagged release can proceed. Subsequent deploys use
# the real manifest written by form_scraper_dag each Monday.
MANIFEST_GCS="gs://${GCS_BUCKET_FORMS}/manifests/form_catalog_manifest.json"
if ! gsutil -q stat "${MANIFEST_GCS}" 2>/dev/null; then
  echo "⚠️  No manifest found at ${MANIFEST_GCS} — seeding empty manifest for first deploy."
  echo '{"forms":[],"total_active_forms":0}' | gsutil cp - "${MANIFEST_GCS}"
fi

# ── 2. Checkout exact deployed SHA ────────────────────────────────────────────
# fetch + reset guarantees the VM is at the tagged commit, not branch HEAD.
# A plain `git pull` would advance to HEAD and could deploy wrong code if the
# tag was placed on an older commit.
echo "── [1/8] Checking out ${1} ──"
git -C "${APP_DIR}" fetch --tags origin
git -C "${APP_DIR}" reset --hard "$1"

# ── 3. Pin all services to the new image SHA ───────────────────────────────────
export APP_VERSION="$1"
echo "── [2/8] APP_VERSION=${APP_VERSION} ──"

# ── 4. Pull all new images from Artifact Registry ─────────────────────────────
# Old containers continue serving traffic during this step (the zero-downtime
# part). New images are fully downloaded before any container is stopped.
echo "── [3/8] Pulling images from Artifact Registry ──"
${COMPOSE} pull

# ── 4b. Rebuild and recreate mlflow ───────────────────────────────────────────
# mlflow uses build: in docker-compose.prod.yml (not image:), so `pull` skips
# it. Build from the freshly checked-out mlflow.Dockerfile and recreate the
# container so changes in mlflow.Dockerfile are actually deployed.
echo "── [3b/8] Rebuilding mlflow ──"
${COMPOSE} build mlflow
${COMPOSE} up mlflow -d --no-deps --force-recreate

# ── 5. Load updated model weights into the shared-models volume ────────────────
# model-loader copies .dvc pointer files from the new image layer and pulls
# any changed model blobs from GCS. The api is still running with the old
# model during this step.
echo "── [4/8] Running model-loader ──"
${COMPOSE} up model-loader --force-recreate --no-deps

# ── 6. Run DB migrations ───────────────────────────────────────────────────────
echo "── [5/8] Running airflow-init (DB migrations) ──"
${COMPOSE} up airflow-init --force-recreate --no-deps

# ── 7. Restart Airflow services with new image ─────────────────────────────────
echo "── [6/8] Restarting Airflow services ──"
${COMPOSE} up airflow-scheduler airflow-dag-processor airflow-apiserver airflow-triggerer \
  -d --no-deps

# ── 8. Restart API with new image ─────────────────────────────────────────────
# This is the ~5-10 second gap where the API is unavailable.
echo "── [7/8] Restarting API ──"
${COMPOSE} up api -d --no-deps

# ── 9. Wait for API to be healthy ─────────────────────────────────────────────
# --retry 10 --retry-delay 3 = up to 30 seconds. Fails the CI step (and
# triggers rollback-on-failure) if the API doesn't come up in time.
echo "── [8/8] Waiting for API health check ──"
curl -f http://localhost:8000/health \
  --retry 10 \
  --retry-delay 3 \
  --retry-connrefused \
  --silent \
  --show-error
echo ""
echo "✅ /health → 200 OK"

# ── 10. Record deployed SHA ────────────────────────────────────────────────────
echo "APP_VERSION=${APP_VERSION}" >> "${STATE_FILE}"
echo "DEPLOYED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >> "${STATE_FILE}"
echo "✅ Deploy complete: ${APP_VERSION}"
