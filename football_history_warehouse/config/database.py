"""
Database connectivity settings — loaded from the environment.

**Primary variable:** ``FOOTBALL_WAREHOUSE_DATABASE_URL`` (SQLAlchemy URL).

Resolution order (see :func:`resolve_warehouse_database_url`): explicit env value wins; if unset
and ``PLAYCALLER_DEV_MODE`` is truthy, a local SQLite file (``./warehouse.db`` under the repo root)
is used for development only; otherwise configuration is missing.

Examples::

    postgresql+psycopg://user:pass@localhost:5432/football_history
    sqlite+pysqlite:///./var/football_history/local.db

**SQLite relative paths**

URLs whose database segment is a relative filesystem path (e.g. ``./warehouse.db``) are
resolved against the **repository root** (parent of the ``football_history_warehouse/``
package), then rewritten to an absolute file path in the URL. That matches developer
expectation (“project DB”) and avoids ``os.getcwd()`` surprises when Streamlit or CLIs
run from different working directories. ``:memory:`` and non-SQLite URLs are unchanged.

Do not commit secrets; use ``.env`` locally (see ``.env.example`` at repo root).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.engine.url import make_url

from football_history_warehouse.config.exceptions import WarehouseConfigError

_ENV_URL = "FOOTBALL_WAREHOUSE_DATABASE_URL"
_ENV_ECHO = "FOOTBALL_WAREHOUSE_SQL_ECHO"
_DEV_MODE_ENV = "PLAYCALLER_DEV_MODE"

# Local SQLite default when (1) env URL is unset and (2) PLAYCALLER_DEV_MODE is truthy only.
_LOCAL_DEV_SQLITE_FALLBACK = "sqlite+pysqlite:///./warehouse.db"

logger = logging.getLogger(__name__)

_fallback_usage_logged = False


def _repo_root() -> Path:
    """``football_history_warehouse/config/database.py`` → repo root (``…/Test2``)."""
    return Path(__file__).resolve().parents[2]


def normalize_warehouse_database_url(raw_url: str) -> tuple[str, Path | None]:
    """
    For file-based SQLite URLs with a relative ``database`` segment, rewrite to an absolute
    path (anchored to the repo root). Returns ``(url, absolute_path)``; ``absolute_path`` is
    ``None`` for non-SQLite, ``:memory:``, or when unchanged.
    """
    url = (raw_url or "").strip()
    if not url:
        return url, None
    u = make_url(url)
    if not (u.drivername or "").lower().startswith("sqlite"):
        return url, None
    db = u.database
    if not db or db == ":memory:":
        return url, None
    path = Path(db)
    root = _repo_root()
    abs_path = path.resolve() if path.is_absolute() else (root / path).resolve()
    new_u = u.set(database=abs_path.as_posix())
    return str(new_u), abs_path


def resolve_warehouse_db_path(raw_url: str) -> Path | None:
    """Return the absolute SQLite database file path, or ``None`` if not a file-based SQLite URL."""
    _, p = normalize_warehouse_database_url(raw_url)
    return p


def _playcaller_dev_mode_truthy() -> bool:
    return str(os.environ.get(_DEV_MODE_ENV) or "").strip().lower() in ("1", "true", "yes")


def resolve_warehouse_database_url() -> tuple[str | None, bool]:
    """
    Resolve the warehouse database URL with explicit precedence (no UI side effects):

    1. Non-empty ``FOOTBALL_WAREHOUSE_DATABASE_URL`` in the process environment → use it
       (SQLite relative paths normalized via :func:`normalize_warehouse_database_url`).
    2. Else if ``PLAYCALLER_DEV_MODE`` is truthy → local SQLite dev fallback
       (``sqlite+pysqlite:///./warehouse.db``, normalized to an absolute repo-root path).
    3. Else → ``None`` (unconfigured; warehouse inventory shows “not configured”).

    Returns ``(normalized_url_or_none, used_dev_fallback)``. When ``used_dev_fallback`` is
    True, the explicit env var was **not** set; callers may surface that in operator UI.

    Logs at INFO the first time per process the dev fallback is used (avoids Streamlit rerun spam).
    """
    global _fallback_usage_logged
    raw = os.environ.get(_ENV_URL, "").strip()
    if raw:
        nu, _ = normalize_warehouse_database_url(raw)
        return nu, False
    if _playcaller_dev_mode_truthy():
        nu, _ = normalize_warehouse_database_url(_LOCAL_DEV_SQLITE_FALLBACK)
        if not _fallback_usage_logged:
            logger.info(
                "%s unset; using local SQLite dev fallback (%s=1): %s",
                _ENV_URL,
                _DEV_MODE_ENV,
                nu,
            )
            _fallback_usage_logged = True
        return nu, True
    return None, False


class DatabaseConfig(BaseModel):
    """Immutable DB settings derived from env or passed explicitly (tests, tools)."""

    model_config = ConfigDict(frozen=True)

    database_url: str = Field(..., min_length=1, description="SQLAlchemy URL.")
    echo_sql: bool = Field(default=False, description="Log SQL statements (dev only).")

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_sqlite_paths(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        nu, _ = normalize_warehouse_database_url(v)
        return nu

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        url, _used_fb = resolve_warehouse_database_url()
        if not url:
            raise WarehouseConfigError(
                f"Set {_ENV_URL} to a SQLAlchemy URL "
                f"(e.g. postgresql+psycopg://... or sqlite+pysqlite:///... ), "
                f"or set {_DEV_MODE_ENV}=1 for local dev SQLite fallback.",
            )
        echo = os.environ.get(_ENV_ECHO, "").strip().lower() in ("1", "true", "yes")
        return cls(database_url=url, echo_sql=echo)


def get_database_url(*, required: bool = True) -> str | None:
    """
    Resolved warehouse URL (same rules as :func:`resolve_warehouse_database_url`).

    Used by Alembic ``env.py``. When ``required`` is False, returns ``None`` if unconfigured
    (no env URL and no dev-mode fallback).
    """
    url, _used_fb = resolve_warehouse_database_url()
    if not url:
        if required:
            raise WarehouseConfigError(
                f"{_ENV_URL} is not set (and {_DEV_MODE_ENV} is not enabled); "
                "export the URL before running migrations or the app.",
            )
        return None
    return DatabaseConfig(database_url=url, echo_sql=False).database_url
