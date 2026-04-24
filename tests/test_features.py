from __future__ import annotations

from datetime import date

from warehouse.features import compute_features
from warehouse.models import DataSource, Game, GameStatus, GameType, Play
from warehouse.taxonomy import PlayResult, PlayType


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
        "raw_description": "",
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


def _game() -> Game:
    return Game(
        id="gameidgameidgame",
        source=DataSource.NFLVERSE,
        external_game_id="x",
        season=2025,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2025, 9, 5),
        status=GameStatus.IN_PROGRESS,
    )


def test_drive_number_non_decreasing() -> None:
    """Drive index never decreases along the play list."""
    g = _game()
    plays = [
        _play(id="01" * 8, external_play_id="1", play_sequence=1, play_type=PlayType.KICKOFF),
        _play(
            id="02" * 8,
            external_play_id="2",
            play_sequence=2,
            play_type=PlayType.RUN,
            possession_team="KC",
        ),
        _play(id="03" * 8, external_play_id="3", play_sequence=3, play_type=PlayType.RUN),
        _play(
            id="04" * 8,
            external_play_id="4",
            play_sequence=4,
            play_type=PlayType.PASS,
            touchdown=True,
            play_result=PlayResult.TOUCHDOWN_PASS,
        ),
        _play(
            id="05" * 8,
            external_play_id="5",
            play_sequence=5,
            play_type=PlayType.EXTRA_POINT,
            play_result=PlayResult.EXTRA_POINT_MADE,
        ),
    ]
    feats = compute_features(plays, game=g)
    drives = [f.drive_number for f in feats]
    assert len(drives) == len(plays)
    assert all(drives[i] <= drives[i + 1] for i in range(len(drives) - 1))
    assert drives[-1] >= drives[0]


def test_previous_play_type_resets_on_new_drive() -> None:
    g = _game()
    plays = [
        _play(id="a1" * 8, external_play_id="1", play_sequence=1),
        _play(id="a2" * 8, external_play_id="2", play_sequence=2, play_type=PlayType.RUN),
        _play(
            id="a3" * 8,
            external_play_id="3",
            play_sequence=3,
            play_type=PlayType.PUNT,
            possession_team="KC",
        ),
        _play(
            id="a4" * 8,
            external_play_id="4",
            play_sequence=4,
            play_type=PlayType.RUN,
            possession_team="BUF",
        ),
    ]
    feats = compute_features(plays, game=g)
    assert feats[0].previous_play_type is None
    assert feats[1].previous_play_type == "PASS"
    assert feats[3].previous_play_type is None


def test_score_diff_bucket_boundaries() -> None:
    g = _game()
    p = _play(
        id="b1" * 8,
        score_offense=10,
        score_defense=27,
    )
    feats = compute_features([p], game=g)
    assert feats[0].score_diff == -17
    assert feats[0].score_diff_bucket == "blowout_trail"

    p2 = _play(
        id="b2" * 8,
        score_offense=10,
        score_defense=26,
    )
    assert compute_features([p2], game=g)[0].score_diff_bucket == "trail"


def test_field_zone_and_red_zone() -> None:
    g = _game()
    deep = _play(id="c1" * 8, yardline_100=90)
    assert compute_features([deep], game=g)[0].field_zone == "own_deep"
    rz = _play(id="c2" * 8, yardline_100=15)
    f = compute_features([rz], game=g)[0]
    assert f.field_zone == "red_zone"
    assert f.red_zone is True


def test_distance_bucket_na() -> None:
    g = _game()
    p = _play(id="d1" * 8, distance=None)
    assert compute_features([p], game=g)[0].distance_bucket == "na"
