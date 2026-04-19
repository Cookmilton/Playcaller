"""
SQLAlchemy :class:`~sqlalchemy.engine.Engine` factory.

Prefer constructing engines through this module so pool and dialect options stay
consistent (PostgreSQL for production, SQLite acceptable for local-only).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from football_history_warehouse.config.database import DatabaseConfig


def create_warehouse_engine(config: DatabaseConfig, *, pool_pre_ping: bool = True) -> Engine:
    """
    Create a new engine. Callers own lifecycle (dispose on shutdown in long-runners).

    ``pool_pre_ping`` avoids stale connections to PostgreSQL behind NAT or idle
    timeouts; harmless for SQLite.
    """
    return create_engine(
        config.database_url,
        echo=config.echo_sql,
        pool_pre_ping=pool_pre_ping,
        future=True,
    )
