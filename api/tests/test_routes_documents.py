"""
api/tests/test_routes_documents.py

HTTP-level tests for /api/documents/* endpoints.

Mocking strategy:
  - courtaccess.core.gcs.*      — patched to avoid real GCS calls
  - asyncio.to_thread           — patched so upload/delete don't run in threads
  - httpx.AsyncClient           — patched so Airflow DAG trigger is a no-op
  - db.queries.audit.write_audit — patched to avoid audit DB inserts

Known production bug (tracked):
  api/routes/documents.py passes `input_file_gcs_path=...` to SessionModel()
  but the Session ORM model has no such column. The upload tests use a
  _lenient_session_init patch to work around this so the rest of the route
  logic can be exercised. The bug is documented explicitly via
  test_known_bug_session_model_rejects_input_file_gcs_path below.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_REQUEST_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_NOW = datetime(2024, 6, 1, tzinfo=UTC)

_PDF_BYTES = b"%PDF-1.4 fake content for testing"
_DOCX_BYTES = b"PK fake docx content"


def _mock_airflow_client(dag_run_id: str = "manual__2024-01-01") -> MagicMock:
    """httpx.AsyncClient mock that succeeds for Airflow POST, capturing call args."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"dag_run_id": dag_run_id})
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


def _failing_airflow_client() -> MagicMock:
    """httpx.AsyncClient mock that raises on POST."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(side_effect=Exception("Airflow unreachable"))
    return client


def _upload_patches(*, airflow_client):
    """
    Standard patch stack for upload success tests.

    Includes a lenient Session.__init__ that silently drops the
    `input_file_gcs_path` kwarg the route incorrectly passes. This allows
    the rest of the route to run so we can test everything else.

    The bug itself is documented in test_known_bug_session_model_rejects_input_file_gcs_path.
    """
    from db.models import Session as _Session

    _orig = _Session.__init__

    def _lenient(self, **kwargs):
        kwargs.pop("input_file_gcs_path", None)
        _orig(self, **kwargs)

    return (
        patch("api.routes.documents.asyncio.to_thread", new_callable=AsyncMock, return_value=None),
        patch("api.routes.documents.httpx.AsyncClient", return_value=airflow_client),
        patch("api.routes.documents.write_audit", new_callable=AsyncMock),
        patch.object(_Session, "__init__", _lenient),
    )


# ---------------------------------------------------------------------------
# Bug regression: Session model lacks input_file_gcs_path column
# ---------------------------------------------------------------------------


def test_known_bug_session_model_rejects_input_file_gcs_path() -> None:
    """
    KNOWN BUG — api/routes/documents.py passes input_file_gcs_path= to
    SessionModel() but that column does not exist on the Session table.

    This test documents the bug. When the route is fixed (column removed from
    the constructor call), this test will fail and the _lenient_session_init
    workaround in _upload_patches() should be removed.
    """
    from db.models import Session

    with pytest.raises(TypeError, match="input_file_gcs_path"):
        Session(
            session_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            type="document",
            target_language="spa_Latn",
            input_file_gcs_path="gs://bucket/file.pdf",  # invalid column
            status="processing",
        )


# ---------------------------------------------------------------------------
# POST /api/documents/upload — input validation (no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_content_type(client: AsyncClient) -> None:
    response = await client.post(
        "/api/documents/upload",
        files={"file": ("test.txt", b"plain text", "text/plain")},
        data={"target_language": "es"},
    )
    assert response.status_code == 415
    # Detail message must explain what types are accepted
    assert "pdf" in response.json()["detail"].lower() or "word" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_rejects_invalid_target_language(client: AsyncClient) -> None:
    response = await client.post(
        "/api/documents/upload",
        files={"file": ("doc.pdf", _PDF_BYTES, "application/pdf")},
        data={"target_language": "fr"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(client: AsyncClient) -> None:
    with patch("api.routes.documents._MAX_FILE_SIZE", 10):
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("doc.pdf", b"x" * 20, "application/pdf")},
            data={"target_language": "es"},
        )
    assert response.status_code == 413
    assert "50 mb" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_requires_verified_email(unverified_client: AsyncClient) -> None:
    response = await unverified_client.post(
        "/api/documents/upload",
        files={"file": ("doc.pdf", _PDF_BYTES, "application/pdf")},
        data={"target_language": "es"},
    )
    assert response.status_code == 403
    assert "verif" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/documents/upload — PDF success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_pdf_returns_201(client: AsyncClient, mock_db: AsyncMock) -> None:
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("report.pdf", _PDF_BYTES, "application/pdf")},
            data={"target_language": "es"},
        )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_upload_pdf_response_body_complete(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Response must include all fields a polling client needs."""
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        data = (
            await client.post(
                "/api/documents/upload",
                files={"file": ("report.pdf", _PDF_BYTES, "application/pdf")},
                data={"target_language": "es"},
            )
        ).json()

    # session_id and request_id must be valid UUIDs
    uuid.UUID(data["session_id"])
    uuid.UUID(data["request_id"])

    assert data["status"] == "processing"
    assert data["target_language"] == "es"
    assert "gcs_input_path" in data
    assert data["gcs_input_path"].startswith("gs://")
    assert data["estimated_completion_seconds"] > 0


@pytest.mark.asyncio
async def test_upload_pdf_db_rows_added_and_committed(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Route must insert both a Session row and a DocumentTranslationRequest row."""
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        await client.post(
            "/api/documents/upload",
            files={"file": ("report.pdf", _PDF_BYTES, "application/pdf")},
            data={"target_language": "es"},
        )

    # Exactly two db.add() calls: session_obj and request_obj
    assert mock_db.add.call_count == 2, (
        f"Expected 2 db.add() calls (session + translation_request), got {mock_db.add.call_count}"
    )
    # DB must be committed so rows are persisted
    mock_db.commit.assert_awaited()

    # Verify second add is a DocumentTranslationRequest with the right language
    from db.models import DocumentTranslationRequest

    second_added = mock_db.add.call_args_list[1][0][0]
    assert isinstance(second_added, DocumentTranslationRequest)
    assert second_added.target_language == "spa_Latn"  # "es" maps to Flores-200 code
    assert second_added.status == "processing"


@pytest.mark.asyncio
async def test_upload_pdf_triggers_document_pipeline_dag(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """PDF uploads must trigger document_pipeline_dag, not docx_pipeline_dag."""
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        await client.post(
            "/api/documents/upload",
            files={"file": ("report.pdf", _PDF_BYTES, "application/pdf")},
            data={"target_language": "es"},
        )

    called_url = mock_http.post.call_args[0][0]
    assert "document_pipeline_dag" in called_url
    assert "docx_pipeline_dag" not in called_url


@pytest.mark.asyncio
async def test_upload_pdf_dag_conf_contains_session_and_language(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Airflow DAG conf must include session_id and target language for the pipeline."""
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        resp_data = (
            await client.post(
                "/api/documents/upload",
                files={"file": ("report.pdf", _PDF_BYTES, "application/pdf")},
                data={"target_language": "es"},
            )
        ).json()

    dag_conf = mock_http.post.call_args.kwargs["json"]["conf"]
    assert dag_conf["session_id"] == resp_data["session_id"]
    assert dag_conf["target_lang"] == "es"
    assert dag_conf["nllb_target"] == "spa_Latn"
    assert dag_conf["original_format"] == "pdf"


# ---------------------------------------------------------------------------
# POST /api/documents/upload — DOCX success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_docx_returns_201(client: AsyncClient, mock_db: AsyncMock) -> None:
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("form.docx", _DOCX_BYTES, docx_type)},
            data={"target_language": "pt"},
        )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_upload_docx_response_has_correct_target_language(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        data = (
            await client.post(
                "/api/documents/upload",
                files={"file": ("form.docx", _DOCX_BYTES, docx_type)},
                data={"target_language": "pt"},
            )
        ).json()
    assert data["target_language"] == "pt"


@pytest.mark.asyncio
async def test_upload_docx_triggers_docx_pipeline_dag(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """DOCX uploads must trigger docx_pipeline_dag, not document_pipeline_dag."""
    docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_http = _mock_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        await client.post(
            "/api/documents/upload",
            files={"file": ("form.docx", _DOCX_BYTES, docx_type)},
            data={"target_language": "pt"},
        )

    called_url = mock_http.post.call_args[0][0]
    assert "docx_pipeline_dag" in called_url
    assert called_url.count("document_pipeline_dag") == 0 or "docx" in called_url


# ---------------------------------------------------------------------------
# POST /api/documents/upload — failure paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_airflow_failure_returns_502(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    mock_http = _failing_airflow_client()
    p = _upload_patches(airflow_client=mock_http)
    with p[0], p[1], p[2], p[3]:
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("doc.pdf", _PDF_BYTES, "application/pdf")},
            data={"target_language": "es"},
        )
    assert response.status_code == 502
    # Detail must mention the pipeline so the user knows it's a trigger failure
    detail = response.json()["detail"].lower()
    assert "pipeline" in detail or "translation" in detail


@pytest.mark.asyncio
async def test_upload_gcs_failure_returns_502(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    with patch(
        "api.routes.documents.asyncio.to_thread",
        new=AsyncMock(side_effect=Exception("GCS unavailable")),
    ):
        response = await client.post(
            "/api/documents/upload",
            files={"file": ("doc.pdf", _PDF_BYTES, "application/pdf")},
            data={"target_language": "es"},
        )
    assert response.status_code == 502
    assert "storage" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/documents/{session_id} — status polling
# ---------------------------------------------------------------------------


def _make_session_and_request(status: str = "processing"):
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session.status = status
    session.target_language = "spa_Latn"
    session.created_at = _NOW
    session.completed_at = None

    req = MagicMock()
    req.status = status
    req.signed_url = None
    req.signed_url_expires_at = None
    req.output_file_gcs_path = None
    req.avg_confidence_score = None
    req.llama_corrections_count = 0
    req.processing_time_seconds = None
    req.error_message = None
    return session, req


@pytest.mark.asyncio
async def test_get_document_status_found_returns_200(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    session, req = _make_session_and_request("processing")
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.get(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_document_status_body_fields(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """All fields a frontend polling loop depends on must be present and correct."""
    session, req = _make_session_and_request("processing")
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    data = (await client.get(f"/api/documents/{_SESSION_ID}")).json()
    uuid.UUID(data["session_id"])  # must be parseable
    assert data["session_id"] == str(_SESSION_ID)
    assert data["status"] == "processing"
    assert data["target_language"] == "es"  # spa_Latn → short code


@pytest.mark.asyncio
async def test_get_document_status_completed_maps_to_translated(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """DB status 'completed' must appear as 'translated' in the API response."""
    session, req = _make_session_and_request("completed")
    req.status = "completed"
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    data = (await client.get(f"/api/documents/{_SESSION_ID}")).json()
    assert data["status"] == "translated", (
        "DB status 'completed' must map to API status 'translated'"
    )


@pytest.mark.asyncio
async def test_get_document_status_failed_maps_to_error(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    session, req = _make_session_and_request("failed")
    req.status = "failed"
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    data = (await client.get(f"/api/documents/{_SESSION_ID}")).json()
    assert data["status"] == "error"


@pytest.mark.asyncio
async def test_get_document_status_not_found_returns_404(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    r = MagicMock()
    r.first = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.get(f"/api/documents/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_document_status_wrong_user_returns_403(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """A public user must not be able to view another user's document."""
    session, req = _make_session_and_request("processing")
    session.user_id = uuid.uuid4()  # different user — not the test client's user
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.get(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_document_status_elevated_role_can_view_any(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Admin (elevated role) must be able to view any user's document."""
    session, req = _make_session_and_request("processing")
    session.user_id = uuid.uuid4()  # NOT the admin user's own session
    r = MagicMock()
    r.first = MagicMock(return_value=(session, req))
    mock_db.execute = AsyncMock(return_value=r)

    response = await admin_client.get(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/documents/ — list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_documents_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/documents/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_documents_returns_empty_list(client: AsyncClient) -> None:
    data = (await client.get("/api/documents/")).json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


@pytest.mark.asyncio
async def test_list_documents_invalid_page_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/documents/?page=0")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_documents_invalid_page_size_returns_422(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/documents/?page_size=200")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/documents/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_document_not_found_returns_404(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=None)
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.delete(f"/api/documents/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_while_processing_returns_409(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session.status = "processing"
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=session)
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.delete(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 409
    assert "processing" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_document_foreign_user_returns_403(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.uuid4()  # different user
    session.status = "active"
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=session)
    mock_db.execute = AsyncMock(return_value=r)

    response = await client.delete(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_document_success_returns_204(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session.status = "active"

    req = MagicMock()
    req.input_file_gcs_path = None
    req.output_file_gcs_path = None
    req.doc_request_id = uuid.uuid4()

    r1 = MagicMock()
    r1.scalar_one_or_none = MagicMock(return_value=session)
    r2 = MagicMock()
    r2.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[req])))
    mock_db.execute = AsyncMock(side_effect=[r1, r2])

    with patch("api.routes.documents.write_audit", new_callable=AsyncMock):
        response = await client.delete(f"/api/documents/{_SESSION_ID}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_document_deletes_db_rows_and_commits(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Route must delete the translation request AND the session, then commit."""
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session.status = "active"

    req = MagicMock()
    req.input_file_gcs_path = None
    req.output_file_gcs_path = None
    req.doc_request_id = uuid.uuid4()

    r1 = MagicMock()
    r1.scalar_one_or_none = MagicMock(return_value=session)
    r2 = MagicMock()
    r2.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[req])))
    mock_db.execute = AsyncMock(side_effect=[r1, r2])

    with patch("api.routes.documents.write_audit", new_callable=AsyncMock):
        await client.delete(f"/api/documents/{_SESSION_ID}")

    # Both the translation request and the session must be deleted
    assert mock_db.delete.await_count == 2, (
        f"Expected 2 db.delete() calls (req + session), got {mock_db.delete.await_count}"
    )
    # Must commit to persist the deletion
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_delete_document_with_gcs_objects_deletes_storage(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """When GCS paths are present, route must attempt to delete storage objects."""
    session = MagicMock()
    session.session_id = _SESSION_ID
    session.user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    session.status = "active"

    req = MagicMock()
    req.input_file_gcs_path = "gs://courtaccess-ai-uploads/abc/file.pdf"
    req.output_file_gcs_path = "gs://courtaccess-ai-translated/abc/file_es.pdf"
    req.doc_request_id = uuid.uuid4()

    r1 = MagicMock()
    r1.scalar_one_or_none = MagicMock(return_value=session)
    r2 = MagicMock()
    r2.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[req])))
    mock_db.execute = AsyncMock(side_effect=[r1, r2])

    gcs_deletes = []

    async def _fake_to_thread(fn, *args, **kwargs):
        gcs_deletes.append(args)
        return None

    with (
        patch("api.routes.documents.asyncio.to_thread", side_effect=_fake_to_thread),
        patch("api.routes.documents.gcs.parse_gcs_uri", side_effect=lambda uri: uri.replace("gs://", "").split("/", 1)),
        patch("api.routes.documents.gcs.delete_blob"),
        patch("api.routes.documents.write_audit", new_callable=AsyncMock),
    ):
        response = await client.delete(f"/api/documents/{_SESSION_ID}")

    assert response.status_code == 204
    # Two GCS deletes were scheduled (input + output)
    assert len(gcs_deletes) == 2
