# ══════════════════════════════════════════════════════════════════════════════
# gpu.Dockerfile — CourtAccess AI (GPU + API + Frontend)
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

# ── GPU base ──────────────────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

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
    libcublas-12-4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /bin/uv

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

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
