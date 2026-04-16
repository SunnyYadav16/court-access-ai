# ══════════════════════════════════════════════════════════════════════════════
# gpu.Dockerfile — CourtAccess AI (GPU targets)
#
# Multi-stage build with two GPU targets:
#   api     — FastAPI + frontend served on CUDA runtime (default)
#   airflow — Airflow workers on the same CUDA runtime so that
#             libcublas.so.12 is present and CTranslate2 can use the GPU.
#             (apache/airflow base image lacks CUDA libs, causing _cuda_available()
#              to return False and fall back to CPU even when a GPU is exposed.)
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 0: Build React frontend ────────────────────────────────────────────
FROM node:22.22.0-slim AS frontend-build

WORKDIR /frontend

RUN npm install -g pnpm@10.30.3

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./

ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_STORAGE_BUCKET
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_APP_ID
ARG VITE_API_BASE_URL

ENV VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID \
    VITE_FIREBASE_STORAGE_BUCKET=$VITE_FIREBASE_STORAGE_BUCKET \
    VITE_FIREBASE_MESSAGING_SENDER_ID=$VITE_FIREBASE_MESSAGING_SENDER_ID \
    VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID \
    VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN pnpm build

# ── Shared GPU base ───────────────────────────────────────────────────────────
# Both the api and airflow targets inherit from here so libcublas.so.12 is
# present in every container that runs GPU inference.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS cuda-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_SYSTEM_PYTHON=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3-pip \
    build-essential \
    libpq-dev \
    postgresql-client \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /bin/uv

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && ln -sf /usr/bin/python3 /usr/bin/python

# ── API target ────────────────────────────────────────────────────────────────
FROM cuda-base AS api

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY courtaccess/ ./courtaccess/

# CUDA PyTorch — overrides CPU wheel from pyproject.toml
RUN uv pip install "torch>=2.3.0" --index-url https://download.pytorch.org/whl/cu124

# Core + speech pipeline deps
RUN uv pip install ".[speech]"

# GPU inference libs
RUN uv pip install paddlepaddle-gpu "paddleocr>=2.7.0"

# DVC for model pulling at startup
RUN uv pip install "dvc[gs]>=3.50.0"

# Copy API source and DB migrations
COPY api/ ./api/
COPY db/ ./db/
COPY models/*.dvc ./models/
# dvc-pointers/ is never a volume mount — lives purely in the image layer.
# Mirrors the pattern in the airflow target so this image can also serve as a
# model-loader source if the deployment topology ever changes.
COPY models/*.dvc ./dvc-pointers/

# Copy compiled frontend
COPY --from=frontend-build /frontend/dist ./frontend/dist

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/model-loader.sh /usr/local/bin/model-loader.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/model-loader.sh

# Run as non-root for container hardening.
# UID/GID 50000 matches AIRFLOW_UID used throughout the project so that the
# shared-models volume (chowned to 50000 by model-loader) is readable here.
# HOME=/tmp gives DVC and git a writable directory for caches/config
# without needing a real home directory.
RUN groupadd --gid 50000 appuser && useradd --uid 50000 --gid 50000 --no-create-home --home-dir /tmp appuser \
    && chown -R appuser:appuser /app /usr/local/bin/docker-entrypoint.sh /usr/local/bin/model-loader.sh

ENV HOME=/tmp

USER appuser

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["fastapi", "run", "api/main.py", "--port", "8000"]

# ── Extract Airflow entrypoint ────────────────────────────────────────────────
# The official /entrypoint script handles _AIRFLOW_DB_MIGRATE, _AIRFLOW_WWW_USER_CREATE,
# DB connectivity checks, and `exec airflow <cmd>`.  docker-compose airflow-init
# calls `exec /entrypoint airflow version` directly, and docker-entrypoint.sh
# chains into it for scheduler/api-server/triggerer/dag-processor.
FROM apache/airflow:3.1.7 AS airflow-entrypoint

# ── Airflow target ────────────────────────────────────────────────────────────
# Inherits cuda-base so libcublas.so.12 is present inside the container.
# _cuda_available() in translation.py verifies this library is loadable before
# selecting the GPU device; without it CTranslate2 falls back to CPU even
# when the GPU device node is exposed via the compose deploy.resources block.
FROM cuda-base AS airflow

ENV HOME=/home/airflow \
    AIRFLOW_HOME=/opt/airflow \
    AIRFLOW_USER_HOME_DIR=/home/airflow

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    netcat-openbsd \
    # Playwright / Chromium system deps — required by courtaccess/forms/scraper.py
    # to download PDFs from mass.gov (plain requests() returns 403, needs browser)
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the official Airflow /entrypoint script — required by airflow-init and
# docker-entrypoint.sh for DB migration, user creation, and signal propagation.
COPY --from=airflow-entrypoint /entrypoint /entrypoint
RUN chmod +x /entrypoint

# Create the airflow user/group to match AIRFLOW_UID expected by compose
RUN groupadd --gid 50000 airflow \
    && useradd --uid 50000 --gid 50000 --create-home --home-dir /home/airflow airflow \
    && mkdir -p /opt/airflow \
    && chown -R airflow:airflow /opt/airflow /home/airflow

WORKDIR /opt/airflow

# Install Airflow first (pins its own dependency tree), then CUDA PyTorch
# so torch resolves to the cu124 wheel rather than the CPU stub.
RUN uv pip install "apache-airflow==3.1.7" \
    "apache-airflow-providers-fab>=1.5.2"

RUN uv pip install "torch>=2.3.0" --index-url https://download.pytorch.org/whl/cu124

# Copy and install the courtaccess package so DAGs can import from it.
COPY --chown=airflow:airflow pyproject.toml uv.lock /opt/airflow/
COPY --chown=airflow:airflow courtaccess/ /opt/airflow/courtaccess/
COPY --chown=airflow:airflow db/ /opt/airflow/db/

RUN uv pip install '/opt/airflow/[airflow]'

# Upgrade DVC with GCS support (base dvc from pyproject.toml lacks [gs] extras)
RUN uv pip install "dvc[gs]>=3.50.0"

# spaCy model — required by Translator.load() for proper noun protection (step 2)
RUN python3 -m spacy download en_core_web_lg

# Install Playwright's Chromium browser for the form scraper
RUN playwright install chromium

RUN chown -R airflow:airflow /opt/airflow /home/airflow

USER airflow

# Copy DAGs, model stubs, and entrypoint
COPY --chown=airflow:airflow dags/ /opt/airflow/dags/
COPY --chown=airflow:airflow models/*.dvc /opt/airflow/models/
# dvc-pointers/ is never a volume mount — it lives purely in the image layer.
# model-loader.sh (prod mode) copies from here into the shared-models volume to
# overwrite any stale .dvc hashes that persisted from a previous image version.
COPY --chown=airflow:airflow models/*.dvc /opt/airflow/dvc-pointers/
COPY --chown=airflow:airflow scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --chown=airflow:airflow scripts/model-loader.sh /usr/local/bin/model-loader.sh
USER root
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/model-loader.sh
USER airflow

ENTRYPOINT ["docker-entrypoint.sh"]
