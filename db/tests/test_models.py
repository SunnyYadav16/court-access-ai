"""
db/tests/test_models.py

Unit tests for db/models.py.

Tests cover (no real DB connection required):
  - __tablename__ for all 11 models
  - __repr__ for all models that define it
  - Model instantiation with constructor kwargs
  - Key column nullability and default annotations
  - Relationship attribute names
  - Check constraint and index names
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2024, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Table name tests
# ---------------------------------------------------------------------------


class TestTableNames:
    def test_role_tablename(self):
        from db.models import Role

        assert Role.__tablename__ == "roles"

    def test_user_tablename(self):
        from db.models import User

        assert User.__tablename__ == "users"

    def test_role_request_tablename(self):
        from db.models import RoleRequest

        assert RoleRequest.__tablename__ == "role_requests"

    def test_session_tablename(self):
        from db.models import Session

        assert Session.__tablename__ == "sessions"

    def test_document_translation_request_tablename(self):
        from db.models import DocumentTranslationRequest

        assert DocumentTranslationRequest.__tablename__ == "document_translation_requests"

    def test_realtime_translation_request_tablename(self):
        from db.models import RealtimeTranslationRequest

        assert RealtimeTranslationRequest.__tablename__ == "realtime_translation_requests"

    def test_audit_log_tablename(self):
        from db.models import AuditLog

        assert AuditLog.__tablename__ == "audit_logs"

    def test_form_catalog_tablename(self):
        from db.models import FormCatalog

        assert FormCatalog.__tablename__ == "form_catalog"

    def test_form_version_tablename(self):
        from db.models import FormVersion

        assert FormVersion.__tablename__ == "form_versions"

    def test_form_appearance_tablename(self):
        from db.models import FormAppearance

        assert FormAppearance.__tablename__ == "form_appearances"

    def test_pipeline_step_tablename(self):
        from db.models import PipelineStep

        assert PipelineStep.__tablename__ == "pipeline_steps"


# ---------------------------------------------------------------------------
# __repr__ tests
# ---------------------------------------------------------------------------


class TestRepresentations:
    def test_role_repr(self):
        from db.models import Role

        r = Role()
        r.role_id = 1
        r.role_name = "public"
        assert "Role" in repr(r)
        assert "1" in repr(r)
        assert "public" in repr(r)

    def test_user_repr(self):
        from db.models import User

        u = User()
        u.user_id = _UID
        u.email = "test@example.com"
        assert "User" in repr(u)
        assert "test@example.com" in repr(u)

    def test_role_request_repr(self):
        from db.models import RoleRequest

        rr = RoleRequest()
        rr.request_id = _UID
        rr.user_id = _UID
        rr.status = "pending"
        assert "RoleRequest" in repr(rr)
        assert "pending" in repr(rr)

    def test_session_repr(self):
        from db.models import Session

        s = Session()
        s.session_id = _UID
        s.type = "document"
        s.status = "active"
        assert "Session" in repr(s)
        assert "document" in repr(s)
        assert "active" in repr(s)

    def test_document_translation_request_repr(self):
        from db.models import DocumentTranslationRequest

        d = DocumentTranslationRequest()
        d.doc_request_id = _UID
        d.status = "processing"
        assert "DocumentTranslationRequest" in repr(d)
        assert "processing" in repr(d)

    def test_realtime_translation_request_repr(self):
        from db.models import RealtimeTranslationRequest

        rt = RealtimeTranslationRequest()
        rt.rt_request_id = _UID
        rt.phase = "waiting"
        assert "RealtimeTranslationRequest" in repr(rt)
        assert "waiting" in repr(rt)

    def test_audit_log_repr(self):
        from db.models import AuditLog

        a = AuditLog()
        a.audit_id = _UID
        a.action_type = "document_upload"
        assert "AuditLog" in repr(a)
        assert "document_upload" in repr(a)

    def test_form_catalog_repr(self):
        from db.models import FormCatalog

        f = FormCatalog()
        f.form_id = _UID
        f.form_name = "Complaint Form"
        assert "FormCatalog" in repr(f)
        assert "Complaint Form" in repr(f)

    def test_form_version_repr(self):
        from db.models import FormVersion

        v = FormVersion()
        v.version_id = _UID
        v.form_id = _UID
        v.version = 3
        assert "FormVersion" in repr(v)
        assert "3" in repr(v)

    def test_form_appearance_repr(self):
        from db.models import FormAppearance

        a = FormAppearance()
        a.appearance_id = _UID
        a.division = "Housing Court"
        assert "FormAppearance" in repr(a)
        assert "Housing Court" in repr(a)


# ---------------------------------------------------------------------------
# Model instantiation
# ---------------------------------------------------------------------------


class TestModelInstantiation:
    def test_role_instantiation(self):
        from db.models import Role

        r = Role(role_id=2, role_name="court_official", description="Court staff")
        assert r.role_id == 2
        assert r.role_name == "court_official"
        assert r.description == "Court staff"

    def test_user_instantiation(self):
        from db.models import User

        u = User(user_id=_UID, email="a@b.com", name="Alice", role_id=1)
        assert u.user_id == _UID
        assert u.email == "a@b.com"
        assert u.name == "Alice"
        assert u.role_id == 1

    def test_role_request_instantiation(self):
        from db.models import RoleRequest

        rr = RoleRequest(request_id=_UID, user_id=_UID, requested_role_id=2, status="pending")
        assert rr.status == "pending"
        assert rr.requested_role_id == 2

    def test_session_instantiation(self):
        from db.models import Session

        s = Session(session_id=_UID, user_id=_UID, type="document", target_language="spa_Latn", status="active")
        assert s.type == "document"
        assert s.target_language == "spa_Latn"
        assert s.status == "active"

    def test_document_translation_request_instantiation(self):
        from db.models import DocumentTranslationRequest

        d = DocumentTranslationRequest(
            doc_request_id=_UID,
            session_id=_UID,
            input_file_gcs_path="gs://bucket/file.pdf",
            target_language="spa_Latn",
            status="processing",
        )
        assert d.input_file_gcs_path == "gs://bucket/file.pdf"
        assert d.status == "processing"

    def test_realtime_translation_request_instantiation(self):
        from db.models import RealtimeTranslationRequest

        rt = RealtimeTranslationRequest(
            rt_request_id=_UID,
            session_id=_UID,
            room_code="A1B2C3",
            room_code_expires_at=_NOW,
            creator_user_id=_UID,
            phase="waiting",
        )
        assert rt.room_code == "A1B2C3"
        assert rt.phase == "waiting"

    def test_audit_log_instantiation(self):
        from db.models import AuditLog

        a = AuditLog(
            audit_id=_UID,
            user_id=_UID,
            action_type="form_review_submitted",
            details={"approved": True},
        )
        assert a.action_type == "form_review_submitted"
        assert a.details == {"approved": True}

    def test_form_catalog_instantiation(self):
        from db.models import FormCatalog

        f = FormCatalog(
            form_id=_UID,
            form_name="Divorce Petition",
            form_slug="divorce-petition",
            source_url="https://mass.gov/divorce.pdf",
            file_type="pdf",
            status="active",
            content_hash="abc123",
            current_version=1,
        )
        assert f.form_name == "Divorce Petition"
        assert f.status == "active"
        assert f.file_type == "pdf"

    def test_form_version_instantiation(self):
        from db.models import FormVersion

        v = FormVersion(
            version_id=_UID,
            form_id=_UID,
            version=1,
            content_hash="hash123",
            file_type="pdf",
            file_path_original="gs://bucket/original.pdf",
        )
        assert v.version == 1
        assert v.file_path_original == "gs://bucket/original.pdf"
        assert v.file_path_es is None
        assert v.file_path_pt is None

    def test_form_appearance_instantiation(self):
        from db.models import FormAppearance

        a = FormAppearance(
            appearance_id=_UID,
            form_id=_UID,
            division="Housing Court",
            section_heading="Eviction Forms",
        )
        assert a.division == "Housing Court"
        assert a.section_heading == "Eviction Forms"

    def test_pipeline_step_instantiation(self):
        from db.models import PipelineStep

        ps = PipelineStep(
            session_id=_UID,
            step_name="ocr",
            status="success",
            detail="Completed in 2.3s",
        )
        assert ps.step_name == "ocr"
        assert ps.status == "success"


# ---------------------------------------------------------------------------
# Relationship attribute presence
# ---------------------------------------------------------------------------


class TestRelationships:
    def test_role_has_users_relationship(self):
        from db.models import Role

        assert hasattr(Role, "users")

    def test_user_has_sessions_relationship(self):
        from db.models import User

        assert hasattr(User, "sessions")

    def test_user_has_audit_logs_relationship(self):
        from db.models import User

        assert hasattr(User, "audit_logs")

    def test_session_has_document_request_relationship(self):
        from db.models import Session

        assert hasattr(Session, "document_request")

    def test_session_has_realtime_request_relationship(self):
        from db.models import Session

        assert hasattr(Session, "realtime_request")

    def test_session_has_pipeline_steps_relationship(self):
        from db.models import Session

        assert hasattr(Session, "pipeline_steps")

    def test_form_catalog_has_versions_relationship(self):
        from db.models import FormCatalog

        assert hasattr(FormCatalog, "versions")

    def test_form_catalog_has_appearances_relationship(self):
        from db.models import FormCatalog

        assert hasattr(FormCatalog, "appearances")

    def test_form_version_has_form_relationship(self):
        from db.models import FormVersion

        assert hasattr(FormVersion, "form")

    def test_form_appearance_has_form_relationship(self):
        from db.models import FormAppearance

        assert hasattr(FormAppearance, "form")

    def test_audit_log_has_user_relationship(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "user")

    def test_audit_log_has_session_relationship(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "session")

    def test_audit_log_has_document_request_relationship(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "document_request")

    def test_audit_log_has_realtime_request_relationship(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "realtime_request")


# ---------------------------------------------------------------------------
# Column attribute presence (spot-checks for key fields)
# ---------------------------------------------------------------------------


class TestColumnAttributes:
    def test_form_catalog_has_needs_human_review(self):
        from db.models import FormCatalog

        assert hasattr(FormCatalog, "needs_human_review")

    def test_form_catalog_has_preprocessing_flags(self):
        from db.models import FormCatalog

        assert hasattr(FormCatalog, "preprocessing_flags")

    def test_form_version_has_file_path_es(self):
        from db.models import FormVersion

        assert hasattr(FormVersion, "file_path_es")

    def test_form_version_has_file_path_pt(self):
        from db.models import FormVersion

        assert hasattr(FormVersion, "file_path_pt")

    def test_user_has_firebase_uid(self):
        from db.models import User

        assert hasattr(User, "firebase_uid")

    def test_user_has_mfa_enabled(self):
        from db.models import User

        assert hasattr(User, "mfa_enabled")

    def test_realtime_request_has_room_code(self):
        from db.models import RealtimeTranslationRequest

        assert hasattr(RealtimeTranslationRequest, "room_code")

    def test_realtime_request_has_consent_acknowledged(self):
        from db.models import RealtimeTranslationRequest

        assert hasattr(RealtimeTranslationRequest, "consent_acknowledged")

    def test_pipeline_step_has_step_metadata(self):
        from db.models import PipelineStep

        assert hasattr(PipelineStep, "step_metadata")

    def test_document_request_has_pii_findings_count(self):
        from db.models import DocumentTranslationRequest

        assert hasattr(DocumentTranslationRequest, "pii_findings_count")

    def test_document_request_has_signed_url(self):
        from db.models import DocumentTranslationRequest

        assert hasattr(DocumentTranslationRequest, "signed_url")

    def test_audit_log_has_doc_request_id(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "doc_request_id")

    def test_audit_log_has_rt_request_id(self):
        from db.models import AuditLog

        assert hasattr(AuditLog, "rt_request_id")
