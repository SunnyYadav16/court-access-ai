"""
db/queries/audit.py

Shared audit log writer used by all API routes.

All DB operations in the forms and documents flows write audit entries
through this single function so the schema, field names, and commit
discipline stay consistent across the codebase.

Usage:
    from db.queries.audit import write_audit

    await write_audit(
        db,
        user_id=user.user_id,
        action_type="document_upload",
        details={"filename": ..., "gcs_path": ...},
        session_id=session_id,   # optional
        request_id=request_id,  # optional
    )
    # caller commits — write_audit only adds to the session
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


async def write_audit(
    db: AsyncSession,
    user_id: uuid.UUID,
    action_type: str,
    details: dict[str, Any],
    *,
    session_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
) -> None:
    """
    Append an immutable audit log row to the current session.

    Does NOT commit — the caller is responsible for ``await db.commit()``.
    This keeps the audit write transactional with the surrounding business
    logic: if the enclosing commit rolls back, the audit row is also rolled
    back, preventing orphan audit entries.

    Args:
        db:          The active async SQLAlchemy session.
        user_id:     UUID of the acting user. Use the system user UUID
                     ``00000000-0000-0000-0000-000000000001`` for scheduler-
                     triggered DAG runs (added by migration 007).
        action_type: Short snake_case label, e.g. ``document_upload``,
                     ``form_scrape_triggered``, ``form_review_submitted``.
        details:     Arbitrary JSON-serialisable dict stored in the JSONB
                     ``details`` column.
        session_id:  Optional FK to ``sessions.session_id``.
        request_id:  Optional FK to ``translation_requests.request_id``.
    """
    from db.models import AuditLog

    log = AuditLog(
        audit_id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
        action_type=action_type,
        details=details,
    )
    db.add(log)


def write_audit_sync(
    conn: sa.Connection,
    *,
    user_id: str,
    action_type: str,
    details: dict[str, Any],
    session_id: str | None = None,
    request_id: str | None = None,
) -> None:
    """
    Sync audit writer for Airflow DAG tasks.

    Does NOT commit. Caller owns transaction boundary (use conn in a begin() block).
    """
    conn.execute(
        sa.text(
            """
            INSERT INTO audit_logs
                (audit_id, user_id, session_id, request_id, action_type, details, created_at)
            VALUES
                (CAST(:audit_id AS uuid), CAST(:user_id AS uuid), CAST(:session_id AS uuid), CAST(:request_id AS uuid), :action_type, CAST(:details AS jsonb), NOW())
            """
        ),
        {
            "audit_id": str(uuid.uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "request_id": request_id,
            "action_type": action_type,
            "details": json.dumps(details),
        },
    )
