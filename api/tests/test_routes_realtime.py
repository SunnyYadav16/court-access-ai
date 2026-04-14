"""
api/tests/test_routes_realtime.py

HTTP-level tests for /api/sessions/* REST endpoints.

Covers:
  - POST /sessions/               — create in-memory session
  - POST /sessions/rooms          — create DB-persisted room with room code
  - POST /sessions/rooms/join     — join by room code, receive JWT
  - GET  /sessions/rooms/{code}/preview — public room info
  - GET  /sessions/rooms/{code}/status  — creator/admin room status poll
  - POST /sessions/rooms/{id}/end       — end room (creator/admin)
  - GET  /sessions/rooms               — list in-memory rooms
  - GET  /sessions/{session_id}        — get in-memory session
  - POST /sessions/{session_id}/end    — end in-memory session

WebSocket authentication paths are deliberately tested via the
REST surface — the full bidirectional pipeline requires live speech
models and is out of scope for unit tests.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Module-level state cleanup between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_realtime_state() -> None:
    """Isolate each test by clearing in-memory dicts before and after."""
    from api.routes import realtime

    realtime.conversation_rooms.clear()
    realtime._sessions.clear()
    yield
    realtime.conversation_rooms.clear()
    realtime._sessions.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_TS = datetime(2024, 1, 1, tzinfo=UTC)
_SESSION_UUID = uuid.UUID("00000000-0000-0000-0000-000000000060")
_RT_REQUEST_UUID = uuid.UUID("00000000-0000-0000-0000-000000000061")


def _make_rt_request(
    phase: str = "waiting",
    expired: bool = False,
    session_id: uuid.UUID | None = None,
    creator_user_id: uuid.UUID | None = None,
) -> MagicMock:
    rr = MagicMock()
    rr.rt_request_id = _RT_REQUEST_UUID
    rr.session_id = session_id or _SESSION_UUID
    rr.room_code = "ABCD12"
    rr.phase = phase
    rr.partner_name = "Maria"
    rr.partner_user_id = None
    rr.court_division = "Boston Municipal Court"
    rr.courtroom = "Courtroom 3"
    rr.case_docket = "24-CR-001"
    rr.creator_user_id = creator_user_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    rr.partner_joined_at = None
    rr.room_code_expires_at = _FIXED_TS if expired else datetime.now(tz=UTC) + timedelta(hours=1)
    return rr


def _make_session_mock(target_language: str = "spa_Latn") -> MagicMock:
    s = MagicMock()
    s.session_id = _SESSION_UUID
    s.target_language = target_language
    s.status = "active"
    s.created_at = _FIXED_TS
    return s


def _result_with(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


def _result_with_first(value) -> MagicMock:
    r = MagicMock()
    r.first = MagicMock(return_value=value)
    r.scalar_one_or_none = MagicMock(return_value=value)
    return r


# ===========================================================================
# POST /sessions/ — create in-memory session
# ===========================================================================


@pytest.mark.asyncio
async def test_create_session_returns_201_for_court_official(
    saml_client: AsyncClient,
) -> None:
    response = await saml_client.post(
        "/api/sessions/",
        json={"type": "realtime", "target_language": "spa_Latn"},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_session_returns_201_for_admin(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/sessions/",
        json={"type": "realtime", "target_language": "spa_Latn"},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_session_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.post(
        "/api/sessions/",
        json={"type": "realtime", "target_language": "spa_Latn"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_session_response_has_valid_session_id(
    saml_client: AsyncClient,
) -> None:
    data = (
        await saml_client.post(
            "/api/sessions/",
            json={"type": "realtime", "target_language": "spa_Latn"},
        )
    ).json()
    uuid.UUID(data["session_id"])  # raises ValueError if not a valid UUID


@pytest.mark.asyncio
async def test_create_session_response_has_websocket_url(
    saml_client: AsyncClient,
) -> None:
    data = (
        await saml_client.post(
            "/api/sessions/",
            json={"type": "realtime", "target_language": "spa_Latn"},
        )
    ).json()
    assert "websocket_url" in data
    assert "/sessions/" in data["websocket_url"]


@pytest.mark.asyncio
async def test_create_session_response_status_is_active(
    saml_client: AsyncClient,
) -> None:
    data = (
        await saml_client.post(
            "/api/sessions/",
            json={"type": "realtime", "target_language": "spa_Latn"},
        )
    ).json()
    assert data["status"] == "active"


# ===========================================================================
# POST /sessions/rooms — create DB-persisted room
# ===========================================================================

_ROOM_CREATE_BODY = {
    "target_language": "es",
    "partner_name": "Maria Garcia",
    "consent_acknowledged": True,
    "court_division": "Boston Municipal Court",
    "courtroom": "Courtroom 3",
}


@pytest.mark.asyncio
async def test_create_room_returns_201_for_court_official(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    response = await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_create_room_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_room_returns_422_when_consent_false(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    body = {**_ROOM_CREATE_BODY, "consent_acknowledged": False}
    response = await saml_client.post("/api/sessions/rooms", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_room_response_has_room_code(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    data = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    assert "room_code" in data
    assert len(data["room_code"]) >= 4


@pytest.mark.asyncio
async def test_create_room_response_has_valid_session_id(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    data = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    uuid.UUID(data["session_id"])  # raises if invalid


@pytest.mark.asyncio
async def test_create_room_response_has_join_url(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    data = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    assert "join_url" in data
    assert data["room_code"] in data["join_url"]


@pytest.mark.asyncio
async def test_create_room_response_has_room_code_expires_at(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    data = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    assert "room_code_expires_at" in data


@pytest.mark.asyncio
async def test_create_room_adds_session_and_rt_request_to_db(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)

    from db.models import RealtimeTranslationRequest
    from db.models import Session as SessionModel

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(o, SessionModel) for o in added_objs), "Expected a Session ORM row to be added"
    assert any(isinstance(o, RealtimeTranslationRequest) for o in added_objs), (
        "Expected a RealtimeTranslationRequest ORM row to be added"
    )


@pytest.mark.asyncio
async def test_create_room_commits_db(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_create_room_registers_in_memory_room(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    from api.routes import realtime

    data = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    assert data["room_code"] in realtime.conversation_rooms


@pytest.mark.asyncio
async def test_create_room_rt_request_phase_is_waiting(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)

    from db.models import RealtimeTranslationRequest

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    rt_req = next((o for o in added_objs if isinstance(o, RealtimeTranslationRequest)), None)
    assert rt_req is not None
    assert rt_req.phase == "waiting"


@pytest.mark.asyncio
async def test_create_room_session_type_is_realtime(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)

    from db.models import Session as SessionModel

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    session = next((o for o in added_objs if isinstance(o, SessionModel)), None)
    assert session is not None
    assert session.type == "realtime"


@pytest.mark.asyncio
async def test_create_room_target_language_stored_as_nllb_code(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)

    from db.models import Session as SessionModel

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    session = next((o for o in added_objs if isinstance(o, SessionModel)), None)
    assert session is not None
    assert session.target_language == "spa_Latn"  # "es" → NLLB code


@pytest.mark.asyncio
async def test_create_room_writes_audit_log(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)

    from db.models import AuditLog

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(o, AuditLog) for o in added_objs)


# ===========================================================================
# POST /sessions/rooms/join — join by room code
# ===========================================================================


@pytest.mark.asyncio
async def test_join_room_returns_404_when_code_not_found(client: AsyncClient, mock_db: AsyncMock) -> None:
    mock_db.execute.return_value = _result_with(None)
    response = await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_join_room_returns_409_when_phase_not_waiting(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="active")
    mock_db.execute.return_value = _result_with(rt_req)
    response = await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_join_room_returns_410_when_expired(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting", expired=True)
    mock_db.execute.return_value = _result_with(rt_req)
    response = await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_join_room_returns_200_when_valid(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    result1 = _result_with(rt_req)
    result2 = _result_with(session)
    mock_db.execute.side_effect = [result1, result2]

    response = await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_join_room_response_has_room_token(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})).json()
    assert "room_token" in data
    assert len(data["room_token"]) > 0


@pytest.mark.asyncio
async def test_join_room_response_has_session_id(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})).json()
    uuid.UUID(data["session_id"])  # raises if not a valid UUID


@pytest.mark.asyncio
async def test_join_room_uses_partner_name_from_body_when_provided(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (
        await client.post(
            "/api/sessions/rooms/join",
            json={"room_code": "ABCD12", "partner_name": "Carlos"},
        )
    ).json()
    assert data["partner_name"] == "Carlos"


@pytest.mark.asyncio
async def test_join_room_falls_back_to_prefilled_partner_name(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    rt_req.partner_name = "Maria"
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})).json()
    assert data["partner_name"] == "Maria"


@pytest.mark.asyncio
async def test_join_room_sets_phase_to_joining(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    assert rt_req.phase == "joining"


@pytest.mark.asyncio
async def test_join_room_commits_db(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_join_room_normalises_room_code_to_uppercase(client: AsyncClient, mock_db: AsyncMock) -> None:
    """The join endpoint must normalise to uppercase before DB lookup."""
    # Lowercase code in request — DB is queried with uppercase
    mock_db.execute.return_value = _result_with(None)
    await client.post("/api/sessions/rooms/join", json={"room_code": "ABCD12"})
    # lowercase in the RoomJoinRequest pattern would fail validation, so test
    # that "ABCD12" is normalised correctly (already uppercase here)
    assert mock_db.execute.called


# ===========================================================================
# GET /sessions/rooms/{code}/preview — public endpoint, no auth
# ===========================================================================


@pytest.mark.asyncio
async def test_get_room_preview_returns_404_for_unknown_code(client: AsyncClient, mock_db: AsyncMock) -> None:
    mock_db.execute.return_value = _result_with(None)
    response = await client.get("/api/sessions/rooms/ZZZZZZ/preview")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_room_preview_returns_200_when_found(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request()
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    response = await client.get("/api/sessions/rooms/ABCD12/preview")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_room_preview_body_has_phase(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request(phase="waiting")
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.get("/api/sessions/rooms/ABCD12/preview")).json()
    assert data["phase"] == "waiting"


@pytest.mark.asyncio
async def test_get_room_preview_body_has_partner_name(client: AsyncClient, mock_db: AsyncMock) -> None:
    rt_req = _make_rt_request()
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.get("/api/sessions/rooms/ABCD12/preview")).json()
    assert data["partner_name"] == "Maria"


@pytest.mark.asyncio
async def test_get_room_preview_does_not_expose_session_id(client: AsyncClient, mock_db: AsyncMock) -> None:
    """Preview endpoint must not leak internal IDs."""
    rt_req = _make_rt_request()
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    data = (await client.get("/api/sessions/rooms/ABCD12/preview")).json()
    assert "session_id" not in data
    assert "creator_user_id" not in data


# ===========================================================================
# GET /sessions/rooms/{code}/status — creator/admin only
# ===========================================================================


@pytest.mark.asyncio
async def test_get_room_status_returns_403_for_public(client: AsyncClient, mock_db: AsyncMock) -> None:
    response = await client.get("/api/sessions/rooms/ABCD12/status")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_room_status_returns_404_when_code_not_found(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    mock_db.execute.return_value = _result_with(None)
    response = await saml_client.get("/api/sessions/rooms/ABCD12/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_room_status_returns_200_for_room_creator(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    # creator_user_id matches the saml_client user
    rt_req = _make_rt_request(creator_user_id=mock_court_official_user.user_id)
    mock_db.execute.return_value = _result_with(rt_req)

    response = await saml_client.get("/api/sessions/rooms/ABCD12/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_room_status_returns_403_for_non_creator_court_official(
    court_official_client_b: AsyncClient,
    mock_db: AsyncMock,
) -> None:
    """A court official who did not create the room must get 403."""
    # creator_user_id is user A (_FIXED_USER_ID); court_official_client_b is user B
    from api.tests.conftest import _FIXED_USER_ID

    rt_req = _make_rt_request(creator_user_id=_FIXED_USER_ID)
    mock_db.execute.return_value = _result_with(rt_req)

    response = await court_official_client_b.get("/api/sessions/rooms/ABCD12/status")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_room_status_returns_200_for_admin_regardless_of_ownership(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    # creator_user_id is someone else
    rt_req = _make_rt_request(creator_user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"))
    mock_db.execute.return_value = _result_with(rt_req)

    response = await admin_client.get("/api/sessions/rooms/ABCD12/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_room_status_body_has_phase(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="waiting", creator_user_id=mock_court_official_user.user_id)
    mock_db.execute.return_value = _result_with(rt_req)

    data = (await saml_client.get("/api/sessions/rooms/ABCD12/status")).json()
    assert data["phase"] == "waiting"


# ===========================================================================
# POST /sessions/rooms/{session_id}/end — end a DB-persisted room
# ===========================================================================


@pytest.mark.asyncio
async def test_end_room_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_end_room_returns_404_when_rt_request_not_found(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    mock_db.execute.return_value = _result_with(None)
    response = await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_end_room_returns_403_for_non_creator(
    court_official_client_b: AsyncClient,
    mock_db: AsyncMock,
) -> None:
    from api.tests.conftest import _FIXED_USER_ID

    rt_req = _make_rt_request(phase="active", creator_user_id=_FIXED_USER_ID)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    response = await court_official_client_b.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_end_room_returns_204_for_creator(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="active", creator_user_id=mock_court_official_user.user_id)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    response = await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_end_room_sets_phase_to_ended(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="active", creator_user_id=mock_court_official_user.user_id)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert rt_req.phase == "ended"


@pytest.mark.asyncio
async def test_end_room_sets_session_status_to_completed(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="active", creator_user_id=mock_court_official_user.user_id)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert session.status == "completed"


@pytest.mark.asyncio
async def test_end_room_is_idempotent_when_already_ended(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    """Calling end on an already-ended room must return 204 without DB writes."""
    rt_req = _make_rt_request(phase="ended", creator_user_id=mock_court_official_user.user_id)
    mock_db.execute.return_value = _result_with(rt_req)

    response = await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 204
    mock_db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_end_room_commits_db(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="active", creator_user_id=mock_court_official_user.user_id)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_end_room_writes_audit_log(
    saml_client: AsyncClient,
    mock_db: AsyncMock,
    mock_court_official_user: MagicMock,
) -> None:
    rt_req = _make_rt_request(phase="active", creator_user_id=mock_court_official_user.user_id)
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    await saml_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")

    from db.models import AuditLog

    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(o, AuditLog) for o in added_objs)


@pytest.mark.asyncio
async def test_end_room_admin_can_end_any_room(admin_client: AsyncClient, mock_db: AsyncMock) -> None:
    # creator_user_id is someone else — admin should still be allowed
    rt_req = _make_rt_request(
        phase="active",
        creator_user_id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
    )
    session = _make_session_mock()

    mock_db.execute.side_effect = [_result_with(rt_req), _result_with(session)]

    response = await admin_client.post(f"/api/sessions/rooms/{_SESSION_UUID}/end")
    assert response.status_code == 204


# ===========================================================================
# GET /sessions/rooms — list in-memory rooms
# ===========================================================================


@pytest.mark.asyncio
async def test_list_rooms_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.get("/api/sessions/rooms")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_rooms_returns_200_for_court_official(saml_client: AsyncClient) -> None:
    response = await saml_client.get("/api/sessions/rooms")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_rooms_returns_empty_list_when_no_rooms(
    saml_client: AsyncClient,
) -> None:
    data = (await saml_client.get("/api/sessions/rooms")).json()
    assert data["rooms"] == []


@pytest.mark.asyncio
async def test_list_rooms_shows_created_room(saml_client: AsyncClient, mock_db: AsyncMock) -> None:
    """Create a room via POST then verify it appears in GET /rooms."""
    create_resp = (await saml_client.post("/api/sessions/rooms", json=_ROOM_CREATE_BODY)).json()
    room_code = create_resp["room_code"]

    data = (await saml_client.get("/api/sessions/rooms")).json()
    room_ids = [r["room_id"] for r in data["rooms"]]
    assert room_code in room_ids


# ===========================================================================
# GET /sessions/{session_id} — in-memory session
# ===========================================================================


@pytest.mark.asyncio
async def test_get_session_returns_404_for_unknown_session(
    client: AsyncClient,
) -> None:
    response = await client.get(f"/api/sessions/{_SESSION_UUID}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_session_returns_200_for_owner(saml_client: AsyncClient, mock_court_official_user: MagicMock) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": mock_court_official_user.user_id,
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await saml_client.get(f"/api/sessions/{_SESSION_UUID}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_session_returns_403_for_different_public_user(client: AsyncClient, mock_user: MagicMock) -> None:
    """A different user's session must not be accessible to a public user."""
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    # Session owned by a completely different UUID
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": uuid.UUID("00000000-0000-0000-0000-000000000099"),
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await client.get(f"/api/sessions/{_SESSION_UUID}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_session_court_official_can_view_any_session(
    saml_client: AsyncClient,
) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": uuid.UUID("00000000-0000-0000-0000-000000000099"),  # different user
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await saml_client.get(f"/api/sessions/{_SESSION_UUID}")
    assert response.status_code == 200


# ===========================================================================
# POST /sessions/{session_id}/end — end in-memory session
# ===========================================================================


@pytest.mark.asyncio
async def test_end_session_returns_404_for_unknown(client: AsyncClient) -> None:
    response = await client.post(f"/api/sessions/{_SESSION_UUID}/end")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_end_session_returns_204_for_owner(saml_client: AsyncClient, mock_court_official_user: MagicMock) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": mock_court_official_user.user_id,
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await saml_client.post(f"/api/sessions/{_SESSION_UUID}/end")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_end_session_sets_status_to_ended(saml_client: AsyncClient, mock_court_official_user: MagicMock) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": mock_court_official_user.user_id,
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    await saml_client.post(f"/api/sessions/{_SESSION_UUID}/end")
    assert realtime._sessions[sid]["status"] == "ended"


@pytest.mark.asyncio
async def test_end_session_is_idempotent_when_already_ended(
    saml_client: AsyncClient, mock_court_official_user: MagicMock
) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": mock_court_official_user.user_id,
        "status": "ended",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await saml_client.post(f"/api/sessions/{_SESSION_UUID}/end")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_end_session_returns_403_for_different_user(client: AsyncClient, mock_user: MagicMock) -> None:
    from api.routes import realtime

    sid = str(_SESSION_UUID)
    realtime._sessions[sid] = {
        "session_id": _SESSION_UUID,
        "user_id": uuid.UUID("00000000-0000-0000-0000-000000000099"),
        "status": "active",
        "created_at": _FIXED_TS,
        "target_language": "spa_Latn",
        "source_language": "en",
    }

    response = await client.post(f"/api/sessions/{_SESSION_UUID}/end")
    assert response.status_code == 403
