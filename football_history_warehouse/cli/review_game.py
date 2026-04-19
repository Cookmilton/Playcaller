"""
Dev/ops CLI: emit a JSON game review package for validation.

    python -m football_history_warehouse.cli.review_game --game-id espn-401test001

Requires ``FOOTBALL_WAREHOUSE_DATABASE_URL`` or ``--database-url``.
"""

from __future__ import annotations

import argparse
import json
import sys

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.review import build_game_review_package
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build JSON game review package from warehouse DB.")
    p.add_argument("--database-url", default=None, help="Override FOOTBALL_WAREHOUSE_DATABASE_URL")
    p.add_argument("--game-id", required=True, help="Canonical game_id")
    p.add_argument("--no-migrate", action="store_true", help="Skip alembic upgrade_to_head")
    args = p.parse_args(argv)

    if args.database_url and args.database_url.strip():
        cfg = DatabaseConfig(database_url=args.database_url.strip(), echo_sql=False)
    else:
        try:
            cfg = DatabaseConfig.from_env()
        except WarehouseConfigError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

    if not args.no_migrate:
        upgrade_to_head(database_url=str(cfg.database_url))

    engine = create_warehouse_engine(cfg)
    try:
        with session_scope(engine) as session:
            pkg = build_game_review_package(session, args.game_id.strip())
        if pkg is None:
            print(f"Game not found: {args.game_id!r}", file=sys.stderr)
            return 1
        print(json.dumps(pkg.model_dump(mode="json"), indent=2))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
