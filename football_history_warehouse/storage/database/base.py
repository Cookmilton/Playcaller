"""
SQLAlchemy declarative base for future ORM models.

Domain logic remains in ``football_history_warehouse.domain``; tables here will
map to those concepts. Keep ``Base.metadata`` as Alembic's ``target_metadata``.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for warehouse tables (empty until models are added)."""

    pass
