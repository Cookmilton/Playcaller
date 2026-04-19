"""
Database: engine, sessions, ORM base, migrations (Alembic).

Import paths for consumers inside the warehouse::

    from football_history_warehouse.storage.database import Base, create_warehouse_engine
    from football_history_warehouse.storage.database.session import session_scope
"""

from __future__ import annotations

from football_history_warehouse.storage.database.base import Base
from football_history_warehouse.storage.database.engine import create_warehouse_engine
from football_history_warehouse.storage.database.health import check_connection
import football_history_warehouse.storage.database.models  # noqa: F401
from football_history_warehouse.storage.database.session import make_session_factory, session_scope

__all__ = [
    "Base",
    "check_connection",
    "create_warehouse_engine",
    "make_session_factory",
    "session_scope",
]
