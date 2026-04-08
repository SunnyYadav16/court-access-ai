"""
api/tests/test_routes_forms.py

HTTP-level tests for /api/forms/* endpoints.

Assertions go beyond HTTP status codes to verify:
  - Correct arguments forwarded to DB query functions
  - DB commit called after mutations
  - Response body contains the right content from the DB layer
  - Airflow DAG conf includes the triggering user's ID
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from api.schemas.schemas import FormResponse

_NOW = datetime(2024, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form(form_id: uuid.UUID | None = None) -> MagicMock:
    form = MagicMock(spec=FormResponse)
    form.form_id = form_id or uuid.uuid4()
    form.form_name = "Complaint Form"
    form.form_slug = "complaint-form"
    form.source_url = "https://mass.gov/forms/complaint.pdf"
    form.file_type = "pdf"
    form.status = "active"
    form.content_hash = "abc123"
    form.current_version = 1
    form.needs_human_review = False
    form.preprocessing_flags = []
    form.created_at = _NOW
    form.last_scraped_at = _NOW
    form.versions = []
    form.appearances = []
    return form


def _mock_airflow_client(dag_run_id: str = "manual__2024-01-01") -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"dag_run_id": dag_run_id})
    c = AsyncMock()
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    c.post = AsyncMock(return_value=resp)
    return c


# ---------------------------------------------------------------------------
# GET /api/forms/ — list with filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_forms_returns_200(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        response = await client.get("/api/forms/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_forms_empty_response_structure(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        data = (await client.get("/api/forms/")).json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert "filters_applied" in data


@pytest.mark.asyncio
async def test_list_forms_query_param_forwarded_to_db(client: AsyncClient) -> None:
    """The 'q' search term must be passed through to the DB query function."""
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_fn:
        await client.get("/api/forms/?q=complaint")

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("q") == "complaint", (
        f"Expected q='complaint' forwarded to list_forms(), got: {call_kwargs}"
    )


@pytest.mark.asyncio
async def test_list_forms_division_filter_forwarded_to_db(client: AsyncClient) -> None:
    """The 'division' filter must be passed through to the DB query function."""
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_fn:
        await client.get("/api/forms/?division=District+Court")

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("division") == "District Court"


@pytest.mark.asyncio
async def test_list_forms_language_filter_forwarded_to_db(client: AsyncClient) -> None:
    """The 'language' filter value must be forwarded as the string value."""
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_fn:
        await client.get("/api/forms/?language=es")

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("language") == "es"


@pytest.mark.asyncio
async def test_list_forms_status_filter_defaults_to_active(client: AsyncClient) -> None:
    """Without an explicit status param, the default must filter to 'active' forms."""
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_fn:
        await client.get("/api/forms/")

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("status") == "active"


@pytest.mark.asyncio
async def test_list_forms_pagination_forwarded_to_db(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ) as mock_fn:
        await client.get("/api/forms/?page=3&page_size=5")

    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs.get("page") == 3
    assert call_kwargs.get("page_size") == 5


@pytest.mark.asyncio
async def test_list_forms_invalid_language_returns_422(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.list_forms",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        response = await client.get("/api/forms/?language=ZULU")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/forms/divisions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_divisions_returns_200(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.list_divisions",
        new_callable=AsyncMock,
        return_value=["Boston Municipal Court", "District Court"],
    ):
        response = await client.get("/api/forms/divisions")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_list_divisions_content_matches_db_return(client: AsyncClient) -> None:
    """The response must contain exactly the divisions returned by the DB layer."""
    divisions = ["Probate Court", "District Court", "Housing Court"]
    with patch(
        "api.routes.forms.db_queries_forms.list_divisions",
        new_callable=AsyncMock,
        return_value=divisions,
    ):
        data = (await client.get("/api/forms/divisions")).json()

    assert data == divisions, (
        f"Response divisions {data} do not match what the DB layer returned {divisions}"
    )


# ---------------------------------------------------------------------------
# GET /api/forms/{form_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_form_not_found_returns_404(client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.get_form_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await client.get(f"/api/forms/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_form_invalid_uuid_returns_422(client: AsyncClient) -> None:
    response = await client.get("/api/forms/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_form_found_returns_200(client: AsyncClient) -> None:
    form = _make_form()
    with (
        patch(
            "api.routes.forms.db_queries_forms.get_form_by_id",
            new_callable=AsyncMock,
            return_value=form,
        ),
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        response = await client.get(f"/api/forms/{form.form_id}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_get_form_queries_db_with_correct_form_id(client: AsyncClient) -> None:
    """Route must query the DB with the form_id from the URL path."""
    target_id = uuid.uuid4()
    with patch(
        "api.routes.forms.db_queries_forms.get_form_by_id",
        new_callable=AsyncMock,
        return_value=None,
    ) as mock_fn:
        await client.get(f"/api/forms/{target_id}")

    mock_fn.assert_awaited_once()
    called_form_id = mock_fn.call_args[0][1]  # second positional arg is form_id
    assert called_form_id == target_id


# ---------------------------------------------------------------------------
# PATCH /api/forms/{form_id}/review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_review_public_user_returns_403(client: AsyncClient) -> None:
    """Public users (role_id=1) must be rejected by require_role guard."""
    with patch(
        "api.routes.forms.db_queries_forms.submit_form_review",
        new_callable=AsyncMock,
        return_value=_make_form(),
    ):
        response = await client.patch(
            f"/api/forms/{uuid.uuid4()}/review",
            json={"approved": True},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_review_admin_returns_200(admin_client: AsyncClient) -> None:
    form = _make_form()
    with (
        patch(
            "api.routes.forms.db_queries_forms.submit_form_review",
            new_callable=AsyncMock,
            return_value=form,
        ),
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        response = await admin_client.patch(
            f"/api/forms/{form.form_id}/review",
            json={"approved": True, "reviewer_notes": "Looks good"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_submit_review_calls_db_with_correct_args(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Route must forward form_id, approved flag, reviewer user_id, and notes to DB."""
    form = _make_form()
    target_id = form.form_id

    with (
        patch(
            "api.routes.forms.db_queries_forms.submit_form_review",
            new_callable=AsyncMock,
            return_value=form,
        ) as mock_fn,
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        await admin_client.patch(
            f"/api/forms/{target_id}/review",
            json={"approved": True, "reviewer_notes": "Approved by court"},
        )

    mock_fn.assert_awaited_once()
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["form_id"] == target_id
    assert call_kwargs["approved"] is True
    assert call_kwargs["notes"] == "Approved by court"
    # reviewer_user_id must be the authenticated user's ID
    assert call_kwargs["reviewer_user_id"] is not None


@pytest.mark.asyncio
async def test_submit_review_commits_db(
    admin_client: AsyncClient, mock_db: AsyncMock
) -> None:
    """Review decision must be committed to the database."""
    form = _make_form()
    with (
        patch(
            "api.routes.forms.db_queries_forms.submit_form_review",
            new_callable=AsyncMock,
            return_value=form,
        ),
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        await admin_client.patch(
            f"/api/forms/{form.form_id}/review",
            json={"approved": True},
        )
    mock_db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_submit_review_rejection_works(admin_client: AsyncClient) -> None:
    """approved=False (rejection) must also return 200 — both outcomes are valid."""
    form = _make_form()
    with (
        patch(
            "api.routes.forms.db_queries_forms.submit_form_review",
            new_callable=AsyncMock,
            return_value=form,
        ),
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        response = await admin_client.patch(
            f"/api/forms/{form.form_id}/review",
            json={"approved": False, "reviewer_notes": "Needs corrections"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_submit_review_rejection_forwarded_to_db(
    admin_client: AsyncClient,
) -> None:
    """approved=False must be forwarded correctly — not silently converted to True."""
    form = _make_form()
    with (
        patch(
            "api.routes.forms.db_queries_forms.submit_form_review",
            new_callable=AsyncMock,
            return_value=form,
        ) as mock_fn,
        patch("api.routes.forms.gcs.parse_gcs_uri", return_value=("bucket", "blob")),
        patch("api.routes.forms.gcs.generate_signed_url", return_value="https://signed.url"),
    ):
        await admin_client.patch(
            f"/api/forms/{form.form_id}/review",
            json={"approved": False},
        )

    assert mock_fn.call_args.kwargs["approved"] is False


@pytest.mark.asyncio
async def test_submit_review_not_found_returns_404(admin_client: AsyncClient) -> None:
    with patch(
        "api.routes.forms.db_queries_forms.submit_form_review",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = await admin_client.patch(
            f"/api/forms/{uuid.uuid4()}/review",
            json={"approved": False},
        )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/forms/scraper/trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_scraper_public_user_returns_403(client: AsyncClient) -> None:
    response = await client.post("/api/forms/scraper/trigger", json={"force": False})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_trigger_scraper_admin_returns_200(admin_client: AsyncClient) -> None:
    mock_http = _mock_airflow_client()
    with (
        patch("api.routes.forms.httpx.AsyncClient", return_value=mock_http),
        patch("api.routes.forms.write_audit", new_callable=AsyncMock),
    ):
        response = await admin_client.post(
            "/api/forms/scraper/trigger", json={"force": False}
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_trigger_scraper_returns_dag_run_id(admin_client: AsyncClient) -> None:
    mock_http = _mock_airflow_client(dag_run_id="manual__test_run")
    with (
        patch("api.routes.forms.httpx.AsyncClient", return_value=mock_http),
        patch("api.routes.forms.write_audit", new_callable=AsyncMock),
    ):
        data = (
            await admin_client.post("/api/forms/scraper/trigger", json={"force": False})
        ).json()
    assert data["dag_run_id"] == "manual__test_run"


@pytest.mark.asyncio
async def test_trigger_scraper_response_has_triggered_at_datetime(
    admin_client: AsyncClient,
) -> None:
    """triggered_at must be a parseable ISO 8601 datetime, not a placeholder."""
    mock_http = _mock_airflow_client()
    with (
        patch("api.routes.forms.httpx.AsyncClient", return_value=mock_http),
        patch("api.routes.forms.write_audit", new_callable=AsyncMock),
    ):
        data = (
            await admin_client.post("/api/forms/scraper/trigger", json={"force": False})
        ).json()

    assert "triggered_at" in data
    from datetime import datetime

    # Must parse as a valid datetime without raising
    triggered_at = datetime.fromisoformat(data["triggered_at"].replace("Z", "+00:00"))
    # Must be recent (within the last 60 seconds)
    now = datetime.now(tz=UTC)
    assert abs((now - triggered_at).total_seconds()) < 60


@pytest.mark.asyncio
async def test_trigger_scraper_sends_user_id_in_airflow_conf(
    admin_client: AsyncClient, mock_admin_user: MagicMock
) -> None:
    """Airflow DAG conf must include the triggering admin's user_id for audit trail."""
    mock_http = _mock_airflow_client()
    with (
        patch("api.routes.forms.httpx.AsyncClient", return_value=mock_http),
        patch("api.routes.forms.write_audit", new_callable=AsyncMock),
    ):
        await admin_client.post("/api/forms/scraper/trigger", json={"force": False})

    dag_conf = mock_http.post.call_args.kwargs["json"]["conf"]
    assert "triggered_by_user_id" in dag_conf
    assert dag_conf["triggered_by_user_id"] == str(mock_admin_user.user_id)


@pytest.mark.asyncio
async def test_trigger_scraper_airflow_unreachable_returns_502(
    admin_client: AsyncClient,
) -> None:
    import httpx as _httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(
        side_effect=_httpx.RequestError("connection refused", request=MagicMock())
    )
    with patch("api.routes.forms.httpx.AsyncClient", return_value=mock_client):
        response = await admin_client.post(
            "/api/forms/scraper/trigger", json={"force": False}
        )
    assert response.status_code == 502
    assert "airflow" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_trigger_scraper_airflow_http_error_returns_502(
    admin_client: AsyncClient,
) -> None:
    """Airflow returning a 4xx/5xx HTTP error must also result in a 502."""
    import httpx as _httpx

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(
        side_effect=_httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_resp
        )
    )
    with patch("api.routes.forms.httpx.AsyncClient", return_value=mock_client):
        response = await admin_client.post(
            "/api/forms/scraper/trigger", json={"force": False}
        )
    assert response.status_code == 502
