"""
dags/gpu_pool.py

Constants for the 'gpu_inference' Airflow pool.

The pool itself is created by airflow-init (see docker-compose.yml /
docker-compose.prod.yml) via `airflow pools set` after DB migration,
so it exists before any task runs.

All GPU-heavy tasks reference pool=GPU_POOL_NAME to limit concurrency
to 1 slot, preventing VRAM OOM when multiple DAGs run in parallel.
"""

GPU_POOL_NAME = "gpu_inference"
GPU_POOL_SLOTS = 1
GPU_POOL_DESCRIPTION = (
    "Limits concurrent GPU-heavy tasks (NLLB translation, OCR, DOCX translation) "
    "to prevent VRAM OOM when multiple DAGs run in parallel."
)
