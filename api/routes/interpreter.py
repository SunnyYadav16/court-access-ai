"""
api/routes/interpreter.py

Interpreter-only endpoints for the CourtAccess AI API.

All routes are gated by require_role("interpreter") and require a valid Bearer token.

Endpoints:
  GET  /interpreter/review                       — List scraped court forms pending human review
  GET  /interpreter/review/{session_id}          — Get a single form's details for review
  POST /interpreter/review/{session_id}/correct  — Submit a correction to a translation
  POST /interpreter/review/{session_id}/approve  — Approve a form translation
  POST /interpreter/review/{session_id}/flag     — Flag a form translation for recorrection
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from api.dependencies import CurrentUser, DBSession, require_role
from courtaccess.core.config import get_settings
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(
    prefix="/interpreter",
    tags=["interpreter"],
    # All routes in this file require interpreter (or higher) role.
    dependencies=[Depends(require_role("interpreter", "admin"))],
)

_InterpreterUser = Annotated[CurrentUser, Depends(require_role("interpreter", "admin"))]


# ══════════════════════════════════════════════════════════════════════════════
# Response / request models
# ══════════════════════════════════════════════════════════════════════════════


class TranslationCorrectionRequest(BaseModel):
    """Interpreter-submitted correction for a specific utterance translation."""

    original_text: str
    original_language: str
    corrected_translation: str
    target_language: str
    correction_notes: str | None = None


class FlagRequest(BaseModel):
    """Request body for flagging a translation for recorrection."""

    notes: str
    correction_requested: bool = True


class ReviewSummary(BaseModel):
    """Summary of a scraped court form for the review queue."""

    session_id: uuid.UUID  # actually form_id — reused so the frontend key stays stable
    target_language: str
    status: str
    review_status: str  # "pending" | "approved" | "flagged"
    avg_confidence_score: float | None
    llama_corrections_count: int
    original_filename: str | None
    signed_url_original: str | None
    signed_url_translated: str | None
    signed_url_expires_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


async def _generate_signed_url_if_available(gcs_path: str | None) -> str | None:
    """Generate a signed URL for a GCS path, or return None if unavailable."""
    if not gcs_path:
        return None
    try:
        from courtaccess.core import gcs

        bucket, blob = gcs.parse_gcs_uri(gcs_path)
        return await asyncio.to_thread(
            gcs.generate_signed_url,
            bucket,
            blob,
            settings.signed_url_expiry_seconds,
            settings.gcp_service_account_json,
        )
    except Exception as exc:
        logger.warning("Failed to generate signed URL for %s: %s", gcs_path, exc)
        return None


async def _get_review_statuses(
    db: DBSession,
    form_ids: list[uuid.UUID],
) -> dict[str, str]:
    """
    Build a mapping of form_id → review_status by checking audit logs.

    Approve/flag actions store form_id in the JSONB ``details`` column
    (not in the ``session_id`` FK which is NULL for form reviews).

    Returns "approved" if an interpreter_approved entry exists (latest wins),
    "flagged" if interpreter_flagged exists, else "pending".
    """
    if not form_ids:
        return {}

    from db.models import AuditLog

    form_id_strs = [str(fid) for fid in form_ids]

    result = await db.execute(
        select(
            AuditLog.details["form_id"].astext.label("form_id"),
            AuditLog.action_type,
        )
        .where(
            AuditLog.action_type.in_(["interpreter_approved", "interpreter_flagged"]),
            AuditLog.details["form_id"].astext.in_(form_id_strs),
        )
        .order_by(desc(AuditLog.created_at))
    )

    statuses: dict[str, str] = {}
    for row in result.all():
        fid = str(row.form_id)
        if fid not in statuses:
            statuses[fid] = "approved" if row.action_type == "interpreter_approved" else "flagged"

    return statuses


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review",
    summary="List scraped court forms pending human review",
    response_model=list[ReviewSummary],
    description=(
        "Returns mass.gov court forms automatically scraped and translated by the DAG pipeline "
        "that are flagged needs_human_review=True. Interpreters approve or flag these — "
        "NOT user-uploaded documents."
    ),
)
async def list_review_sessions(
    interpreter: _InterpreterUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    target_language: str | None = Query(
        default=None,
        description="Filter by target language code: 'es' or 'pt'",
    ),
) -> list[ReviewSummary]:
    """
    Returns active, scraped court forms where needs_human_review is True.

    Review status is derived from audit log entries:
    - "approved" if interpreter_approved audit entry exists
    - "flagged" if interpreter_flagged audit entry exists
    - "pending" otherwise
    """
    from db.models import FormCatalog, FormVersion

    # Base query: active forms that need human review, latest version only
    q = (
        select(FormCatalog, FormVersion)
        .join(
            FormVersion,
            (FormVersion.form_id == FormCatalog.form_id) & (FormVersion.version == FormCatalog.current_version),
        )
        .where(
            FormCatalog.status == "active",
            FormCatalog.needs_human_review == True,  # noqa: E712
        )
        .order_by(desc(FormCatalog.last_scraped_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    # Language filter: only show forms that have a translation for the requested language
    if target_language:
        if target_language == "es":
            q = q.where(FormVersion.file_path_es.isnot(None))
        elif target_language == "pt":
            q = q.where(FormVersion.file_path_pt.isnot(None))
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported target_language '{target_language}'. Allowed values: es, pt.",
            )

    result = await db.execute(q)
    rows = result.all()

    if not rows:
        return []

    # Derive review statuses from audit logs (keyed by form_id)
    form_ids = [f.form_id for f, _v in rows]
    review_statuses = await _get_review_statuses(db, form_ids)

    now = datetime.now(UTC)
    expires_at = (now + timedelta(seconds=settings.signed_url_expiry_seconds)).isoformat()

    summaries: list[ReviewSummary] = []
    for form, version in rows:
        fid = str(form.form_id)

        # Determine which translated file to surface
        if target_language == "pt":
            translated_path = version.file_path_pt
        else:
            translated_path = version.file_path_es or version.file_path_pt

        signed_original = await _generate_signed_url_if_available(version.file_path_original)
        signed_translated = await _generate_signed_url_if_available(translated_path)

        # Surface the target language for display
        if target_language:
            lang_code = target_language
        elif version.file_path_es:
            lang_code = "es"
        elif version.file_path_pt:
            lang_code = "pt"
        else:
            continue  # no translation available — skip this form

        summaries.append(
            ReviewSummary(
                session_id=form.form_id,  # reuse session_id field — frontend uses this as item key
                target_language=lang_code,
                status="completed",
                review_status=review_statuses.get(fid, "pending"),
                avg_confidence_score=None,  # forms don't track per-form confidence
                llama_corrections_count=0,
                original_filename=form.form_name,
                signed_url_original=signed_original,
                signed_url_translated=signed_translated,
                signed_url_expires_at=expires_at if (signed_original or signed_translated) else None,
                created_at=form.last_scraped_at.isoformat() if form.last_scraped_at else form.created_at.isoformat(),
            )
        )

    return summaries


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review/{session_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review/{session_id}",
    summary="Get scraped form details for review",
    response_model=ReviewSummary,
)
async def get_review_session(
    session_id: uuid.UUID,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> ReviewSummary:
    from db.models import FormCatalog, FormVersion

    result = await db.execute(
        select(FormCatalog, FormVersion)
        .join(
            FormVersion,
            (FormVersion.form_id == FormCatalog.form_id) & (FormVersion.version == FormCatalog.current_version),
        )
        .where(FormCatalog.form_id == session_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    form, version = row
    fid = str(form.form_id)

    review_statuses = await _get_review_statuses(db, [form.form_id])
    review_status = review_statuses.get(fid, "pending")

    signed_original = await _generate_signed_url_if_available(version.file_path_original)
    signed_translated = await _generate_signed_url_if_available(version.file_path_es or version.file_path_pt)
    lang_code = "es" if version.file_path_es else "pt"

    now = datetime.now(UTC)
    expires_at = (now + timedelta(seconds=settings.signed_url_expiry_seconds)).isoformat()

    return ReviewSummary(
        session_id=form.form_id,
        target_language=lang_code,
        status="completed",
        review_status=review_status,
        avg_confidence_score=None,
        llama_corrections_count=0,
        original_filename=form.form_name,
        signed_url_original=signed_original,
        signed_url_translated=signed_translated,
        signed_url_expires_at=expires_at if (signed_original or signed_translated) else None,
        created_at=form.last_scraped_at.isoformat() if form.last_scraped_at else form.created_at.isoformat(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /interpreter/review/{session_id}/correct
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/review/{session_id}/correct",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a translation correction",
    description="Interpreter submits a correction for a form translation. Written to the audit log.",
)
async def submit_correction(
    session_id: uuid.UUID,
    body: TranslationCorrectionRequest,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import FormCatalog
    from db.queries.audit import write_audit

    # Verify form exists
    result = await db.execute(select(FormCatalog.form_id).where(FormCatalog.form_id == session_id))
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_correction",
        session_id=None,
        details={
            "form_id": str(session_id),
            "original_text": body.original_text,
            "original_language": body.original_language,
            "corrected_translation": body.corrected_translation,
            "target_language": body.target_language,
            "notes": body.correction_notes,
        },
    )
    await db.commit()

    logger.info(
        "Interpreter correction submitted: form=%s interpreter=%s target=%s",
        session_id,
        interpreter.user_id,
        body.target_language,
    )

    return {"status": "accepted", "session_id": str(session_id)}


# ══════════════════════════════════════════════════════════════════════════════
# POST /interpreter/review/{session_id}/approve
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/review/{session_id}/approve",
    status_code=status.HTTP_200_OK,
    summary="Approve a form translation",
    description="Mark a scraped form translation as approved. Clears needs_human_review flag.",
)
async def approve_translation(
    session_id: uuid.UUID,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import FormCatalog
    from db.queries.audit import write_audit

    result = await db.execute(select(FormCatalog).where(FormCatalog.form_id == session_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    # Clear the human review flag — form is now certified
    form.needs_human_review = False

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_approved",
        session_id=None,
        details={"approved_by": str(interpreter.user_id), "form_id": str(session_id)},
    )
    await db.commit()

    logger.info(
        "Form translation approved: form=%s interpreter=%s",
        session_id,
        interpreter.user_id,
    )

    return {"status": "approved", "session_id": str(session_id)}


# ══════════════════════════════════════════════════════════════════════════════
# POST /interpreter/review/{session_id}/flag
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/review/{session_id}/flag",
    status_code=status.HTTP_200_OK,
    summary="Flag a form translation for recorrection",
    description=(
        "Flag a scraped form translation as needing recorrection. "
        "The form keeps needs_human_review=True and the flag is logged."
    ),
)
async def flag_for_recorrection(
    session_id: uuid.UUID,
    body: FlagRequest,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import FormCatalog
    from db.queries.audit import write_audit

    result = await db.execute(select(FormCatalog).where(FormCatalog.form_id == session_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Form not found")

    # Ensure the form stays in (or returns to) the review queue
    form.needs_human_review = True

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_flagged",
        session_id=None,
        details={
            "notes": body.notes,
            "correction_requested": body.correction_requested,
            "form_id": str(session_id),
        },
    )
    await db.commit()

    logger.info(
        "Form translation flagged: form=%s interpreter=%s notes=%s",
        session_id,
        interpreter.user_id,
        body.notes[:50],
    )

    return {"status": "flagged", "session_id": str(session_id)}
