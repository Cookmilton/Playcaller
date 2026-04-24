from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from warehouse.ingest import load_week_games
from warehouse.pipeline import IngestionResult, run_week_ingestion
from warehouse.storage import REPO_ROOT, _make_game_id, processed_data_dir

logger = logging.getLogger("warehouse.bulk")

_V2_PLAY_FIELDS = (
    "epa",
    "success",
    "shotgun",
    "no_huddle",
    "qb_dropback",
    "defenders_in_box",
    "offense_personnel",
    "air_yards",
    "yards_after_catch",
    "xpass",
    "passer_player_name",
    "receiver_player_name",
    "rusher_player_name",
)
_V2_FIELD_NOTE: dict[str, str] = {
    "air_yards": " (expected high on non-pass plays)",
    "yards_after_catch": " (expected high on non-pass plays)",
    "passer_player_name": " (expected high on non-pass plays)",
    "receiver_player_name": " (expected high on non-pass plays)",
}


def _expected_internal_game_ids(season: int, week: int, result: IngestionResult) -> set[str]:
    failed = set(result.failed_game_ids)
    out: set[str] = set()
    for gd in load_week_games(season, week):
        meta = gd["meta"]
        internal = _make_game_id(meta)
        ext = str(meta.get("external_game_id", "") or "")
        if ext in failed or internal in failed:
            continue
        out.add(internal)
    return out


def _null_rates_from_plays(plays: list[dict[str, Any]]) -> dict[str, float]:
    if not plays:
        return {f: 0.0 for f in _V2_PLAY_FIELDS}
    n = 0
    nulls = {f: 0 for f in _V2_PLAY_FIELDS}
    for pl in plays:
        if not isinstance(pl, dict):
            continue
        n += 1
        for f in _V2_PLAY_FIELDS:
            if f not in pl or pl[f] is None:
                nulls[f] += 1
    return {f: 100.0 * nulls[f] / n for f in _V2_PLAY_FIELDS}


def _null_rates_for_processed_paths_written(paths: tuple[str, ...]) -> dict[str, float]:
    combined: list[dict[str, Any]] = []
    for ps in paths:
        p = Path(ps)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for pl in raw.get("plays") or []:
            if isinstance(pl, dict):
                combined.append(pl)
    return _null_rates_from_plays(combined)


def _log_week_v2_null_rates(paths: tuple[str, ...]) -> None:
    rates = _null_rates_for_processed_paths_written(paths)
    logger.info("Null rates (schema v2 fields):")
    for f in _V2_PLAY_FIELDS:
        pct = rates[f]
        note = _V2_FIELD_NOTE.get(f, "")
        line = f"  {f:<20}: {pct:.1f}%{note}"
        if pct > 95.0:
            logger.warning(
                "%s [WARN null>95%% — possible nflverse column drift]",
                line,
            )
        else:
            logger.info("%s", line)


def _prune_orphans_week(season: int, week: int, valid_ids: set[str]) -> None:
    if not valid_ids:
        logger.info("Orphan prune skipped: empty expected game id set (season=%s week=%s)", season, week)
        return
    wd = processed_data_dir() / str(season) / f"week_{week:02d}"
    if not wd.is_dir():
        return
    for f in sorted(wd.glob("*.json")):
        if f.stem in valid_ids:
            continue
        logger.info("Removing orphan processed file: %s", f.resolve())
        try:
            f.unlink()
        except OSError as e:
            logger.warning("Could not remove orphan %s: %s", f, e)


def _checkpoint_path(season: int) -> Path:
    return REPO_ROOT / "data" / "checkpoints" / f"{season}_bulk.json"


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


def _load_checkpoint(season: int) -> dict[str, Any] | None:
    path = _checkpoint_path(season)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read checkpoint %s: %s", path, e)
        return None


def _save_checkpoint(season: int, completed_weeks: list[int]) -> None:
    payload = {
        "season": season,
        "completed_weeks": sorted(set(completed_weeks)),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_json(_checkpoint_path(season), payload)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (OSError, ConnectionError, TimeoutError, BrokenPipeError)):
        return True
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, RuntimeError):
        cause = exc.__cause__
        if isinstance(cause, OSError):
            return True
        msg = str(exc).lower()
        if "network" in msg or "timeout" in msg or "ssl" in msg or "certificate" in msg:
            return True
    return False


def _run_week_with_retries(
    season: int,
    week: int,
    *,
    max_retries: int,
    **kwargs: Any,
) -> IngestionResult:
    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return run_week_ingestion(season, week, **kwargs)
        except Exception as e:
            last_exc = e
            if not _is_transient(e) or attempt >= max_retries:
                raise
            delay = 1 << attempt
            logger.warning(
                "Week %s transient error (attempt %s/%s): %s — retry in %ss",
                week,
                attempt + 1,
                max_retries + 1,
                e,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _default_weeks(*, include_playoffs: bool) -> list[int]:
    if include_playoffs:
        return list(range(1, 23))
    return list(range(1, 19))


def parse_weeks_spec(spec: str) -> list[int]:
    s = spec.strip()
    if not s:
        return []
    if "," in s:
        return [int(x.strip()) for x in s.split(",") if x.strip()]
    if "-" in s:
        lo, hi = s.split("-", 1)
        return list(range(int(lo.strip()), int(hi.strip()) + 1))
    return [int(s)]


def _maybe_tqdm(
    iterable: Iterable[Any],
    *,
    total: int | None,
    desc: str | None,
) -> Iterable[Any]:
    try:
        from tqdm import tqdm as tqdm_fn
    except ImportError:
        return iterable
    return tqdm_fn(iterable, total=total, desc=desc)


@dataclass(kw_only=True, slots=True)
class BulkIngestionResult:
    season: int
    weeks_processed: list[int]
    total_games: int
    total_failures: int
    per_week: dict[int, IngestionResult]
    elapsed_seconds: float


def run_bulk_ingestion(
    season: int,
    weeks: list[int] | None = None,
    *,
    max_retries: int = 2,
    resume: bool = True,
    force_refresh: bool = False,
    include_playoffs: bool = False,
    validate: bool = True,
    compute_features: bool = True,
    quality_checks: bool = True,
    prune_orphans: bool = False,
) -> BulkIngestionResult:
    if weeks is None:
        week_list = _default_weeks(include_playoffs=include_playoffs)
    else:
        week_list = sorted(set(weeks))

    completed_from_file: list[int] = []
    if resume and not force_refresh:
        cp = _load_checkpoint(season)
        if isinstance(cp, dict):
            raw = cp.get("completed_weeks")
            if isinstance(raw, list):
                completed_from_file = [int(w) for w in raw]

    t0 = time.perf_counter()
    per_week: dict[int, IngestionResult] = {}
    weeks_processed: list[int] = []
    total_games = 0
    total_failures = 0
    completed_set = set(completed_from_file)

    to_run: list[int] = []
    for w in week_list:
        if resume and not force_refresh and w in completed_set:
            logger.info(
                "Bulk season=%s: skipping week %s (checkpoint resume)",
                season,
                w,
            )
            continue
        to_run.append(w)

    iterator: Iterator[int] = iter(to_run)
    iterator = _maybe_tqdm(iterator, total=len(to_run), desc=f"bulk {season}")

    for week in iterator:
        wk_t0 = time.perf_counter()
        logger.info(
            "Bulk season=%s week=%s start (elapsed_bulk=%.1fs)",
            season,
            week,
            time.perf_counter() - t0,
        )
        result = _run_week_with_retries(
            season,
            week,
            max_retries=max_retries,
            force_refresh=force_refresh,
            validate=validate,
            compute_features=compute_features,
            quality_checks=quality_checks,
        )
        wk_elapsed = time.perf_counter() - wk_t0
        per_week[week] = result
        weeks_processed.append(week)
        total_games += result.games_loaded
        total_failures += result.games_failed
        completed_set.add(week)
        _save_checkpoint(season, list(completed_set))
        logger.info(
            "Bulk season=%s week=%s end in %.1fs (games_loaded=%s failures=%s)",
            season,
            week,
            wk_elapsed,
            result.games_loaded,
            result.games_failed,
        )
        if result.processed_paths_written:
            _log_week_v2_null_rates(result.processed_paths_written)

    if prune_orphans and weeks_processed:
        for week in weeks_processed:
            res = per_week[week]
            valid = _expected_internal_game_ids(season, week, res)
            if not valid:
                logger.info("Orphan prune skipped: no expected ids from nflverse (week=%s)", week)
                continue
            _prune_orphans_week(season, week, valid)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Bulk season=%s finished: weeks_processed=%s total_games=%s total_failures=%s in %.1fs",
        season,
        weeks_processed,
        total_games,
        total_failures,
        elapsed,
    )
    return BulkIngestionResult(
        season=season,
        weeks_processed=weeks_processed,
        total_games=total_games,
        total_failures=total_failures,
        per_week=per_week,
        elapsed_seconds=elapsed,
    )


def _configure_logging() -> None:
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bulk warehouse ingestion by season/week.")
    p.add_argument("--season", type=int, required=True)
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--weeks",
        type=str,
        help='Weeks: "1-5" (inclusive range) or "1,3,5" (list).',
    )
    g.add_argument(
        "--full",
        action="store_true",
        help="All regular-season weeks (1–18), or 1–22 with --include-playoffs.",
    )
    p.add_argument(
        "--include-playoffs",
        action="store_true",
        help="With --full (or default week list), use weeks 1–22 instead of 1–18.",
    )
    p.add_argument("--retries", type=int, default=2, help="Max retries per week on transient errors.")
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore checkpoint and process all requested weeks.",
    )
    p.add_argument(
        "--force-refresh",
        action="store_true",
        help="Passed to each week (overwrite raw; ignore checkpoint for skipping).",
    )
    p.add_argument("--no-validate", action="store_true")
    p.add_argument("--no-features", action="store_true")
    p.add_argument("--no-quality", action="store_true")
    p.add_argument(
        "--prune-orphans",
        action="store_true",
        help="After ingest, delete processed JSON not in nflverse slate for each week processed.",
    )
    return p


def main() -> None:
    _configure_logging()
    parser = _build_arg_parser()
    args = parser.parse_args()

    if args.weeks:
        week_list = parse_weeks_spec(args.weeks)
    elif args.full:
        week_list = _default_weeks(include_playoffs=args.include_playoffs)
    else:
        parser.error("Specify --weeks or --full")

    run_bulk_ingestion(
        args.season,
        week_list,
        max_retries=args.retries,
        resume=not args.no_resume,
        force_refresh=args.force_refresh,
        include_playoffs=args.include_playoffs,
        validate=not args.no_validate,
        compute_features=not args.no_features,
        quality_checks=not args.no_quality,
        prune_orphans=args.prune_orphans,
    )


if __name__ == "__main__":
    main()
