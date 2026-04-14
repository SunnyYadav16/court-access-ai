"""
db/tests/test_queries_audit.py

Unit tests for db/queries/audit.py.

Coverage:
  write_audit (async):
    - Adds exactly one AuditLog to the session
    - Does NOT call db.commit (caller owns transaction)
    - Sets user_id and action_type correctly
    - details defaults to {} when None is passed
    - details dict is passed through unchanged
    - session_id is None by default
    - session_id, doc_request_id, rt_request_id forwarded when provided
    - Each call generates a distinct audit_id (uuid4)

  write_audit_sync (sync):
    - Calls conn.execute exactly once
    - Does NOT call conn.commit
    - Passes the correct action_type in the SQL params
    - Generates a uuid4 audit_id (string)
    - JSON-serialises the details dict
    - session_id and request_id forwarded as strings / None
"""

from __future__ import annotations

import json
import uuid

import pytest

# ---------------------------------------------------------------------------
# write_audit (async)
# ---------------------------------------------------------------------------


class TestWriteAudit:
    @pytest.mark.asyncio
    async def test_adds_exactly_one_audit_log(self, mock_db):
        from db.queries.audit import write_audit

        user_id = uuid.uuid4()
        await write_audit(mock_db, user_id=user_id, action_type="test_action")
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_added_object_is_audit_log(self, mock_db):
        from db.models import AuditLog
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x")
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AuditLog)

    @pytest.mark.asyncio
    async def test_does_not_commit(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x")
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_id_set_correctly(self, mock_db):
        from db.queries.audit import write_audit

        uid = uuid.uuid4()
        await write_audit(mock_db, user_id=uid, action_type="x")
        log = mock_db.add.call_args[0][0]
        assert log.user_id == uid

    @pytest.mark.asyncio
    async def test_action_type_set_correctly(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="document_upload")
        log = mock_db.add.call_args[0][0]
        assert log.action_type == "document_upload"

    @pytest.mark.asyncio
    async def test_details_defaults_to_empty_dict_when_none(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x", details=None)
        log = mock_db.add.call_args[0][0]
        assert log.details == {}

    @pytest.mark.asyncio
    async def test_details_passed_through(self, mock_db):
        from db.queries.audit import write_audit

        payload = {"file": "test.pdf", "size": 1024}
        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x", details=payload)
        log = mock_db.add.call_args[0][0]
        assert log.details == payload

    @pytest.mark.asyncio
    async def test_session_id_defaults_to_none(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x")
        log = mock_db.add.call_args[0][0]
        assert log.session_id is None

    @pytest.mark.asyncio
    async def test_session_id_forwarded(self, mock_db):
        from db.queries.audit import write_audit

        sid = uuid.uuid4()
        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x", session_id=sid)
        log = mock_db.add.call_args[0][0]
        assert log.session_id == sid

    @pytest.mark.asyncio
    async def test_doc_request_id_forwarded(self, mock_db):
        from db.queries.audit import write_audit

        doc_id = uuid.uuid4()
        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x", doc_request_id=doc_id)
        log = mock_db.add.call_args[0][0]
        assert log.doc_request_id == doc_id

    @pytest.mark.asyncio
    async def test_rt_request_id_forwarded(self, mock_db):
        from db.queries.audit import write_audit

        rt_id = uuid.uuid4()
        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x", rt_request_id=rt_id)
        log = mock_db.add.call_args[0][0]
        assert log.rt_request_id == rt_id

    @pytest.mark.asyncio
    async def test_doc_and_rt_ids_default_to_none(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x")
        log = mock_db.add.call_args[0][0]
        assert log.doc_request_id is None
        assert log.rt_request_id is None

    @pytest.mark.asyncio
    async def test_each_call_generates_distinct_audit_id(self, mock_db):
        from db.queries.audit import write_audit

        uid = uuid.uuid4()
        await write_audit(mock_db, user_id=uid, action_type="first")
        first_log = mock_db.add.call_args_list[0][0][0]

        await write_audit(mock_db, user_id=uid, action_type="second")
        second_log = mock_db.add.call_args_list[1][0][0]

        assert first_log.audit_id != second_log.audit_id

    @pytest.mark.asyncio
    async def test_audit_id_is_uuid(self, mock_db):
        from db.queries.audit import write_audit

        await write_audit(mock_db, user_id=uuid.uuid4(), action_type="x")
        log = mock_db.add.call_args[0][0]
        assert isinstance(log.audit_id, uuid.UUID)


# ---------------------------------------------------------------------------
# write_audit_sync
# ---------------------------------------------------------------------------


class TestWriteAuditSync:
    def test_calls_execute_once(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        write_audit_sync(
            mock_sync_conn,
            user_id=str(uuid.uuid4()),
            action_type="scrape_complete",
            details={"forms": 10},
        )
        mock_sync_conn.execute.assert_called_once()

    def test_does_not_commit(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        write_audit_sync(
            mock_sync_conn,
            user_id=str(uuid.uuid4()),
            action_type="x",
            details={},
        )
        mock_sync_conn.commit.assert_not_called()

    def test_action_type_in_params(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        write_audit_sync(
            mock_sync_conn,
            user_id=str(uuid.uuid4()),
            action_type="form_scrape_triggered",
            details={},
        )
        _, params = mock_sync_conn.execute.call_args[0]
        assert params["action_type"] == "form_scrape_triggered"

    def test_user_id_in_params(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        uid = str(uuid.uuid4())
        write_audit_sync(mock_sync_conn, user_id=uid, action_type="x", details={})
        _, params = mock_sync_conn.execute.call_args[0]
        assert params["user_id"] == uid

    def test_details_json_serialised(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        payload = {"count": 5, "status": "ok"}
        write_audit_sync(mock_sync_conn, user_id=str(uuid.uuid4()), action_type="x", details=payload)
        _, params = mock_sync_conn.execute.call_args[0]
        # details should be a JSON string
        assert params["details"] == json.dumps(payload)

    def test_audit_id_is_uuid_string(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        write_audit_sync(mock_sync_conn, user_id=str(uuid.uuid4()), action_type="x", details={})
        _, params = mock_sync_conn.execute.call_args[0]
        # Should be parseable as a UUID
        parsed = uuid.UUID(params["audit_id"])
        assert isinstance(parsed, uuid.UUID)

    def test_session_id_defaults_to_none(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        write_audit_sync(mock_sync_conn, user_id=str(uuid.uuid4()), action_type="x", details={})
        _, params = mock_sync_conn.execute.call_args[0]
        assert params["session_id"] is None

    def test_session_id_forwarded(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        sid = str(uuid.uuid4())
        write_audit_sync(
            mock_sync_conn,
            user_id=str(uuid.uuid4()),
            action_type="x",
            details={},
            session_id=sid,
        )
        _, params = mock_sync_conn.execute.call_args[0]
        assert params["session_id"] == sid

    def test_consecutive_calls_produce_unique_audit_ids(self, mock_sync_conn):
        from db.queries.audit import write_audit_sync

        uid = str(uuid.uuid4())
        write_audit_sync(mock_sync_conn, user_id=uid, action_type="first", details={})
        first_params = mock_sync_conn.execute.call_args_list[0][0][1]

        write_audit_sync(mock_sync_conn, user_id=uid, action_type="second", details={})
        second_params = mock_sync_conn.execute.call_args_list[1][0][1]

        assert first_params["audit_id"] != second_params["audit_id"]
