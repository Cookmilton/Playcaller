"""
Operational bootstrap: migrations and connectivity smoke tests.

Not imported by the playcalling app. Use from scripts, CI, or local shell.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from football_history_warehouse.config.database import DatabaseConfig, get_database_url
from football_history_warehouse.storage.database import check_connection, create_warehouse_engine


def alembic_config_path() -> Path:
    return Path(__file__).resolve().parent / "database" / "migrations" / "alembic.ini"


def upgrade_to_head(*, database_url: str | None = None) -> None:
    """
    Apply all Alembic revisions. Uses ``FOOTBALL_WAREHOUSE_DATABASE_URL`` unless
    ``database_url`` is passed (tests).
    """
    url = database_url or get_database_url(required=True)
    assert url is not None
    cfg = Config(str(alembic_config_path()))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def ensure_schema_exists(engine: Engine) -> bool:
    """
    Apply Alembic migrations so warehouse tables exist. Idempotent: safe to call repeatedly.

    Returns True if the core schema was missing before this call (``leagues`` table did not
    exist), False if tables were already present (migration may still have been a no-op).
    Does not run at app startup — call from ingest scripts or explicit init commands only.
    """
    before = not inspect(engine).has_table("leagues")
    u = engine.url
    url = u.render_as_string(hide_password=False) if hasattr(u, "render_as_string") else str(u)
    cfg = Config(str(alembic_config_path()))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return before


def smoke_check_engine(*, database_url: str | None = None) -> bool:
    """Run ``SELECT 1`` against the configured or given URL."""
    if database_url:
        cfg = DatabaseConfig(database_url=database_url)
    else:
        cfg = DatabaseConfig.from_env()
    engine = create_warehouse_engine(cfg)
    try:
        return check_connection(engine)
    finally:
        engine.dispose()
