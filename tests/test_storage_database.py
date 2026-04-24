"""Storage engine, session scope, and Alembic baseline (SQLite)."""

from __future__ import annotations

import os

import pytest

import football_history_warehouse.config.database as wh_database

from football_history_warehouse.config.database import DatabaseConfig, resolve_warehouse_database_url
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import (
    check_connection,
    create_warehouse_engine,
    session_scope,
)


def test_database_config_from_env_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOOTBALL_WAREHOUSE_DATABASE_URL", raising=False)
    monkeypatch.delenv("PLAYCALLER_DEV_MODE", raising=False)
    wh_database._fallback_usage_logged = False
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


def test_get_database_url_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    from football_history_warehouse.config.database import get_database_url

    if "FOOTBALL_WAREHOUSE_DATABASE_URL" in os.environ:
        pytest.skip("env URL set")
    monkeypatch.delenv("PLAYCALLER_DEV_MODE", raising=False)
    wh_database._fallback_usage_logged = False
    assert get_database_url(required=False) is None


def test_resolve_warehouse_database_url_dev_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOOTBALL_WAREHOUSE_DATABASE_URL", raising=False)
    monkeypatch.setenv("PLAYCALLER_DEV_MODE", "1")
    wh_database._fallback_usage_logged = False
    url, used_fb = resolve_warehouse_database_url()
    assert used_fb is True
    assert url is not None
    assert "warehouse.db" in url


def test_resolve_explicit_env_beats_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    dbf = tmp_path / "explicit.sqlite"
    url_in = f"sqlite+pysqlite:///{dbf}"
    monkeypatch.setenv("FOOTBALL_WAREHOUSE_DATABASE_URL", url_in)
    monkeypatch.setenv("PLAYCALLER_DEV_MODE", "1")
    wh_database._fallback_usage_logged = False
    url, used_fb = resolve_warehouse_database_url()
    assert used_fb is False
    assert url is not None
    assert str(dbf.resolve()) in url or "explicit.sqlite" in url


def test_database_config_from_env_dev_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOOTBALL_WAREHOUSE_DATABASE_URL", raising=False)
    monkeypatch.setenv("PLAYCALLER_DEV_MODE", "1")
    wh_database._fallback_usage_logged = False
    cfg = DatabaseConfig.from_env()
    assert "warehouse.db" in cfg.database_url
