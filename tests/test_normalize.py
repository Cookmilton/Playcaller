from __future__ import annotations

import math

from warehouse.models import GameStatus, GameType
from warehouse.normalize import _int_or_none, _ordered_rows, normalize_game


def test_int_or_none() -> None:
    assert _int_or_none(None) is None
    assert _int_or_none("") is None
    assert _int_or_none(float("nan")) is None
    assert _int_or_none(3.7) == 3
    assert _int_or_none("12") == 12
    assert _int_or_none(True) is None


def test_normalize_game_smoke() -> None:
    payload = {
        "meta": {
            "external_game_id": "2025_01_AA_BB",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2025-09-05",
        },
        "plays": [
            {
                "play_id": 1.0,
                "qtr": 1,
                "quarter_seconds_remaining": 900,
                "posteam": "BUF",
                "defteam": "KC",
                "down": 1.0,
                "ydstogo": 10,
                "yardline_100": 75,
                "posteam_score": 0,
                "defteam_score": 0,
                "play_type": "pass",
                "yards_gained": 12,
                "first_down_pass": 1.0,
                "touchdown": 0.0,
                "interception": 0.0,
                "fumble_lost": 0.0,
                "desc": "(15:00) (Shotgun) J.Allen pass short right for 12 yards",
                "home_score": 0,
                "away_score": 0,
                "result": math.nan,
            },
            {
                "play_id": 2.0,
                "qtr": 1,
                "quarter_seconds_remaining": 860,
                "posteam": "BUF",
                "defteam": "KC",
                "down": 1.0,
                "ydstogo": 10,
                "yardline_100": 63,
                "posteam_score": 0,
                "defteam_score": 0,
                "play_type": "pass",
                "sack": 1.0,
                "desc": "J.Allen sacked at KC 40 for -8 yards",
                "home_score": 7,
                "away_score": 24,
                "result": "BUF @ KC",
            },
        ],
    }
    game, plays = normalize_game(payload)
    assert game.id
    assert game.game_type is GameType.REG
    assert game.status is GameStatus.FINAL
    assert len(plays) == 2
    assert plays[0].play_sequence == 1
    assert plays[0].yards_gained == 12
    assert plays[1].play_type.name == "SACK"


def test_ordered_rows_resorts_when_play_ids_not_increasing() -> None:
    plays = [
        {"play_id": 3.0, "qtr": 1, "quarter_seconds_remaining": 100, "play_type": "run", "desc": "b"},
        {"play_id": 1.0, "qtr": 1, "quarter_seconds_remaining": 200, "play_type": "run", "desc": "a"},
    ]
    rows = _ordered_rows(plays)
    assert [r["play_id"] for r in rows] == [1.0, 3.0]


def test_skip_empty_play_type_and_desc() -> None:
    plays = [
        {"play_type": None, "desc": ""},
        {"play_id": 1.0, "play_type": "run", "desc": "rush"},
    ]
    rows = _ordered_rows(plays)
    assert len(rows) == 1
