# ══════════════════════════════════════════════════════════════════════════════
# gpu.Dockerfile — CourtAccess AI GPU Inference Services
#
# Used ONLY for inference pods that require a GPU:
#   - Whisper Large V3   (ASR — CTranslate2 INT8)
#   - NLLB-200 1.3B      (Translation)
#   - PaddleOCR v3       (Printed text OCR)
#   - Qwen2.5-VL         (Handwritten text OCR)
#
# The API and Airflow services use the CPU Dockerfile instead.
# In GKE, GPU pods are scheduled on the gpu-node-pool only.
# ══════════════════════════════════════════════════════════════════════════════

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
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Make python3.11 the default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

WORKDIR /app

# Copy package definition + lockfile for caching
COPY pyproject.toml uv.lock ./
COPY courtaccess/ ./courtaccess/

# torch with CUDA support — overrides the CPU torch from pyproject.toml
RUN uv pip install torch==2.3.0 --index-url https://download.pytorch.org/whl/cu124
RUN uv pip install -e .
RUN uv pip install \
    ctranslate2>=4.0.0 \
    faster-whisper>=1.0.0 \
    paddlepaddle-gpu \
    paddleocr>=2.7.0

# Install DVC with GCS support for model pulling at startup
RUN uv pip install "dvc[gs]>=3.50.0"

# Copy entrypoint
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Model weights are pulled at startup via DVC (see entrypoint).
# In GKE, an init container runs gsutil cp instead.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["echo", "GPU inference container ready. Start the appropriate inference server."]
