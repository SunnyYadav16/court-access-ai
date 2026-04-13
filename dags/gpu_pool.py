"""
dags/gpu_pool.py

Creates the 'gpu_inference' Airflow pool at DAG-parse time if it doesn't
already exist.  This pool limits how many GPU-consuming tasks (OCR, NLLB
translation, DOCX translation) can run concurrently across ALL DAGs.

With 1 slot, only one translation/OCR task loads the NLLB model onto the
GPU at a time — preventing OOM when form_pretranslation_dag and
docx_pipeline_dag are triggered simultaneously by form_scraper_dag.

The pool is created via the Airflow stable API and is safe to run
repeatedly (idempotent).  If the pool already exists, the INSERT is
silently skipped.
"""

import logging

logger = logging.getLogger(__name__)

# Pool name — referenced by all GPU-heavy tasks via pool="gpu_inference"
GPU_POOL_NAME = "gpu_inference"
GPU_POOL_SLOTS = 1
GPU_POOL_DESCRIPTION = (
    "Limits concurrent GPU-heavy tasks (NLLB translation, OCR, DOCX translation) "
    "to prevent VRAM OOM when multiple DAGs run in parallel."
)


def ensure_gpu_pool() -> None:
    """Create the gpu_inference pool if it doesn't exist yet."""
    try:
        from airflow.models import Pool
        from airflow.utils.session import create_session

        with create_session() as session:
            existing = session.query(Pool).filter(Pool.pool == GPU_POOL_NAME).first()
            if existing is None:
                pool = Pool(
                    pool=GPU_POOL_NAME,
                    slots=GPU_POOL_SLOTS,
                    description=GPU_POOL_DESCRIPTION,
                    include_deferred=False,
                )
                session.add(pool)
                logger.info(
                    "Created Airflow pool '%s' with %d slot(s).",
                    GPU_POOL_NAME,
                    GPU_POOL_SLOTS,
                )
            else:
                logger.debug("Airflow pool '%s' already exists (%d slots).", GPU_POOL_NAME, existing.slots)
    except Exception as exc:
        # Never crash DAG parsing — pool creation is best-effort.
        # If it fails (e.g. DB not ready yet during first parse), Airflow uses
        # the default_pool and tasks run unthrottled — same as before this change.
        logger.warning("Could not ensure gpu_inference pool: %s", exc)


# Run at import time (DAG parse).  Airflow parses DAG files after DB migrate,
# so the pools table exists by the time this runs.
ensure_gpu_pool()
