"""
api/routes/documents.py

REST endpoints for user-uploaded document translation.

Endpoints:
  POST   /documents/upload                  — Upload PDF, trigger DAG
  GET    /documents/{session_id}            — Poll translation status
  GET    /documents/{session_id}/steps      — Poll per-task progress (progress screen)
  GET    /documents/                        — List current user's document sessions
  DELETE /documents/{session_id}            — Delete session + GCS objects

All endpoints require authentication.
Users can only access their own sessions unless they have
the 'court_official', 'interpreter', or 'admin' role.

DB tables used:
  sessions             — one row per document upload (type='document')
  translation_requests — one row per language run within a session
  pipeline_steps       — one row per DAG task, upserted during processing
  audit_logs           — written on upload and delete
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import desc, func, select

from api.dependencies import CurrentUser, DBSession, require_verified_email
from api.schemas.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentStatus,
    PipelineStepResponse,
    TranslationStatusResponse,
)
from courtaccess.core import gcs
from courtaccess.core.config import get_settings
from db.models import PipelineStep, TranslationRequest
from db.models import Session as SessionModel
from db.queries.audit import write_audit

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/documents", tags=["documents"])

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_ALLOWED_TYPES = {"application/pdf"}
_NLLB_TARGET = {"es": "spa_Latn", "pt": "por_Latn"}
_NLLB_TO_SHORT = {"spa_Latn": "es", "por_Latn": "pt"}

# Maps translation_requests.status → DocumentStatus shown to frontend
_STATUS_MAP = {
    "processing": DocumentStatus.PROCESSING,
    "completed": DocumentStatus.TRANSLATED,
    "failed": DocumentStatus.ERROR,
    "rejected": DocumentStatus.REJECTED,
}

# Role IDs allowed to access other users' documents
_ELEVATED_ROLES = {2, 3, 4}  # court_official, interpreter, admin


# ══════════════════════════════════════════════════════════════════════════════
# POST /documents/upload
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for translation",
)
async def upload_document(
    user: Annotated[CurrentUser, Depends(require_verified_email)],
    db: DBSession,
    file: UploadFile = File(...),  # noqa: B008
    target_language: str = Form(
        default="es",
        description="Language code to translate into: 'es' or 'pt'",
    ),
    notes: str | None = Form(default=None, max_length=500),
) -> DocumentResponse:
    """
    Validate PDF, upload to GCS, insert session + translation_request rows,
    trigger document_pipeline_dag. Returns session_id for polling.

    One language per upload — the frontend offers the second language
    on the results page via a second upload call.
    """
    # ── Validate file ────────────────────────────────────────────────────────
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF files accepted. Got: '{file.content_type}'",
        )

    contents = await file.read()

    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds 50 MB ({len(contents) / 1_048_576:.1f} MB received)",
        )

    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File does not appear to be a valid PDF (missing %PDF- header)",
        )

    # ── Validate language ────────────────────────────────────────────────────
    lang = target_language.strip().lower()
    if lang not in _NLLB_TARGET:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported language: '{lang}'. Must be 'es' or 'pt'.",
        )
    nllb_target = _NLLB_TARGET[lang]

    # ── IDs and timestamps ───────────────────────────────────────────────────
    session_id = uuid.uuid4()
    request_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    start_time = now.isoformat()

    # ── Upload to GCS ────────────────────────────────────────────────────────
    blob_name = f"{session_id}/{file.filename}"
    gcs_path = f"gs://{settings.gcs_bucket_uploads}/{blob_name}"

    try:
        await asyncio.to_thread(
            gcs.upload_bytes,
            settings.gcs_bucket_uploads,
            blob_name,
            contents,
            "application/pdf",
        )
    except Exception as exc:
        logger.error("GCS upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload file to storage. Please try again.",
        ) from exc

    # ── Insert session row ───────────────────────────────────────────────────
    # status='active' is the only valid starting value per the CHECK constraint:
    # ('active', 'processing', 'completed', 'failed', 'ended')
    session_obj = SessionModel(
        session_id=session_id,
        user_id=user.user_id,
        type="document",
        target_language=nllb_target,
        input_file_gcs_path=gcs_path,
        status="active",
        created_at=now,
    )
    db.add(session_obj)

    # ── Insert translation_request row ───────────────────────────────────────
    # The DAG only UPDATEs this row — it never INSERTs.
    request_obj = TranslationRequest(
        request_id=request_id,
        session_id=session_id,
        target_language=nllb_target,
        status="processing",
        created_at=now,
    )
    db.add(request_obj)

    # ── Audit log ────────────────────────────────────────────────────────────
    await write_audit(
        db,
        user.user_id,
        action_type="document_upload",
        details={
            "filename": file.filename,
            "target_language": lang,
            "gcs_path": gcs_path,
            "file_size_bytes": len(contents),
        },
        session_id=session_id,
        request_id=request_id,
    )

    await db.commit()

    # ── Trigger Airflow DAG ──────────────────────────────────────────────────
    # Fire-and-forget with a short timeout. The DB rows are already committed,
    # so even if the trigger call fails the user can retry via the Airflow UI
    # or a re-trigger endpoint. We log the error but don't fail the upload.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.airflow_base_url}/api/v2/dags/document_pipeline_dag/dagRuns",
                auth=(settings.airflow_username, settings.airflow_password),
                json={
                    "conf": {
                        "session_id": str(session_id),
                        "request_id": str(request_id),
                        "user_id": str(user.user_id),
                        "gcs_input_path": gcs_path,
                        "target_lang": lang,
                        "nllb_target": nllb_target,
                        "filename": file.filename,
                        "start_time": start_time,
                    }
                },
            )
            resp.raise_for_status()
            logger.info(
                "DAG triggered: session=%s lang=%s dag_run_id=%s",
                session_id,
                lang,
                resp.json().get("dag_run_id"),
            )
    except Exception as exc:
        # Log but don't fail — the translation_request row is already in the DB
        # with status='processing'. An admin can re-trigger from the Airflow UI.
        logger.error("Airflow trigger failed for session=%s: %s", session_id, exc)

    return DocumentResponse(
        session_id=session_id,
        request_id=request_id,
        status=DocumentStatus.PROCESSING,
        gcs_input_path=gcs_path,
        target_language=lang,
        created_at=now,
        estimated_completion_seconds=300,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /documents/{session_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/{session_id}",
    response_model=TranslationStatusResponse,
    summary="Poll translation status",
    description=(
        "Poll the translation status for a document session. "
        "When status is 'translated', signed_url contains a GCS download URL "
        "valid for 1 hour."
    ),
)
async def get_document_status(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> TranslationStatusResponse:
    # ── Fetch session + latest translation_request ───────────────────────────
    result = await db.execute(
        select(SessionModel, TranslationRequest)
        .join(TranslationRequest, TranslationRequest.session_id == SessionModel.session_id)
        .where(SessionModel.session_id == session_id)
        .order_by(desc(TranslationRequest.created_at))
        .limit(1)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    session_obj, req_obj = row

    # ── Access control ───────────────────────────────────────────────────────
    if session_obj.user_id != user.user_id and user.role_id not in _ELEVATED_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # ── Map DB status → DocumentStatus ──────────────────────────────────────
    # sessions.status drives PENDING/PROCESSING state.
    # translation_requests.status drives terminal states.
    if session_obj.status == "active":
        doc_status = DocumentStatus.PENDING
    else:
        doc_status = _STATUS_MAP.get(req_obj.status, DocumentStatus.PROCESSING)

    return TranslationStatusResponse(
        session_id=session_obj.session_id,
        status=doc_status,
        target_language=_NLLB_TO_SHORT.get(session_obj.target_language, session_obj.target_language),
        created_at=session_obj.created_at,
        completed_at=session_obj.completed_at,
        signed_url=req_obj.signed_url,
        signed_url_expires_at=req_obj.signed_url_expires_at,
        gcs_output_path=req_obj.output_file_gcs_path,
        avg_confidence_score=req_obj.avg_confidence_score,
        llama_corrections_count=req_obj.llama_corrections_count or 0,
        processing_time_seconds=req_obj.processing_time_seconds,
        error_message=req_obj.error_message,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /documents/{session_id}/steps
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/{session_id}/steps",
    response_model=list[PipelineStepResponse],
    summary="Get per-task pipeline progress",
    description=(
        "Returns one row per DAG task for the progress screen. Poll every 2-3 seconds while status is 'processing'."
    ),
)
async def get_pipeline_steps(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> list[PipelineStepResponse]:
    # ── Verify session ownership ─────────────────────────────────────────────
    result = await db.execute(select(SessionModel.user_id).where(SessionModel.session_id == session_id))
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row.user_id != user.user_id and user.role_id not in _ELEVATED_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # ── Fetch steps ordered by update time ───────────────────────────────────
    result = await db.execute(
        select(PipelineStep).where(PipelineStep.session_id == session_id).order_by(PipelineStep.updated_at)
    )
    steps = result.scalars().all()

    return [
        PipelineStepResponse(
            step_name=s.step_name,
            status=s.status,
            detail=s.detail,
            metadata=s.step_metadata or {},
            updated_at=s.updated_at,
        )
        for s in steps
    ]


# ══════════════════════════════════════════════════════════════════════════════
# GET /documents/
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List user's document sessions",
)
async def list_documents(
    user: CurrentUser,
    db: DBSession,
    page: int = 1,
    page_size: int = 20,
) -> DocumentListResponse:
    if page < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="page must be ≥ 1")
    if not 1 <= page_size <= 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="page_size must be 1-100")

    # ── Total count ──────────────────────────────────────────────────────────
    count_result = await db.execute(
        select(func.count())
        .select_from(SessionModel)
        .where(SessionModel.user_id == user.user_id, SessionModel.type == "document")
    )
    total = count_result.scalar_one()

    # ── Paginated rows ───────────────────────────────────────────────────────
    result = await db.execute(
        select(SessionModel, TranslationRequest)
        .join(TranslationRequest, TranslationRequest.session_id == SessionModel.session_id)
        .where(SessionModel.user_id == user.user_id, SessionModel.type == "document")
        .order_by(desc(SessionModel.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    items = [
        TranslationStatusResponse(
            session_id=s.session_id,
            status=(
                DocumentStatus.PENDING if s.status == "active" else _STATUS_MAP.get(r.status, DocumentStatus.PROCESSING)
            ),
            target_language=_NLLB_TO_SHORT.get(s.target_language, s.target_language),
            created_at=s.created_at,
            completed_at=s.completed_at,
            signed_url=r.signed_url,
            signed_url_expires_at=r.signed_url_expires_at,
            gcs_output_path=r.output_file_gcs_path,
            avg_confidence_score=r.avg_confidence_score,
            llama_corrections_count=r.llama_corrections_count or 0,
            processing_time_seconds=r.processing_time_seconds,
            error_message=r.error_message,
        )
        for s, r in rows
    ]

    return DocumentListResponse(items=items, total=total, page=page, page_size=page_size)


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /documents/{session_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document session",
    description=(
        "Delete the session, its translation_request, pipeline_steps, "
        "and GCS objects. Cannot delete while status is 'processing'."
    ),
)
async def delete_document(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> None:
    # ── Fetch session + request ──────────────────────────────────────────────
    result = await db.execute(
        select(SessionModel, TranslationRequest)
        .join(TranslationRequest, TranslationRequest.session_id == SessionModel.session_id)
        .where(SessionModel.session_id == session_id)
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    session_obj, req_obj = row

    # ── Access control ───────────────────────────────────────────────────────
    if session_obj.user_id != user.user_id and user.role_id != 4:  # admin only
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # ── Block deletion while DAG is running ──────────────────────────────────
    if session_obj.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a session that is currently processing. "
            "Wait for completion or contact an admin to cancel the DAG run.",
        )

    # ── Delete GCS objects ───────────────────────────────────────────────────
    # Run both deletes concurrently in threads — don't block on either
    gcs_tasks = []
    if session_obj.input_file_gcs_path:
        b, bl = gcs.parse_gcs_uri(session_obj.input_file_gcs_path)
        gcs_tasks.append(asyncio.to_thread(gcs.delete_blob, b, bl))
    if req_obj.output_file_gcs_path:
        b, bl = gcs.parse_gcs_uri(req_obj.output_file_gcs_path)
        gcs_tasks.append(asyncio.to_thread(gcs.delete_blob, b, bl))
    if gcs_tasks:
        await asyncio.gather(*gcs_tasks, return_exceptions=True)

    # ── Audit log before deletion ────────────────────────────────────────────
    await write_audit(
        db,
        user.user_id,
        action_type="document_delete",
        details={"deleted_by": str(user.user_id), "session_status": session_obj.status},
        session_id=session_id,
        request_id=req_obj.request_id,
    )

    # ── Delete session (cascades to translation_requests + pipeline_steps) ───
    await db.delete(session_obj)
    await db.commit()

    logger.info("Session deleted: session_id=%s by user_id=%s", session_id, user.user_id)
