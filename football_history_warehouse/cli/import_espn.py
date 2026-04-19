"""
CLI: import ESPN game summary JSON (one file or manifest).

Run with:

    python -m football_history_warehouse.cli.import_espn --manifest manual_games/manifest.json

or:

    python -m football_history_warehouse.cli.import_espn --file path/to/summary.json \\
        --league-id league-nfl --season-id season-2024 \\
        --team-map-json '{"espn:10":"team-nyg","espn:14":"team-lar"}'

Requires ``FOOTBALL_WAREHOUSE_DATABASE_URL`` (or ``--database-url``).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.pipeline.espn_summary_import import (
    EspnSummaryImportSpec,
    import_espn_summary_game_file,
    load_manifest,
    spec_from_manifest_entry,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope


def _print_result(r, *, verbose: bool) -> None:
    if verbose and r.pipeline_report is not None:
        print(json.dumps(r.pipeline_report, indent=2))
    else:
        print(
            f"{r.outcome}\tjob={r.job_id}\tgame_id={r.game_id}\tartifact={r.artifact_id}\t{r.message}",
            file=sys.stdout,
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import ESPN game summary JSON into the warehouse.")
    p.add_argument("--database-url", default=None, help="Override FOOTBALL_WAREHOUSE_DATABASE_URL")
    p.add_argument("--file", type=Path, default=None, help="Single ESPN summary JSON file")
    p.add_argument("--manifest", type=Path, default=None, help="JSON manifest with multiple games")
    p.add_argument("--league-id", default=None)
    p.add_argument("--season-id", default=None)
    p.add_argument("--season-year-label", default=None)
    p.add_argument("--league-name", default=None)
    p.add_argument("--team-map-json", default=None, help='JSON object, e.g. {"espn:10":"team-nyg"}')
    p.add_argument("--verbose", action="store_true", help="Print full pipeline_report JSON")
    p.add_argument("--no-skip-duplicate", action="store_true", help="Disable duplicate raw/game short-circuit (dangerous)")
    args = p.parse_args(argv)

    if args.database_url and args.database_url.strip():
        cfg = DatabaseConfig(database_url=args.database_url.strip(), echo_sql=False)
    else:
        try:
            cfg = DatabaseConfig.from_env()
        except WarehouseConfigError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

    upgrade_to_head(database_url=str(cfg.database_url))
    engine = create_warehouse_engine(cfg)
    skip_dup = not args.no_skip_duplicate

    try:
        if args.manifest is not None:
            defaults, games, mdir = load_manifest(args.manifest.resolve())
            exit_code = 0
            for g in games:
                if not isinstance(g, dict):
                    print("Invalid manifest: each game must be an object.", file=sys.stderr)
                    return 2
                path, spec = spec_from_manifest_entry(mdir, defaults, g)
                job_id = f"job-{uuid.uuid4().hex[:16]}"
                with session_scope(engine) as session:
                    r = import_espn_summary_game_file(
                        session,
                        json_path=path,
                        spec=spec,
                        job_id=job_id,
                        skip_if_duplicate_raw_checksum=skip_dup,
                        skip_if_canonical_game_exists=skip_dup,
                    )
                _print_result(r, verbose=args.verbose)
                if r.outcome not in ("persisted", "duplicate_raw_skipped", "duplicate_game_skipped"):
                    exit_code = 1
            return exit_code

        if args.file is None:
            print("Provide --file or --manifest.", file=sys.stderr)
            return 2
        if not args.league_id or not args.season_id or not args.team_map_json:
            print("--league-id, --season-id, and --team-map-json are required with --file.", file=sys.stderr)
            return 2
        tm = json.loads(args.team_map_json)
        if not isinstance(tm, dict):
            print("--team-map-json must be a JSON object.", file=sys.stderr)
            return 2
        team_ref = {
            (k if str(k).startswith("espn:") else f"espn:{k}"): str(v) for k, v in tm.items()
        }
        spec = EspnSummaryImportSpec(
            league_id=args.league_id,
            season_id=args.season_id,
            season_year_label=args.season_year_label,
            league_name=args.league_name,
            team_id_by_external_ref=team_ref,
        )
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        with session_scope(engine) as session:
            r = import_espn_summary_game_file(
                session,
                json_path=args.file.resolve(),
                spec=spec,
                job_id=job_id,
                skip_if_duplicate_raw_checksum=skip_dup,
                skip_if_canonical_game_exists=skip_dup,
            )
        _print_result(r, verbose=args.verbose)
        if r.outcome not in ("persisted", "duplicate_raw_skipped", "duplicate_game_skipped"):
            return 1
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
