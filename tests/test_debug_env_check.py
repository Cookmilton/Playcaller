"""Tests for :mod:`playcaller.debug.env_check`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from playcaller.debug.env_check import check_warehouse_env, mask_database_url

KEY = "FOOTBALL_WAREHOUSE_DATABASE_URL"


def test_mask_sqlite_unchanged() -> None:
    u = "sqlite+pysqlite:///./warehouse.db"
    assert mask_database_url(u) == u


def test_mask_postgres_password() -> None:
    u = "postgresql+psycopg://alice:secret@localhost:5432/football"
    m = mask_database_url(u)
    assert "secret" not in m
    assert "alice:***" in m
    assert "localhost:5432" in m


@pytest.fixture
def clear_warehouse_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(KEY, raising=False)


def test_check_missing(clear_warehouse_url: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAYCALLER_DEV_MODE", raising=False)
    r = check_warehouse_env(repo_root=tmp_path)
    assert r == {
        "present": False,
        "source": "missing",
        "masked_value": None,
        "scheme": None,
        "sqlite_resolved_path": None,
    }


def test_check_dev_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(KEY, raising=False)
    monkeypatch.setenv("PLAYCALLER_DEV_MODE", "1")
    r = check_warehouse_env(repo_root=tmp_path)
    assert r["present"] is True
    assert r["source"] == "dev_fallback"
    assert r.get("masked_value") and "warehouse.db" in str(r.get("masked_value"))
    assert r.get("scheme") == "sqlite"
    assert r.get("sqlite_resolved_path") and str(r["sqlite_resolved_path"]).endswith("warehouse.db")


def test_check_dotenv_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "sqlite+pysqlite:///./local.db"
    (tmp_path / ".env").write_text(f"{KEY}={url}\n", encoding="utf-8")
    monkeypatch.setenv(KEY, url)
    r = check_warehouse_env(repo_root=tmp_path)
    assert r["present"] is True
    assert r["source"] == "dotenv"
    assert r["masked_value"] == url
    assert r["scheme"] == "sqlite"
    assert r.get("sqlite_resolved_path") and str(r["sqlite_resolved_path"]).endswith("local.db")


def test_check_env_source_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Process has URL but .env does not match → classified as shell/env."""
    (tmp_path / ".env").write_text(f"{KEY}=sqlite+pysqlite:///./other.db\n", encoding="utf-8")
    monkeypatch.setenv(KEY, "sqlite+pysqlite:///./from_shell.db")
    r = check_warehouse_env(repo_root=tmp_path)
    assert r["present"] is True
    assert r["source"] == "env"
