"""
Compatibility entry point for “connection” wording.

Prefer :mod:`football_history_warehouse.storage.database.engine` and
:mod:`football_history_warehouse.storage.database.session` in new code.
"""

from __future__ import annotations

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.storage.database.engine import create_warehouse_engine
from football_history_warehouse.storage.database.session import make_session_factory, session_scope

__all__ = [
    "DatabaseConfig",
    "create_warehouse_engine",
    "make_session_factory",
    "session_scope",
]
