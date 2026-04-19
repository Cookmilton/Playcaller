"""ESPN game summary parser — intermediate representation only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_history_warehouse.parsers.espn_summary import (
    SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1,
    EspnSummaryParserError,
    parse_espn_game_summary,
    parse_espn_game_summary_json_file,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def test_parse_synthetic_fixture_structure() -> None:
    result = parse_espn_game_summary_json_file(FIXTURE)
    g = result.game
    assert g.source_format == SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1
    assert g.source_event_id == "401test001"
    assert len(g.teams) == 2
    home = next(t for t in g.teams if t.home_away == "home")
    away = next(t for t in g.teams if t.home_away == "away")
    assert home.abbreviation == "NYG"
    assert away.abbreviation == "LAR"
    assert home.score == 14
    assert away.score == 10
    assert g.broadcast is not None
    assert g.broadcast.period == 3
    assert len(g.drives) >= 2
    assert g.drives[0].source_drive_id == "401test001d1"
    assert g.drives[0].offense_espn_team_id == "10"
    assert len(g.drives[0].plays) == 3
    p0 = g.drives[0].plays[0]
    assert p0.source_play_id == "401test001x1"
    assert p0.play_type_text == "Rush"
    assert p0.stat_yardage == 4
    assert p0.raw_play.get("text") == "(14:22) 4 Yd Rush"
    # current drive merged
    assert any(d.source_drive_id == "__current__" for d in g.drives)
    codes = {n.code for n in result.notices}
    assert "current_drive_missing_team" in codes


def test_parse_minimal_valid_payload() -> None:
    payload = {
        "header": {
            "competitions": [
                {
                    "id": "g1",
                    "competitors": [
                        {
                            "id": "1",
                            "homeAway": "home",
                            "score": "0",
                            "team": {"abbreviation": "AAA", "displayName": "A"},
                        },
                        {
                            "id": "2",
                            "homeAway": "away",
                            "score": "0",
                            "team": {"abbreviation": "BBB", "displayName": "B"},
                        },
                    ],
                }
            ]
        },
        "drives": {"previous": []},
    }
    r = parse_espn_game_summary(payload)
    assert r.game.source_event_id == "g1"
    assert len(r.game.drives) == 0


def test_missing_competition_raises() -> None:
    with pytest.raises(EspnSummaryParserError) as ei:
        parse_espn_game_summary({"header": {"competitions": []}})
    assert ei.value.code == "missing_competition"


def test_missing_teams_raises() -> None:
    with pytest.raises(EspnSummaryParserError) as ei:
        parse_espn_game_summary(
            {
                "header": {
                    "competitions": [
                        {
                            "id": "x",
                            "competitors": [
                                {"id": "1", "homeAway": "home", "team": {"abbreviation": "A"}},
                            ],
                        }
                    ]
                }
            }
        )
    assert ei.value.code == "missing_teams"


def test_play_missing_id_emits_notice() -> None:
    payload = {
        "header": {
            "competitions": [
                {
                    "id": "g1",
                    "competitors": [
                        {
                            "id": "1",
                            "homeAway": "home",
                            "score": "0",
                            "team": {"abbreviation": "A"},
                        },
                        {
                            "id": "2",
                            "homeAway": "away",
                            "score": "0",
                            "team": {"abbreviation": "B"},
                        },
                    ],
                }
            ]
        },
        "drives": {
            "previous": [
                {
                    "id": "d1",
                    "team": {"id": "1"},
                    "plays": [{"type": {"text": "Rush"}, "text": "run", "statYardage": 3}],
                }
            ]
        },
    }
    r = parse_espn_game_summary(payload)
    assert len(r.game.drives[0].plays) == 0
    assert any(n.code == "play_missing_id" for n in r.notices)


def test_fixture_path_read_bytes_roundtrip() -> None:
    data = FIXTURE.read_bytes()
    from football_history_warehouse.parsers.espn_summary.parse import parse_espn_game_summary_json_bytes

    r1 = parse_espn_game_summary_json_bytes(data)
    r2 = parse_espn_game_summary(json.loads(data.decode("utf-8")))
    assert r1.game.source_event_id == r2.game.source_event_id
