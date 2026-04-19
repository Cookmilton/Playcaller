"""HTTP API (FastAPI) exposing the consumer client over JSON."""

from __future__ import annotations

from football_history_warehouse.api.app import app, create_app

__all__ = ["app", "create_app"]
