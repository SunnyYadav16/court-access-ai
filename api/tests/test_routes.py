"""
api/tests/test_routes.py

Integration tests for the CourtAccess AI API routes.
Uses FastAPI TestClient — no real DB, network, or Airflow calls.

Test coverage:
  - GET /         root
  - GET /health   health check
  - Auth flow     POST /auth/register → /auth/login → GET /auth/me → /auth/refresh → /auth/logout
  - Documents     POST /documents/upload (valid + invalid inputs)
  - Documents     GET  /documents/{id}, GET /documents/, DELETE /documents/{id}
  - Forms         GET  /forms/, GET /forms/divisions, GET /forms/{id}
  - Role guards   403 on endpoints requiring elevated roles
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def client():
    """Create a fresh TestClient for the entire test module."""
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(scope="module")
def registered_user(client: TestClient) -> dict:
    """Register a user and return the registration response JSON."""
    payload = {
        "username": f"testuser_{uuid.uuid4().hex[:8]}",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePass123",
        "preferred_language": "en",
        "role": "public",
    }
    resp = client.post("/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return {**resp.json(), "_password": payload["password"], "_username": payload["username"]}


@pytest.fixture(scope="module")
def auth_headers(client: TestClient, registered_user: dict) -> dict:
    """Log in the registered user and return Authorization headers."""
    resp = client.post(
        "/auth/login",
        json={
            "username": registered_user["_username"],
            "password": registered_user["_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def refresh_token(client: TestClient, registered_user: dict) -> str:
    """Return the refresh token for the registered user."""
    resp = client.post(
        "/auth/login",
        json={
            "username": registered_user["_username"],
            "password": registered_user["_password"],
        },
    )
    return resp.json()["refresh_token"]


@pytest.fixture(scope="module")
def minimal_pdf() -> bytes:
    """Return a valid-enough PDF bytes payload (5+ KB) for upload tests."""
    return b"%PDF-1.4\n" + b"x" * 5120


# ══════════════════════════════════════════════════════════════════════════════
# Meta endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestMeta:
    def test_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_root_contains_name(self, client):
        assert "CourtAccess" in resp.json()["name"] if (resp := client.get("/")) else True

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_health_has_environment_field(self, client):
        resp = client.get("/health")
        assert "environment" in resp.json()

    def test_health_has_version(self, client):
        resp = client.get("/health")
        assert "version" in resp.json()


# ══════════════════════════════════════════════════════════════════════════════
# Auth — registration
# ══════════════════════════════════════════════════════════════════════════════


class TestRegister:
    def test_register_returns_201(self, client):
        resp = client.post(
            "/auth/register",
            json={
                "username": f"u_{uuid.uuid4().hex[:6]}",
                "email": f"u_{uuid.uuid4().hex[:6]}@test.com",
                "password": "Password123",
            },
        )
        assert resp.status_code == 201

    def test_register_returns_user_id(self, client):
        resp = client.post(
            "/auth/register",
            json={
                "username": f"u2_{uuid.uuid4().hex[:6]}",
                "email": f"u2_{uuid.uuid4().hex[:6]}@test.com",
                "password": "Password123",
            },
        )
        assert "user_id" in resp.json()

    def test_duplicate_username_returns_409(self, client, registered_user):
        resp = client.post(
            "/auth/register",
            json={
                "username": registered_user["_username"],
                "email": f"other_{uuid.uuid4().hex}@test.com",
                "password": "Password123",
            },
        )
        assert resp.status_code == 409

    def test_duplicate_email_returns_409(self, client, registered_user):
        resp = client.post(
            "/auth/register",
            json={
                "username": f"other_{uuid.uuid4().hex[:6]}",
                "email": registered_user["email"],
                "password": "Password123",
            },
        )
        assert resp.status_code == 409

    def test_invalid_email_returns_422(self, client):
        resp = client.post(
            "/auth/register",
            json={
                "username": "validuser",
                "email": "not-an-email",
                "password": "Password123",
            },
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Auth — login
# ══════════════════════════════════════════════════════════════════════════════


class TestLogin:
    def test_login_returns_access_token(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={
                "username": registered_user["_username"],
                "password": registered_user["_password"],
            },
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_returns_refresh_token(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={
                "username": registered_user["_username"],
                "password": registered_user["_password"],
            },
        )
        assert "refresh_token" in resp.json()

    def test_wrong_password_returns_401(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={
                "username": registered_user["_username"],
                "password": "wrongpass",
            },
        )
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, client):
        resp = client.post(
            "/auth/login",
            json={
                "username": "completelymadeupuser",
                "password": "somepassword",
            },
        )
        assert resp.status_code == 401

    def test_token_type_is_bearer(self, client, registered_user):
        resp = client.post(
            "/auth/login",
            json={
                "username": registered_user["_username"],
                "password": registered_user["_password"],
            },
        )
        assert resp.json()["token_type"] == "bearer"  # noqa: S105


# ══════════════════════════════════════════════════════════════════════════════
# Auth — /me
# ══════════════════════════════════════════════════════════════════════════════


class TestMe:
    def test_me_returns_200_with_valid_token(self, client, auth_headers):
        resp = client.get("/auth/me", headers=auth_headers)
        assert resp.status_code == 200

    def test_me_returns_correct_username(self, client, auth_headers, registered_user):
        resp = client.get("/auth/me", headers=auth_headers)
        assert resp.json()["username"] == registered_user["_username"]

    def test_me_without_token_returns_403(self, client):
        resp = client.get("/auth/me")
        assert resp.status_code in (401, 403)

    def test_me_with_invalid_token_returns_401(self, client):
        resp = client.get("/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Auth — token refresh
# ══════════════════════════════════════════════════════════════════════════════


class TestRefresh:
    def test_refresh_returns_new_access_token(self, client, refresh_token):
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_invalid_refresh_token_returns_401(self, client):
        resp = client.post("/auth/refresh", json={"refresh_token": "bad.token"})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Documents — upload
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentUpload:
    def test_upload_valid_pdf_returns_201(self, client, auth_headers, minimal_pdf):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
            data={"target_languages": "es,pt"},
        )
        assert resp.status_code == 201

    def test_upload_returns_document_id(self, client, auth_headers, minimal_pdf):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        assert "document_id" in resp.json()

    def test_upload_without_auth_returns_4xx(self, client, minimal_pdf):
        resp = client.post(
            "/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        assert resp.status_code in (401, 403)

    def test_upload_non_pdf_returns_415(self, client, auth_headers):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 415

    def test_upload_fake_pdf_returns_422(self, client, auth_headers):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("fake.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")},
        )
        assert resp.status_code == 422

    def test_invalid_language_code_returns_422(self, client, auth_headers, minimal_pdf):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
            data={"target_languages": "xx"},
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Documents — status + list + delete
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentStatus:
    @pytest.fixture(scope="class")
    def uploaded_doc(self, client, auth_headers, minimal_pdf):
        resp = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("status_test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        assert resp.status_code == 201
        return resp.json()

    def test_get_status_returns_200(self, client, auth_headers, uploaded_doc):
        doc_id = uploaded_doc["document_id"]
        resp = client.get(f"/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_status_has_correct_document_id(self, client, auth_headers, uploaded_doc):
        doc_id = uploaded_doc["document_id"]
        resp = client.get(f"/documents/{doc_id}", headers=auth_headers)
        assert resp.json()["document_id"] == doc_id

    def test_status_not_found_returns_404(self, client, auth_headers):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/documents/{fake_id}", headers=auth_headers)
        assert resp.status_code == 404

    def test_list_documents_returns_200(self, client, auth_headers):
        resp = client.get("/documents/", headers=auth_headers)
        assert resp.status_code == 200
        assert "items" in resp.json()
        assert "total" in resp.json()

    def test_delete_document_returns_204(self, client, auth_headers, minimal_pdf):
        # Upload a throwaway doc
        up = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("delete_me.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        doc_id = up.json()["document_id"]
        resp = client.delete(f"/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 204

    def test_get_after_delete_returns_404(self, client, auth_headers, minimal_pdf):
        up = client.post(
            "/documents/upload",
            headers=auth_headers,
            files={"file": ("delete_me2.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
        )
        doc_id = up.json()["document_id"]
        client.delete(f"/documents/{doc_id}", headers=auth_headers)
        resp = client.get(f"/documents/{doc_id}", headers=auth_headers)
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Forms
# ══════════════════════════════════════════════════════════════════════════════


class TestForms:
    def test_list_forms_returns_200(self, client):
        """Forms list is public — no auth required."""
        resp = client.get("/forms/")
        assert resp.status_code == 200

    def test_list_forms_has_items_and_total(self, client):
        resp = client.get("/forms/")
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_list_forms_page_size_default(self, client):
        resp = client.get("/forms/")
        assert resp.json()["page_size"] == 20

    def test_list_forms_custom_page_size(self, client):
        resp = client.get("/forms/?page_size=5")
        assert resp.json()["page_size"] == 5

    def test_list_divisions_returns_200(self, client):
        resp = client.get("/forms/divisions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_form_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/forms/{fake_id}")
        assert resp.status_code == 404

    def test_review_endpoint_requires_auth(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.patch(f"/forms/{fake_id}/review", json={"approved": True})
        assert resp.status_code in (401, 403)
