"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from football_history_warehouse.consumer.client import FootballWarehouseClient


def get_warehouse_client(request: Request) -> FootballWarehouseClient:
    return request.app.state.warehouse_client
