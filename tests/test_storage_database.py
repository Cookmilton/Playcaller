"""Storage engine, session scope, and Alembic baseline (SQLite)."""

from __future__ import annotations

import os

import pytest

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import (
    check_connection,
    create_warehouse_engine,
    session_scope,
)


def test_database_config_from_env_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOOTBALL_WAREHOUSE_DATABASE_URL", raising=False)
    with pytest.raises(WarehouseConfigError):
        DatabaseConfig.from_env()


def test_engine_and_session_sqlite_memory() -> None:
    cfg = DatabaseConfig(database_url="sqlite+pysqlite:///:memory:")
    engine = create_warehouse_engine(cfg)
    try:
        assert check_connection(engine)
        with session_scope(engine) as s:
            s.connection()
    finally:
        engine.dispose()


def test_alembic_upgrade_sqlite_file(tmp_path) -> None:
    dbfile = tmp_path / "wh.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    cfg = DatabaseConfig(database_url=url)
    engine = create_warehouse_engine(cfg)
    try:
        assert check_connection(engine)
    finally:
        engine.dispose()


def test_get_database_url_optional() -> None:
    from football_history_warehouse.config.database import get_database_url

    if "FOOTBALL_WAREHOUSE_DATABASE_URL" in os.environ:
        pytest.skip("env URL set")
    assert get_database_url(required=False) is None
