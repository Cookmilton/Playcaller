"""Lightweight connectivity checks (ops, startup probes)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def check_connection(engine: Engine) -> bool:
    """Return True if ``SELECT 1`` succeeds."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
