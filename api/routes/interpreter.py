"""
api/routes/interpreter.py

Interpreter-only endpoints for the CourtAccess AI API.

All routes are gated by require_role("interpreter") and require a valid Bearer token.

Endpoints:
  GET  /interpreter/review         — List document translation sessions flagged for review
  GET  /interpreter/review/{session_id} — Get a single session's transcript for review
  POST /interpreter/review/{session_id}/correct — Submit a correction to a translation
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from api.dependencies import CurrentUser, DBSession, require_role
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

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


class ReviewSummary(BaseModel):
    """Lightweight summary of a document session that needs review."""

    session_id: uuid.UUID
    target_language: str
    status: str
    avg_confidence_score: float | None
    llama_corrections_count: int
    created_at: str

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review",
    summary="List sessions flagged for interpreter review",
    response_model=list[ReviewSummary],
    description=(
        "Returns document translation sessions where the confidence score is below "
        "threshold or the translation was flagged by the legal verifier. "
        "Interpreter-only endpoint."
    ),
)
async def list_review_sessions(
    interpreter: _InterpreterUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    # Target language filter — interpreters typically cover one language
    target_language: str | None = Query(
        default=None,
        description="Filter by target language code: 'es' or 'pt'",
    ),
) -> list[ReviewSummary]:
    """
    Returns sessions where avg_confidence_score < 0.80 OR llama_corrections_count > 0.

    These are the translations that most benefit from a human review pass.
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
            # Flag: low confidence or LLaMA made corrections
            (DocumentTranslationRequest.avg_confidence_score < 0.80)
            | (DocumentTranslationRequest.llama_corrections_count > 0),
        )
        .order_by(desc(SessionModel.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    if target_language:
        nllb = nllb_target.get(target_language.strip().lower())
        if nllb:
            q = q.where(SessionModel.target_language == nllb)

    result = await db.execute(q)
    rows = result.all()

    return [
        ReviewSummary(
            session_id=s.session_id,
            target_language=s.target_language,
            status=r.status,
            avg_confidence_score=r.avg_confidence_score,
            llama_corrections_count=r.llama_corrections_count,
            created_at=s.created_at.isoformat(),
        )
        for s, r in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
# GET /interpreter/review/{session_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/review/{session_id}",
    summary="Get session transcript for review",
    description="Returns the signed download URL and translation metadata for a session flagged for review.",
)
async def get_review_session(
    session_id: uuid.UUID,
    interpreter: _InterpreterUser,
    db: DBSession,
) -> dict:
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

    return {
        "session_id": str(s.session_id),
        "target_language": s.target_language,
        "status": r.status,
        "avg_confidence_score": r.avg_confidence_score,
        "llama_corrections_count": r.llama_corrections_count,
        "signed_url": r.signed_url,
        "signed_url_expires_at": r.signed_url_expires_at.isoformat() if r.signed_url_expires_at else None,
        "created_at": s.created_at.isoformat(),
    }


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
