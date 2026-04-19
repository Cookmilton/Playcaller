"""
Database connectivity settings — loaded from the environment.

**Primary variable:** ``FOOTBALL_WAREHOUSE_DATABASE_URL`` (SQLAlchemy URL).

Examples::

    postgresql+psycopg://user:pass@localhost:5432/football_history
    sqlite+pysqlite:///./var/football_history/local.db

Do not commit secrets; use ``.env`` locally (see ``.env.example`` at repo root).
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from football_history_warehouse.config.exceptions import WarehouseConfigError

_ENV_URL = "FOOTBALL_WAREHOUSE_DATABASE_URL"
_ENV_ECHO = "FOOTBALL_WAREHOUSE_SQL_ECHO"


class DatabaseConfig(BaseModel):
    """Immutable DB settings derived from env or passed explicitly (tests, tools)."""

    model_config = ConfigDict(frozen=True)

    database_url: str = Field(..., min_length=1, description="SQLAlchemy URL.")
    echo_sql: bool = Field(default=False, description="Log SQL statements (dev only).")

    @classmethod
    def from_env(cls) -> DatabaseConfig:
        url = os.environ.get(_ENV_URL, "").strip()
        if not url:
            raise WarehouseConfigError(
                f"Set {_ENV_URL} to a SQLAlchemy URL "
                f"(e.g. postgresql+psycopg://... or sqlite+pysqlite:///... ).",
            )
        echo = os.environ.get(_ENV_ECHO, "").strip().lower() in ("1", "true", "yes")
        return cls(database_url=url, echo_sql=echo)


def get_database_url(*, required: bool = True) -> str | None:
    """
    Return the raw URL from the environment.

    Used by Alembic ``env.py``. When ``required`` is False, returns ``None`` if unset.
    """
    url = os.environ.get(_ENV_URL, "").strip()
    if not url:
        if required:
            raise WarehouseConfigError(
                f"{_ENV_URL} is not set; export it before running migrations or the app.",
            )
        return None
    return url
