"""
api/routes/admin.py

Admin-only endpoints for the CourtAccess AI API.

All routes are gated by require_role("admin") and require a valid Bearer token.

Endpoints:
  GET  /admin/users             — List all users with their roles
  GET  /admin/users/{user_id}   — Get a single user's profile
  POST /admin/users/{user_id}/role — Promote or demote a user's role
  GET  /admin/role-requests      — List pending role upgrade requests
  POST /admin/role-requests/{request_id}/approve — Approve a role request
  POST /admin/role-requests/{request_id}/reject  — Reject a role request
  GET  /admin/audit-logs         — Paginated audit trail
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text

from api.dependencies import CurrentUser, DBSession, require_role
from api.schemas.schemas import UserResponse
from courtaccess.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    # Every route in this file requires admin role.
    # Individual routes still declare the dependency explicitly for
    # OpenAPI schema visibility.
    dependencies=[Depends(require_role("admin"))],
)

_AdminUser = Annotated[CurrentUser, Depends(require_role("admin"))]


# ══════════════════════════════════════════════════════════════════════════════
# Response models
# ══════════════════════════════════════════════════════════════════════════════


class AdminUserRow(BaseModel):
    user_id: uuid.UUID
    name: str
    email: str
    role: str
    last_login_at: datetime | None
    session_count: int
    is_active: bool  # True if last_login_at within the past 30 days
    created_at: datetime


class AuditEventSummary(BaseModel):
    audit_id: uuid.UUID
    action_type: str
    created_at: datetime
    details: dict | None

    model_config = {"from_attributes": True}


class AdminStats(BaseModel):
    active_sessions_total: int
    active_sessions_realtime: int
    active_sessions_document: int
    todays_translations_total: int
    todays_translations_docs: int
    todays_translations_realtime: int
    avg_nmt_confidence: float | None
    avg_asr_confidence: float | None
    last_scrape_at: datetime | None
    recent_audit_events: list[AuditEventSummary]


class AdminMetrics(BaseModel):
    # Drift: 7-day rolling averages
    nmt_confidence_es_7d: float | None
    nmt_confidence_pt_7d: float | None
    asr_confidence_7d: float | None
    ocr_confidence_7d: float | None
    llama_correction_rate_7d: float | None  # avg corrections per document request
    # Model health: avg seconds per step, derived from pipeline_steps.updated_at deltas
    model_latencies: dict[str, float | None]


class RoleAssignRequest(BaseModel):
    role_name: str  # "public" | "court_official" | "interpreter" | "admin"


class RoleRequestDecision(BaseModel):
    notes: str | None = None


class RoleRequestSummary(BaseModel):
    request_id: uuid.UUID
    user_id: uuid.UUID
    requested_role_id: int
    status: str
    requested_at: datetime
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/stats
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/stats",
    summary="Aggregated monitoring stats (admin only)",
    response_model=AdminStats,
)
async def get_admin_stats(
    admin: _AdminUser,
    db: DBSession,
) -> AdminStats:
    """
    Returns live session counts, today's translation totals, avg NMT confidence,
    last scrape timestamp, and the 8 most recent audit log entries.
    """
    from db.models import AuditLog, DocumentTranslationRequest, RealtimeTranslationRequest, Session

    now = datetime.now(tz=UTC)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Run sequentially — AsyncSession is not safe for concurrent execute() calls
    active_q = await db.execute(
        select(Session.type, func.count().label("cnt")).where(Session.status == "active").group_by(Session.type)
    )
    today_q = await db.execute(
        select(Session.type, func.count().label("cnt"))
        .where(Session.created_at >= today_midnight)
        .group_by(Session.type)
    )
    conf_q = await db.execute(
        select(func.avg(DocumentTranslationRequest.avg_confidence_score)).where(
            DocumentTranslationRequest.created_at >= today_midnight,
            DocumentTranslationRequest.avg_confidence_score.is_not(None),
        )
    )
    asr_conf_q = await db.execute(
        select(func.avg(RealtimeTranslationRequest.avg_asr_confidence_score)).where(
            RealtimeTranslationRequest.completed_at >= today_midnight,
            RealtimeTranslationRequest.avg_asr_confidence_score.is_not(None),
        )
    )
    scrape_q = await db.execute(
        select(AuditLog.created_at)
        .where(AuditLog.action_type == "form_scrape_triggered")
        .order_by(desc(AuditLog.created_at))
        .limit(1)
    )
    audit_q = await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(8))

    active_by_type: dict[str, int] = {row.type: row.cnt for row in active_q}
    today_by_type: dict[str, int] = {row.type: row.cnt for row in today_q}
    avg_nmt: float | None = conf_q.scalar()
    avg_asr: float | None = asr_conf_q.scalar()
    last_scrape_at: datetime | None = scrape_q.scalar()
    recent_events = audit_q.scalars().all()

    return AdminStats(
        active_sessions_total=sum(active_by_type.values()),
        active_sessions_realtime=active_by_type.get("realtime", 0),
        active_sessions_document=active_by_type.get("document", 0),
        todays_translations_total=sum(today_by_type.values()),
        todays_translations_docs=today_by_type.get("document", 0),
        todays_translations_realtime=today_by_type.get("realtime", 0),
        avg_nmt_confidence=round(avg_nmt, 4) if avg_nmt is not None else None,
        avg_asr_confidence=round(avg_asr, 4) if avg_asr is not None else None,
        last_scrape_at=last_scrape_at,
        recent_audit_events=[
            AuditEventSummary(
                audit_id=e.audit_id,
                action_type=e.action_type,
                created_at=e.created_at,
                details=e.details,
            )
            for e in recent_events
        ],
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/metrics
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/metrics",
    summary="7-day drift + model latency metrics (admin only)",
    response_model=AdminMetrics,
)
async def get_admin_metrics(
    admin: _AdminUser,
    db: DBSession,
) -> AdminMetrics:
    """
    Returns 7-day rolling averages for NMT/ASR/OCR confidence, Llama correction
    rate, and per-step model latency derived from pipeline_steps.updated_at deltas.
    """
    from db.models import DocumentTranslationRequest, RealtimeTranslationRequest

    now = datetime.now(tz=UTC)
    seven_days_ago = now - timedelta(days=7)

    # NMT confidence — Spanish (spa_Latn), last 7d completed document requests
    nmt_es_q = await db.execute(
        select(func.avg(DocumentTranslationRequest.avg_confidence_score)).where(
            DocumentTranslationRequest.created_at >= seven_days_ago,
            DocumentTranslationRequest.target_language == "spa_Latn",
            DocumentTranslationRequest.avg_confidence_score.is_not(None),
        )
    )

    # NMT confidence — Portuguese (por_Latn), last 7d
    nmt_pt_q = await db.execute(
        select(func.avg(DocumentTranslationRequest.avg_confidence_score)).where(
            DocumentTranslationRequest.created_at >= seven_days_ago,
            DocumentTranslationRequest.target_language == "por_Latn",
            DocumentTranslationRequest.avg_confidence_score.is_not(None),
        )
    )

    # ASR confidence — realtime sessions completed in the last 7d
    asr_q = await db.execute(
        select(func.avg(RealtimeTranslationRequest.avg_asr_confidence_score)).where(
            RealtimeTranslationRequest.completed_at >= seven_days_ago,
            RealtimeTranslationRequest.avg_asr_confidence_score.is_not(None),
        )
    )

    # OCR confidence — from pipeline_steps.metadata->>'avg_confidence' (raw SQL for JSONB cast)
    ocr_q = await db.execute(
        text("""
            SELECT AVG(CAST(metadata->>'avg_confidence' AS float))
            FROM pipeline_steps
            WHERE step_name = 'ocr_printed_text'
              AND status    = 'success'
              AND updated_at >= :cutoff
              AND metadata->>'avg_confidence' IS NOT NULL
        """),
        {"cutoff": seven_days_ago},
    )

    # Llama correction rate — SUM(corrections) / COUNT(requests) over last 7d
    llama_q = await db.execute(
        select(
            func.sum(DocumentTranslationRequest.llama_corrections_count),
            func.count(),
        ).where(
            DocumentTranslationRequest.created_at >= seven_days_ago,
        )
    )

    # Model latencies — avg seconds between consecutive step completions per session
    # Uses LAG() window function partitioned by session so each step's "duration"
    # is the gap from when the previous step finished to when this one finished.
    latency_q = await db.execute(
        text("""
            SELECT step_name,
                   AVG(EXTRACT(EPOCH FROM (updated_at - prev_updated_at))) AS avg_seconds
            FROM (
                SELECT step_name,
                       updated_at,
                       LAG(updated_at) OVER (
                           PARTITION BY session_id ORDER BY updated_at
                       ) AS prev_updated_at
                FROM pipeline_steps
                WHERE updated_at >= :cutoff
                  AND status     = 'success'
            ) sub
            WHERE prev_updated_at IS NOT NULL
            GROUP BY step_name
        """),
        {"cutoff": seven_days_ago},
    )

    # ── Collate ───────────────────────────────────────────────────────────────
    nmt_es: float | None = nmt_es_q.scalar()
    nmt_pt: float | None = nmt_pt_q.scalar()
    avg_asr: float | None = asr_q.scalar()
    avg_ocr: float | None = ocr_q.scalar()

    llama_sum, llama_count = llama_q.one()
    llama_rate: float | None = round(llama_sum / llama_count, 4) if llama_count else None

    model_latencies: dict[str, float | None] = {
        row.step_name: round(row.avg_seconds, 3) if row.avg_seconds is not None else None for row in latency_q.all()
    }

    return AdminMetrics(
        nmt_confidence_es_7d=round(nmt_es, 4) if nmt_es is not None else None,
        nmt_confidence_pt_7d=round(nmt_pt, 4) if nmt_pt is not None else None,
        asr_confidence_7d=round(avg_asr, 4) if avg_asr is not None else None,
        ocr_confidence_7d=round(avg_ocr, 4) if avg_ocr is not None else None,
        llama_correction_rate_7d=llama_rate,
        model_latencies=model_latencies,
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/users
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/users",
    summary="List all users (admin only)",
    response_model=list[AdminUserRow],
)
async def list_users(
    admin: _AdminUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> list[AdminUserRow]:
    """Return all registered users with session counts, ordered by created_at desc."""
    from api.schemas.schemas import ROLE_ID_TO_NAME
    from db.models import Session, User

    # Single query: users + their session count via correlated subquery
    session_count_subq = select(func.count()).where(Session.user_id == User.user_id).correlate(User).scalar_subquery()
    result = await db.execute(
        select(User, session_count_subq.label("session_count"))
        .order_by(desc(User.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    now = datetime.now(tz=UTC)
    active_threshold = now - timedelta(days=30)

    return [
        AdminUserRow(
            user_id=u.user_id,
            name=u.name,
            email=u.email,
            role=ROLE_ID_TO_NAME.get(u.role_id, "public"),
            last_login_at=u.last_login_at,
            session_count=count,
            is_active=u.last_login_at is not None and u.last_login_at >= active_threshold,
            created_at=u.created_at,
        )
        for u, count in rows
    ]


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/users/{user_id}
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/users/{user_id}",
    summary="Get a user's profile (admin only)",
    response_model=UserResponse,
)
async def get_user(
    user_id: uuid.UUID,
    admin: _AdminUser,
    db: DBSession,
) -> UserResponse:
    from db.models import User

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.from_orm_user(user)


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/users/{user_id}/role
# ══════════════════════════════════════════════════════════════════════════════


_ROLE_MAP = {"public": 1, "court_official": 2, "interpreter": 3, "admin": 4}


@router.post(
    "/users/{user_id}/role",
    summary="Set a user's role (admin only)",
    response_model=UserResponse,
)
async def set_user_role(
    user_id: uuid.UUID,
    body: RoleAssignRequest,
    admin: _AdminUser,
    db: DBSession,
) -> UserResponse:
    """Directly promote or demote any user to any role."""
    from db.models import User
    from db.queries.audit import write_audit

    role_id = _ROLE_MAP.get(body.role_name)
    if role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown role '{body.role_name}'. Must be one of: {list(_ROLE_MAP)}",
        )

    result = await db.execute(select(User).where(User.user_id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_role_id = target.role_id
    target.role_id = role_id
    target.role_approved_by = admin.user_id
    target.role_approved_at = datetime.now(tz=UTC)

    await write_audit(
        db,
        user_id=admin.user_id,
        action_type="admin_role_change",
        details={
            "target_user_id": str(user_id),
            "old_role_id": old_role_id,
            "new_role_id": role_id,
            "new_role_name": body.role_name,
        },
    )
    await db.commit()
    await db.refresh(target)

    logger.info(
        "Admin role change: target_user=%s old_role=%s new_role=%s by admin=%s",
        user_id,
        old_role_id,
        role_id,
        admin.user_id,
    )
    return UserResponse.from_orm_user(target)


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/role-requests
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/role-requests",
    summary="List role upgrade requests (admin only)",
    response_model=list[RoleRequestSummary],
)
async def list_role_requests(
    admin: _AdminUser,
    db: DBSession,
    pending_only: bool = Query(default=True, description="If true, return only 'pending' requests"),
) -> list[RoleRequestSummary]:
    from db.models import RoleRequest

    q = select(RoleRequest).order_by(desc(RoleRequest.requested_at))
    if pending_only:
        q = q.where(RoleRequest.status == "pending")
    result = await db.execute(q)
    return result.scalars().all()


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/role-requests/{request_id}/approve
# POST /admin/role-requests/{request_id}/reject
# ══════════════════════════════════════════════════════════════════════════════


async def _resolve_role_request(
    request_id: uuid.UUID,
    decision: str,  # "approved" | "rejected"
    admin_user_id: uuid.UUID,
    db: DBSession,
    notes: str | None,
) -> RoleRequestSummary:
    from db.models import RoleRequest, User
    from db.queries.audit import write_audit

    result = await db.execute(select(RoleRequest).where(RoleRequest.request_id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role request not found")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role request is already '{req.status}'",
        )

    req.status = decision
    req.reviewed_by = admin_user_id
    req.reviewed_at = datetime.now(tz=UTC)

    if decision == "approved":
        user_result = await db.execute(select(User).where(User.user_id == req.user_id))
        target = user_result.scalar_one_or_none()
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {req.user_id} not found — cannot apply role approval.",
            )
        target.role_id = req.requested_role_id
        target.role_approved_by = admin_user_id
        target.role_approved_at = req.reviewed_at

    await write_audit(
        db,
        user_id=admin_user_id,
        action_type=f"role_request_{decision}",
        details={"request_id": str(request_id), "notes": notes},
    )
    await db.commit()
    await db.refresh(req)
    return req


@router.post(
    "/role-requests/{request_id}/approve",
    summary="Approve a role request (admin only)",
    response_model=RoleRequestSummary,
)
async def approve_role_request(
    request_id: uuid.UUID,
    body: RoleRequestDecision,
    admin: _AdminUser,
    db: DBSession,
) -> RoleRequestSummary:
    return await _resolve_role_request(request_id, "approved", admin.user_id, db, body.notes)


@router.post(
    "/role-requests/{request_id}/reject",
    summary="Reject a role request (admin only)",
    response_model=RoleRequestSummary,
)
async def reject_role_request(
    request_id: uuid.UUID,
    body: RoleRequestDecision,
    admin: _AdminUser,
    db: DBSession,
) -> RoleRequestSummary:
    return await _resolve_role_request(request_id, "rejected", admin.user_id, db, body.notes)


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/audit-logs
# ══════════════════════════════════════════════════════════════════════════════


class AuditLogSummary(BaseModel):
    audit_id: uuid.UUID
    user_id: uuid.UUID
    session_id: uuid.UUID | None
    action_type: str
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get(
    "/audit-logs",
    summary="List audit logs (admin only)",
    response_model=list[AuditLogSummary],
)
async def list_audit_logs(
    admin: _AdminUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> list[AuditLogSummary]:
    from db.models import AuditLog

    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    )
    return result.scalars().all()


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/container-stats — live Docker container resource usage
# ══════════════════════════════════════════════════════════════════════════════


class ContainerStat(BaseModel):
    name: str
    cpu: str
    mem: str
    gpu: str | None = None


@router.get(
    "/container-stats",
    summary="Live Docker container resource usage (admin only)",
    response_model=list[ContainerStat],
)
async def get_container_stats(admin: _AdminUser) -> list[ContainerStat]:
    """
    Runs `docker stats --no-stream --format json` via subprocess and returns
    CPU/memory usage per container.
    """
    import asyncio
    import json as _json

    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "stats",
            "--no-stream",
            "--format",
            '{"name":"{{.Name}}","cpu":"{{.CPUPerc}}","mem":"{{.MemPerc}}"}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        lines = stdout.decode().strip().splitlines()
        results = []
        for line in lines:
            if not line.strip():
                continue
            try:
                d = _json.loads(line)
                results.append(
                    ContainerStat(
                        name=d["name"].removeprefix("court-access-ai-").removesuffix("-1"),
                        cpu=d["cpu"],
                        mem=d["mem"],
                    )
                )
            except Exception:
                logger.debug("Skipping unparseable docker stats line: %s", line)
                continue
        return results
    except Exception as exc:
        logger.warning("docker stats failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Container stats unavailable — docker CLI not accessible from this process.",
        ) from exc


# ══════════════════════════════════════════════════════════════════════════════
# POST /admin/cleanup-stale-sessions — mark abandoned sessions as completed
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/cleanup-stale-sessions",
    summary="Mark abandoned sessions as completed (admin only)",
)
async def cleanup_stale_sessions(admin: _AdminUser, db: DBSession) -> dict:
    """
    Sessions that have been 'active' for more than 2 hours with no
    completed_at are considered abandoned and marked completed.
    """
    from db.models import Session as SessionModel

    cutoff = datetime.now(tz=UTC) - timedelta(hours=2)
    result = await db.execute(
        select(SessionModel).where(
            SessionModel.status == "active",
            SessionModel.created_at < cutoff,
        )
    )
    stale = result.scalars().all()
    for s in stale:
        s.status = "completed"
        s.completed_at = datetime.now(tz=UTC)
    await db.commit()
    logger.info("Cleaned up %d stale sessions (admin: %s)", len(stale), admin.user_id)
    return {"cleaned": len(stale)}


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/scraper-stats — last form scraper DAG run results
# ══════════════════════════════════════════════════════════════════════════════


class ScraperStats(BaseModel):
    last_run_at: datetime | None
    dag_run_id: str | None
    scenario_a_new: int
    scenario_b_updated: int
    scenario_c_deleted: int
    scenario_d_renamed: int
    scenario_e_no_change: int
    pretranslation_queued: int
    active_forms: int
    forms_with_es: int
    forms_with_pt: int


@router.get(
    "/scraper-stats",
    summary="Last form scraper DAG run results (admin only)",
    response_model=ScraperStats,
)
async def get_scraper_stats(admin: _AdminUser, db: DBSession) -> ScraperStats:
    """Read the most recent form_scrape_completed audit log entry."""
    from db.models import AuditLog

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.action_type == "form_scrape_completed")
        .order_by(desc(AuditLog.created_at))
        .limit(1)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return ScraperStats(
            last_run_at=None,
            dag_run_id=None,
            scenario_a_new=0,
            scenario_b_updated=0,
            scenario_c_deleted=0,
            scenario_d_renamed=0,
            scenario_e_no_change=0,
            pretranslation_queued=0,
            active_forms=0,
            forms_with_es=0,
            forms_with_pt=0,
        )
    d = entry.details or {}
    counts = d.get("counts", {})
    catalog = d.get("catalog_metrics", {})
    return ScraperStats(
        last_run_at=entry.created_at,
        dag_run_id=d.get("dag_run_id"),
        scenario_a_new=counts.get("new", 0),
        scenario_b_updated=counts.get("updated", 0),
        scenario_c_deleted=counts.get("deleted", 0),
        scenario_d_renamed=counts.get("renamed", 0),
        scenario_e_no_change=counts.get("no_change", 0),
        pretranslation_queued=d.get("pretranslation_queued", 0),
        active_forms=d.get("active_forms", 0),
        forms_with_es=catalog.get("forms_with_es", 0),
        forms_with_pt=catalog.get("forms_with_pt", 0),
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/system-stats — DB latency, form counts, avg pipeline step time
# ══════════════════════════════════════════════════════════════════════════════


class SystemStatsResponse(BaseModel):
    db_latency_ms: float
    active_form_count: int
    pending_review_count: int
    avg_pipeline_step_seconds: float | None


@router.get(
    "/system-stats",
    summary="System health stats (admin only)",
    response_model=SystemStatsResponse,
)
async def get_system_stats(admin: _AdminUser, db: DBSession) -> SystemStatsResponse:
    """DB latency ping, form catalog counts, and avg pipeline step duration."""
    import time

    from db.models import FormCatalog

    # DB latency ping
    t0 = time.monotonic()
    await db.execute(text("SELECT 1"))
    latency_ms = round((time.monotonic() - t0) * 1000, 2)

    # Form counts
    counts_q = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(FormCatalog.needs_human_review.is_(True)).label("pending"),
        ).where(FormCatalog.status == "active")
    )
    row = counts_q.one()
    active_total = row.total or 0
    pending = row.pending or 0

    # Avg pipeline step duration (last 7 days)
    latency_q = await db.execute(
        text("""
        SELECT AVG(EXTRACT(EPOCH FROM (updated_at - prev_updated_at)))
        FROM (
            SELECT updated_at,
                   LAG(updated_at) OVER (PARTITION BY session_id ORDER BY updated_at) AS prev_updated_at
            FROM pipeline_steps
            WHERE status = 'success'
              AND updated_at >= NOW() - INTERVAL '7 days'
        ) sub WHERE prev_updated_at IS NOT NULL
    """)
    )
    avg_secs = latency_q.scalar()

    return SystemStatsResponse(
        db_latency_ms=latency_ms,
        active_form_count=active_total,
        pending_review_count=pending,
        avg_pipeline_step_seconds=round(avg_secs, 3) if avg_secs else None,
    )
