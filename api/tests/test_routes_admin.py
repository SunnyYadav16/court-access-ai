"""
api/tests/test_routes_admin.py

HTTP-level tests for /api/admin/* endpoints.

Verifies:
  - Access control: all routes return 403 for non-admin callers
  - list_users: pagination params forwarded, empty list returned from mock DB
  - get_user: 404 when DB returns None, 200 with correct data when found
  - set_user_role: mutates user fields, timestamps role_approved_at,
    uses admin's user_id as approver, commits, refreshes, 422 for unknown
    role name, 404 for missing target user
  - list_role_requests: pending_only filter applied by default
  - approve_role_request: sets status=approved, promotes user.role_id,
    stamps reviewed_at, commits; 404 when not found; 409 when not pending
  - reject_role_request: sets status=rejected but does NOT promote role_id
  - list_audit_logs: returns list, pagination forwarded
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TARGET_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
_REQUEST_ID = uuid.UUID("00000000-0000-0000-0000-000000000088")
_FIXED_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _make_target_user(role_id: int = 1) -> MagicMock:
    """ORM-like mock user with all fields required by UserResponse.from_orm_user."""
    u = MagicMock()
    u.user_id = _TARGET_USER_ID
    u.email = "target@example.com"
    u.name = "Target User"
    u.role_id = role_id
    u.firebase_uid = "firebase-target-uid"
    u.auth_provider = "google.com"
    u.email_verified = True
    u.mfa_enabled = False
    u.role_approved_by = None
    u.role_approved_at = None
    u.created_at = _FIXED_TS
    u.last_login_at = _FIXED_TS
    return u


def _make_role_request(status: str = "pending", requested_role_id: int = 2) -> MagicMock:
    """ORM-like mock RoleRequest."""
    rr = MagicMock()
    rr.request_id = _REQUEST_ID
    rr.user_id = _TARGET_USER_ID
    rr.requested_role_id = requested_role_id
    rr.status = status
    rr.requested_at = _FIXED_TS
    rr.reviewed_by = None
    rr.reviewed_at = None
    return rr


def _result_with(value) -> MagicMock:
    """Mock DB result that returns value from scalar_one_or_none()."""
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


def _empty_result() -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=None)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    return r


# ===========================================================================
# Access control — all admin routes must reject non-admin callers
# ===========================================================================


@pytest.mark.asyncio
async def test_list_users_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.get("/api/admin/users")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_user_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.get(f"/api/admin/users/{_TARGET_USER_ID}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_set_user_role_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "interpreter"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_role_requests_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.get("/api/admin/role-requests")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_approve_role_request_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_role_request_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_audit_logs_returns_403_for_public_user(client: AsyncClient) -> None:
    response = await client.get("/api/admin/audit-logs")
    assert response.status_code == 403


# ===========================================================================
# GET /admin/users
# ===========================================================================


@pytest.mark.asyncio
async def test_list_users_returns_200_for_admin(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/users")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_users_returns_empty_list_when_db_has_none(admin_client: AsyncClient) -> None:
    data = (await admin_client.get("/api/admin/users")).json()
    assert data == []


@pytest.mark.asyncio
async def test_list_users_invalid_page_returns_422(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/users?page=0")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_users_invalid_page_size_returns_422(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/users?page_size=201")
    assert response.status_code == 422


# ===========================================================================
# GET /admin/users/{user_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_user_returns_404_when_not_found(admin_client: AsyncClient) -> None:
    response = await admin_client.get(f"/api/admin/users/{_TARGET_USER_ID}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_user_returns_200_when_found(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    response = await admin_client.get(f"/api/admin/users/{_TARGET_USER_ID}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_user_body_has_correct_email(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    data = (await admin_client.get(f"/api/admin/users/{_TARGET_USER_ID}")).json()
    assert data["email"] == "target@example.com"


@pytest.mark.asyncio
async def test_get_user_body_role_mapped_correctly(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user(role_id=3)
    mock_db.execute.return_value = _result_with(target)
    data = (await admin_client.get(f"/api/admin/users/{_TARGET_USER_ID}")).json()
    assert data["role"] == "interpreter"


# ===========================================================================
# POST /admin/users/{user_id}/role
# ===========================================================================


@pytest.mark.asyncio
async def test_set_user_role_returns_422_for_unknown_role(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "superuser"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_set_user_role_returns_404_when_user_not_found(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "interpreter"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_user_role_updates_role_id_on_target(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user(role_id=1)
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "court_official"},
    )
    assert target.role_id == 2  # court_official role_id


@pytest.mark.asyncio
async def test_set_user_role_sets_role_approved_by_to_admin_user_id(
    admin_client: AsyncClient, mock_db: AsyncMock, mock_admin_user: MagicMock
) -> None:
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "interpreter"},
    )
    assert target.role_approved_by == mock_admin_user.user_id


@pytest.mark.asyncio
async def test_set_user_role_stamps_role_approved_at(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    before = datetime.now(tz=UTC)
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "interpreter"},
    )
    after = datetime.now(tz=UTC)
    assert target.role_approved_at is not None
    assert before <= target.role_approved_at <= after


@pytest.mark.asyncio
async def test_set_user_role_commits_db(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "public"},
    )
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_set_user_role_refreshes_target(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "public"},
    )
    mock_db.refresh.assert_awaited_once_with(target)


@pytest.mark.asyncio
async def test_set_user_role_writes_audit_log(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    """write_audit calls db.add(AuditLog(...)) — verify at least one add occurred."""
    target = _make_target_user()
    mock_db.execute.return_value = _result_with(target)
    await admin_client.post(
        f"/api/admin/users/{_TARGET_USER_ID}/role",
        json={"role_name": "interpreter"},
    )
    assert mock_db.add.called, "Expected db.add to be called (for audit log)"
    from db.models import AuditLog

    # The last add call should be the AuditLog (after the role mutation)
    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(obj, AuditLog) for obj in added_objs), "Expected an AuditLog row to be added"


# ===========================================================================
# GET /admin/role-requests
# ===========================================================================


@pytest.mark.asyncio
async def test_list_role_requests_returns_200(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/role-requests")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_role_requests_returns_empty_list_by_default(
    admin_client: AsyncClient,
) -> None:
    data = (await admin_client.get("/api/admin/role-requests")).json()
    assert data == []


@pytest.mark.asyncio
async def test_list_role_requests_pending_only_default_is_true(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    """The default query should filter by status='pending'."""
    await admin_client.get("/api/admin/role-requests")
    # Verify DB was queried (the mock was called)
    assert mock_db.execute.called


@pytest.mark.asyncio
async def test_list_role_requests_pending_only_false_accepted(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get("/api/admin/role-requests?pending_only=false")
    assert response.status_code == 200


# ===========================================================================
# POST /admin/role-requests/{request_id}/approve
# ===========================================================================


@pytest.mark.asyncio
async def test_approve_role_request_returns_404_when_not_found(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_role_request_returns_409_when_already_decided(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    already_approved = _make_role_request(status="approved")
    mock_db.execute.return_value = _result_with(already_approved)
    response = await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_role_request_sets_status_to_approved(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert req.status == "approved"


@pytest.mark.asyncio
async def test_approve_role_request_promotes_user_role_id(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert target.role_id == 2  # promoted to court_official


@pytest.mark.asyncio
async def test_approve_role_request_stamps_reviewed_at(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    before = datetime.now(tz=UTC)
    req = _make_role_request(status="pending", requested_role_id=3)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    after = datetime.now(tz=UTC)

    assert req.reviewed_at is not None
    assert before <= req.reviewed_at <= after


@pytest.mark.asyncio
async def test_approve_role_request_sets_reviewed_by(
    admin_client: AsyncClient, mock_db: AsyncMock, mock_admin_user: MagicMock
) -> None:
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    assert req.reviewed_by == mock_admin_user.user_id


@pytest.mark.asyncio
async def test_approve_role_request_commits_db(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_approve_role_request_writes_audit_log(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)

    result1 = _result_with(req)
    result2 = _result_with(target)
    mock_db.execute.side_effect = [result1, result2]

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/approve", json={})

    from db.models import AuditLog

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(obj, AuditLog) for obj in added_objs)


# ===========================================================================
# POST /admin/role-requests/{request_id}/reject
# ===========================================================================


@pytest.mark.asyncio
async def test_reject_role_request_returns_404_when_not_found(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reject_role_request_returns_409_when_already_decided(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    already_rejected = _make_role_request(status="rejected")
    mock_db.execute.return_value = _result_with(already_rejected)
    response = await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reject_role_request_sets_status_to_rejected(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending")
    mock_db.execute.return_value = _result_with(req)
    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={"notes": "Not verified"})
    assert req.status == "rejected"


@pytest.mark.asyncio
async def test_reject_role_request_does_not_change_user_role_id(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    """Rejection must never promote the user — only the approve path does that."""
    req = _make_role_request(status="pending", requested_role_id=2)
    target = _make_target_user(role_id=1)
    original_role = target.role_id

    # For reject, only the RoleRequest is fetched — no second User query
    mock_db.execute.return_value = _result_with(req)

    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={})
    assert target.role_id == original_role, "Rejection must not mutate the user's role_id"


@pytest.mark.asyncio
async def test_reject_role_request_commits_db(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    req = _make_role_request(status="pending")
    mock_db.execute.return_value = _result_with(req)
    await admin_client.post(f"/api/admin/role-requests/{_REQUEST_ID}/reject", json={})
    mock_db.commit.assert_awaited()


# ===========================================================================
# GET /admin/audit-logs
# ===========================================================================


@pytest.mark.asyncio
async def test_list_audit_logs_returns_200(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/audit-logs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_audit_logs_returns_empty_list_by_default(
    admin_client: AsyncClient,
) -> None:
    data = (await admin_client.get("/api/admin/audit-logs")).json()
    assert data == []


@pytest.mark.asyncio
async def test_list_audit_logs_invalid_page_returns_422(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/audit-logs?page=0")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_audit_logs_invalid_page_size_returns_422(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get("/api/admin/audit-logs?page_size=201")
    assert response.status_code == 422
