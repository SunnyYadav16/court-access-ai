"""
api/tests/test_routes_interpreter.py

HTTP-level tests for /api/interpreter/* endpoints.

Verifies:
  - Access control: public users get 403; interpreter and admin users are admitted
  - list_review_sessions: 200 returns empty list from mock DB; language filter
    forwards to DB; invalid language code returns 400
  - get_review_session: 404 when not found; 200 returns all expected fields
  - submit_correction: 201 with status="accepted"; session_id in response;
    writes AuditLog row; commits DB; 404 when session not found
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

_SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000050")
_FIXED_TS = datetime(2024, 1, 1, tzinfo=UTC)


def _make_session_mock() -> MagicMock:
    s = MagicMock()
    s.session_id = _SESSION_ID
    s.target_language = "spa_Latn"
    s.created_at = _FIXED_TS
    return s


def _make_translation_request_mock() -> MagicMock:
    r = MagicMock()
    r.status = "completed"
    r.avg_confidence_score = 0.75
    r.llama_corrections_count = 2
    r.signed_url = "https://storage.googleapis.com/bucket/file.pdf?sig=abc"
    r.signed_url_expires_at = _FIXED_TS
    return r


def _result_with_first(value) -> MagicMock:
    """Mock DB result that returns value from first()."""
    res = MagicMock()
    res.first = MagicMock(return_value=value)
    res.scalar_one_or_none = MagicMock(return_value=value)
    return res


def _result_with_all(rows: list) -> MagicMock:
    """Mock DB result that returns rows from .all()."""
    res = MagicMock()
    res.all = MagicMock(return_value=rows)
    return res


# ===========================================================================
# Access control — all interpreter routes must reject public callers
# ===========================================================================


@pytest.mark.asyncio
async def test_list_review_sessions_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.get("/api/interpreter/review")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_review_session_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.get(f"/api/interpreter/review/{_SESSION_ID}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_correction_returns_403_for_public(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json={
            "original_text": "Hello",
            "original_language": "en",
            "corrected_translation": "Hola",
            "target_language": "es",
        },
    )
    assert response.status_code == 403


# ===========================================================================
# GET /interpreter/review — list sessions
# ===========================================================================


@pytest.mark.asyncio
async def test_list_review_sessions_returns_200_for_interpreter(
    interpreter_client: AsyncClient,
) -> None:
    response = await interpreter_client.get("/api/interpreter/review")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_review_sessions_returns_200_for_admin(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get("/api/interpreter/review")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_review_sessions_returns_empty_list_by_default(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    mock_db.execute.return_value = _result_with_all([])
    data = (await interpreter_client.get("/api/interpreter/review")).json()
    assert data == []


@pytest.mark.asyncio
async def test_list_review_sessions_spanish_language_filter_accepted(
    interpreter_client: AsyncClient,
) -> None:
    response = await interpreter_client.get("/api/interpreter/review?target_language=es")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_review_sessions_portuguese_language_filter_accepted(
    interpreter_client: AsyncClient,
) -> None:
    response = await interpreter_client.get("/api/interpreter/review?target_language=pt")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_review_sessions_invalid_language_returns_400(
    interpreter_client: AsyncClient,
) -> None:
    response = await interpreter_client.get("/api/interpreter/review?target_language=zh")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_review_sessions_invalid_language_detail_mentions_allowed_values(
    interpreter_client: AsyncClient,
) -> None:
    data = (await interpreter_client.get("/api/interpreter/review?target_language=zh")).json()
    detail = data.get("detail", "").lower()
    assert "es" in detail or "pt" in detail or "unsupported" in detail.lower()


@pytest.mark.asyncio
async def test_list_review_sessions_builds_response_from_db_rows(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_all([(s, r)])

    data = (await interpreter_client.get("/api/interpreter/review")).json()
    assert len(data) == 1
    assert data[0]["session_id"] == str(_SESSION_ID)
    assert data[0]["target_language"] == "spa_Latn"
    assert data[0]["status"] == "completed"
    assert data[0]["avg_confidence_score"] == pytest.approx(0.75)
    assert data[0]["llama_corrections_count"] == 2


@pytest.mark.asyncio
async def test_list_review_sessions_invalid_page_returns_422(
    interpreter_client: AsyncClient,
) -> None:
    response = await interpreter_client.get("/api/interpreter/review?page=0")
    assert response.status_code == 422


# ===========================================================================
# GET /interpreter/review/{session_id}
# ===========================================================================


@pytest.mark.asyncio
async def test_get_review_session_returns_404_when_not_found(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    mock_db.execute.return_value = _result_with_first(None)
    response = await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_review_session_returns_200_when_found(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_first((s, r))

    response = await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_review_session_body_has_session_id(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_first((s, r))

    data = (await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")).json()
    assert data["session_id"] == str(_SESSION_ID)


@pytest.mark.asyncio
async def test_get_review_session_body_has_confidence_score(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_first((s, r))

    data = (await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")).json()
    assert data["avg_confidence_score"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_get_review_session_body_has_llama_corrections_count(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_first((s, r))

    data = (await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")).json()
    assert data["llama_corrections_count"] == 2


@pytest.mark.asyncio
async def test_get_review_session_body_has_signed_url(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    s = _make_session_mock()
    r = _make_translation_request_mock()
    mock_db.execute.return_value = _result_with_first((s, r))

    data = (await interpreter_client.get(f"/api/interpreter/review/{_SESSION_ID}")).json()
    assert "signed_url" in data
    assert data["signed_url"].startswith("https://")


# ===========================================================================
# POST /interpreter/review/{session_id}/correct
# ===========================================================================

_CORRECTION_BODY = {
    "original_text": "The defendant shall appear",
    "original_language": "en",
    "corrected_translation": "El acusado deberá comparecer",
    "target_language": "es",
    "correction_notes": "Fixed verb tense",
}


@pytest.mark.asyncio
async def test_submit_correction_returns_404_when_session_not_found(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    mock_db.execute.return_value = _result_with_first(None)
    response = await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json=_CORRECTION_BODY,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_correction_returns_201_when_session_found(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    # Route does: select(SessionModel.session_id).where(...) → first() → not None
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    response = await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json=_CORRECTION_BODY,
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_submit_correction_response_has_status_accepted(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    data = (
        await interpreter_client.post(
            f"/api/interpreter/review/{_SESSION_ID}/correct",
            json=_CORRECTION_BODY,
        )
    ).json()
    assert data["status"] == "accepted"


@pytest.mark.asyncio
async def test_submit_correction_response_has_session_id(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    data = (
        await interpreter_client.post(
            f"/api/interpreter/review/{_SESSION_ID}/correct",
            json=_CORRECTION_BODY,
        )
    ).json()
    assert data["session_id"] == str(_SESSION_ID)


@pytest.mark.asyncio
async def test_submit_correction_commits_db(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json=_CORRECTION_BODY,
    )
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_submit_correction_writes_audit_log(interpreter_client: AsyncClient, mock_db: AsyncMock) -> None:
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json=_CORRECTION_BODY,
    )
    from db.models import AuditLog

    assert mock_db.add.called
    added_objs = [call[0][0] for call in mock_db.add.call_args_list]
    assert any(isinstance(obj, AuditLog) for obj in added_objs), "Expected an AuditLog row to be added by write_audit"


@pytest.mark.asyncio
async def test_submit_correction_audit_contains_correction_fields(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """The AuditLog details dict must include the correction data."""
    result = MagicMock()
    result.first = MagicMock(return_value=(_SESSION_ID,))
    mock_db.execute.return_value = result

    await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json=_CORRECTION_BODY,
    )
    from db.models import AuditLog

    audit_log: AuditLog | None = None
    for call in mock_db.add.call_args_list:
        obj = call[0][0]
        if isinstance(obj, AuditLog):
            audit_log = obj
            break

    assert audit_log is not None
    assert audit_log.details["original_text"] == "The defendant shall appear"
    assert audit_log.details["corrected_translation"] == "El acusado deberá comparecer"
    assert audit_log.details["target_language"] == "es"


@pytest.mark.asyncio
async def test_submit_correction_requires_all_mandatory_fields(
    interpreter_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Omitting required fields must return 422."""
    response = await interpreter_client.post(
        f"/api/interpreter/review/{_SESSION_ID}/correct",
        json={"original_text": "Hello"},  # missing required fields
    )
    assert response.status_code == 422
