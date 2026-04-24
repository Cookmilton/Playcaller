"""
Load **processed** warehouse JSON (``game`` / ``plays`` / ``features``) for Review Session.

Builds a :class:`playcaller.game.Game` whose drive indices align with
``drive_id`` on :func:`warehouse.adapters.to_review_rows` (0-based:
``drive_number - 1``).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, TextIO, Tuple

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_UNKNOWN,
    Game,
    complete_drive_from_plays,
)
from playcaller.review.unified_review import UnifiedComparison, UnifiedReviewRow
from playcaller.session_game_metadata import fresh_session_metadata_dict

from warehouse.adapters import to_review_rows
from warehouse.normalize import _bool_or_none, _float_or_none, _int_or_none, _str_or_none
from warehouse.storage import processed_data_dir
from warehouse.models import (
    DataSource,
    DerivedPlayFeatures,
    Game as WarehouseGame,
    GameStatus,
    GameType,
    Play,
)
from warehouse.taxonomy import PlayResult, PlayType

logger = logging.getLogger(__name__)

_PUNT_PLAY_RESULTS: Final[frozenset[PlayResult]] = frozenset(
    {
        PlayResult.PUNT_NORMAL,
        PlayResult.PUNT_BLOCKED,
        PlayResult.PUNT_TOUCHBACK,
        PlayResult.PUNT_FAIR_CATCH,
        PlayResult.PUNT_DOWNED,
    }
)

# Indexing reads only a prefix so listing stays cheap as ``plays``/``features`` grow.
_INDEX_PREFIX_CHARS = 262_144
_GAME_KEY_PATTERN = re.compile(r'"game"\s*:\s*\{')

# UnifiedReviewRow fields that carry model / recommendation-side data for film-room cards.
# Historical warehouse rows must keep these at schema defaults (no fabricated predictions).
HISTORICAL_ACTUALS_ONLY_FIELDS: tuple[str, ...] = (
    "model_headline",
    "model_subline",
    "model_structured",
    "comparison",
    "confidence",
)

_WAREHOUSE_MODEL_HEADLINE_DEFAULT = "—"
_WAREHOUSE_MODEL_SUBLINE_DEFAULT = ""
_WAREHOUSE_MODEL_STRUCTURED_DEFAULT: Dict[str, Any] = {
    "summary_bucket": "",
    "family": "",
    "play_name": "",
    "run_pass": None,
}
_WAREHOUSE_COMPARISON_DEFAULT = UnifiedComparison(
    run_pass_match=None,
    summary_bucket_match=None,
    family_match=None,
)


@dataclass(kw_only=True, slots=True)
class ProcessedGameIndexEntry:
    season: int
    week: int
    game_id: str
    matchup_label: str
    path: Path


def _row_model_fields_are_warehouse_defaults(row: UnifiedReviewRow) -> bool:
    if row.model_headline != _WAREHOUSE_MODEL_HEADLINE_DEFAULT:
        return False
    if row.model_subline != _WAREHOUSE_MODEL_SUBLINE_DEFAULT:
        return False
    if row.model_structured != _WAREHOUSE_MODEL_STRUCTURED_DEFAULT:
        return False
    if row.confidence is not None:
        return False
    c = row.comparison
    if (
        c.run_pass_match is not None
        or c.summary_bucket_match is not None
        or c.family_match is not None
    ):
        return False
    return True


def _finalize_warehouse_historical_rows(rows: List[UnifiedReviewRow]) -> List[UnifiedReviewRow]:
    """Ensure model-side fields stay at warehouse defaults; log if any row was sanitized."""
    out: List[UnifiedReviewRow] = []
    bad = 0
    for r in rows:
        if _row_model_fields_are_warehouse_defaults(r):
            out.append(r)
            continue
        bad += 1
        out.append(
            replace(
                r,
                model_headline=_WAREHOUSE_MODEL_HEADLINE_DEFAULT,
                model_subline=_WAREHOUSE_MODEL_SUBLINE_DEFAULT,
                model_structured=dict(_WAREHOUSE_MODEL_STRUCTURED_DEFAULT),
                comparison=_WAREHOUSE_COMPARISON_DEFAULT,
                confidence=None,
            )
        )
    if bad:
        logger.warning(
            "Sanitized %s warehouse review row(s) with non-default model / recommendation fields",
            bad,
        )
    if __debug__:
        for r in out:
            assert _row_model_fields_are_warehouse_defaults(r)
    return out


def list_available_processed_games(
    root: str | Path | None = None,
) -> List[ProcessedGameIndexEntry]:
    root_p = processed_data_dir() if root is None else Path(root).expanduser()
    if not root_p.is_dir():
        logger.info(
            "Processed games root does not exist or is not a directory: %s",
            root_p.resolve(),
        )
        return []

    entries: List[ProcessedGameIndexEntry] = []
    for path in sorted(root_p.rglob("*.json")):
        ent = _try_index_entry_from_processed_file(path)
        if ent is not None:
            entries.append(ent)

    entries.sort(key=lambda e: (-e.season, e.week, e.matchup_label))
    return entries


def _game_dict_from_processed_prefix(prefix: str) -> Optional[dict[str, Any]]:
    """
    Parse the ``game`` object from the start of a processed JSON file without
    loading ``plays`` / ``features``.

    Expects root layout ``{"game": { ... }, ...}`` (same as the warehouse writer).
    """
    s = prefix.lstrip("\ufeff").lstrip()
    if not s.startswith("{"):
        return None
    m = _GAME_KEY_PATTERN.search(s)
    if not m:
        return None
    brace_start = m.end() - 1
    try:
        g, _end = json.JSONDecoder().raw_decode(s, brace_start)
    except json.JSONDecodeError:
        return None
    if not isinstance(g, dict):
        return None
    return g


def processed_schema_version(data: dict[str, Any]) -> str:
    """Return ``\"1.0\"`` when :data:`schema_version` is absent (legacy processed JSON)."""
    raw = data.get("schema_version")
    if raw is None:
        return "1.0"
    return str(raw)


def _warn_processed_schema_version(data: dict[str, Any], *, path: Path) -> None:
    raw = data.get("schema_version")
    if raw is None:
        return
    s = str(raw).strip()
    if not s or "." not in s:
        logger.warning(
            "processed file %s: malformed schema_version %r; reading as v1-compatible",
            path.name,
            raw,
        )
        return
    major, _, _rest = s.partition(".")
    if not major.isdigit():
        logger.warning(
            "processed file %s: malformed schema_version %r; reading as v1-compatible",
            path.name,
            raw,
        )
        return
    mi = int(major)
    if mi <= 2:
        return
    logger.warning(
        "processed file %s: schema_version %s newer than reader (v2); best-effort load",
        path.name,
        s,
    )


def _try_index_entry_from_processed_file(path: Path) -> Optional[ProcessedGameIndexEntry]:
    try:
        with path.open(encoding="utf-8") as f:
            prefix = f.read(_INDEX_PREFIX_CHARS)
    except OSError:
        return None
    g = _game_dict_from_processed_prefix(prefix)
    if g is None:
        return None
    try:
        season = int(g["season"])
        week = int(g["week"])
        home = str(g.get("home_team", "") or "")
        away = str(g.get("away_team", "") or "")
        gid = str(g.get("id") or path.stem)
    except (KeyError, TypeError, ValueError):
        return None
    matchup_label = f"{away} @ {home} — {season} W{week}"
    return ProcessedGameIndexEntry(
        season=season,
        week=week,
        game_id=gid,
        matchup_label=matchup_label,
        path=path.resolve(),
    )


def warehouse_bundle_from_processed_path(path: str | Path) -> Tuple[Game, List[UnifiedReviewRow]]:
    """
    Read one processed JSON file from disk and return the same bundle as
    :func:`warehouse_bundle_from_processed_dict`, plus model-field sanitization for historical rows.
    """
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        p = Path(path).expanduser()
    if not p.is_file():
        msg = f"processed game file does not exist: {p}"
        raise FileNotFoundError(msg)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        msg = f"cannot read processed game file {p}: {e}"
        raise ValueError(msg) from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        msg = (
            f"invalid JSON in processed game file {p.name} (path: {p}): {e}. "
            "Re-run warehouse ingestion for that week (e.g. python -m warehouse.pipeline SEASON WEEK)."
        )
        raise ValueError(msg) from e
    if not isinstance(data, dict):
        msg = (
            f"processed game root must be a JSON object in {p.name} (path: {p}). "
            "Re-run warehouse ingestion for that week."
        )
        raise ValueError(msg)
    _warn_processed_schema_version(data, path=p)
    game, rows = warehouse_bundle_from_processed_dict(data)
    rows = _finalize_warehouse_historical_rows(rows)
    return game, rows


def warehouse_game_to_review_rows(path: str | Path) -> List[UnifiedReviewRow]:
    """Convenience: load from disk and return review rows only (model fields sanitized)."""
    _, rows = warehouse_bundle_from_processed_path(path)
    return rows


def _game_from_processed_dict(raw: dict[str, Any]) -> WarehouseGame:
    g = raw["game"]
    gd = g["game_date"]
    if isinstance(gd, date):
        game_date = gd
    else:
        game_date = date.fromisoformat(str(gd))

    return WarehouseGame(
        id=str(g["id"]),
        source=DataSource(str(g["source"])),
        external_game_id=str(g["external_game_id"]),
        season=int(g["season"]),
        week=int(g["week"]),
        game_type=GameType(str(g["game_type"])),
        home_team=str(g["home_team"]),
        away_team=str(g["away_team"]),
        game_date=game_date,
        status=GameStatus(str(g["status"])),
        final_home_score=int(g["final_home_score"]) if g.get("final_home_score") is not None else None,
        final_away_score=int(g["final_away_score"]) if g.get("final_away_score") is not None else None,
    )


def _play_from_processed_dict(d: dict[str, Any]) -> Play:
    return Play(
        id=str(d["id"]),
        game_id=str(d["game_id"]),
        external_play_id=str(d["external_play_id"]),
        play_sequence=int(d["play_sequence"]),
        quarter=int(d["quarter"]),
        score_offense=int(d["score_offense"]),
        score_defense=int(d["score_defense"]),
        play_type=PlayType(str(d["play_type"])),
        play_result=PlayResult(str(d["play_result"])),
        first_down=bool(d["first_down"]),
        touchdown=bool(d["touchdown"]),
        turnover=bool(d["turnover"]),
        raw_description=str(d.get("raw_description") or ""),
        clock_seconds=int(d["clock_seconds"]) if d.get("clock_seconds") is not None else None,
        possession_team=(str(d["possession_team"]) if d.get("possession_team") is not None else None),
        defense_team=(str(d["defense_team"]) if d.get("defense_team") is not None else None),
        down=int(d["down"]) if d.get("down") is not None else None,
        distance=int(d["distance"]) if d.get("distance") is not None else None,
        yardline_100=int(d["yardline_100"]) if d.get("yardline_100") is not None else None,
        yards_gained=int(d["yards_gained"]) if d.get("yards_gained") is not None else None,
        epa=_float_or_none(d.get("epa")),
        wpa=_float_or_none(d.get("wpa")),
        success=_bool_or_none(d.get("success")),
        shotgun=_bool_or_none(d.get("shotgun")),
        no_huddle=_bool_or_none(d.get("no_huddle")),
        qb_dropback=_bool_or_none(d.get("qb_dropback")),
        defenders_in_box=_int_or_none(d.get("defenders_in_box")),
        offense_personnel=_str_or_none(d.get("offense_personnel")),
        air_yards=_float_or_none(d.get("air_yards")),
        yards_after_catch=_float_or_none(d.get("yards_after_catch")),
        xpass=_float_or_none(d.get("xpass")),
        passer_player_name=_str_or_none(d.get("passer_player_name")),
        receiver_player_name=_str_or_none(d.get("receiver_player_name")),
        rusher_player_name=_str_or_none(d.get("rusher_player_name")),
        pass_length=_str_or_none(d.get("pass_length")),
        pass_location=_str_or_none(d.get("pass_location")),
        run_location=_str_or_none(d.get("run_location")),
        run_gap=_str_or_none(d.get("run_gap")),
    )


def _features_from_processed_dict(d: dict[str, Any]) -> DerivedPlayFeatures:
    return DerivedPlayFeatures(
        play_id=str(d["play_id"]),
        red_zone=bool(d["red_zone"]),
        goal_to_go=bool(d["goal_to_go"]),
        four_down_territory=bool(d["four_down_territory"]),
        two_minute=bool(d["two_minute"]),
        score_diff=int(d["score_diff"]),
        score_diff_bucket=str(d["score_diff_bucket"]),
        field_zone=str(d["field_zone"]),
        distance_bucket=str(d["distance_bucket"]),
        game_script=str(d["game_script"]),
        previous_play_type=(str(d["previous_play_type"]) if d.get("previous_play_type") is not None else None),
        drive_number=int(d["drive_number"]),
    )


def parse_processed_payload(data: dict[str, Any]) -> Tuple[WarehouseGame, List[Play], List[DerivedPlayFeatures]]:
    if not isinstance(data, dict):
        msg = "processed payload must be a dict"
        raise TypeError(msg)
    for key in ("game", "plays", "features"):
        if key not in data:
            msg = f"processed payload missing {key!r}"
            raise KeyError(msg)
    wh_game = _game_from_processed_dict(data)
    plays = [_play_from_processed_dict(p) for p in data["plays"]]
    feats = [_features_from_processed_dict(f) for f in data["features"]]
    if len(plays) != len(feats):
        msg = f"plays/features length mismatch: {len(plays)} plays vs {len(feats)} features"
        raise ValueError(msg)
    return wh_game, plays, feats


def _actual_play_from_warehouse(p: Play) -> ActualPlayResult:
    wr = p.play_result
    wt = p.play_type
    yds = int(p.yards_gained) if p.yards_gained is not None else 0

    play_type = "pass"
    sack = False
    scramble = False
    if wt == PlayType.RUN:
        play_type = "run"
    elif wt == PlayType.PASS:
        play_type = "pass"
    elif wt == PlayType.SACK:
        play_type = "pass"
        sack = True
    elif wt == PlayType.SCRAMBLE:
        play_type = "pass"
        scramble = True
    elif wt in (PlayType.KNEEL, PlayType.SPIKE):
        play_type = "run"
    elif wt == PlayType.TWO_POINT:
        play_type = "two_point"

    turnover = bool(p.turnover)
    turnover_kind = ""
    pass_result = ""
    result_type = ""

    if wr == PlayResult.INTERCEPTION:
        turnover = True
        turnover_kind = "interception"
        pass_result = "intercepted"
        result_type = "interception"
    elif wr == PlayResult.FUMBLE_LOST:
        turnover = True
        turnover_kind = "fumble"
        result_type = "fumble"
    elif wr in (PlayResult.FIELD_GOAL_MADE,):
        result_type = "field_goal"
    elif wr in (PlayResult.FIELD_GOAL_MISSED, PlayResult.FIELD_GOAL_BLOCKED):
        result_type = "field_goal_miss"
    elif wr in _PUNT_PLAY_RESULTS or wt == PlayType.PUNT:
        result_type = "punt"
    elif wr == PlayResult.SACK_TAKEN:
        sack = True
    elif wr in (PlayResult.TOUCHDOWN_RUN, PlayResult.TOUCHDOWN_PASS, PlayResult.TOUCHDOWN_RETURN):
        result_type = "touchdown"

    desc = (p.raw_description or "").strip()
    return ActualPlayResult(
        description=desc,
        yards_gained=yds,
        first_down=bool(p.first_down),
        touchdown=bool(p.touchdown)
        or wr
        in (PlayResult.TOUCHDOWN_RUN, PlayResult.TOUCHDOWN_PASS, PlayResult.TOUCHDOWN_RETURN),
        turnover=turnover,
        turnover_kind=turnover_kind,
        sack=sack,
        scramble=scramble,
        play_type=play_type,
        result_type=result_type,
        pass_result=pass_result,
        external_play_id=str(p.external_play_id) if p.external_play_id else None,
    )


def _end_kind_override_for_last_play(p: Play) -> Optional[str]:
    wr = p.play_result
    wt = p.play_type
    if p.touchdown or wr in (
        PlayResult.TOUCHDOWN_RUN,
        PlayResult.TOUCHDOWN_PASS,
        PlayResult.TOUCHDOWN_RETURN,
    ):
        return DRIVE_END_TOUCHDOWN
    if wt == PlayType.PUNT or wr in _PUNT_PLAY_RESULTS:
        return DRIVE_END_PUNT
    if wr == PlayResult.FIELD_GOAL_MADE:
        return DRIVE_END_FIELD_GOAL
    if wr in (PlayResult.FIELD_GOAL_MISSED, PlayResult.FIELD_GOAL_BLOCKED):
        return DRIVE_END_FIELD_GOAL_MISS
    if wr == PlayResult.INTERCEPTION:
        return DRIVE_END_TURNOVER_INT
    if wr == PlayResult.FUMBLE_LOST:
        return DRIVE_END_TURNOVER_FUMBLE
    return None


def build_playcaller_game_from_warehouse(
    wh_game: WarehouseGame,
    plays: List[Play],
    features: List[DerivedPlayFeatures],
) -> Game:
    by_pid = {f.play_id: f for f in features}
    by_drive: Dict[int, List[Play]] = defaultdict(list)
    for p in plays:
        feat = by_pid.get(p.id)
        if feat is None:
            msg = f"missing DerivedPlayFeatures for play id {p.id!r}"
            raise ValueError(msg)
        by_drive[feat.drive_number].append(p)

    for dn, plist in by_drive.items():
        plist.sort(key=lambda x: x.play_sequence)
        _ = dn

    max_dn = max(by_drive.keys()) if by_drive else 0
    drives = []
    for dn in range(1, max_dn + 1):
        plist = by_drive.get(dn, [])
        if not plist:
            drives.append(
                complete_drive_from_plays([], end_kind_override=DRIVE_END_UNKNOWN),
            )
            continue
        actuals = [_actual_play_from_warehouse(p) for p in plist]
        end_ov = _end_kind_override_for_last_play(plist[-1]) or DRIVE_END_UNKNOWN
        drives.append(complete_drive_from_plays(actuals, end_kind_override=end_ov))

    meta = fresh_session_metadata_dict()
    meta["warehouse_processed"] = True
    meta["warehouse_external_game_id"] = wh_game.external_game_id
    meta["warehouse_season"] = str(wh_game.season)
    meta["warehouse_week"] = str(wh_game.week)
    meta["game_label"] = f"{wh_game.away_team} @ {wh_game.home_team} (nflverse)"

    oh = wh_game.final_home_score
    oa = wh_game.final_away_score
    offense_points = int(oh) if oh is not None else 0
    defense_points = int(oa) if oa is not None else 0

    return Game(
        game_id=str(wh_game.external_game_id or wh_game.id),
        drives=drives,
        offense_points=offense_points,
        defense_points=defense_points,
        possession="offense",
        quarter=1,
        clock_seconds_remaining=None,
        recommendation_audit=[],
        session_metadata=meta,
    )


def warehouse_bundle_from_processed_dict(
    data: dict[str, Any],
) -> Tuple[Game, List[UnifiedReviewRow]]:
    wh_game, plays, feats = parse_processed_payload(data)
    pc_game = build_playcaller_game_from_warehouse(wh_game, plays, feats)
    rows = to_review_rows(plays, feats, wh_game)
    return pc_game, rows


def print_processed_inventory_summary(
    root: str | Path | None = None,
    *,
    file: TextIO | None = None,
) -> int:
    """Print processed games (matchup label + path) for CLI smoke checks.

    When *root* is omitted, uses :func:`warehouse.storage.processed_data_dir` (same
    tree Review Session targets under the repo root).

    Returns the number of indexed games (0 if the root is missing or empty).
    """
    sink = file if file is not None else sys.stdout
    root_p = Path(root).expanduser() if root is not None else processed_data_dir()
    resolved = root_p.resolve()
    entries = list_available_processed_games(root_p)
    print(f"Processed games root: {resolved}", file=sink)
    if not entries:
        print(
            "No processed games found — Review Session (Warehouse processed JSON) will have no dropdown options.",
            file=sink,
        )
        return 0
    print(
        f"Found {len(entries)} game(s) — Review Session should list this many options in the dropdown.\n",
        file=sink,
    )
    for e in entries:
        print(f"  {e.matchup_label}", file=sink)
        print(f"    {e.path}", file=sink)
    return len(entries)


def _cli_main() -> None:
    print_processed_inventory_summary()


if __name__ == "__main__":
    _cli_main()
