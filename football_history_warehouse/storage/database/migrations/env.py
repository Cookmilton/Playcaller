"""
Alembic migration environment.

Reads ``FOOTBALL_WAREHOUSE_DATABASE_URL``; keeps schema revisions next to the
warehouse package. Repo root is prepended via ``alembic.ini`` ``prepend_sys_path``.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# If prepend_sys_path in alembic.ini fails (unusual), fall back explicitly.
_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from football_history_warehouse.config.database import get_database_url
from football_history_warehouse.storage.database.base import Base
import football_history_warehouse.storage.database.models  # noqa: F401  # register tables on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """
    Prefer URL injected via ``Config.set_main_option`` (e.g. ``bootstrap.upgrade_to_head``);
    otherwise read ``FOOTBALL_WAREHOUSE_DATABASE_URL``.
    """
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url and not ini_url.startswith("driver://"):
        return ini_url
    u = get_database_url(required=True)
    assert u is not None
    return u


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
