"""
courtaccess/forms/catalog.py

Catalog CRUD helpers — load, save, and search form_catalog.json.
Migrated from data_pipeline/dags/src/preprocess_forms.py and scrape_forms.py.

Later migration: swap _load_catalog / _save_catalog for Cloud SQL queries.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Default catalog path (Docker container). Override via env var or constructor arg.
DEFAULT_CATALOG_PATH = "/opt/airflow/courtaccess/data/form_catalog.json"


def load_catalog(catalog_path: str = DEFAULT_CATALOG_PATH) -> list[dict]:
    """Return the full catalog as a list of form-dicts."""
    p = Path(catalog_path)
    if not p.exists():
        logger.info("Catalog file not found at %s — returning empty catalog.", catalog_path)
        return []
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save_catalog(catalog: list[dict], catalog_path: str = DEFAULT_CATALOG_PATH) -> None:
    """Persist the catalog back to disk."""
    p = Path(catalog_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
    logger.debug("Catalog saved to %s", catalog_path)


def find_by_url(catalog: list[dict], url: str) -> dict | None:
    """Return the catalog entry whose source_url matches, or None."""
    return next((f for f in catalog if f["source_url"] == url), None)


def find_by_hash(catalog: list[dict], content_hash: str) -> dict | None:
    """Return the first catalog entry whose content_hash matches, or None."""
    return next((f for f in catalog if f["content_hash"] == content_hash), None)


def find_by_id(catalog: list[dict], form_id: str) -> tuple[int, dict]:
    """Return (index, entry) or raise ValueError if form_id not found."""
    for i, entry in enumerate(catalog):
        if entry.get("form_id") == form_id:
            return i, entry
    raise ValueError(f"form_id '{form_id}' not found in catalog.")
