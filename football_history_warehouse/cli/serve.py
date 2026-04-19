"""
Run the warehouse read API (FastAPI + Uvicorn).

Requires ``FOOTBALL_WAREHOUSE_DATABASE_URL``.

    python -m football_history_warehouse.cli.serve --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import argparse
import sys

from football_history_warehouse.config.exceptions import WarehouseConfigError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Serve FootballWarehouseClient over HTTP (FastAPI).")
    p.add_argument("--host", default="127.0.0.1", help="Bind address")
    p.add_argument("--port", type=int, default=8000, help="Port")
    p.add_argument("--reload", action="store_true", help="Dev-only autoreload (single worker)")
    args = p.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:
        print("Install uvicorn (e.g. pip install 'uvicorn[standard]')", file=sys.stderr)
        raise SystemExit(2) from exc

    # Fail fast if DB URL missing (matches other CLIs)
    try:
        from football_history_warehouse.config.database import DatabaseConfig

        DatabaseConfig.from_env()
    except WarehouseConfigError as exc:
        print(f"{exc}", file=sys.stderr)
        return 2

    uvicorn.run(
        "football_history_warehouse.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        factory=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
