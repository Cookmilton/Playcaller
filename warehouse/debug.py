from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from warehouse.features import compute_features as compute_play_features
from warehouse.models import DataSource, DerivedPlayFeatures, Game, GameStatus, GameType, Play
from warehouse.normalize import normalize_game
from warehouse.storage import REPO_ROOT, _make_game_id, _read_payload_from_path, _raw_root
from warehouse.taxonomy import PlayResult, PlayType
from warehouse.validation import ValidationIssue, validate_play_sequence

_DIV = "=" * 60


def _processed_root() -> Path:
    return REPO_ROOT / "data" / "processed"


def _find_processed_payload(game_ref: str) -> dict[str, Any] | None:
    root = _processed_root()
    if not root.is_dir():
        return None
    for path in sorted(root.rglob("*.json")):
        if path.stem == game_ref:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    for path in sorted(root.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        g = data.get("game")
        if not isinstance(g, dict):
            continue
        if str(g.get("id", "")) == game_ref or str(g.get("external_game_id", "")) == game_ref:
            return data
    return None


def _find_raw_game_dict(game_ref: str) -> dict[str, Any] | None:
    for path in sorted(_raw_root().rglob("*.json")):
        if path.stem == game_ref:
            rec2 = _read_payload_from_path(path)
            if rec2 is not None:
                return json.loads(rec2.payload_json)
    for path in sorted(_raw_root().rglob("*.json")):
        rec3 = _read_payload_from_path(path)
        if rec3 is None:
            continue
        try:
            body = json.loads(rec3.payload_json)
        except json.JSONDecodeError:
            continue
        meta = body.get("meta") or {}
        if str(meta.get("external_game_id", "")) == game_ref or _make_game_id(meta) == game_ref:
            return body
    return None


def _parse_game(d: dict[str, Any]) -> Game:
    gd = d.get("game_date")
    if isinstance(gd, str):
        gdate = date.fromisoformat(gd[:10])
    else:
        gdate = date(1900, 1, 1)
    return Game(
        id=str(d["id"]),
        source=DataSource(str(d["source"])),
        external_game_id=str(d.get("external_game_id", "")),
        season=int(d["season"]),
        week=int(d["week"]),
        game_type=GameType(str(d["game_type"])),
        home_team=str(d.get("home_team", "") or ""),
        away_team=str(d.get("away_team", "") or ""),
        game_date=gdate,
        status=GameStatus(str(d.get("status", "FINAL"))),
        final_home_score=_opt_int(d.get("final_home_score")),
        final_away_score=_opt_int(d.get("final_away_score")),
    )


def _opt_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_play(d: dict[str, Any]) -> Play:
    from warehouse.normalize import _bool_or_none, _float_or_none, _str_or_none

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
        first_down=bool(d.get("first_down", False)),
        touchdown=bool(d.get("touchdown", False)),
        turnover=bool(d.get("turnover", False)),
        raw_description=str(d.get("raw_description", "") or ""),
        clock_seconds=_opt_int(d.get("clock_seconds")),
        possession_team=d.get("possession_team"),
        defense_team=d.get("defense_team"),
        down=_opt_int(d.get("down")),
        distance=_opt_int(d.get("distance")),
        yardline_100=_opt_int(d.get("yardline_100")),
        yards_gained=_opt_int(d.get("yards_gained")),
        epa=_float_or_none(d.get("epa")),
        wpa=_float_or_none(d.get("wpa")),
        success=_bool_or_none(d.get("success")),
        shotgun=_bool_or_none(d.get("shotgun")),
        no_huddle=_bool_or_none(d.get("no_huddle")),
        qb_dropback=_bool_or_none(d.get("qb_dropback")),
        defenders_in_box=_opt_int(d.get("defenders_in_box")),
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


def _parse_feature(d: dict[str, Any]) -> DerivedPlayFeatures:
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
        previous_play_type=d.get("previous_play_type"),
        drive_number=int(d["drive_number"]),
    )


def _load_bundle(game_ref: str) -> tuple[Game, list[Play], list[DerivedPlayFeatures]] | None:
    proc = _find_processed_payload(game_ref)
    if proc is not None:
        g = _parse_game(proc["game"])
        plays = [_parse_play(x) for x in proc.get("plays") or []]
        feats = [_parse_feature(x) for x in proc.get("features") or []]
        return g, plays, feats

    raw = _find_raw_game_dict(game_ref)
    if raw is None:
        return None
    game, plays = normalize_game(raw)
    feats = compute_play_features(plays, game=game)
    return game, plays, feats


def _away_home_tuple(play: Play, game: Game) -> tuple[int, int]:
    po = play.possession_team
    if po == game.home_team:
        return int(play.score_defense), int(play.score_offense)
    if po == game.away_team:
        return int(play.score_offense), int(play.score_defense)
    return 0, 0


def _final_away_home(game: Game, plays: list[Play]) -> tuple[int, int]:
    if game.final_home_score is not None and game.final_away_score is not None:
        return int(game.final_away_score), int(game.final_home_score)
    if plays:
        return _away_home_tuple(plays[-1], game)
    return 0, 0


def _format_clock(clock_seconds: int | None) -> str:
    if clock_seconds is None:
        return "-"
    cs = int(clock_seconds)
    if cs < 0:
        return "-"
    m, s = divmod(cs, 60)
    return f"{m}:{s:02d}"


def _format_play_row(p: Play) -> str:
    desc = (p.raw_description or "").replace("\n", " ")
    if len(desc) > 52:
        desc = desc[:49] + "..."
    return (
        f"{p.play_sequence:>4}  "
        f"{p.quarter:>3}  "
        f"{_format_clock(p.clock_seconds):>5}  "
        f"{(str(p.down) if p.down is not None else '-'):>4}  "
        f"{(str(p.distance) if p.distance is not None else '-'):>4}  "
        f"{(str(p.yardline_100) if p.yardline_100 is not None else '-'):>3}  "
        f"{(p.possession_team or '-'):>4}  "
        f"{desc}"
    )


def _issue_play_seq(issue: ValidationIssue, plays: list[Play]) -> str:
    if issue.play_id is None:
        return "—"
    pid = str(issue.play_id)
    for p in plays:
        if p.external_play_id == pid or p.id == pid:
            return str(p.play_sequence)
    return pid


def _severity_tag(severity: str) -> str:
    s = severity.lower()
    if s == "warning":
        label = "WARN"
    else:
        label = s.upper()
    return f"[{label:<5}]"


def _print_validation(issues: list[ValidationIssue], plays: list[Play]) -> None:
    print(f"=== VALIDATION ({len(issues)} issues) ===")
    if not issues:
        print("(none)")
        return
    for issue in issues:
        seq = _issue_play_seq(issue, plays)
        print(
            f"{_severity_tag(issue.severity)} play_seq={seq} "
            f"rule={issue.rule}: {issue.message}"
        )


def _print_play_table(title: str, rows: list[Play]) -> None:
    print(title)
    print(" seq  qtr  clock  down  dist  yln  poss  desc")
    for p in rows:
        print(_format_play_row(p))


def _print_score_progression(game: Game, plays: list[Play]) -> None:
    print("=== SCORE PROGRESSION ===")
    if not plays:
        print("(no plays)")
        return
    prev: tuple[int, int] | None = None
    any_line = False
    for p in plays:
        cur = _away_home_tuple(p, game)
        if prev is None:
            prev = cur
            continue
        if cur != prev:
            any_line = True
            away, home = cur
            paway, phome = prev
            desc = (p.raw_description or "").replace("\n", " ")
            if len(desc) > 70:
                desc = desc[:67] + "..."
            print(
                f"  qtr {p.quarter}: {paway}-{phome} -> {away}-{home} "
                f"({desc})"
            )
        prev = cur
    if not any_line:
        print("(no score changes between plays in normalized totals)")


def _print_features_sample(features: list[DerivedPlayFeatures], plays: list[Play], n: int) -> None:
    print("=== FEATURES (first rows) ===")
    if not features:
        print("(none)")
        return
    by_pid = {f.play_id: f for f in features}
    head_plays = plays[:n]
    print(" play_id   drive  red_zone  g2g  script          diff_bucket")
    for p in head_plays:
        f = by_pid.get(p.id)
        if f is None:
            continue
        print(
            f" {p.id[:12]:12} {f.drive_number:>5}  "
            f"{str(f.red_zone):>8}  {str(f.goal_to_go):>3}  "
            f"{f.game_script:<14}  {f.score_diff_bucket}"
        )


def run_single_game_debug(
    game_id: str,
    *,
    show_features: bool = True,
    show_validation: bool = True,
    head: int = 10,
    tail: int = 10,
) -> None:
    bundle = _load_bundle(game_id)
    if bundle is None:
        print("Game not found — no matching processed JSON under data/processed/")
        print("and no matching raw game under data/raw/.")
        return

    game, plays, features = bundle
    issues: list[ValidationIssue] = []
    if show_validation:
        report = validate_play_sequence(game, plays)
        issues = list(report.issues)

    away, home = _final_away_home(game, plays)
    print(_DIV)
    print("=== MATCHUP ===")
    print(
        f"{game.away_team} @ {game.home_team} — Season {game.season} "
        f"Week {game.week} — {game.game_date.isoformat()}"
    )
    print(f"Final (reconstructed): away {away} — home {home}")
    print(f"Total plays: {len(plays)}")
    print(_DIV)

    if show_validation:
        _print_validation(issues, plays)
        print(_DIV)

    h = max(0, head)
    t = max(0, tail)
    if plays and h > 0:
        _print_play_table(f"=== FIRST {min(h, len(plays))} PLAYS ===", plays[:h])
        print(_DIV)
        if t > 0 and len(plays) > h:
            tail_rows = plays[-t:]
            _print_play_table(f"=== LAST {len(tail_rows)} PLAYS ===", tail_rows)
            print(_DIV)
    elif plays and h == 0:
        print("=== FIRST 0 PLAYS ===")
        print("(skipped — head=0)")
        print(_DIV)

    _print_score_progression(game, plays)
    print(_DIV)

    if show_features and features:
        _print_features_sample(features, plays, max(h, 1))
        print(_DIV)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Debug one warehouse game (processed or raw).")
    parser.add_argument("game_id", help="Internal game id, or external_game_id to search.")
    parser.add_argument("--no-features", action="store_true")
    parser.add_argument("--no-validation", action="store_true")
    parser.add_argument("--head", type=int, default=10)
    parser.add_argument("--tail", type=int, default=10)
    args = parser.parse_args()
    run_single_game_debug(
        args.game_id,
        show_features=not args.no_features,
        show_validation=not args.no_validation,
        head=args.head,
        tail=args.tail,
    )


if __name__ == "__main__":
    _main()
