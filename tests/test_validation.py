from __future__ import annotations

from datetime import date

from warehouse.models import DataSource, Game, GameStatus, GameType, Play
from warehouse.taxonomy import PlayResult, PlayType
from warehouse.validation import validate_play_sequence


def _play(**kwargs: object) -> Play:
    defaults: dict[str, object] = {
        "id": "aaaaaaaaaaaaaaaa",
        "game_id": "gameidgameidgame",
        "external_play_id": "1",
        "play_sequence": 1,
        "quarter": 1,
        "score_offense": 0,
        "score_defense": 0,
        "play_type": PlayType.PASS,
        "play_result": PlayResult.COMPLETE,
        "first_down": False,
        "touchdown": False,
        "turnover": False,
        "raw_description": "test play",
        "clock_seconds": 900,
        "possession_team": "BUF",
        "defense_team": "KC",
        "down": 1,
        "distance": 10,
        "yardline_100": 50,
        "yards_gained": 0,
    }
    defaults.update(kwargs)
    return Play(**defaults)


def _sample_game() -> Game:
    return Game(
        id="gameidgameidgame",
        source=DataSource.NFLVERSE,
        external_game_id="2025_01_BUF_KC",
        season=2025,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2025, 9, 5),
        status=GameStatus.IN_PROGRESS,
    )


def test_illegal_score_jump_single_error() -> None:
    """Play 2 increases total score without a scoring event — one score_only error."""
    plays = [
        _play(
            id="1111111111111111",
            external_play_id="1",
            play_sequence=1,
            score_offense=0,
            score_defense=0,
            clock_seconds=900,
        ),
        _play(
            id="2222222222222222",
            external_play_id="2",
            play_sequence=2,
            score_offense=7,
            score_defense=0,
            clock_seconds=880,
            touchdown=False,
            play_result=PlayResult.INCOMPLETE,
        ),
        _play(
            id="3333333333333333",
            external_play_id="3",
            play_sequence=3,
            score_offense=7,
            score_defense=0,
            clock_seconds=860,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    err = [i for i in report.issues if i.severity == "error"]
    assert len(err) == 1
    assert err[0].rule == "score_only_on_scoring_play"
    assert err[0].play_id == "2"


def test_clean_sequence_no_errors() -> None:
    plays = [
        _play(
            id="1111111111111111",
            external_play_id="1",
            play_sequence=1,
            score_offense=0,
            score_defense=0,
            clock_seconds=900,
        ),
        _play(
            id="2222222222222222",
            external_play_id="2",
            play_sequence=2,
            score_offense=7,
            score_defense=0,
            clock_seconds=880,
            touchdown=True,
            play_result=PlayResult.TOUCHDOWN_PASS,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert report.valid
    assert not any(i.severity == "error" for i in report.issues)
