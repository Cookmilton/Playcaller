"""Schema v2: optional Play fields + ``schema_version`` on processed JSON."""

from __future__ import annotations

from pathlib import Path

import pytest

from warehouse.normalize import normalize_game
from warehouse.review_loader import (
    _warn_processed_schema_version,
    parse_processed_payload,
    processed_schema_version,
    warehouse_bundle_from_processed_dict,
)


def _minimal_meta() -> dict:
    return {
        "external_game_id": "2025_01_AA_BB",
        "season": 2025,
        "week": 1,
        "game_type": "REG",
        "home_team": "KC",
        "away_team": "BUF",
        "game_date": "2025-09-05",
    }


def _base_row() -> dict:
    return {
        "play_id": 1.0,
        "qtr": 1,
        "quarter_seconds_remaining": 900,
        "posteam": "BUF",
        "defteam": "KC",
        "down": 1,
        "ydstogo": 10,
        "yardline_100": 75,
        "posteam_score": 0,
        "defteam_score": 0,
        "play_type": "pass",
        "yards_gained": 5,
        "desc": "test snap",
        "touchdown": 0.0,
        "interception": 0.0,
        "fumble_lost": 0.0,
        "home_score": 0,
        "away_score": 0,
    }


_POPULATED = [
    ("epa", "epa", 0.25, 0.25),
    ("wpa", "wpa", -0.01, -0.01),
    ("success", "success", 1.0, True),
    ("shotgun", "shotgun", 1.0, True),
    ("no_huddle", "no_huddle", 0.0, False),
    ("qb_dropback", "qb_dropback", 1.0, True),
    ("defenders_in_box", "defenders_in_box", 7, 7),
    ("offense_personnel", "offense_personnel", "1 RB, 1 TE, 3 WR", "1 RB, 1 TE, 3 WR"),
    ("air_yards", "air_yards", 8.5, 8.5),
    ("yards_after_catch", "yards_after_catch", 3.0, 3.0),
    ("xpass", "xpass", 0.62, 0.62),
    ("passer_player_name", "passer_player_name", "J.Allen", "J.Allen"),
    ("receiver_player_name", "receiver_player_name", "S.Diggs", "S.Diggs"),
    ("rusher_player_name", "rusher_player_name", "J.Allen", "J.Allen"),
    ("pass_length", "pass_length", "short", "short"),
    ("pass_location", "pass_location", "middle", "middle"),
    ("run_location", "run_location", "left", "left"),
    ("run_gap", "run_gap", "end", "end"),
]


@pytest.mark.parametrize("attr,nfl_key,raw,expected", _POPULATED)
def test_normalize_maps_optional_field_populated(
    attr: str,
    nfl_key: str,
    raw: object,
    expected: object,
) -> None:
    row = {**_base_row(), nfl_key: raw}
    _g, plays = normalize_game({"meta": _minimal_meta(), "plays": [row]})
    assert len(plays) == 1
    assert getattr(plays[0], attr) == expected


@pytest.mark.parametrize("attr,nfl_key", [(a, b) for a, b, _, _ in _POPULATED])
def test_normalize_optional_field_none_when_absent(attr: str, nfl_key: str) -> None:
    row = {**_base_row()}
    assert nfl_key not in row
    _g, plays = normalize_game({"meta": _minimal_meta(), "plays": [row]})
    assert getattr(plays[0], attr) is None


def test_normalize_optional_float_none_when_nan() -> None:
    row = {**_base_row(), "epa": float("nan")}
    _g, plays = normalize_game({"meta": _minimal_meta(), "plays": [row]})
    assert plays[0].epa is None


def test_processed_schema_version_missing_is_1_0() -> None:
    assert processed_schema_version({"game": {}}) == "1.0"


def test_processed_schema_version_present() -> None:
    assert processed_schema_version({"schema_version": "2.0"}) == "2.0"


def test_v1_payload_loads_new_fields_default_none() -> None:
    """Legacy processed JSON without ``schema_version`` or new Play keys."""
    payload = {
        "game": {
            "id": "v1",
            "source": "NFLVERSE",
            "external_game_id": "x",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2025-09-05",
            "status": "FINAL",
            "final_home_score": 7,
            "final_away_score": 7,
        },
        "plays": [
            {
                "id": "p1",
                "game_id": "v1",
                "external_play_id": "1",
                "play_sequence": 1,
                "quarter": 1,
                "score_offense": 0,
                "score_defense": 0,
                "play_type": "RUN",
                "play_result": "RUSH_GAIN",
                "first_down": True,
                "touchdown": False,
                "turnover": False,
                "raw_description": "run",
                "clock_seconds": 900,
                "possession_team": None,
                "defense_team": None,
                "down": 1,
                "distance": 10,
                "yardline_100": 70,
                "yards_gained": 4,
            },
        ],
        "features": [
            {
                "play_id": "p1",
                "red_zone": False,
                "goal_to_go": False,
                "four_down_territory": False,
                "two_minute": False,
                "score_diff": 0,
                "score_diff_bucket": "tied",
                "field_zone": "own",
                "distance_bucket": "medium",
                "game_script": "neutral",
                "previous_play_type": None,
                "drive_number": 1,
            },
        ],
    }
    assert processed_schema_version(payload) == "1.0"
    _wh, plays, _feats = parse_processed_payload(payload)
    assert plays[0].epa is None and plays[0].passer_player_name is None
    _g, rows = warehouse_bundle_from_processed_dict(payload)
    assert rows
    assert len(rows) == 1


def test_schema_v3_warns_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs: list[str] = []
    import warehouse.review_loader as rl

    def _cap(msg: str, *args: object, **kwargs: object) -> None:
        msgs.append(msg % args if args else msg)

    monkeypatch.setattr(rl.logger, "warning", _cap)
    _warn_processed_schema_version({"schema_version": "3.0"}, path=Path("fixture.json"))
    assert any("newer than reader" in m for m in msgs)


def test_schema_malformed_warns_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    msgs: list[str] = []
    import warehouse.review_loader as rl

    def _cap(msg: str, *args: object, **kwargs: object) -> None:
        msgs.append(msg % args if args else msg)

    monkeypatch.setattr(rl.logger, "warning", _cap)
    _warn_processed_schema_version({"schema_version": "not_a_dotted"}, path=Path("fixture.json"))
    assert any("malformed schema_version" in m for m in msgs)
