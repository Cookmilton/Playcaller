"""Helpers for SQLite tables whose BIGINT PK was created without AUTOINCREMENT."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def allocate_sqlite_bigint_pk(session: Session, model: type, *, count: int = 1) -> list[int] | None:
    """
    Return the next ``count`` integer primary keys for ``model.id`` on SQLite.

    Alembic renders ``BIGINT PRIMARY KEY`` without ``AUTOINCREMENT`` for some
    tables, so inserts must supply ``id`` explicitly. On other dialects,
    returns ``None`` so callers omit ``id`` and use server-generated values.
    """
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return None
    if count < 1:
        raise ValueError("count must be >= 1")
    m = session.scalar(select(func.coalesce(func.max(model.id), 0)))
    start = int(m) + 1
    return list(range(start, start + count))
