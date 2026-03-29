"""
db/queries/forms.py

Async ORM query functions for the form catalog domain.

All functions take an ``AsyncSession`` as their first argument and expect the
caller to commit after mutations.  They call ``db.flush()`` internally so that
any auto-generated server-side values (e.g. ``version_id``) are visible to the
session before the caller commits.

Upserts use the PostgreSQL ``INSERT … ON CONFLICT … DO UPDATE`` dialect so
every function is safe to re-run on repeated DAG runs — idempotent by design.

Import pattern:
    from db.queries import forms as form_queries

    form = await form_queries.get_form_by_id(db, form_id)
    await form_queries.upsert_form_catalog(db, entry_dict)
    await db.commit()
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# ══════════════════════════════════════════════════════════════════════════════
# Upserts
# ══════════════════════════════════════════════════════════════════════════════


async def upsert_form_catalog(
    db: AsyncSession,
    entry_dict: dict[str, Any],
) -> Any:
    """
    Upsert a row in ``form_catalog``.

    ``entry_dict`` must contain at least ``form_id`` plus any subset of the
    other ``FormCatalog`` columns.  The ``created_at`` column is intentionally
    excluded from the UPDATE SET so the original creation timestamp is
    preserved across re-runs.

    Returns the refreshed ``FormCatalog`` ORM object.
    """
    from db.models import FormCatalog

    form_id = entry_dict["form_id"]
    set_dict = {k: v for k, v in entry_dict.items() if k not in ("form_id", "created_at")}

    stmt = (
        pg_insert(FormCatalog)
        .values(**entry_dict)
        .on_conflict_do_update(
            index_elements=["form_id"],
            set_=set_dict,
        )
    )
    await db.execute(stmt)
    await db.flush()
    return await db.get(FormCatalog, form_id)


async def upsert_form_version(
    db: AsyncSession,
    form_id: uuid.UUID,
    version_dict: dict[str, Any],
) -> Any:
    """
    Upsert a row in ``form_versions``.

    Conflict key: ``(form_id, version)`` — unique constraint
    ``form_versions_form_id_version_key``.

    On conflict, updates the five file-path/type columns only.  The
    ``version_id`` and ``created_at`` of the original row are preserved.

    ``version_dict`` must contain ``version`` plus the file path/type fields.
    GCS URIs (``gs://…``) should already be resolved by the time this is
    called (the DAG's ``task_upload_forms_to_gcs`` runs first).

    Returns the ``FormVersion`` ORM object.
    """
    from db.models import FormVersion

    row = {
        "version_id": version_dict.get("version_id", uuid.uuid4()),
        "form_id": form_id,
        **version_dict,
    }

    insert_stmt = pg_insert(FormVersion).values(**row)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["form_id", "version"],
        set_={
            "file_path_original": insert_stmt.excluded.file_path_original,
            "file_path_es": insert_stmt.excluded.file_path_es,
            "file_path_pt": insert_stmt.excluded.file_path_pt,
            "file_type_es": insert_stmt.excluded.file_type_es,
            "file_type_pt": insert_stmt.excluded.file_type_pt,
            "content_hash": insert_stmt.excluded.content_hash,
        },
    )
    await db.execute(upsert_stmt)
    await db.flush()

    result = await db.execute(
        select(FormVersion).where(
            FormVersion.form_id == form_id,
            FormVersion.version == version_dict["version"],
        )
    )
    return result.scalar_one_or_none()


async def upsert_form_appearance(
    db: AsyncSession,
    form_id: uuid.UUID,
    division: str,
    section_heading: str,
) -> None:
    """
    Insert a row in ``form_appearances``, silently ignoring duplicates.

    Conflict key: ``(form_id, division, section_heading)`` — unique constraint
    ``form_appearances_form_id_division_section_heading_key``.
    """
    from db.models import FormAppearance

    stmt = (
        pg_insert(FormAppearance)
        .values(
            appearance_id=uuid.uuid4(),
            form_id=form_id,
            division=division,
            section_heading=section_heading,
        )
        .on_conflict_do_nothing(
            index_elements=["form_id", "division", "section_heading"],
        )
    )
    await db.execute(stmt)
    await db.flush()


# ══════════════════════════════════════════════════════════════════════════════
# Updates
# ══════════════════════════════════════════════════════════════════════════════


async def update_form_version_translations(
    db: AsyncSession,
    form_id: uuid.UUID,
    version: int,
    file_path_es: str | None,
    file_path_pt: str | None,
    file_type_es: str | None,
    file_type_pt: str | None,
) -> None:
    """
    Write translated GCS paths back to an existing ``form_versions`` row.

    Called by ``form_pretranslation_dag`` after it uploads translated PDFs
    to GCS and needs to record their locations in the DB.
    """
    from db.models import FormVersion

    await db.execute(
        update(FormVersion)
        .where(FormVersion.form_id == form_id, FormVersion.version == version)
        .values(
            file_path_es=file_path_es,
            file_path_pt=file_path_pt,
            file_type_es=file_type_es,
            file_type_pt=file_type_pt,
        )
    )
    await db.flush()


async def update_form_catalog_fields(
    db: AsyncSession,
    form_id: uuid.UUID,
    **kwargs: Any,
) -> None:
    """
    Generic field updater for ``form_catalog``.

    Caller supplies keyword arguments matching ``FormCatalog`` column names.
    Example:
        await update_form_catalog_fields(
            db, form_id,
            needs_human_review=True,
            preprocessing_flags=["mislabeled_file"],
        )
    """
    from db.models import FormCatalog

    await db.execute(update(FormCatalog).where(FormCatalog.form_id == form_id).values(**kwargs))
    await db.flush()


# ══════════════════════════════════════════════════════════════════════════════
# Reads
# ══════════════════════════════════════════════════════════════════════════════


async def get_form_by_id(
    db: AsyncSession,
    form_id: uuid.UUID,
) -> Any | None:
    """
    Fetch a single ``FormCatalog`` row with all versions and appearances
    eagerly loaded in two additional SELECT statements (selectinload).

    Returns ``None`` if the form does not exist.
    """
    from db.models import FormCatalog

    result = await db.execute(
        select(FormCatalog)
        .options(
            selectinload(FormCatalog.versions),
            selectinload(FormCatalog.appearances),
        )
        .where(FormCatalog.form_id == form_id)
    )
    return result.scalar_one_or_none()


async def list_forms(
    db: AsyncSession,
    *,
    status: str | None = "active",
    division: str | None = None,
    language: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Any], int]:
    """
    Paginated, filtered list of ``FormCatalog`` rows with eager-loaded
    relationships.

    Filters:
        status   — exact match on ``form_catalog.status`` (default: ``"active"``)
        division — case-insensitive substring match via correlated EXISTS on
                   ``form_appearances.division``
        language — ``"es"`` or ``"pt"``: form must have at least one version
                   with the corresponding ``file_path_*`` set
        q        — case-insensitive substring match on ``form_catalog.form_name``

    Returns:
        A ``(items, total)`` tuple where ``items`` is the page slice and
        ``total`` is the unfiltered count matching all filters.
    """
    from db.models import FormAppearance, FormCatalog, FormVersion

    conditions = []

    if status:
        conditions.append(FormCatalog.status == status)

    if division:
        conditions.append(FormCatalog.appearances.any(FormAppearance.division.ilike(f"%{division}%")))

    if language == "es":
        conditions.append(FormCatalog.versions.any(FormVersion.file_path_es.isnot(None)))
    elif language == "pt":
        conditions.append(FormCatalog.versions.any(FormVersion.file_path_pt.isnot(None)))

    if q:
        conditions.append(FormCatalog.form_name.ilike(f"%{q}%"))

    # ── Total count (no pagination, no relationship loading) ─────────────────
    count_stmt = select(func.count(FormCatalog.form_id)).where(*conditions)
    total: int = (await db.execute(count_stmt)).scalar_one()

    # ── Paginated rows with eager-loaded relationships ────────────────────────
    fetch_stmt = (
        select(FormCatalog)
        .options(
            selectinload(FormCatalog.versions),
            selectinload(FormCatalog.appearances),
        )
        .where(*conditions)
        .order_by(FormCatalog.form_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(fetch_stmt)
    forms = result.scalars().all()

    return list(forms), total


async def list_divisions(db: AsyncSession) -> list[str]:
    """
    Return a sorted list of all distinct court division names from
    ``form_appearances``.
    """
    from db.models import FormAppearance

    result = await db.execute(select(distinct(FormAppearance.division)).order_by(FormAppearance.division))
    return list(result.scalars().all())


# ═════════════════════════════════════════════════════════════════════════════=
# Sync helpers for Airflow DAGs
# ═════════════════════════════════════════════════════════════════════════════=


def get_all_forms_sync() -> list[dict[str, Any]]:
    """
    Return the entire form catalog as a list of dicts in the exact shape the
    scraper expects (legacy JSON schema).

    This function is synchronous by design for Airflow task processes.
    It does NOT commit and does not mutate DB state.
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    from db.database import get_sync_engine
    from db.models import FormCatalog, FormVersion

    engine = get_sync_engine()
    with Session(engine) as session:
        rows = (
            session.execute(
                sa.select(FormCatalog).options(
                    selectinload(FormCatalog.versions),
                    selectinload(FormCatalog.appearances),
                )
            )
            .scalars()
            .all()
        )

        out: list[dict[str, Any]] = []
        for f in rows:
            versions = sorted(
                list(f.versions),
                key=lambda v: v.version,
                reverse=True,
            )
            versions_dicts = [
                {
                    "version": v.version,
                    "content_hash": v.content_hash,
                    "file_type": v.file_type,
                    "file_path_original": v.file_path_original,
                    "file_path_es": v.file_path_es,
                    "file_path_pt": v.file_path_pt,
                    "file_type_es": v.file_type_es,
                    "file_type_pt": v.file_type_pt,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ]

            latest: FormVersion | None = versions[0] if versions else None

            out.append(
                {
                    "form_id": str(f.form_id),
                    "form_name": f.form_name,
                    "form_slug": f.form_slug,
                    "source_url": f.source_url,
                    "file_type": f.file_type,
                    "status": f.status,
                    "content_hash": f.content_hash
                    if getattr(f, "content_hash", None)
                    else (latest.content_hash if latest else ""),
                    "current_version": f.current_version,
                    "needs_human_review": f.needs_human_review,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "last_scraped_at": f.last_scraped_at.isoformat() if f.last_scraped_at else None,
                    "appearances": [
                        {"division": a.division, "section_heading": a.section_heading} for a in f.appearances
                    ],
                    "versions": versions_dicts,
                }
            )

        return out


def upsert_form_catalog_sync(session, entry_dict: dict[str, Any]):
    """
    Sync variant of ``upsert_form_catalog`` for Airflow tasks.

    Does NOT commit. Caller owns transaction boundary.

    Note: ``ON CONFLICT (form_id) DO UPDATE`` cannot intercept a violation on
    the *separate* ``form_catalog_form_slug_key`` unique index.  If a slug
    collision occurs, the caller (``task_write_catalog_to_db`` /
    ``_write_single_form_to_db``) catches ``IntegrityError``, suffixes the
    slug, and retries inside a fresh Session.
    """
    import logging

    from db.models import FormCatalog

    _logger = logging.getLogger(__name__)

    form_id = entry_dict["form_id"]
    set_dict = {k: v for k, v in entry_dict.items() if k not in ("form_id", "created_at")}

    _logger.debug(
        "upsert_form_catalog_sync: form_id=%s slug=%r",
        form_id,
        entry_dict.get("form_slug"),
    )

    stmt = (
        pg_insert(FormCatalog)
        .values(**entry_dict)
        .on_conflict_do_update(
            index_elements=["form_id"],
            set_=set_dict,
        )
    )
    session.execute(stmt)
    session.flush()
    return session.get(FormCatalog, form_id)


def upsert_form_version_sync(session, form_id: uuid.UUID, version_dict: dict[str, Any]):
    """
    Sync variant of ``upsert_form_version`` for Airflow tasks.

    Does NOT commit. Caller owns transaction boundary.
    """
    from db.models import FormVersion

    row = {
        "version_id": version_dict.get("version_id", uuid.uuid4()),
        "form_id": form_id,
        **version_dict,
    }

    insert_stmt = pg_insert(FormVersion).values(**row)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["form_id", "version"],
        set_={
            "file_path_original": insert_stmt.excluded.file_path_original,
            "file_path_es": insert_stmt.excluded.file_path_es,
            "file_path_pt": insert_stmt.excluded.file_path_pt,
            "file_type_es": insert_stmt.excluded.file_type_es,
            "file_type_pt": insert_stmt.excluded.file_type_pt,
            "content_hash": insert_stmt.excluded.content_hash,
        },
    )
    session.execute(upsert_stmt)
    session.flush()

    return (
        session.query(FormVersion)
        .filter(FormVersion.form_id == form_id, FormVersion.version == version_dict["version"])
        .one_or_none()
    )


def upsert_form_appearance_sync(session, form_id: uuid.UUID, division: str, section_heading: str) -> None:
    """
    Sync variant of ``upsert_form_appearance`` for Airflow tasks.

    Does NOT commit. Caller owns transaction boundary.
    """
    from db.models import FormAppearance

    stmt = (
        pg_insert(FormAppearance)
        .values(
            appearance_id=uuid.uuid4(),
            form_id=form_id,
            division=division,
            section_heading=section_heading,
        )
        .on_conflict_do_nothing(
            index_elements=["form_id", "division", "section_heading"],
        )
    )
    session.execute(stmt)
    session.flush()


def get_form_by_id_sync(session, form_id: uuid.UUID):
    """
    Sync variant of ``get_form_by_id`` for Airflow tasks.

    Returns a FormCatalog ORM object with versions + appearances eagerly loaded,
    or None if not found.
    """
    from db.models import FormCatalog

    return (
        session.execute(
            select(FormCatalog)
            .options(
                selectinload(FormCatalog.versions),
                selectinload(FormCatalog.appearances),
            )
            .where(FormCatalog.form_id == form_id)
        )
        .scalars()
        .one_or_none()
    )


def update_form_version_translations_sync(
    session,
    *,
    form_id: uuid.UUID,
    version: int,
    file_path_es: str | None,
    file_path_pt: str | None,
    file_type_es: str | None,
    file_type_pt: str | None,
) -> None:
    """Sync variant of ``update_form_version_translations`` (no commit)."""
    from db.models import FormVersion

    session.execute(
        update(FormVersion)
        .where(FormVersion.form_id == form_id, FormVersion.version == version)
        .values(
            file_path_es=file_path_es,
            file_path_pt=file_path_pt,
            file_type_es=file_type_es,
            file_type_pt=file_type_pt,
        )
    )
    session.flush()


def update_form_catalog_fields_sync(session, form_id: uuid.UUID, **kwargs: Any) -> None:
    """Sync variant of ``update_form_catalog_fields`` (no commit)."""
    from db.models import FormCatalog

    session.execute(update(FormCatalog).where(FormCatalog.form_id == form_id).values(**kwargs))
    session.flush()


# ══════════════════════════════════════════════════════════════════════════════
# Review workflow
# ══════════════════════════════════════════════════════════════════════════════


async def submit_form_review(
    db: AsyncSession,
    form_id: uuid.UUID,
    approved: bool,
    reviewer_user_id: uuid.UUID,
    notes: str | None,
) -> Any | None:
    """
    Record a human review decision for a court form.

    Sets ``form_catalog.needs_human_review`` based on ``approved``:
      - ``approved=True``  → ``needs_human_review=False`` (review satisfied)
      - ``approved=False`` → ``needs_human_review=True``  (flag kept open)

    Inserts an ``audit_logs`` row for the decision.

    Returns the updated ``FormCatalog`` object, or ``None`` if not found.
    Caller is responsible for ``await db.commit()``.
    """
    from db.models import FormCatalog
    from db.queries.audit import write_audit

    form = await db.get(FormCatalog, form_id)
    if form is None:
        return None

    form.needs_human_review = not approved

    await write_audit(
        db,
        user_id=reviewer_user_id,
        action_type="form_review_submitted",
        details={
            "form_id": str(form_id),
            "form_name": form.form_name,
            "approved": approved,
            "notes": notes,
        },
    )

    await db.flush()
    return form
