"""
Warehouse-wide operational settings.

Database URLs live in :mod:`football_history_warehouse.config.database` so
credentials stay in one documented place.
"""

from __future__ import annotations

from football_history_warehouse.config.database import DatabaseConfig


class WarehouseSettings:
    """Aggregate for non-secret operational settings (expand over time)."""

    __slots__ = ("database",)

    def __init__(self, *, database: DatabaseConfig) -> None:
        self.database = database

    @classmethod
    def from_env(cls) -> WarehouseSettings:
        return cls(database=DatabaseConfig.from_env())
