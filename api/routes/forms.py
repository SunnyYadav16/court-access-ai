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

import logging
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import (
    FormListResponse,
    FormResponse,
    Language,
)
from courtaccess.core import gcs
from courtaccess.core.config import get_settings
from db.queries import forms as db_queries_forms
from db.queries.audit import write_audit

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/forms", tags=["forms"])


# ══════════════════════════════════════════════════════════════════════════════
# POST /forms/scraper/trigger — admin only
# ══════════════════════════════════════════════════════════════════════════════


class TriggerScraperRequest(BaseModel):
    force: bool = False


class TriggerScraperResponse(BaseModel):
    dag_run_id: str
    triggered_at: datetime


@router.post(
    "/scraper/trigger",
    response_model=TriggerScraperResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger form scraper DAG run",
    description="Admin-only endpoint to trigger an immediate form_scraper_dag run via Airflow API.",
)
async def trigger_form_scraper(
    payload: TriggerScraperRequest,
    user: CurrentUser,
    db: DBSession,
    _: dict = Depends(require_role("admin")),  # noqa: B008
) -> TriggerScraperResponse:
    """
    Trigger `form_scraper_dag` in Airflow with the acting admin user_id.

    Note:
      - `force` is accepted for forward compatibility but not sent to Airflow
        yet. Current DAG behavior is unchanged.
      - The regular Monday schedule remains unaffected.
    """
    _ = payload.force

    if not settings.airflow_base_url or not settings.airflow_username or not settings.airflow_password:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Airflow configuration is missing. Cannot trigger scraper DAG.",
        )

    token_url = f"{settings.airflow_base_url}/auth/token"
    dag_run_url = f"{settings.airflow_base_url}/api/v2/dags/form_scraper_dag/dagRuns"
    triggered_at = datetime.now(tz=UTC)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Airflow 3 requires a JWT exchange before calling the REST API.
            token_resp = await client.post(
                token_url,
                json={"username": settings.airflow_username, "password": settings.airflow_password},
            )
            token_resp.raise_for_status()
            airflow_token = token_resp.json()["access_token"]

            resp = await client.post(
                dag_run_url,
                headers={"Authorization": f"Bearer {airflow_token}"},
                json={"conf": {"triggered_by_user_id": str(user.user_id)}},
            )
            resp.raise_for_status()
    except httpx.RequestError as exc:
        logger.error("Airflow unreachable while triggering form_scraper_dag: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Airflow is unreachable. Please try again in a moment.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error("Airflow trigger failed with status %s: %s", exc.response.status_code, exc.response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Airflow rejected the trigger request.",
        ) from exc

    dag_run_id = resp.json().get("dag_run_id")
    if not dag_run_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Airflow trigger response did not include dag_run_id.",
        )

    # Best-effort audit — the DAG has already been triggered successfully.
    # A DB failure here must not surface as a 500 to the client.
    try:
        await write_audit(
            db,
            user_id=user.user_id,
            action_type="form_scrape_triggered",
            details={"dag_run_id": dag_run_id},
        )
        await db.commit()
    except Exception as exc:
        logger.error(
            "Audit write failed for form_scrape_triggered (dag_run_id=%s): %s",
            dag_run_id,
            exc,
        )

    return TriggerScraperResponse(
        dag_run_id=dag_run_id,
        triggered_at=triggered_at,
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
async def list_divisions(_user: CurrentUser, db: DBSession) -> list[str]:
    return await db_queries_forms.list_divisions(db)


# ══════════════════════════════════════════════════════════════════════════════
# GET /forms/
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/",
    response_model=FormListResponse,
    summary="Search and list court forms",
    description=(
        "Paginated, filterable list of pre-translated court forms. "
        "Requires authentication — all authenticated roles are permitted."
    ),
)
async def list_forms(
    _user: CurrentUser,
    db: DBSession,
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
    filters_applied: dict[str, str] = {}
    if status_filter:
        filters_applied["status"] = status_filter
    if division:
        filters_applied["division"] = division
    if language:
        filters_applied["language"] = language.value
    if q:
        filters_applied["q"] = q

    items, total = await db_queries_forms.list_forms(
        db,
        status=status_filter,
        division=division,
        language=(language.value if language else None),
        q=q,
        page=page,
        page_size=page_size,
    )
    return FormListResponse(
        items=items,
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
    description="Return full metadata and signed download URLs for a single court form. Requires authentication.",
)
async def get_form(form_id: uuid.UUID, _user: CurrentUser, db: DBSession) -> FormResponse:
    """
    Look up a form by form_id.

    TODO (production):
      - Query FormCatalog DB table by form_id (indexed lookup)
      - Generate signed 1-hour GCS URLs for PDF downloads
    """
    form = await db_queries_forms.get_form_by_id(db, form_id)
    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")
    # Generate signed URLs for the latest version only.
    # Use max() by version number — versions[0] is insertion-order dependent
    # and may not be the highest version when the ORM loads the relationship.
    versions = getattr(form, "versions", []) or []
    if versions:
        latest = max(versions, key=lambda v: v.version)

        def _sign(path: str | None) -> str | None:
            if not path or not isinstance(path, str) or not path.startswith("gs://"):
                return None
            b, bl = gcs.parse_gcs_uri(path)
            return gcs.generate_signed_url(
                b,
                bl,
                settings.signed_url_expiry_seconds,
                settings.gcp_service_account_json,
            )

        latest.signed_url_original = _sign(getattr(latest, "file_path_original", None))
        latest.signed_url_es = _sign(getattr(latest, "file_path_es", None))
        latest.signed_url_pt = _sign(getattr(latest, "file_path_pt", None))

    return form


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
    db: DBSession,
    _: dict = Depends(require_role("court_official", "admin")),  # noqa: B008
) -> FormResponse:
    """
    Record a human review decision.

    TODO (production):
      - Persist decision to AuditLog DB table
      - Update FormCatalog.needs_human_review and last_reviewed_by
      - Write review decision back into form_catalog.json on disk
    """
    updated = await db_queries_forms.submit_form_review(
        db,
        form_id=form_id,
        approved=decision.approved,
        reviewer_user_id=user.user_id,
        notes=decision.reviewer_notes,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")
    await db.commit()
    return updated
