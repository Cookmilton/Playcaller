"""
Read-only **warehouse advisory** context for Generate (not blended into ranking).

Warehouse access is via :mod:`football_history_warehouse.consumer` (client + re-exported query types).
No ORM, repositories, or ingest imports.
"""

from __future__ import annotations

from playcaller.warehouse.advisory import attach_warehouse_advisory_to_result
from playcaller.warehouse.binding import WarehouseBinding, build_warehouse_binding

__all__ = [
    "WarehouseBinding",
    "attach_warehouse_advisory_to_result",
    "build_warehouse_binding",
]
