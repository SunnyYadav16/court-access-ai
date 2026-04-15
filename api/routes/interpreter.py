"""
api/routes/interpreter.py

Interpreter-only endpoints for the CourtAccess AI API.

All routes are gated by require_role("interpreter") and require a valid Bearer token.

Endpoints:
  GET  /interpreter/review                       — List completed document translations for review
  GET  /interpreter/review/{session_id}          — Get a single session's details for review
  POST /interpreter/review/{session_id}/correct  — Submit a correction to a translation
  POST /interpreter/review/{session_id}/approve  — Approve a translation
  POST /interpreter/review/{session_id}/flag     — Flag a translation for recorrection
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
    """Summary of a document session for the review queue."""

    session_id: uuid.UUID
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

# NLLB code → short code mapping
_NLLB_TO_SHORT = {"spa_Latn": "es", "por_Latn": "pt"}


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
    session_ids: list[uuid.UUID],
) -> dict[str, str]:
    """
    Build a mapping of session_id → review_status by checking audit logs.

    Returns "approved" if an interpreter_approved entry exists (latest wins),
    "flagged" if interpreter_flagged exists, else "pending".
    """
    if not session_ids:
        return {}

    from db.models import AuditLog

    result = await db.execute(
        select(AuditLog.session_id, AuditLog.action_type)
        .where(
            AuditLog.session_id.in_(session_ids),
            AuditLog.action_type.in_(["interpreter_approved", "interpreter_flagged"]),
        )
        .order_by(desc(AuditLog.created_at))
    )

    statuses: dict[str, str] = {}
    for row in result.all():
        sid = str(row.session_id)
        if sid not in statuses:
            # First (most recent) entry wins
            if row.action_type == "interpreter_approved":
                statuses[sid] = "approved"
            elif row.action_type == "interpreter_flagged":
                statuses[sid] = "flagged"

    return statuses


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review",
    summary="List completed translations for interpreter review",
    response_model=list[ReviewSummary],
    description=(
        "Returns all completed document translation sessions for the review queue. "
        "Includes review status derived from audit logs and signed download URLs "
        "for both original and translated files."
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
    Returns all completed document translation sessions for interpreter review.

    Review status is derived from audit log entries:
    - "approved" if interpreter_approved audit entry exists
    - "flagged" if interpreter_flagged audit entry exists
    - "pending" otherwise
    """
    from db.models import DocumentTranslationRequest
    from db.models import Session as SessionModel

    nllb_target = {"es": "spa_Latn", "pt": "por_Latn"}

    q = (
        select(SessionModel, DocumentTranslationRequest)
        .join(
            DocumentTranslationRequest,
            DocumentTranslationRequest.session_id == SessionModel.session_id,
        )
        .where(
            SessionModel.type == "document",
            DocumentTranslationRequest.status == "completed",
        )
        .order_by(desc(SessionModel.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    if target_language:
        nllb = nllb_target.get(target_language.strip().lower())
        if nllb is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported target_language '{target_language}'. Allowed values: {list(nllb_target.keys())}.",
            )
        q = q.where(SessionModel.target_language == nllb)

    result = await db.execute(q)
    rows = result.all()

    if not rows:
        return []

    # Derive review statuses from audit logs
    session_ids = [s.session_id for s, _r in rows]
    review_statuses = await _get_review_statuses(db, session_ids)

    # Compute signed URL expiry (same for all URLs in this batch)
    now = datetime.now(UTC)
    expires_at = (now + timedelta(seconds=settings.signed_url_expiry_seconds)).isoformat()

    summaries: list[ReviewSummary] = []
    for s, r in rows:
        sid = str(s.session_id)

        # Generate signed URLs for both original and translated files
        signed_original = await _generate_signed_url_if_available(r.input_file_gcs_path)
        signed_translated = await _generate_signed_url_if_available(r.output_file_gcs_path)

        # Extract filename from GCS path
        original_filename = r.input_file_gcs_path.split("/")[-1] if r.input_file_gcs_path else None

        summaries.append(
            ReviewSummary(
                session_id=s.session_id,
                target_language=_NLLB_TO_SHORT.get(s.target_language, s.target_language),
                status=r.status,
                review_status=review_statuses.get(sid, "pending"),
                avg_confidence_score=r.avg_confidence_score,
                llama_corrections_count=r.llama_corrections_count or 0,
                original_filename=original_filename,
                signed_url_original=signed_original,
                signed_url_translated=signed_translated,
                signed_url_expires_at=expires_at if (signed_original or signed_translated) else None,
                created_at=s.created_at.isoformat(),
            )
        )

    return summaries


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review/{session_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review/{session_id}",
    summary="Get session details for review",
    response_model=ReviewSummary,
    description="Returns full review details including signed download URLs for a single session.",
)
async def get_review_session(
    session_id: uuid.UUID,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> ReviewSummary:
    from db.models import DocumentTranslationRequest
    from db.models import Session as SessionModel

    result = await db.execute(
        select(SessionModel, DocumentTranslationRequest)
        .join(
            DocumentTranslationRequest,
            DocumentTranslationRequest.session_id == SessionModel.session_id,
        )
        .where(SessionModel.session_id == session_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    s, r = row

    # Derive review status
    review_statuses = await _get_review_statuses(db, [s.session_id])
    review_status = review_statuses.get(str(s.session_id), "pending")

    # Generate signed URLs
    signed_original = await _generate_signed_url_if_available(r.input_file_gcs_path)
    signed_translated = await _generate_signed_url_if_available(r.output_file_gcs_path)

    now = datetime.now(UTC)
    expires_at = (now + timedelta(seconds=settings.signed_url_expiry_seconds)).isoformat()

    original_filename = r.input_file_gcs_path.split("/")[-1] if r.input_file_gcs_path else None

    return ReviewSummary(
        session_id=s.session_id,
        target_language=_NLLB_TO_SHORT.get(s.target_language, s.target_language),
        status=r.status,
        review_status=review_status,
        avg_confidence_score=r.avg_confidence_score,
        llama_corrections_count=r.llama_corrections_count or 0,
        original_filename=original_filename,
        signed_url_original=signed_original,
        signed_url_translated=signed_translated,
        signed_url_expires_at=expires_at if (signed_original or signed_translated) else None,
        created_at=s.created_at.isoformat(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# POST /interpreter/review/{session_id}/correct
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/review/{session_id}/correct",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a translation correction",
    description="Interpreter submits a correction for a translation in the flagged session. Written to the audit log.",
)
async def submit_correction(
    session_id: uuid.UUID,
    body: TranslationCorrectionRequest,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import Session as SessionModel
    from db.queries.audit import write_audit

    # Verify session exists
    result = await db.execute(select(SessionModel.session_id).where(SessionModel.session_id == session_id))
    if not result.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_correction",
        session_id=session_id,
        details={
            "original_text": body.original_text,
            "original_language": body.original_language,
            "corrected_translation": body.corrected_translation,
            "target_language": body.target_language,
            "notes": body.correction_notes,
        },
    )
    await db.commit()

    logger.info(
        "Interpreter correction submitted: session=%s interpreter=%s target=%s",
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
    summary="Approve a translation",
    description="Mark a translation as approved by the interpreter. Writes an audit log entry.",
)
async def approve_translation(
    session_id: uuid.UUID,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import DocumentTranslationRequest
    from db.models import Session as SessionModel
    from db.queries.audit import write_audit

    result = await db.execute(
        select(DocumentTranslationRequest)
        .join(SessionModel, SessionModel.session_id == DocumentTranslationRequest.session_id)
        .where(DocumentTranslationRequest.session_id == session_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_approved",
        session_id=session_id,
        details={"approved_by": str(interpreter.user_id)},
    )
    await db.commit()

    logger.info(
        "Translation approved: session=%s interpreter=%s",
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
    summary="Flag a translation for recorrection",
    description=(
        "Flag a translation as needing recorrection. Optionally marks the "
        "translation request as failed so it can be re-processed."
    ),
)
async def flag_for_recorrection(
    session_id: uuid.UUID,
    body: FlagRequest,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
    from db.models import DocumentTranslationRequest
    from db.queries.audit import write_audit

    result = await db.execute(
        select(DocumentTranslationRequest).where(DocumentTranslationRequest.session_id == session_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Mark as failed so DAG can re-trigger on next upload attempt
    if body.correction_requested:
        req.status = "failed"
        req.error_message = f"Flagged for recorrection by interpreter: {body.notes}"

    await write_audit(
        db,
        user_id=interpreter.user_id,
        action_type="interpreter_flagged",
        session_id=session_id,
        details={"notes": body.notes, "correction_requested": body.correction_requested},
    )
    await db.commit()

    logger.info(
        "Translation flagged: session=%s interpreter=%s notes=%s",
        session_id,
        interpreter.user_id,
        body.notes[:50],
    )

    return {"status": "flagged", "session_id": str(session_id)}
