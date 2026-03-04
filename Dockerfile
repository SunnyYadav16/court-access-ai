# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — CourtAccess AI
# Multi-stage build with two targets:
#   api     — FastAPI application server
#   airflow — Airflow scheduler/workers with courtaccess package pre-installed
#
# GPU inference (Whisper, NLLB, PaddleOCR, Qwen) uses gpu.Dockerfile instead.
# ══════════════════════════════════════════════════════════════════════════════

# ── Shared base ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

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

# Copy API source
COPY api/ ./api/

EXPOSE 8000

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

# Install Playwright's Chromium browser for the form scraper
RUN playwright install chromium

# Copy DAGs
COPY --chown=airflow:root dags/ /opt/airflow/dags/
