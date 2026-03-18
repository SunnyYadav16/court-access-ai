"""
api/routes/forms.py

REST endpoints for the pre-translated court form catalog.

Endpoints:
  GET    /forms/                — Search / list available court forms (paginated)
  GET    /forms/{form_id}       — Get details for a single form with signed URLs
  GET    /forms/divisions       — List all available court divisions

These endpoints are read-only and publicly accessible (no authentication required).
Court officials and admins can additionally:
  PATCH  /forms/{form_id}/review — Approve or reject human review for a form

The catalog is backed by the JSON file maintained by form_scraper_dag.
In production this will be queryable via the PostgreSQL FormCatalog table.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import (
    FormListResponse,
    FormResponse,
    Language,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forms", tags=["forms"])

# ── Catalog path (only used for local/dev file-backed reads) ──────────────────
_CATALOG_PATH = Path("/opt/airflow/courtaccess/data/form_catalog.json")


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _load_catalog() -> list[dict]:
    """Load the form catalog from disk (dev) or DB (production)."""
    if not _CATALOG_PATH.exists():
        logger.warning("Catalog file not found at %s — returning empty list", _CATALOG_PATH)
        return []
    try:
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not load catalog: %s", exc)
        return []


def _form_to_response(entry: dict) -> FormResponse:
    """Convert a raw catalog dict into a FormResponse."""
    versions = entry.get("versions", [])
    latest_v = versions[0] if versions else None

    from datetime import datetime

    from api.schemas.schemas import FormAppearance, FormVersion

    return FormResponse(
        form_id=uuid.UUID(entry["form_id"]) if isinstance(entry.get("form_id"), str) else entry["form_id"],
        form_name=entry.get("form_name", ""),
        form_slug=entry.get("form_slug", ""),
        source_url=entry.get("source_url", ""),
        status=entry.get("status", "unknown"),
        current_version=entry.get("current_version", 1),
        needs_human_review=entry.get("needs_human_review", True),
        languages_available=entry.get("languages_available", []),
        appearances=[
            FormAppearance(
                division=a.get("division", ""),
                section_heading=a.get("section_heading", ""),
            )
            for a in entry.get("appearances", [])
        ],
        latest_version=FormVersion(
            version=latest_v.get("version", 1),
            content_hash=latest_v.get("content_hash", ""),
            file_url_original=None,  # TODO: generate signed GCS URL
            file_url_es=None,  # TODO: generate signed GCS URL
            file_url_pt=None,  # TODO: generate signed GCS URL
            created_at=datetime.fromisoformat(latest_v["created_at"].rstrip("Z"))
            if latest_v and latest_v.get("created_at")
            else datetime.utcnow(),
        )
        if latest_v
        else None,
        last_scraped_at=(
            datetime.fromisoformat(entry["last_scraped_at"].rstrip("Z")) if entry.get("last_scraped_at") else None
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /forms/divisions — must be before /{form_id} to avoid path collision
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/divisions",
    response_model=list[str],
    summary="List all court divisions",
    description="Returns a sorted list of all court division names that have forms in the catalog.",
)
async def list_divisions() -> list[str]:
    """
    Return all unique division names from the catalog.

    TODO (production): Replace with indexed DB query.
    """
    catalog = _load_catalog()
    divisions: set[str] = set()
    for entry in catalog:
        for app in entry.get("appearances", []):
            if div := app.get("division"):
                divisions.add(div)
    return sorted(divisions)


# ══════════════════════════════════════════════════════════════════════════════
# GET /forms/
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/",
    response_model=FormListResponse,
    summary="Search and list court forms",
    description=(
        "Paginated, filterable list of pre-translated court forms. "
        "No authentication required — all forms are publicly accessible."
    ),
)
async def list_forms(
    q: str | None = Query(default=None, max_length=200, description="Keyword search over form names"),
    division: str | None = Query(default=None, description="Filter by court division"),
    language: Language | None = Query(default=None, description="Only return forms with this language available"),  # noqa: B008
    status_filter: str | None = Query(
        default="active", alias="status", description="'active', 'archived', or None for all"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FormListResponse:
    """
    Filterable list of court forms.

    Filters applied in order:
      1. status   (default: 'active')
      2. division (substring match on court division names)
      3. language (form must have file_path_{lang} in its latest version)
      4. q        (case-insensitive substring match on form_name)

    TODO (production):
      - Replace full-catalog scan with indexed SQL query
      - Add full-text search index on form_name
      - Generate signed GCS URLs for file_url_* fields
    """
    catalog = _load_catalog()
    filters_applied: dict[str, str] = {}

    results = catalog

    # ── Status filter ────────────────────────────────────────────────────────
    if status_filter:
        results = [e for e in results if e.get("status") == status_filter]
        filters_applied["status"] = status_filter

    # ── Division filter ──────────────────────────────────────────────────────
    if division:
        div_lower = division.lower()
        results = [
            e for e in results if any(div_lower in a.get("division", "").lower() for a in e.get("appearances", []))
        ]
        filters_applied["division"] = division

    # ── Language filter ──────────────────────────────────────────────────────
    if language and language != Language.ENGLISH:
        lang_field = f"file_path_{language.value}"
        results = [e for e in results if e.get("versions") and e["versions"][0].get(lang_field)]
        filters_applied["language"] = language.value

    # ── Keyword filter ───────────────────────────────────────────────────────
    if q:
        q_lower = q.lower()
        results = [e for e in results if q_lower in e.get("form_name", "").lower()]
        filters_applied["q"] = q

    total = len(results)
    start = (page - 1) * page_size
    page_results = results[start : start + page_size]

    return FormListResponse(
        items=[_form_to_response(e) for e in page_results],
        total=total,
        page=page,
        page_size=page_size,
        filters_applied=filters_applied,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /forms/{form_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/{form_id}",
    response_model=FormResponse,
    summary="Get a single court form",
    description="Return full metadata and signed download URLs for a single court form.",
)
async def get_form(form_id: uuid.UUID) -> FormResponse:
    """
    Look up a form by form_id.

    TODO (production):
      - Query FormCatalog DB table by form_id (indexed lookup)
      - Generate signed 1-hour GCS URLs for PDF downloads
    """
    catalog = _load_catalog()
    entry = next(
        (e for e in catalog if e.get("form_id") == str(form_id)),
        None,
    )
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    return _form_to_response(entry)


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /forms/{form_id}/review — court officials and admins only
# ══════════════════════════════════════════════════════════════════════════════


class ReviewDecision(BaseModel):
    """Approve or reject the human review flag for a form."""

    approved: bool
    reviewer_notes: str | None = None


@router.patch(
    "/{form_id}/review",
    status_code=status.HTTP_200_OK,
    summary="Submit human review decision for a form",
    description=(
        "Court officials and admins can approve or reject the human review flag "
        "for a translated court form. Approved forms have needs_human_review set to False."
    ),
)
async def submit_form_review(
    form_id: uuid.UUID,
    decision: ReviewDecision,
    user: CurrentUser,
    _: dict = Depends(require_role("court_official", "admin")),  # noqa: B008
    db: DBSession = None,
) -> dict:
    """
    Record a human review decision.

    TODO (production):
      - Persist decision to AuditLog DB table
      - Update FormCatalog.needs_human_review and last_reviewed_by
      - Write review decision back into form_catalog.json on disk
    """
    catalog = _load_catalog()
    entry = next((e for e in catalog if e.get("form_id") == str(form_id)), None)
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    logger.info(
        "Form review submitted: form_id=%s approved=%s reviewer=%s notes=%s",
        form_id,
        decision.approved,
        user.user_id,
        decision.reviewer_notes,
    )

    # TODO: persist to DB/disk
    return {
        "form_id": str(form_id),
        "approved": decision.approved,
        "reviewed_by": str(user.user_id),
        "notes": decision.reviewer_notes,
        "message": "Review decision recorded (STUB — not yet persisted)",
    }
