# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — CourtAccess AI
# Multi-stage build with two targets:
#   api     — FastAPI application server
#   airflow — Airflow scheduler/workers with courtaccess package pre-installed
#
# GPU inference (Whisper, NLLB, PaddleOCR, Qwen) uses gpu.Dockerfile instead.
# ══════════════════════════════════════════════════════════════════════════════

# ── Stage 0: Build React frontend ────────────────────────────────────────────
# node:22-slim ships with Node 22 as default — no nvm needed in the container.
# pnpm build outputs to /frontend/dist/ which is then copied into the api stage.
FROM node:22-slim AS frontend-build

WORKDIR /frontend

# Install pnpm globally
RUN npm install -g pnpm

# Copy lockfile + manifest first for layer caching
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy full source and build
COPY frontend/ ./
RUN pnpm build
# dist/ is now at /frontend/dist/

# ── Shared base ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System dependencies shared between targets
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── API target ────────────────────────────────────────────────────────────────
FROM base AS api

# Copy package definition first for layer caching
COPY pyproject.toml ./
COPY courtaccess/ ./courtaccess/

# Install courtaccess core dependencies (all ARM64-compatible)
RUN pip install -e .

# Install DVC with GCS support for model pulling at startup
RUN pip install --no-cache-dir "dvc[gs]>=3.50.0"

# Copy API source and entrypoint
COPY api/ ./api/
COPY db/ ./db/

# Copy built frontend (from frontend-build stage) — served as static files by FastAPI
COPY --from=frontend-build /frontend/dist ./frontend/dist

COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# Entrypoint: pulls models via DVC + registers in MLflow, then starts CMD
ENTRYPOINT ["docker-entrypoint.sh"]

# Using `fastapi run` (exec form) per FastAPI docs — ensures graceful shutdown
# and correct lifespan event triggering in production.
CMD ["fastapi", "run", "api/main.py", "--port", "8000"]

# ── Airflow target ────────────────────────────────────────────────────────────
# apache/airflow:3.1.7 base already includes Airflow; we add the courtaccess package on top
FROM apache/airflow:3.1.7 AS airflow

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    # Playwright / Chromium system deps — required by courtaccess/forms/scraper.py
    # to download PDFs from mass.gov (plain requests() returns 403, needs browser)
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Copy and install the courtaccess package so DAGs can import from it.
# This is required — without it, every DAG fails with ModuleNotFoundError.
COPY --chown=airflow:root pyproject.toml /opt/airflow/
COPY --chown=airflow:root courtaccess/ /opt/airflow/courtaccess/

RUN pip install --no-cache-dir -e '/opt/airflow/[airflow]'

# Upgrade DVC with GCS support (base dvc from pyproject.toml lacks [gs] extras)
RUN pip install --no-cache-dir "dvc[gs]>=3.50.0"

# Install Playwright's Chromium browser for the form scraper
RUN playwright install chromium

# Copy DAGs and entrypoint
COPY --chown=airflow:root dags/ /opt/airflow/dags/
COPY --chown=airflow:root scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER root
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
USER airflow

ENTRYPOINT ["docker-entrypoint.sh"]
