"""SQLite warehouse URL normalization (repo-root anchor for relative paths)."""

from __future__ import annotations

from football_history_warehouse.config.database import (
    DatabaseConfig,
    _repo_root,
    normalize_warehouse_database_url,
    resolve_warehouse_db_path,
)


def test_normalize_postgres_unchanged() -> None:
    raw = "postgresql+psycopg://user:pass@localhost:5432/wh"
    nu, p = normalize_warehouse_database_url(raw)
    assert p is None
    assert nu == raw


def test_normalize_sqlite_memory_unchanged() -> None:
    raw = "sqlite+pysqlite:///:memory:"
    nu, p = normalize_warehouse_database_url(raw)
    assert p is None
    assert nu == raw


def test_normalize_sqlite_relative_paths_to_repo_root() -> None:
    nu, p = normalize_warehouse_database_url("sqlite+pysqlite:///./warehouse.db")
    root = _repo_root()
    assert p == (root / "warehouse.db").resolve()
    assert str(nu).startswith("sqlite+pysqlite:///")
    assert "warehouse.db" in nu


def test_database_config_validator_applies_normalization() -> None:
    cfg = DatabaseConfig(database_url="sqlite+pysqlite:///./normalize_me.sqlite", echo_sql=False)
    assert resolve_warehouse_db_path(cfg.database_url) == (_repo_root() / "normalize_me.sqlite").resolve()


def test_resolve_warehouse_db_path() -> None:
    p = resolve_warehouse_db_path("sqlite+pysqlite:///./x.sqlite")
    assert p is not None
    assert p == (_repo_root() / "x.sqlite").resolve()
