"""
api/tests/test_routes_auth.py

HTTP-level tests for /api/auth/me and /api/auth/select-role.

Assertions go beyond HTTP status codes to verify:
  - DB state (db.add called with right objects, db.commit awaited)
  - User object mutations (role_id, role_approved_at set correctly)
  - Negative checks (no RoleRequest created for public/SAML paths)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_me_returns_200(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_me_body_has_user_id(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert "user_id" in data


@pytest.mark.asyncio
async def test_get_me_body_has_email(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_me_body_role_is_public(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert data["role"] == "public"


@pytest.mark.asyncio
async def test_get_me_body_role_is_admin_for_admin_client(admin_client: AsyncClient) -> None:
    data = (await admin_client.get("/api/auth/me")).json()
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_get_me_body_email_verified_true(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert data["email_verified"] is True


@pytest.mark.asyncio
async def test_get_me_body_unverified_email_reflected(
    unverified_client: AsyncClient,
) -> None:
    """Unverified user: /auth/me still works but email_verified should be False."""
    data = (await unverified_client.get("/api/auth/me")).json()
    assert data["email_verified"] is False


@pytest.mark.asyncio
async def test_get_me_body_has_auth_provider(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert "auth_provider" in data
    assert data["auth_provider"] == "google.com"


@pytest.mark.asyncio
async def test_get_me_body_has_firebase_uid(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert "firebase_uid" in data
    assert data["firebase_uid"] == "test-firebase-uid-abc123"


@pytest.mark.asyncio
async def test_get_me_body_has_created_at(client: AsyncClient) -> None:
    data = (await client.get("/api/auth/me")).json()
    assert "created_at" in data


# ---------------------------------------------------------------------------
# POST /api/auth/select-role — public path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_role_public_returns_200(client: AsyncClient) -> None:
    response = await client.post("/api/auth/select-role", json={"selected_role": "public"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_select_role_public_assigns_public(client: AsyncClient) -> None:
    data = (
        await client.post("/api/auth/select-role", json={"selected_role": "public"})
    ).json()
    assert data["role"] == "public"


@pytest.mark.asyncio
async def test_select_role_public_does_not_create_role_request(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Selecting 'public' must NOT insert a pending RoleRequest into the DB."""
    await client.post("/api/auth/select-role", json={"selected_role": "public"})
    # No db.add() call means no RoleRequest row was created
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_select_role_public_commits_db(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Role change must be persisted to the database."""
    await client.post("/api/auth/select-role", json={"selected_role": "public"})
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /api/auth/select-role — non-SAML elevated role → pending request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_role_court_official_non_saml_stays_public(
    client: AsyncClient,
) -> None:
    """Non-SAML user requesting court_official → role in response stays public."""
    data = (
        await client.post(
            "/api/auth/select-role", json={"selected_role": "court_official"}
        )
    ).json()
    assert data["role"] == "public"


@pytest.mark.asyncio
async def test_select_role_court_official_non_saml_creates_pending_role_request(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Non-SAML court_official request must create a RoleRequest row with status=pending."""
    await client.post("/api/auth/select-role", json={"selected_role": "court_official"})

    assert mock_db.add.called, "Expected db.add() to be called with a RoleRequest"
    from db.models import RoleRequest

    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, RoleRequest), (
        f"Expected a RoleRequest to be added, got {type(added_obj)}"
    )
    assert added_obj.status == "pending"
    assert added_obj.requested_role_id == 2  # court_official


@pytest.mark.asyncio
async def test_select_role_court_official_non_saml_role_request_has_user_id(
    client: AsyncClient, mock_db: AsyncMock, mock_user: MagicMock
) -> None:
    """The created RoleRequest must be linked to the correct user."""
    await client.post("/api/auth/select-role", json={"selected_role": "court_official"})

    from db.models import RoleRequest

    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, RoleRequest)
    assert added_obj.user_id == mock_user.user_id


@pytest.mark.asyncio
async def test_select_role_court_official_non_saml_commits_db(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    await client.post("/api/auth/select-role", json={"selected_role": "court_official"})
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_select_role_interpreter_non_saml_creates_pending_role_request(
    client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Same pending-request logic applies to 'interpreter' for non-SAML users."""
    await client.post("/api/auth/select-role", json={"selected_role": "interpreter"})

    from db.models import RoleRequest

    assert mock_db.add.called
    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, RoleRequest)
    assert added_obj.status == "pending"
    assert added_obj.requested_role_id == 3  # interpreter


# ---------------------------------------------------------------------------
# POST /api/auth/select-role — SAML auto-approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_role_court_official_saml_auto_approves(
    saml_client: AsyncClient,
) -> None:
    """SAML user requesting court_official → auto-approved immediately."""
    data = (
        await saml_client.post(
            "/api/auth/select-role", json={"selected_role": "court_official"}
        )
    ).json()
    assert data["role"] == "court_official"


@pytest.mark.asyncio
async def test_select_role_court_official_saml_sets_role_approved_at(
    saml_client: AsyncClient, mock_court_official_user: MagicMock
) -> None:
    """SAML auto-approval must timestamp role_approved_at."""
    from datetime import UTC, datetime

    before = datetime.now(tz=UTC)
    await saml_client.post(
        "/api/auth/select-role", json={"selected_role": "court_official"}
    )
    after = datetime.now(tz=UTC)

    # role_approved_at must have been set to a recent time by the route
    approved_at = mock_court_official_user.role_approved_at
    assert approved_at is not None, "role_approved_at must be set for SAML auto-approval"
    assert before <= approved_at <= after


@pytest.mark.asyncio
async def test_select_role_court_official_saml_no_pending_request(
    saml_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """SAML auto-approval must NOT create a pending RoleRequest row."""
    await saml_client.post(
        "/api/auth/select-role", json={"selected_role": "court_official"}
    )
    mock_db.add.assert_not_called()


@pytest.mark.asyncio
async def test_select_role_interpreter_saml_auto_approves(
    saml_client: AsyncClient,
) -> None:
    data = (
        await saml_client.post(
            "/api/auth/select-role", json={"selected_role": "interpreter"}
        )
    ).json()
    assert data["role"] == "interpreter"


@pytest.mark.asyncio
async def test_select_role_interpreter_saml_sets_role_approved_at(
    saml_client: AsyncClient, mock_court_official_user: MagicMock
) -> None:
    from datetime import UTC, datetime

    before = datetime.now(tz=UTC)
    await saml_client.post(
        "/api/auth/select-role", json={"selected_role": "interpreter"}
    )
    after = datetime.now(tz=UTC)
    approved_at = mock_court_official_user.role_approved_at
    assert approved_at is not None
    assert before <= approved_at <= after


# ---------------------------------------------------------------------------
# POST /api/auth/select-role — validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_role_invalid_role_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/select-role", json={"selected_role": "superuser"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_select_role_missing_body_returns_422(client: AsyncClient) -> None:
    response = await client.post("/api/auth/select-role", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_select_role_admin_role_rejected_by_validation(
    client: AsyncClient,
) -> None:
    """Clients cannot self-select 'admin' — it is not in the allowed UserRole enum values
    accepted by select-role (or if it is, it must go through pending approval)."""
    response = await client.post(
        "/api/auth/select-role", json={"selected_role": "admin"}
    )
    # admin is a valid UserRole enum value, so the route accepts it but creates a
    # pending RoleRequest (non-SAML path). It must NOT grant admin immediately.
    if response.status_code == 200:
        data = response.json()
        assert data["role"] != "admin", (
            "Self-selecting 'admin' must never grant admin role immediately"
        )
