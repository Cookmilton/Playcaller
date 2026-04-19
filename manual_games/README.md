# Manual ESPN game imports (proof-of-life)

This folder holds an example **manifest** for loading saved ESPN **game summary** JSON files through the real warehouse pipeline:

`ingest (raw artifact + job) → parse → normalize → validate → persist`

## Prerequisites

1. Set `FOOTBALL_WAREHOUSE_DATABASE_URL` (see `.env.example` at the repo root).
2. Run migrations on that database once (the CLI runs `upgrade_to_head` for you).

## Import one file

```bash
export FOOTBALL_WAREHOUSE_DATABASE_URL="sqlite+pysqlite:///./var/warehouse.db"
python -m football_history_warehouse.cli.import_espn \
  --file /path/to/espn_summary.json \
  --league-id league-nfl-manual \
  --season-id season-2024 \
  --team-map-json '{"espn:10":"team-nyg","espn:14":"team-lar"}'
```

`--team-map-json` maps ESPN team ids from the JSON (`competitors[].id`) to canonical `teams.team_id` strings (create stable ids you will reuse).

Use `--verbose` to print the full structured `pipeline_report` JSON.

## Import several games (manifest)

Copy `manifest.example.json` to e.g. `manifest.json`, edit `league_id`, `season_id`, and `team_map`, and list one object per game under `games` with a `path` to each JSON file. Paths are resolved relative to the manifest file’s directory.

To load about **five** historical games, add five entries under `games` (each file must be **distinct** bytes or the second copy will be treated as a duplicate raw upload; each ESPN **event id** maps to a canonical `game_id` `espn-{event_id}` unless you set `game_id_override` on an entry).

```bash
python -m football_history_warehouse.cli.import_espn --manifest manual_games/manifest.json
```

Exit code `0` means every row succeeded or was skipped as a **duplicate** (idempotent re-run). Non-zero means at least one game failed validation or persistence.

## Duplicates (idempotency)

- **Same file bytes** + same `source_system`: skipped as `duplicate_raw_skipped` (no second artifact for the same checksum).
- **Same canonical `game_id`** already in `games`: skipped as `duplicate_game_skipped` before a new import job is created.

## Programmatic API

`import_espn_summary_game_file` from `football_history_warehouse.pipeline` (or `espn_summary_import`) runs one game inside an open SQLAlchemy session (see `tests/test_pipeline_espn_import.py`).
