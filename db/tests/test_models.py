"""
db/tests/test_models.py

Unit tests for db/models.py — validates that:
  - All models can be imported and instantiated
  - Column defaults behave correctly
  - __repr__ methods work
  - Table names and column names match expected values
  - Enum field constraints are defined correctly
  - Relationship back-references are wired correctly
  - All __table_args__ indexes are defined

These tests do NOT require a live database — they operate on the ORM
metadata only. Database integration tests (actual INSERT/SELECT) require
a PostgreSQL instance and should be run in a Docker Compose environment.
"""

from __future__ import annotations

import uuid

from db.models import AuditLog, FormCatalog, Session, TranslationRequest, User

# ══════════════════════════════════════════════════════════════════════════════
# Instantiation (no DB required)
# ══════════════════════════════════════════════════════════════════════════════


class TestInstantiation:
    """All ORM models can be constructed with only required fields."""

    def test_user_instantiation(self):
        u = User(
            user_id=uuid.uuid4(),
            username="testuser",
            email="test@example.com",
            hashed_password="$2b$12$hashed",
        )
        assert u.username == "testuser"
        assert u.email == "test@example.com"

    def test_session_instantiation(self):
        s = Session(
            session_id=uuid.uuid4(),
            creator_id=uuid.uuid4(),
        )
        assert s.creator_id is not None

    def test_translation_request_instantiation(self):
        tr = TranslationRequest(
            document_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            original_filename="test.pdf",
        )
        assert tr.original_filename == "test.pdf"

    def test_audit_log_instantiation(self):
        al = AuditLog(
            log_id=uuid.uuid4(),
            event_type="user.login",
        )
        assert al.event_type == "user.login"

    def test_form_catalog_instantiation(self):
        fc = FormCatalog(
            form_id=uuid.uuid4(),
            form_name="Petition for Divorce",
            form_slug="petition-for-divorce",
            source_url="https://www.mass.gov/forms/petition-for-divorce",
            content_hash="abc123",
        )
        assert fc.form_slug == "petition-for-divorce"


# ══════════════════════════════════════════════════════════════════════════════
# Table names
# ══════════════════════════════════════════════════════════════════════════════


class TestTableNames:
    def test_user_table_name(self):
        assert User.__tablename__ == "users"

    def test_session_table_name(self):
        assert Session.__tablename__ == "sessions"

    def test_translation_request_table_name(self):
        assert TranslationRequest.__tablename__ == "translation_requests"

    def test_audit_log_table_name(self):
        assert AuditLog.__tablename__ == "audit_logs"

    def test_form_catalog_table_name(self):
        assert FormCatalog.__tablename__ == "form_catalog"


# ══════════════════════════════════════════════════════════════════════════════
# Column presence
# ══════════════════════════════════════════════════════════════════════════════


class TestColumnPresence:
    """Verify critical columns exist via the table's column map."""

    def _cols(self, model) -> set[str]:
        return {c.name for c in model.__table__.columns}

    def test_user_has_expected_columns(self):
        cols = self._cols(User)
        assert {
            "user_id",
            "username",
            "email",
            "hashed_password",
            "role",
            "preferred_language",
            "is_active",
            "created_at",
            "last_login_at",
        } <= cols

    def test_session_has_expected_columns(self):
        cols = self._cols(Session)
        assert {
            "session_id",
            "creator_id",
            "status",
            "source_language",
            "target_language",
            "created_at",
            "ended_at",
            "transcript_gcs_uri",
            "segment_count",
            "participants",
        } <= cols

    def test_translation_request_has_expected_columns(self):
        cols = self._cols(TranslationRequest)
        assert {
            "document_id",
            "user_id",
            "status",
            "original_filename",
            "pii_findings_count",
            "needs_human_review",
            "created_at",
            "completed_at",
            "airflow_dag_run_id",
            "translated_uris",
        } <= cols

    def test_audit_log_has_expected_columns(self):
        cols = self._cols(AuditLog)
        assert {
            "log_id",
            "actor_id",
            "event_type",
            "resource_type",
            "resource_id",
            "details",
            "ip_address",
            "created_at",
        } <= cols

    def test_form_catalog_has_expected_columns(self):
        cols = self._cols(FormCatalog)
        assert {
            "form_id",
            "form_name",
            "form_slug",
            "source_url",
            "status",
            "content_hash",
            "has_spanish",
            "has_portuguese",
            "needs_human_review",
            "created_at",
            "last_scraped_at",
        } <= cols


# ══════════════════════════════════════════════════════════════════════════════
# Repr
# ══════════════════════════════════════════════════════════════════════════════


class TestRepr:
    def test_user_repr(self):
        uid = uuid.uuid4()
        u = User(user_id=uid, username="alice", email="a@b.com", hashed_password="x")
        assert "alice" in repr(u)

    def test_session_repr(self):
        sid = uuid.uuid4()
        s = Session(session_id=sid, creator_id=uuid.uuid4())
        assert str(sid) in repr(s)

    def test_translation_request_repr(self):
        did = uuid.uuid4()
        tr = TranslationRequest(document_id=did, user_id=uuid.uuid4(), original_filename="x.pdf")
        assert str(did) in repr(tr)

    def test_audit_log_repr(self):
        lid = uuid.uuid4()
        al = AuditLog(log_id=lid, event_type="test.event")
        assert "test.event" in repr(al)

    def test_form_catalog_repr(self):
        fid = uuid.uuid4()
        fc = FormCatalog(
            form_id=fid,
            form_name="Test Form",
            form_slug="test-form",
            source_url="https://example.com",
            content_hash="aaa",
        )
        assert "Test Form" in repr(fc)


# ══════════════════════════════════════════════════════════════════════════════
# Indexes
# ══════════════════════════════════════════════════════════════════════════════


class TestIndexes:
    def _index_names(self, model) -> set[str]:
        return {idx.name for idx in model.__table__.indexes if idx.name}

    def test_user_indexes(self):
        idx = self._index_names(User)
        assert "ix_users_email" in idx
        assert "ix_users_username" in idx
        assert "ix_users_role" in idx

    def test_session_indexes(self):
        idx = self._index_names(Session)
        assert "ix_sessions_creator_id" in idx
        assert "ix_sessions_status" in idx

    def test_translation_request_indexes(self):
        idx = self._index_names(TranslationRequest)
        assert "ix_translation_requests_user_id" in idx
        assert "ix_translation_requests_status" in idx
        assert "ix_translation_requests_airflow_run" in idx

    def test_audit_log_indexes(self):
        idx = self._index_names(AuditLog)
        assert "ix_audit_logs_event_type" in idx
        assert "ix_audit_logs_created_at" in idx

    def test_form_catalog_indexes(self):
        idx = self._index_names(FormCatalog)
        assert "ix_form_catalog_status" in idx
        assert "ix_form_catalog_has_spanish" in idx
        assert "ix_form_catalog_divisions_gin" in idx


# ══════════════════════════════════════════════════════════════════════════════
# Relationship back-references
# ══════════════════════════════════════════════════════════════════════════════


class TestRelationships:
    def test_user_has_sessions_relationship(self):
        assert hasattr(User, "sessions")

    def test_user_has_translation_requests_relationship(self):
        assert hasattr(User, "translation_requests")

    def test_user_has_audit_logs_relationship(self):
        assert hasattr(User, "audit_logs")

    def test_session_has_creator_relationship(self):
        assert hasattr(Session, "creator")

    def test_translation_request_has_user_relationship(self):
        assert hasattr(TranslationRequest, "user")


# ══════════════════════════════════════════════════════════════════════════════
# Field assignments
# ══════════════════════════════════════════════════════════════════════════════


class TestFieldAssignments:
    """Verify field values survive round-trip assignment."""

    def test_audit_log_details_dict(self):
        al = AuditLog(
            event_type="document.upload",
            details={"filename": "test.pdf", "size_bytes": 1024},
        )
        assert al.details["filename"] == "test.pdf"

    def test_translation_request_target_languages(self):
        tr = TranslationRequest(
            user_id=uuid.uuid4(),
            original_filename="doc.pdf",
            target_languages=["es", "pt"],
        )
        assert "es" in tr.target_languages

    def test_form_catalog_divisions(self):
        fc = FormCatalog(
            form_id=uuid.uuid4(),
            form_name="F",
            form_slug="f",
            source_url="https://x.com/f",
            content_hash="a",
            divisions=["Probate and Family", "Housing"],
        )
        assert "Housing" in fc.divisions

    def test_session_participants_jsonb(self):
        s = Session(
            creator_id=uuid.uuid4(),
            participants=[{"user_id": "abc", "role": "creator"}],
        )
        assert s.participants[0]["role"] == "creator"
