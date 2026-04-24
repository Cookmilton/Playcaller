"""
Run: ``python -m football_history_warehouse.ingest <fixture.json>`` (see package docs).

Loads optional ``.env`` from the current working directory for local parity with Streamlit.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.config.database import get_database_url
from football_history_warehouse.ingest.from_json import (
    ingest_from_json_file,
    table_row_counts,
    verify_ingested_game,
)
from football_history_warehouse.ingest.normalize import normalize_espn_summary


def _load_dotenv_optional() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _print_run_summary(path: Path, db_url: str, *, league: str | None, season: int | None) -> None:
    r = ingest_from_json_file(path, database_url=db_url, league=league, season=season)
    raw = json.loads(path.read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(raw, league_code=league, season_year_override=season)
    ext = bundle.game.external_id
    away = bundle.away_team.display_name
    home = bundle.home_team.display_name
    hs, a_s = bundle.game.home_score, bundle.game.away_score
    score = f"{a_s}–{hs}" if a_s is not None and hs is not None else "?–?"
    new_note = "new" if r.was_new else "re-ingested"
    print(
        f"✓ Ingested game {ext}: {away} @ {home} — {score} "
        f"({new_note}: {r.rows_created} rows created, {r.rows_updated} updated)"
    )
    conf = verify_ingested_game(db_url, r.game_id)
    print(f"Game {r.game_id} confirmed in DB: {conf}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Minimal warehouse game ingest from ESPN summary JSON.")
    p.add_argument("path", nargs="?", type=Path, help="Path to ESPN summary JSON")
    p.add_argument("--batch", type=Path, help="Ingest every *.json in this directory")
    p.add_argument("--league", type=str, default=None, help="Override league code (default NFL)")
    p.add_argument("--season", type=int, default=None, help="Override season year")
    p.add_argument(
        "--twice",
        action="store_true",
        help="Run ingest twice on the same file to demonstrate idempotency (single-file mode only).",
    )
    args = p.parse_args(argv)

    _load_dotenv_optional()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        db_url = get_database_url(required=True)
    except WarehouseConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.batch is not None:
        if args.path is not None:
            print("error: do not pass a file path together with --batch", file=sys.stderr)
            return 2
        paths = sorted(args.batch.glob("*.json"))
        if not paths:
            print(f"error: no *.json in {args.batch}", file=sys.stderr)
            return 2
        for fp in paths:
            print(f"--- {fp.name} ---", file=sys.stderr)
            ingest_from_json_file(fp, database_url=db_url, league=args.league, season=args.season)
        print(f"Batch complete. Table row counts: {table_row_counts(db_url)}")
        return 0

    if args.path is None:
        p.print_help()
        return 2

    if not args.path.is_file():
        print(f"error: not a file: {args.path}", file=sys.stderr)
        return 2

    _print_run_summary(args.path, db_url, league=args.league, season=args.season)
    if args.twice:
        r2 = ingest_from_json_file(args.path, database_url=db_url, league=args.league, season=args.season)
        print(
            f"✓ Re-ingested game: {r2.rows_created} new rows, {r2.rows_updated} updated "
            f"(game_id={r2.game_id})"
        )
    print(f"Table row counts: {table_row_counts(db_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
