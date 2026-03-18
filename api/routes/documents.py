"""
api/routes/documents.py

REST endpoints for user-uploaded document translation.

Endpoints:
  POST   /documents/upload         — Upload a PDF, trigger document_pipeline_dag
  GET    /documents/{document_id}  — Poll translation status + get signed URLs
  GET    /documents/               — List current user's documents (paginated)
  DELETE /documents/{document_id}  — Delete a document and its translations

All endpoints require authentication. Users can only access their own documents
unless they have the 'court_official' or 'admin' role.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.dependencies import CurrentUser, DBSession, require_verified_email
from api.schemas.schemas import (
    DocumentListResponse,
    DocumentResponse,
    DocumentStatus,
    Language,
    TranslationStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# ── In-memory document store (replace with DB + GCS in production) ────────────
_documents: dict[str, dict] = {}

# ── Constants ─────────────────────────────────────────────────────────────────
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_ALLOWED_CONTENT_TYPES = {"application/pdf"}


# ══════════════════════════════════════════════════════════════════════════════
# POST /documents/upload
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document for translation",
    description=(
        "Upload a PDF document (≤50 MB). Returns a document_id for status polling. "
        "Translation runs asynchronously via Airflow document_pipeline_dag."
    ),
)
async def upload_document(
    user: Annotated[CurrentUser, Depends(require_verified_email)],  # Requires verified email
    db: DBSession,
    file: UploadFile = File(..., description="PDF file to translate"),  # noqa: B008
    target_languages: str = Form(
        default="es,pt",
        description="Comma-separated language codes: 'es', 'pt', or 'es,pt'",
    ),
    notes: str | None = Form(default=None, max_length=500),
) -> DocumentResponse:
    """
    Accept a PDF upload, validate it, and enqueue a document translation pipeline.
    
    Validations performed:
    - Content-Type must be "application/pdf".
    - File size must be less than or equal to 50 MB.
    - File must start with the PDF magic bytes ("%PDF-").
    - Target language codes must be supported ('es' or 'pt').
    
    Parameters:
        file: Uploaded PDF file to translate.
        target_languages: Comma-separated language codes (e.g., "es,pt"); defaults to "es,pt".
        notes: Optional user-provided notes (max 500 characters).
    
    Returns:
        DocumentResponse: Contains `document_id`, `status` (PENDING), `upload_path`, `created_at`, and `estimated_completion_seconds`.
    
    Raises:
        HTTPException: 415 if content type is not PDF; 413 if file exceeds 50 MB; 422 if file is not a valid PDF or if an unsupported language code is provided.
    """
    # ── Content-type check ───────────────────────────────────────────────────
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Only PDF files are accepted. Got: '{file.content_type}'",
        )

    # ── Size check ───────────────────────────────────────────────────────────
    contents = await file.read()
    if len(contents) > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds 50 MB limit ({len(contents) / 1_048_576:.1f} MB received)",
        )

    # ── Magic bytes check ────────────────────────────────────────────────────
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File does not appear to be a valid PDF (missing %PDF- header)",
        )

    # ── Parse languages ──────────────────────────────────────────────────────
    langs = []
    for code in target_languages.split(","):
        code = code.strip().lower()
        try:
            langs.append(Language(code))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported language code: '{code}'. Must be 'es' or 'pt'.",
            ) from exc
    if not langs:
        langs = [Language.SPANISH, Language.PORTUGUESE]

    # ── Persist (STUB) ───────────────────────────────────────────────────────
    doc_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    upload_path = f"/opt/airflow/uploads/{doc_id}/{file.filename}"

    _documents[str(doc_id)] = {
        "document_id": doc_id,
        "user_id": user.user_id,
        "status": DocumentStatus.PENDING,
        "upload_path": upload_path,
        "created_at": now,
        "completed_at": None,
        "target_languages": [lang.value for lang in langs],
        "notes": notes,
        "translation_urls": {},
        "legal_review_status": {},
        "pii_findings_count": 0,
        "needs_human_review": True,
        "error_message": None,
    }

    logger.info(
        "Document uploaded: doc_id=%s user_id=%s size=%d bytes file=%s langs=%s",
        doc_id,
        user.user_id,
        len(contents),
        file.filename,
        langs,
    )

    # TODO: Trigger Airflow DAG via REST
    # await _trigger_airflow_dag("document_pipeline_dag", {
    #     "document_id": str(doc_id),
    #     "user_id": str(user.user_id),
    #     "upload_path": upload_path,
    #     "target_langs": [l.value for l in langs],
    # })

    return DocumentResponse(
        document_id=doc_id,
        status=DocumentStatus.PENDING,
        upload_path=upload_path,
        created_at=now,
        estimated_completion_seconds=300,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /documents/{document_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/{document_id}",
    response_model=TranslationStatusResponse,
    summary="Get translation status",
    description=(
        "Poll the translation status for a document. "
        "When status is 'translated', translation_urls contains signed GCS URLs "
        "valid for 1 hour."
    ),
)
async def get_document_status(
    document_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> TranslationStatusResponse:
    """
    Retrieve translation status and associated metadata for a document.
    
    Raises:
        HTTPException: 404 if the document does not exist.
        HTTPException: 403 if the authenticated user is neither the owner nor has a role_id of 4 (admin), 2 (court_official), or 3 (interpreter).
    
    Returns:
        TranslationStatusResponse: Document status and related fields including timestamps, PII findings count, translation URLs, legal review status, human review flag, and any error message.
    """
    doc = _documents.get(str(document_id))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if doc["user_id"] != user.user_id and user.role_id not in (4, 2, 3):  # admin, court_official, interpreter
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return TranslationStatusResponse(
        document_id=doc["document_id"],
        status=doc["status"],
        created_at=doc["created_at"],
        completed_at=doc["completed_at"],
        pii_findings_count=doc["pii_findings_count"],
        translation_urls=doc["translation_urls"],
        legal_review_status=doc["legal_review_status"],
        needs_human_review=doc["needs_human_review"],
        error_message=doc["error_message"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /documents/
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List user's documents",
    description="Return a paginated list of all documents uploaded by the current user.",
)
async def list_documents(
    user: CurrentUser,
    db: DBSession,
    page: int = 1,
    page_size: int = 20,
) -> DocumentListResponse:
    """
    Return a paginated list of documents belonging to the authenticated user.
    
    Documents are ordered by created_at descending and limited to documents owned by the current user. Pagination parameters must satisfy page >= 1 and 1 <= page_size <= 100.
    
    Parameters:
        page (int): Page number to retrieve (1-based).
        page_size (int): Number of items per page.
    
    Returns:
        DocumentListResponse: Contains `items` (list of TranslationStatusResponse), `total` (total documents for the user), `page`, and `page_size`.
    
    Raises:
        HTTPException: If `page` < 1 or `page_size` is outside the 1–100 range.
    """
    if page < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="page must be ≥ 1")
    if not 1 <= page_size <= 100:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="page_size must be 1-100")

    user_docs = [d for d in _documents.values() if d["user_id"] == user.user_id]
    user_docs.sort(key=lambda d: d["created_at"], reverse=True)

    start = (page - 1) * page_size
    page_items = user_docs[start : start + page_size]

    items = [
        TranslationStatusResponse(
            document_id=d["document_id"],
            status=d["status"],
            created_at=d["created_at"],
            completed_at=d["completed_at"],
            pii_findings_count=d["pii_findings_count"],
            translation_urls=d["translation_urls"],
            legal_review_status=d["legal_review_status"],
            needs_human_review=d["needs_human_review"],
            error_message=d["error_message"],
        )
        for d in page_items
    ]

    return DocumentListResponse(
        items=items,
        total=len(user_docs),
        page=page,
        page_size=page_size,
    )


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /documents/{document_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document",
    description=(
        "Delete a document and all its translations. "
        "GCS objects are also deleted. Cannot delete documents with status 'processing'."
    ),
)
async def delete_document(
    document_id: uuid.UUID,
    user: CurrentUser,
    db: DBSession,
) -> None:
    """
    Delete a document if the caller is authorized and the document is not currently processing.
    
    Deletes the document from the store when the requesting user owns the document or when the requester is an admin (role_id == 4). Deletion is disallowed while the document status is PROCESSING.
    
    Raises:
        HTTPException: 404 if the document does not exist.
        HTTPException: 403 if the caller is not the owner and not an admin.
        HTTPException: 409 if the document is currently being processed and cannot be deleted.
    """
    doc = _documents.get(str(document_id))
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if doc["user_id"] != user.user_id and user.role_id != 4:  # admin
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if doc["status"] == DocumentStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a document that is currently being processed. "
            "Wait for completion or contact an admin.",
        )

    del _documents[str(document_id)]
    logger.info("Document deleted: doc_id=%s by user_id=%s", document_id, user.user_id)
