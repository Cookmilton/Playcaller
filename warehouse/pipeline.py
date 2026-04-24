"""Warehouse week pipeline: nflverse (or on-disk raw) → ``data/processed`` JSON.

From the repo root, typical usage::

    python -m warehouse.pipeline SEASON WEEK

When nflverse cannot be reached, build processed files from existing
``data/raw/{season}/week_{WW}/`` files::

    python -m warehouse.pipeline SEASON WEEK --from-raw-cache
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from warehouse.features import compute_features as compute_play_features
from warehouse.ingest import load_week_games, load_week_games_from_raw_cache
from warehouse.models import DerivedPlayFeatures, Game, Play
from warehouse.normalize import normalize_game
from warehouse.quality import check_quality
from warehouse.storage import _make_game_id, processed_data_dir, store_raw_games
from warehouse.validation import validate_play_sequence

logger = logging.getLogger(__name__)

# Canonical processed layout: processed_data_dir() / {season} / week_{WW} / {game_id}.json


@dataclass(kw_only=True, slots=True)
class IngestionResult:
    season: int
    week: int
    games_loaded: int
    games_failed: int
    plays_normalized: int
    validation_issues: dict[str, int]
    quality_issues: dict[str, int]
    failed_game_ids: list[str]
    elapsed_seconds: float
    processed_paths_written: tuple[str, ...] = ()


def _processed_week_dir(season: int, week: int) -> Path:
    return processed_data_dir() / str(season) / f"week_{week:02d}"


def _processed_path(season: int, week: int, game_id: str) -> Path:
    return _processed_week_dir(season, week) / f"{game_id}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, indent=2, default=str)
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                logger.debug("Could not remove temp file %s", tmp, exc_info=True)
        raise


def _game_to_dict(g: Game) -> dict[str, Any]:
    return {
        "id": g.id,
        "source": g.source.value,
        "external_game_id": g.external_game_id,
        "season": g.season,
        "week": g.week,
        "game_type": g.game_type.value,
        "home_team": g.home_team,
        "away_team": g.away_team,
        "game_date": g.game_date.isoformat(),
        "status": g.status.value,
        "final_home_score": g.final_home_score,
        "final_away_score": g.final_away_score,
    }


def _play_to_dict(p: Play) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in fields(Play):
        val = getattr(p, f.name)
        if hasattr(val, "value"):
            out[f.name] = val.value
        else:
            out[f.name] = val
    return out


def _features_to_dict(f: DerivedPlayFeatures) -> dict[str, Any]:
    return asdict(f)


def _print_summary_block(result: IngestionResult) -> None:
    lines = [
        "",
        "========== Ingestion summary ==========",
        f"Season / week:     {result.season} / {result.week}",
        f"Games loaded:      {result.games_loaded}",
        f"Games failed:      {result.games_failed}",
        f"Plays normalized:  {result.plays_normalized:,}",
        f"Validation issues: {dict(result.validation_issues)}",
        f"Quality issues:    {dict(result.quality_issues)}",
        f"Failed game IDs:   {result.failed_game_ids}",
        f"Elapsed:           {result.elapsed_seconds:.1f}s",
    ]
    if result.processed_paths_written:
        lines.append(
            f"Processed JSON:    {len(result.processed_paths_written)} file(s) written"
        )
        for p in result.processed_paths_written:
            lines.append(f"                     {p}")
    else:
        lines.append("Processed JSON:    (no new files this run)")
    lines.extend(["========================================", ""])
    print("\n".join(lines))


def run_week_ingestion(
    season: int,
    week: int,
    *,
    force_refresh: bool = False,
    validate: bool = True,
    compute_features: bool = True,
    quality_checks: bool = True,
    from_raw_cache: bool = False,
) -> IngestionResult:
    t0 = time.perf_counter()
    logger.info("Ingesting season=%s week=%s", season, week)

    if from_raw_cache:
        games = load_week_games_from_raw_cache(season, week)
    else:
        games = load_week_games(season, week)
    games_loaded = len(games)
    total_plays_in = sum(len(g.get("plays") or []) for g in games)
    logger.info("Loaded %s games / %s plays", f"{games_loaded:,}", f"{total_plays_in:,}")

    raw_payloads = store_raw_games(games, overwrite=force_refresh)
    logger.debug("Stored %s raw game payload record(s)", len(raw_payloads))

    validation_counter: Counter[str] = Counter()
    quality_counter: Counter[str] = Counter()
    games_failed = 0
    failed_game_ids: list[str] = []
    plays_normalized = 0
    games_normalized_ok = 0
    games_skipped = 0
    processed_written: list[Path] = []

    for game_dict in games:
        meta = game_dict["meta"]
        ext_id = str(meta.get("external_game_id", "") or "")
        internal_id = _make_game_id(meta)

        if (
            compute_features
            and not force_refresh
            and _processed_path(season, week, internal_id).is_file()
        ):
            logger.info(
                "Skipping game with existing processed output (use force_refresh to rebuild): %s",
                internal_id,
            )
            games_skipped += 1
            continue

        try:
            game, plays = normalize_game(game_dict)
            if validate:
                report = validate_play_sequence(game, plays)
                validation_counter.update(report.summary)
            if quality_checks:
                q_issues = check_quality(game, plays)
                for q in q_issues:
                    logger.warning(
                        "Quality [%s] game=%s play=%s %s",
                        q.rule,
                        game.id,
                        q.play_id,
                        q.detail,
                    )
                quality_counter.update(q.rule for q in q_issues)
            if compute_features:
                feats = compute_play_features(plays, game=game)
                payload = {
                    "schema_version": "2.0",
                    "game": _game_to_dict(game),
                    "plays": [_play_to_dict(p) for p in plays],
                    "features": [_features_to_dict(f) for f in feats],
                }
                out_path = _processed_path(season, week, game.id)
                _atomic_write_json(out_path, payload)
                processed_written.append(out_path)
            plays_normalized += len(plays)
            games_normalized_ok += 1
        except Exception:
            logger.exception("Game %s failed", ext_id or internal_id)
            games_failed += 1
            failed_game_ids.append(ext_id or internal_id)

    elapsed = time.perf_counter() - t0

    vwarn = int(validation_counter.get("warning", 0))
    verr = int(validation_counter.get("error", 0))
    logger.info(
        "Normalized %s games, %s failures",
        games_normalized_ok,
        games_failed,
    )
    if games_skipped:
        logger.info("Skipped %s games (processed JSON already present)", games_skipped)
    if validate and games_normalized_ok > 0:
        logger.info("Validation: %s warnings, %s errors", vwarn, verr)
    if quality_checks and games_normalized_ok > 0 and quality_counter:
        logger.info("Quality: %s", dict(quality_counter))

    if compute_features:
        week_dir = _processed_week_dir(season, week)
        n_new = len(processed_written)
        logger.info("Processed JSON output directory: %s", week_dir.resolve())
        logger.info(
            "Processed summary: %s JSON file(s) written | %s game(s) normalized OK | %s game(s) loaded",
            n_new,
            games_normalized_ok,
            games_loaded,
        )
        for p in processed_written:
            logger.info("  %s", p.resolve())
        if n_new == 0:
            logger.info(
                "No new processed JSON files (existing outputs skipped, failures, or nothing to ingest)."
            )
    else:
        logger.info("Processed JSON output skipped (compute_features=False).")

    logger.info("Done in %ss", f"{elapsed:.1f}")

    result = IngestionResult(
        season=season,
        week=week,
        games_loaded=games_loaded,
        games_failed=games_failed,
        plays_normalized=plays_normalized,
        validation_issues=dict(validation_counter),
        quality_issues=dict(quality_counter),
        failed_game_ids=failed_game_ids,
        elapsed_seconds=elapsed,
        processed_paths_written=tuple(str(p.resolve()) for p in processed_written),
    )
    _print_summary_block(result)
    return result


def _configure_logging() -> None:
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )


if __name__ == "__main__":
    _configure_logging()
    parser = argparse.ArgumentParser(description="Run warehouse week ingestion pipeline.")
    parser.add_argument("season", type=int)
    parser.add_argument("week", type=int)
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Overwrite raw cache and ignore existing processed JSON.",
    )
    parser.add_argument(
        "--from-raw-cache",
        action="store_true",
        help="Skip nflverse; load games from data/raw/{season}/week_{WW}/ only.",
    )
    parser.add_argument("--no-validate", action="store_true")
    parser.add_argument("--no-features", action="store_true")
    parser.add_argument("--no-quality", action="store_true")
    args = parser.parse_args()
    run_week_ingestion(
        args.season,
        args.week,
        force_refresh=args.force_refresh,
        validate=not args.no_validate,
        compute_features=not args.no_features,
        quality_checks=not args.no_quality,
        from_raw_cache=args.from_raw_cache,
    )
