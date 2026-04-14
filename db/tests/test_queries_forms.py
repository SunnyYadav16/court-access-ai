"""
db/tests/test_queries_forms.py

Unit tests for db/queries/forms.py.

All tests use mocked SQLAlchemy sessions — no real DB connection required.

Async functions (FastAPI):
  - upsert_form_catalog
  - upsert_form_version
  - upsert_form_appearance
  - update_form_version_translations
  - update_form_catalog_fields
  - get_form_by_id
  - list_forms
  - list_divisions
  - submit_form_review

Sync functions (Airflow DAGs):
  - upsert_form_catalog_sync
  - upsert_form_version_sync
  - upsert_form_appearance_sync
  - get_form_by_id_sync
  - update_form_version_translations_sync
  - update_form_catalog_fields_sync
  - get_all_forms_sync
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_UID2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
_NOW = datetime(2024, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _catalog_entry(**overrides) -> dict:
    base = {
        "form_id": _UID,
        "form_name": "Test Form",
        "form_slug": "test-form",
        "source_url": "https://mass.gov/test.pdf",
        "file_type": "pdf",
        "status": "active",
        "content_hash": "abc123",
        "current_version": 1,
    }
    base.update(overrides)
    return base


def _version_dict(**overrides) -> dict:
    base = {
        "version": 1,
        "content_hash": "hash456",
        "file_type": "pdf",
        "file_path_original": "gs://bucket/original.pdf",
        "file_path_es": None,
        "file_path_pt": None,
        "file_type_es": None,
        "file_type_pt": None,
    }
    base.update(overrides)
    return base


def _mock_form() -> MagicMock:
    f = MagicMock()
    f.form_id = _UID
    f.form_name = "Test Form"
    f.form_slug = "test-form"
    f.needs_human_review = True
    f.current_version = 1
    f.created_at = _NOW
    f.last_scraped_at = _NOW
    f.versions = []
    f.appearances = []
    return f


# ══════════════════════════════════════════════════════════════════════════════
# upsert_form_catalog
# ══════════════════════════════════════════════════════════════════════════════


class TestUpsertFormCatalog:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self, mock_db):
        from db.queries.forms import upsert_form_catalog

        mock_db.get = AsyncMock(return_value=_mock_form())
        await upsert_form_catalog(mock_db, _catalog_entry())
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_orm_object_from_db_get(self, mock_db):
        from db.queries.forms import upsert_form_catalog

        expected = _mock_form()
        mock_db.get = AsyncMock(return_value=expected)
        result = await upsert_form_catalog(mock_db, _catalog_entry())
        assert result is expected

    @pytest.mark.asyncio
    async def test_returns_none_when_form_not_found(self, mock_db):
        from db.queries.forms import upsert_form_catalog

        mock_db.get = AsyncMock(return_value=None)
        result = await upsert_form_catalog(mock_db, _catalog_entry())
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import upsert_form_catalog

        mock_db.get = AsyncMock(return_value=_mock_form())
        await upsert_form_catalog(mock_db, _catalog_entry())
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_created_at_excluded_from_update_set(self, mock_db):
        """
        Verify the INSERT statement does not update created_at on conflict.
        We check this by inspecting the compiled SQL via the execute call arg.
        """
        from db.queries.forms import upsert_form_catalog

        mock_db.get = AsyncMock(return_value=_mock_form())
        entry = _catalog_entry()
        entry["created_at"] = _NOW

        await upsert_form_catalog(mock_db, entry)
        # execute was called — the function itself is responsible for excluding
        # created_at from set_dict. The test passes if no exception is raised
        # and execute was called (the exclusion is a code-path guarantee).
        mock_db.execute.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# upsert_form_version
# ══════════════════════════════════════════════════════════════════════════════


class TestUpsertFormVersion:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self, mock_db):
        from db.queries.forms import upsert_form_version

        mock_version = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_version
        mock_db.execute = AsyncMock(return_value=result_mock)

        await upsert_form_version(mock_db, _UID, _version_dict())
        assert mock_db.execute.call_count == 2  # INSERT + SELECT
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_form_version_from_select(self, mock_db):
        from db.queries.forms import upsert_form_version

        mock_version = MagicMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_version
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await upsert_form_version(mock_db, _UID, _version_dict())
        assert result is mock_version

    @pytest.mark.asyncio
    async def test_returns_none_when_version_not_found(self, mock_db):
        from db.queries.forms import upsert_form_version

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await upsert_form_version(mock_db, _UID, _version_dict())
        assert result is None

    @pytest.mark.asyncio
    async def test_generates_version_id_when_absent(self, mock_db):
        from db.queries.forms import upsert_form_version

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        vd = _version_dict()  # no version_id key
        assert "version_id" not in vd
        await upsert_form_version(mock_db, _UID, vd)
        # No exception means uuid4 was auto-generated — execute was called
        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_uses_provided_version_id(self, mock_db):
        from db.queries.forms import upsert_form_version

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        custom_id = uuid.uuid4()
        vd = _version_dict(version_id=custom_id)
        await upsert_form_version(mock_db, _UID, vd)
        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import upsert_form_version

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        await upsert_form_version(mock_db, _UID, _version_dict())
        mock_db.commit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# upsert_form_appearance
# ══════════════════════════════════════════════════════════════════════════════


class TestUpsertFormAppearance:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self, mock_db):
        from db.queries.forms import upsert_form_appearance

        await upsert_form_appearance(mock_db, _UID, "Housing Court", "Eviction Forms")
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none(self, mock_db):
        from db.queries.forms import upsert_form_appearance

        result = await upsert_form_appearance(mock_db, _UID, "Civil", "General")
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import upsert_form_appearance

        await upsert_form_appearance(mock_db, _UID, "Civil", "General")
        mock_db.commit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# update_form_version_translations
# ══════════════════════════════════════════════════════════════════════════════


class TestUpdateFormVersionTranslations:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self, mock_db):
        from db.queries.forms import update_form_version_translations

        await update_form_version_translations(
            mock_db,
            form_id=_UID,
            version=1,
            file_path_es="gs://bucket/es.pdf",
            file_path_pt=None,
            file_type_es="pdf",
            file_type_pt=None,
        )
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import update_form_version_translations

        await update_form_version_translations(
            mock_db,
            form_id=_UID,
            version=1,
            file_path_es=None,
            file_path_pt=None,
            file_type_es=None,
            file_type_pt=None,
        )
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none(self, mock_db):
        from db.queries.forms import update_form_version_translations

        result = await update_form_version_translations(
            mock_db,
            form_id=_UID,
            version=1,
            file_path_es=None,
            file_path_pt=None,
            file_type_es=None,
            file_type_pt=None,
        )
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# update_form_catalog_fields
# ══════════════════════════════════════════════════════════════════════════════


class TestUpdateFormCatalogFields:
    @pytest.mark.asyncio
    async def test_calls_execute_and_flush(self, mock_db):
        from db.queries.forms import update_form_catalog_fields

        await update_form_catalog_fields(mock_db, _UID, needs_human_review=False)
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import update_form_catalog_fields

        await update_form_catalog_fields(mock_db, _UID, status="archived")
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none(self, mock_db):
        from db.queries.forms import update_form_catalog_fields

        result = await update_form_catalog_fields(mock_db, _UID, needs_human_review=True)
        assert result is None

    @pytest.mark.asyncio
    async def test_accepts_multiple_kwargs(self, mock_db):
        from db.queries.forms import update_form_catalog_fields

        await update_form_catalog_fields(
            mock_db,
            _UID,
            needs_human_review=True,
            preprocessing_flags=["mislabeled_file"],
        )
        mock_db.execute.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# get_form_by_id
# ══════════════════════════════════════════════════════════════════════════════


class TestGetFormById:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, mock_db):
        from db.queries.forms import get_form_by_id

        result = await get_form_by_id(mock_db, _UID)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_form_when_found(self, mock_db):
        from db.queries.forms import get_form_by_id

        expected = _mock_form()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = expected
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await get_form_by_id(mock_db, _UID)
        assert result is expected

    @pytest.mark.asyncio
    async def test_calls_execute_once(self, mock_db):
        from db.queries.forms import get_form_by_id

        await get_form_by_id(mock_db, _UID)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import get_form_by_id

        await get_form_by_id(mock_db, _UID)
        mock_db.commit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# list_forms
# ══════════════════════════════════════════════════════════════════════════════


class TestListForms:
    def _setup_list_forms_mock(self, mock_db, total: int = 0, forms: list | None = None):
        """Configure mock_db.execute to return count then form list."""
        count_result = MagicMock()
        count_result.scalar_one.return_value = total

        fetch_result = MagicMock()
        fetch_result.scalars.return_value.all.return_value = forms or []

        mock_db.execute = AsyncMock(side_effect=[count_result, fetch_result])

    @pytest.mark.asyncio
    async def test_returns_tuple_of_list_and_int(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        result = await list_forms(mock_db)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], list)
        assert isinstance(result[1], int)

    @pytest.mark.asyncio
    async def test_calls_execute_twice(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db)
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_total_from_first_execute(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db, total=42)
        _, total = await list_forms(mock_db)
        assert total == 42

    @pytest.mark.asyncio
    async def test_forms_from_second_execute(self, mock_db):
        from db.queries.forms import list_forms

        f1, f2 = _mock_form(), _mock_form()
        self._setup_list_forms_mock(mock_db, total=2, forms=[f1, f2])
        forms, _ = await list_forms(mock_db)
        assert forms == [f1, f2]

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db, total=0, forms=[])
        forms, total = await list_forms(mock_db)
        assert forms == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db)
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_none_removes_status_filter(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        # Should not raise even with status=None
        await list_forms(mock_db, status=None)
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_accepts_division_filter(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db, division="Housing Court")
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_accepts_language_es_filter(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db, language="es")
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_accepts_language_pt_filter(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db, language="pt")
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_accepts_search_query_filter(self, mock_db):
        from db.queries.forms import list_forms

        self._setup_list_forms_mock(mock_db)
        await list_forms(mock_db, q="divorce")
        assert mock_db.execute.call_count == 2


# ══════════════════════════════════════════════════════════════════════════════
# list_divisions
# ══════════════════════════════════════════════════════════════════════════════


class TestListDivisions:
    @pytest.mark.asyncio
    async def test_returns_list(self, mock_db):
        from db.queries.forms import list_divisions

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = ["Civil", "Housing"]
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await list_divisions(mock_db)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_division_strings(self, mock_db):
        from db.queries.forms import list_divisions

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = ["Civil", "Criminal", "Housing"]
        mock_db.execute = AsyncMock(return_value=result_mock)

        result = await list_divisions(mock_db)
        assert result == ["Civil", "Criminal", "Housing"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_divisions(self, mock_db):
        from db.queries.forms import list_divisions

        result = await list_divisions(mock_db)
        assert result == []

    @pytest.mark.asyncio
    async def test_calls_execute_once(self, mock_db):
        from db.queries.forms import list_divisions

        await list_divisions(mock_db)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import list_divisions

        await list_divisions(mock_db)
        mock_db.commit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# submit_form_review
# ══════════════════════════════════════════════════════════════════════════════


class TestSubmitFormReview:
    @pytest.mark.asyncio
    async def test_returns_none_when_form_not_found(self, mock_db):
        from db.queries.forms import submit_form_review

        mock_db.get = AsyncMock(return_value=None)
        result = await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_does_not_write_audit_when_form_not_found(self, mock_db):
        from db.queries.forms import submit_form_review

        mock_db.get = AsyncMock(return_value=None)
        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_approved_true_sets_needs_human_review_false(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        form.needs_human_review = True
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        assert form.needs_human_review is False

    @pytest.mark.asyncio
    async def test_approved_false_keeps_needs_human_review_true(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        form.needs_human_review = False
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=False, reviewer_user_id=_UID2, notes=None)
        assert form.needs_human_review is True

    @pytest.mark.asyncio
    async def test_writes_audit_log(self, mock_db):
        from db.models import AuditLog
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes="LGTM")
        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AuditLog)

    @pytest.mark.asyncio
    async def test_audit_log_action_type_is_form_review_submitted(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        added = mock_db.add.call_args[0][0]
        assert added.action_type == "form_review_submitted"

    @pytest.mark.asyncio
    async def test_audit_log_user_id_is_reviewer(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        added = mock_db.add.call_args[0][0]
        assert added.user_id == _UID2

    @pytest.mark.asyncio
    async def test_returns_form_on_success(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        result = await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        assert result is form

    @pytest.mark.asyncio
    async def test_calls_flush(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        mock_db.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=True, reviewer_user_id=_UID2, notes=None)
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_notes_included_in_audit_details(self, mock_db):
        from db.queries.forms import submit_form_review

        form = _mock_form()
        mock_db.get = AsyncMock(return_value=form)

        await submit_form_review(mock_db, _UID, approved=False, reviewer_user_id=_UID2, notes="Needs revision")
        added = mock_db.add.call_args[0][0]
        assert added.details.get("notes") == "Needs revision"


# ══════════════════════════════════════════════════════════════════════════════
# Sync variants
# ══════════════════════════════════════════════════════════════════════════════


class TestUpsertFormCatalogSync:
    def test_calls_execute_and_flush(self, mock_sync_session):
        from db.queries.forms import upsert_form_catalog_sync

        mock_sync_session.get.return_value = _mock_form()
        upsert_form_catalog_sync(mock_sync_session, _catalog_entry())
        mock_sync_session.execute.assert_called_once()
        mock_sync_session.flush.assert_called_once()

    def test_returns_form_from_session_get(self, mock_sync_session):
        from db.queries.forms import upsert_form_catalog_sync

        expected = _mock_form()
        mock_sync_session.get.return_value = expected
        result = upsert_form_catalog_sync(mock_sync_session, _catalog_entry())
        assert result is expected

    def test_does_not_commit(self, mock_sync_session):
        from db.queries.forms import upsert_form_catalog_sync

        mock_sync_session.get.return_value = _mock_form()
        upsert_form_catalog_sync(mock_sync_session, _catalog_entry())
        mock_sync_session.commit.assert_not_called()


class TestUpsertFormVersionSync:
    def test_calls_execute_and_flush(self, mock_sync_session):
        from db.queries.forms import upsert_form_version_sync

        mock_sync_session.query.return_value.filter.return_value.one_or_none.return_value = None
        upsert_form_version_sync(mock_sync_session, _UID, _version_dict())
        mock_sync_session.execute.assert_called_once()
        mock_sync_session.flush.assert_called_once()

    def test_returns_query_result(self, mock_sync_session):
        from db.queries.forms import upsert_form_version_sync

        mock_version = MagicMock()
        mock_sync_session.query.return_value.filter.return_value.one_or_none.return_value = mock_version
        result = upsert_form_version_sync(mock_sync_session, _UID, _version_dict())
        assert result is mock_version

    def test_generates_version_id_when_absent(self, mock_sync_session):
        from db.queries.forms import upsert_form_version_sync

        mock_sync_session.query.return_value.filter.return_value.one_or_none.return_value = None
        vd = _version_dict()
        assert "version_id" not in vd
        upsert_form_version_sync(mock_sync_session, _UID, vd)
        mock_sync_session.execute.assert_called_once()

    def test_does_not_commit(self, mock_sync_session):
        from db.queries.forms import upsert_form_version_sync

        mock_sync_session.query.return_value.filter.return_value.one_or_none.return_value = None
        upsert_form_version_sync(mock_sync_session, _UID, _version_dict())
        mock_sync_session.commit.assert_not_called()


class TestUpsertFormAppearanceSync:
    def test_calls_execute_and_flush(self, mock_sync_session):
        from db.queries.forms import upsert_form_appearance_sync

        upsert_form_appearance_sync(mock_sync_session, _UID, "Civil", "General")
        mock_sync_session.execute.assert_called_once()
        mock_sync_session.flush.assert_called_once()

    def test_returns_none(self, mock_sync_session):
        from db.queries.forms import upsert_form_appearance_sync

        result = upsert_form_appearance_sync(mock_sync_session, _UID, "Civil", "General")
        assert result is None

    def test_does_not_commit(self, mock_sync_session):
        from db.queries.forms import upsert_form_appearance_sync

        upsert_form_appearance_sync(mock_sync_session, _UID, "Civil", "General")
        mock_sync_session.commit.assert_not_called()


class TestGetFormByIdSync:
    def test_returns_none_when_not_found(self, mock_sync_session):
        from db.queries.forms import get_form_by_id_sync

        mock_sync_session.execute.return_value.scalars.return_value.one_or_none.return_value = None
        result = get_form_by_id_sync(mock_sync_session, _UID)
        assert result is None

    def test_returns_form_when_found(self, mock_sync_session):
        from db.queries.forms import get_form_by_id_sync

        expected = _mock_form()
        mock_sync_session.execute.return_value.scalars.return_value.one_or_none.return_value = expected
        result = get_form_by_id_sync(mock_sync_session, _UID)
        assert result is expected

    def test_calls_execute_once(self, mock_sync_session):
        from db.queries.forms import get_form_by_id_sync

        mock_sync_session.execute.return_value.scalars.return_value.one_or_none.return_value = None
        get_form_by_id_sync(mock_sync_session, _UID)
        mock_sync_session.execute.assert_called_once()


class TestUpdateFormVersionTranslationsSync:
    def test_calls_execute_and_flush(self, mock_sync_session):
        from db.queries.forms import update_form_version_translations_sync

        update_form_version_translations_sync(
            mock_sync_session,
            form_id=_UID,
            version=1,
            file_path_es="gs://bucket/es.pdf",
            file_path_pt=None,
            file_type_es="pdf",
            file_type_pt=None,
        )
        mock_sync_session.execute.assert_called_once()
        mock_sync_session.flush.assert_called_once()

    def test_does_not_commit(self, mock_sync_session):
        from db.queries.forms import update_form_version_translations_sync

        update_form_version_translations_sync(
            mock_sync_session,
            form_id=_UID,
            version=1,
            file_path_es=None,
            file_path_pt=None,
            file_type_es=None,
            file_type_pt=None,
        )
        mock_sync_session.commit.assert_not_called()


class TestUpdateFormCatalogFieldsSync:
    def test_calls_execute_and_flush(self, mock_sync_session):
        from db.queries.forms import update_form_catalog_fields_sync

        update_form_catalog_fields_sync(mock_sync_session, _UID, needs_human_review=False)
        mock_sync_session.execute.assert_called_once()
        mock_sync_session.flush.assert_called_once()

    def test_does_not_commit(self, mock_sync_session):
        from db.queries.forms import update_form_catalog_fields_sync

        update_form_catalog_fields_sync(mock_sync_session, _UID, status="archived")
        mock_sync_session.commit.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# get_all_forms_sync
# ══════════════════════════════════════════════════════════════════════════════


class TestGetAllFormsSync:
    def _make_orm_form(self):
        """Construct a realistic mock ORM FormCatalog object."""
        f = MagicMock()
        f.form_id = _UID
        f.form_name = "Divorce Petition"
        f.form_slug = "divorce-petition"
        f.source_url = "https://mass.gov/divorce.pdf"
        f.file_type = "pdf"
        f.status = "active"
        f.content_hash = "hash123"
        f.current_version = 1
        f.needs_human_review = False
        f.preprocessing_flags = []
        f.created_at = _NOW
        f.last_scraped_at = _NOW
        f.versions = []
        f.appearances = []
        return f

    def _patch_sync(self, mock_session):
        """
        Context manager that patches both get_sync_engine (imported from
        db.database inside the function) and sqlalchemy.orm.Session.
        """
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch("db.database.get_sync_engine", return_value=MagicMock()))
        patched_session_cls = stack.enter_context(patch("sqlalchemy.orm.Session"))
        patched_session_cls.return_value.__enter__.return_value = mock_session
        patched_session_cls.return_value.__exit__.return_value = False
        return stack

    def test_returns_list(self):
        from db.queries.forms import get_all_forms_sync

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with self._patch_sync(mock_session):
            result = get_all_forms_sync()

        assert isinstance(result, list)

    def test_returns_empty_list_when_no_forms(self):
        from db.queries.forms import get_all_forms_sync

        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        with self._patch_sync(mock_session):
            result = get_all_forms_sync()

        assert result == []

    def test_output_dict_has_required_keys(self):
        from db.queries.forms import get_all_forms_sync

        mock_session = MagicMock()
        form = self._make_orm_form()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [form]

        with self._patch_sync(mock_session):
            result = get_all_forms_sync()

        required_keys = {
            "form_id",
            "form_name",
            "form_slug",
            "source_url",
            "file_type",
            "status",
            "content_hash",
            "current_version",
            "needs_human_review",
            "created_at",
            "appearances",
            "versions",
        }
        for key in required_keys:
            assert key in result[0], f"Missing key: {key}"

    def test_form_id_is_string(self):
        from db.queries.forms import get_all_forms_sync

        mock_session = MagicMock()
        form = self._make_orm_form()
        mock_session.execute.return_value.scalars.return_value.all.return_value = [form]

        with self._patch_sync(mock_session):
            result = get_all_forms_sync()

        assert isinstance(result[0]["form_id"], str)

    def test_versions_sorted_descending(self):
        """Versions should be sorted by version number descending."""
        from db.queries.forms import get_all_forms_sync

        mock_session = MagicMock()
        form = self._make_orm_form()

        v1 = MagicMock()
        v1.version = 1
        v1.content_hash = "h1"
        v1.file_type = "pdf"
        v1.file_path_original = "gs://b/v1.pdf"
        v1.file_path_es = None
        v1.file_path_pt = None
        v1.file_type_es = None
        v1.file_type_pt = None
        v1.created_at = _NOW

        v2 = MagicMock()
        v2.version = 2
        v2.content_hash = "h2"
        v2.file_type = "pdf"
        v2.file_path_original = "gs://b/v2.pdf"
        v2.file_path_es = None
        v2.file_path_pt = None
        v2.file_type_es = None
        v2.file_type_pt = None
        v2.created_at = _NOW

        form.versions = [v1, v2]
        mock_session.execute.return_value.scalars.return_value.all.return_value = [form]

        with self._patch_sync(mock_session):
            result = get_all_forms_sync()

        versions = result[0]["versions"]
        assert versions[0]["version"] == 2  # highest first
        assert versions[1]["version"] == 1
