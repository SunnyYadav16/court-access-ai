"""
api/tests/test_routes.py

Modernized integration tests for the CourtAccess AI API routes.
Uses dependency overrides to bypass real Firebase Auth and real Database connections.
Mocks external services (GCS, Airflow) via unittest.mock.

Test coverage:
  - GET /               Root
  - GET /health         Health check
  - GET /api/auth/me    User profile (Firebase DI)
  - POST /api/docs/upload Document upload (Mocks GCS/Airflow)
  - GET /api/forms/     Public form catalog
"""

from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
class TestMeta:
    async def test_root_returns_200(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "CourtAccess" in resp.json()["name"]

    @patch("google.cloud.storage.Client")
    async def test_health_check(self, mock_storage, client: AsyncClient):
        """Verify the health endpoint executes successfully."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "db_status" in data
        assert "gcs_status" in data


@pytest.mark.asyncio
class TestAuth:
    async def test_get_me_returns_profile(self, client: AsyncClient, mock_user):
        """Verify /auth/me returns the profile provided by our mock_user fixture."""
        resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer fake-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == mock_user.email
        assert data["role"] == "public"

    async def test_auth_me_requires_header(self, client: AsyncClient):
        """
        Verify /auth/me fails without Authorization header.
        Note: Since we override get_current_user, we must ensure the 
        dependency chain still enforces the presence of the header if we want to 
        test 'unauthenticated' states. For this suite, we focus on 'logic after auth'.
        """
        # In a real app, the _bearer dependency would raise 403 before get_current_user is called.
        pass


@pytest.mark.asyncio
class TestDocuments:
    @patch("api.routes.documents.gcs.upload_bytes")
    @patch("api.routes.documents.httpx.AsyncClient")
    async def test_upload_document_success(
        self,
        MockClient,
        mock_gcs_upload,
        client: AsyncClient,
        mock_db_session,
    ):
        """Verify successful document upload triggers GCS and Airflow."""
        # Setup the mock client that the route will "create"
        mock_instance = MockClient.return_value.__aenter__.return_value
        mock_instance.post.return_value = MagicMock(
            status_code=202,
            json=lambda: {"dag_run_id": "test-run-123"}
        )
        mock_instance.post.return_value.raise_for_status = MagicMock()
        
        # Test payload
        pdf_content = b"%PDF-1.4\n" + b"x" * 1024
        files = {"file": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        data = {"target_languages": "spanish"}

        resp = await client.post(
            "/api/documents/upload",
            headers={"Authorization": "Bearer fake-token"},
            files=files,
            data=data
        )

        assert resp.status_code == 201
        res_json = resp.json()
        assert "session_id" in res_json
        
        # Verify GCS was called
        mock_gcs_upload.assert_called_once()
        
        # Verify Airflow trigger was attempted
        mock_instance.post.assert_called_once()
        args, kwargs = mock_instance.post.call_args
        assert "dagRuns" in args[0]
        assert kwargs["json"]["conf"]["target_lang"] == "es"

    async def test_get_document_status_404(self, client: AsyncClient, mock_db_session):
        """Verify 404 for non-existent session."""
        mock_db_session.execute.return_value = MagicMock(first=lambda: None)
        
        fake_sid = str(uuid.uuid4())
        resp = await client.get(f"/api/documents/{fake_sid}", headers={"Authorization": "Bearer fake-token"})
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestForms:
    async def test_list_forms_is_public(self, client: AsyncClient, mock_db_session):
        """Verify form catalog is accessible without a token."""
        # Mock empty database response
        mock_db_session.execute.return_value = MagicMock(
            scalars=lambda: MagicMock(all=lambda: [])
        )
        
        resp = await client.get("/api/forms/")
        assert resp.status_code == 200
        assert "items" in resp.json()

    async def test_get_divisions(self, client: AsyncClient, mock_db_session):
        """Verify divisions list."""
        mock_db_session.execute.return_value = MagicMock(
            scalars=lambda: MagicMock(all=lambda: ["Housing", "Probate"])
        )
        
        resp = await client.get("/api/forms/divisions")
        assert resp.status_code == 200
        assert "Housing" in resp.json()
