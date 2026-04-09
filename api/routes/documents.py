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
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import aliased

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
from db.models import DocumentTranslationRequest, PipelineStep
from db.models import Session as SessionModel
from db.queries.audit import write_audit

logger = logging.getLogger(__name__)
settings = get_settings()


async def _get_airflow_token(client: httpx.AsyncClient) -> str:
    """Exchange Airflow credentials for a JWT (required by Airflow 3.x REST API)."""
    token_resp = await client.post(
        f"{settings.airflow_base_url}/auth/token",
        json={"username": settings.airflow_username, "password": settings.airflow_password},
    )
    token_resp.raise_for_status()
    return token_resp.json()["access_token"]


async def _unpause_for_trigger(client: httpx.AsyncClient, dag_id: str, token: str) -> None:
    """Unpause a DAG so a triggered run will be picked up by the scheduler.

    DAGs start paused (AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=true).
    A dag run triggered against a paused DAG stays in 'queued' forever.
    Call this before POSTing the dagRun, then call _repause_dag after.
    """
    resp = await client.patch(
        f"{settings.airflow_base_url}/api/v2/dags/{dag_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_paused": False},
    )
    resp.raise_for_status()


async def _repause_dag(client: httpx.AsyncClient, dag_id: str, token: str) -> None:
    """Re-pause a DAG after triggering so the scheduler won't fire it on schedule.

    Best-effort — callers should catch and log exceptions rather than failing
    the request, since the dag run has already been queued successfully.
    """
    await client.patch(
        f"{settings.airflow_base_url}/api/v2/dags/{dag_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_paused": True},
    )


router = APIRouter(prefix="/documents", tags=["documents"])

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
_ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/msword",  # .doc
}
_PDF_TYPES = {"application/pdf"}
_DOCX_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
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
    response: Response,
    file: UploadFile = File(...),  # noqa: B008
    target_language: str = Form(
        default="es",
        description="Language code to translate into: 'es' or 'pt'",
    ),
) -> DocumentResponse:
    """
    Validate file, upload to GCS, insert session + translation_request rows,
    trigger the appropriate pipeline DAG. Returns session_id for polling.

    One language per upload — the frontend offers the second language
    on the results page via a second upload call.
    """
    # ── Validate file ────────────────────────────────────────────────────────
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF and Word (.docx/.doc) files accepted. Got: '{file.content_type}'",
        )

    contents = await file.read()

    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds 50 MB ({len(contents) / 1_048_576:.1f} MB received)",
        )

    # Determine format — each DAG validates magic bytes on the downloaded file
    is_pdf = file.content_type in _PDF_TYPES
    dag_id = "document_pipeline_dag" if is_pdf else "docx_pipeline_dag"
    original_format = "pdf" if is_pdf else "docx"

    # ── Compute content hash (dedup key) ─────────────────────────────────────
    content_hash = hashlib.sha256(contents).hexdigest()

    # ── Validate language ────────────────────────────────────────────────────
    lang = target_language.strip().lower()
    if lang not in _NLLB_TARGET:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported language: '{lang}'. Must be 'es' or 'pt'.",
        )
    nllb_target = _NLLB_TARGET[lang]

    # ── Dedup check ──────────────────────────────────────────────────────────
    # Look for a completed translation of the same file+language by this user.
    # Matching on (content_hash, target_language, user_id, status='completed').
    now = datetime.now(tz=UTC)

    dedup_result = await db.execute(
        select(DocumentTranslationRequest)
        .join(SessionModel, SessionModel.session_id == DocumentTranslationRequest.session_id)
        .where(
            DocumentTranslationRequest.content_hash == content_hash,
            DocumentTranslationRequest.target_language == nllb_target,
            SessionModel.user_id == user.user_id,
            DocumentTranslationRequest.status == "completed",
        )
        .limit(1)
    )
    existing = dedup_result.scalar_one_or_none()

    if existing is not None:
        # ── Case A: URL still valid → return immediately, no DAG ─────────────
        if existing.signed_url and existing.signed_url_expires_at and existing.signed_url_expires_at > now:
            logger.info(
                "Dedup hit (URL valid): doc_request_id=%s hash=%s... lang=%s",
                existing.doc_request_id,
                content_hash[:12],
                lang,
            )
            response.status_code = status.HTTP_200_OK
            return DocumentResponse(
                session_id=existing.session_id,
                request_id=existing.doc_request_id,
                status=DocumentStatus.TRANSLATED,
                gcs_input_path=existing.input_file_gcs_path,
                target_language=lang,
                created_at=existing.created_at,
                estimated_completion_seconds=0,
                signed_url=existing.signed_url,
                signed_url_expires_at=existing.signed_url_expires_at,
            )

        # ── Case B: URL expired → regenerate, update row, return ─────────────
        if existing.output_file_gcs_path:
            try:
                bucket, blob_name = gcs.parse_gcs_uri(existing.output_file_gcs_path)
                new_url = await asyncio.to_thread(
                    gcs.generate_signed_url,
                    bucket,
                    blob_name,
                    settings.signed_url_expiry_seconds,
                    settings.gcp_service_account_json,
                )
                new_expires_at = now + timedelta(seconds=settings.signed_url_expiry_seconds)
                existing.signed_url = new_url
                existing.signed_url_expires_at = new_expires_at
                await db.commit()

                logger.info(
                    "Dedup hit (URL refreshed): doc_request_id=%s hash=%s... lang=%s",
                    existing.doc_request_id,
                    content_hash[:12],
                    lang,
                )
                response.status_code = status.HTTP_200_OK
                return DocumentResponse(
                    session_id=existing.session_id,
                    request_id=existing.doc_request_id,
                    status=DocumentStatus.TRANSLATED,
                    gcs_input_path=existing.input_file_gcs_path,
                    target_language=lang,
                    created_at=existing.created_at,
                    estimated_completion_seconds=0,
                    signed_url=new_url,
                    signed_url_expires_at=new_expires_at,
                )
            except Exception as exc:
                # URL regeneration failed — fall through and re-process the file.
                logger.warning(
                    "Dedup hit but URL refresh failed for doc_request_id=%s: %s — re-processing",
                    existing.doc_request_id,
                    exc,
                )

    # ── No exact dedup hit (or URL refresh failed) — check for second language ─

    # ── IDs and timestamps ───────────────────────────────────────────────────
    session_id = uuid.uuid4()
    request_id = uuid.uuid4()
    start_time = now.isoformat()

    # ── Sanitize filename (needed regardless of upload path) ─────────────────
    import os
    import re

    raw_name = os.path.basename(file.filename or "")
    safe_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", raw_name)
    if not safe_name or safe_name.startswith("."):
        safe_name = f"document.{original_format}"

    # ── Second-language dedup: same file, different target language ───────────
    # The user already uploaded this exact file and got a translation in another
    # language. Reuse the existing GCS object — no re-upload needed.
    second_lang_result = await db.execute(
        select(DocumentTranslationRequest)
        .join(SessionModel, SessionModel.session_id == DocumentTranslationRequest.session_id)
        .where(
            DocumentTranslationRequest.content_hash == content_hash,
            DocumentTranslationRequest.target_language != nllb_target,
            SessionModel.user_id == user.user_id,
        )
        .limit(1)
    )
    same_file = second_lang_result.scalar_one_or_none()

    if same_file is not None:
        # Reuse the existing GCS object — skip the upload entirely.
        gcs_path = same_file.input_file_gcs_path
        # Derive filename from the stored path for audit log and DAG conf.
        safe_name = gcs_path.split("/")[-1]
        logger.info(
            "Second-language reuse: gcs=%s new_lang=%s source_doc_request_id=%s",
            gcs_path,
            lang,
            same_file.doc_request_id,
        )
    else:
        # ── Fresh upload — file not seen before ───────────────────────────
        blob_name = f"{session_id}/{safe_name}"
        gcs_path = f"gs://{settings.gcs_bucket_uploads}/{blob_name}"

        try:
            await asyncio.to_thread(
                gcs.upload_bytes,
                settings.gcs_bucket_uploads,
                blob_name,
                contents,
                file.content_type or "application/octet-stream",
            )
        except Exception as exc:
            logger.error("GCS upload failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to upload file to storage. Please try again.",
            ) from exc

    # ── Insert session row ───────────────────────────────────────────────────
    # status='processing' matches the TranslationRequest status inserted below
    # so GET /documents, GET /{session_id}, and DELETE all see a consistent state
    # immediately.  Starting as 'active' would cause the polling endpoints to
    # return PENDING even though the DAG has already been queued, and would
    # allow DELETE to succeed while the DAG is running (the guard checks for
    # 'processing').
    session_obj = SessionModel(
        session_id=session_id,
        user_id=user.user_id,
        type="document",
        target_language=nllb_target,
        status="processing",
        created_at=now,
    )
    db.add(session_obj)

    # ── Insert document_translation_request row ─────────────────────────────
    # The DAG only UPDATEs this row — it never INSERTs.
    request_obj = DocumentTranslationRequest(
        doc_request_id=request_id,
        session_id=session_id,
        input_file_gcs_path=gcs_path,
        target_language=nllb_target,
        content_hash=content_hash,
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
            "filename": safe_name,
            "target_language": lang,
            "gcs_path": gcs_path,
            "file_size_bytes": len(contents),
        },
        session_id=session_id,
        doc_request_id=request_obj.doc_request_id,
    )

    await db.commit()

    # ── Trigger Airflow DAG ──────────────────────────────────────────────────
    # Fire-and-forget with a short timeout. The DB rows are already committed,
    # so even if the trigger call fails the user can retry via the Airflow UI
    # or a re-trigger endpoint. We log the error but don't fail the upload.
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            airflow_token = await _get_airflow_token(client)
            await _unpause_for_trigger(client, dag_id, airflow_token)
            resp = await client.post(
                f"{settings.airflow_base_url}/api/v2/dags/{dag_id}/dagRuns",
                headers={"Authorization": f"Bearer {airflow_token}"},
                json={
                    "logical_date": start_time,
                    "conf": {
                        "session_id": str(session_id),
                        "request_id": str(request_id),
                        "user_id": str(user.user_id),
                        "gcs_input_path": gcs_path,
                        "target_lang": lang,
                        "nllb_target": nllb_target,
                        "filename": safe_name,
                        "start_time": start_time,
                        "original_format": original_format,
                    },
                },
            )
            resp.raise_for_status()
            logger.info(
                "DAG triggered: dag=%s session=%s lang=%s dag_run_id=%s",
                dag_id,
                session_id,
                lang,
                resp.json().get("dag_run_id"),
            )
            try:
                await _repause_dag(client, dag_id, airflow_token)
            except Exception as repause_exc:
                logger.warning("Could not re-pause %s after trigger: %s", dag_id, repause_exc)
    except Exception as exc:
        # Airflow is unreachable or rejected the trigger.  Mark both the
        # TranslationRequest and Session as 'failed' so the row is never
        # permanently stuck as 'processing', then surface a 502 to the caller.
        logger.error("Airflow trigger failed for session=%s: %s", session_id, exc)
        err_msg = f"DAG trigger failed: {exc}"
        request_obj.status = "failed"
        request_obj.error_message = err_msg
        session_obj.status = "failed"
        try:
            await db.commit()
        except Exception as commit_exc:
            logger.error("Failed to persist trigger-failure state for session=%s: %s", session_id, commit_exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File uploaded successfully but the translation pipeline could not be started. "
            "Please try again or contact support.",
        ) from exc

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
        select(SessionModel, DocumentTranslationRequest)
        .join(DocumentTranslationRequest, DocumentTranslationRequest.session_id == SessionModel.session_id)
        .where(SessionModel.session_id == session_id)
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
    # Use a window-function subquery to pick only the *latest* TranslationRequest
    # per session_id.  A plain JOIN would return multiple rows per session when
    # retranslate creates a second TranslationRequest, causing len(items) != total.
    ranked_tr = select(
        DocumentTranslationRequest,
        func.row_number()
        .over(
            partition_by=DocumentTranslationRequest.session_id,
            order_by=desc(DocumentTranslationRequest.created_at),
        )
        .label("rn"),
    ).subquery("ranked_tr")
    latest_tr = aliased(DocumentTranslationRequest, ranked_tr)

    result = await db.execute(
        select(SessionModel, latest_tr)
        .join(ranked_tr, ranked_tr.c.session_id == SessionModel.session_id)
        .where(
            SessionModel.user_id == user.user_id,
            SessionModel.type == "document",
            ranked_tr.c.rn == 1,
        )
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
# ════════════════════════════════════════════════���══════════════════���══════════


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
    # ── Fetch session + all translation requests ─────────────────────────────
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

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

    req_result = await db.execute(
        select(DocumentTranslationRequest).where(DocumentTranslationRequest.session_id == session_id)
    )
    req_objs = req_result.scalars().all()

    # ── Delete GCS objects ───────────────────────────────────────────────────
    # Run deletes concurrently in threads — don't block on either
    gcs_tasks = []
    # input_file_gcs_path lives on DocumentTranslationRequest (not Session)
    if req_objs and req_objs[0].input_file_gcs_path:
        b, bl = gcs.parse_gcs_uri(req_objs[0].input_file_gcs_path)
        gcs_tasks.append(asyncio.to_thread(gcs.delete_blob, b, bl))

    for req_obj in req_objs:
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
        doc_request_id=req_objs[0].doc_request_id if req_objs else None,
    )

    # ── Delete explicitly (DB FK lacks ondelete="CASCADE" for requests) ──────
    for req_obj in req_objs:
        await db.delete(req_obj)

    # ── Delete session (cascades to pipeline_steps) ───
    await db.delete(session_obj)
    await db.commit()

    logger.info("Session deleted: session_id=%s by user_id=%s", session_id, user.user_id)


# ══════════════════════════════════════════════════════════════════════════════
# POST /documents/{session_id}/retranslate
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{session_id}/retranslate",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Re-translate an existing document into a second language",
    description=(
        "Re-uses the original GCS PDF (still in courtaccess-ai-uploads) and "
        "creates a new translation_request row under the same session_id. "
        "Returns a DocumentResponse whose request_id is the new polling key."
    ),
)
async def retranslate_document(
    session_id: uuid.UUID,
    target_language: Annotated[str, Body(..., embed=True)],
    user: Annotated[CurrentUser, Depends(require_verified_email)],
    db: DBSession,
) -> DocumentResponse:
    """
    Validate the session, ensure the new language differs from the original,
    insert a TranslationRequest, and fire a new DAG run.
    """
    # ── Fetch original session ────────────────────────────────────────────────────
    result = await db.execute(select(SessionModel).where(SessionModel.session_id == session_id))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # ── Access control ──────────────────────────────────────────────────────
    if session_obj.user_id != user.user_id and user.role_id not in _ELEVATED_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # ── Validate target language ──────────────────────────────────────────────
    lang = target_language.strip().lower()
    if lang not in _NLLB_TARGET:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported language: '{lang}'. Must be 'es' or 'pt'.",
        )
    nllb_target = _NLLB_TARGET[lang]

    # Guard: don't re-translate into the same language as the original session
    original_lang_short = _NLLB_TO_SHORT.get(session_obj.target_language, session_obj.target_language)
    if lang == original_lang_short:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session already has a '{lang}' translation. Choose a different language.",
        )

    # Guard: GCS input must still exist — fetch the original doc request to get the path
    doc_req_result = await db.execute(
        select(DocumentTranslationRequest).where(DocumentTranslationRequest.session_id == session_id).limit(1)
    )
    original_req = doc_req_result.scalar_one_or_none()
    if not original_req or not original_req.input_file_gcs_path:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Original file is no longer available for re-translation.",
        )

    # ── New IDs and timestamps ──────────────────────────────────────────────
    new_request_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    gcs_path = original_req.input_file_gcs_path

    # ── Insert new document_translation_request under the SAME session ────────
    request_obj = DocumentTranslationRequest(
        doc_request_id=new_request_id,
        session_id=session_id,
        input_file_gcs_path=gcs_path,
        target_language=nllb_target,
        status="processing",
        created_at=now,
    )
    db.add(request_obj)

    await write_audit(
        db,
        user.user_id,
        action_type="document_retranslate",
        details={"target_language": lang, "gcs_path": gcs_path},
        session_id=session_id,
        doc_request_id=request_obj.doc_request_id,
    )

    await db.commit()

    # ── Trigger Airflow DAG ────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            airflow_token = await _get_airflow_token(client)
            await _unpause_for_trigger(client, "document_pipeline_dag", airflow_token)
            resp = await client.post(
                f"{settings.airflow_base_url}/api/v2/dags/document_pipeline_dag/dagRuns",
                headers={"Authorization": f"Bearer {airflow_token}"},
                json={
                    "logical_date": now.isoformat(),
                    "conf": {
                        "session_id": str(session_id),
                        "request_id": str(new_request_id),
                        "user_id": str(user.user_id),
                        "gcs_input_path": gcs_path,
                        "target_lang": lang,
                        "nllb_target": nllb_target,
                        "filename": gcs_path.split("/")[-1],
                        "start_time": now.isoformat(),
                    },
                },
            )
            resp.raise_for_status()
            logger.info(
                "Retranslate DAG triggered: session=%s lang=%s dag_run_id=%s",
                session_id,
                lang,
                resp.json().get("dag_run_id"),
            )
            try:
                await _repause_dag(client, "document_pipeline_dag", airflow_token)
            except Exception as repause_exc:
                logger.warning("Could not re-pause document_pipeline_dag after trigger: %s", repause_exc)
    except Exception as exc:
        # Same pattern as upload_document: mark failed so the row is never
        # left permanently stuck as 'processing'.
        logger.error("Airflow retranslate trigger failed for session=%s: %s", session_id, exc)
        err_msg = f"DAG retranslate trigger failed: {exc}"
        request_obj.status = "failed"
        request_obj.error_message = err_msg
        try:
            await db.commit()
        except Exception as commit_exc:
            logger.error("Failed to persist retranslate trigger-failure for session=%s: %s", session_id, commit_exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Re-translation request saved but the pipeline could not be started. "
            "Please try again or contact support.",
        ) from exc

    return DocumentResponse(
        session_id=session_id,
        request_id=new_request_id,
        status=DocumentStatus.PROCESSING,
        gcs_input_path=gcs_path,
        target_language=lang,
        created_at=now,
        estimated_completion_seconds=300,
    )
