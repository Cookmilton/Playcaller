from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from warehouse.models import (
    DataSource,
    DerivedPlayFeatures,
    Game,
    GameStatus,
    GameType,
    Play,
    RawGamePayload,
)
from warehouse.taxonomy import PlayResult, PlayType


def test_game_smoke() -> None:
    g = Game(
        id="g1",
        source=DataSource.NFLVERSE,
        external_game_id="ext-1",
        season=2024,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2024, 9, 5),
        status=GameStatus.SCHEDULED,
    )
    assert g.home_team == "KC"
    assert g.final_home_score is None


def test_raw_game_payload_json_roundtrip() -> None:
    fetched = datetime(2024, 9, 1, 12, 0, tzinfo=timezone.utc)
    raw = RawGamePayload(
        id="r1",
        game_id="g1",
        source=DataSource.MANUAL,
        fetched_at=fetched,
        payload_json='{"x": 1}',
    )
    d = raw.to_dict()
    blob = json.dumps(d)
    restored = RawGamePayload.from_dict(json.loads(blob))
    assert restored == raw


def test_raw_game_payload_from_dict_accepts_datetime_instance() -> None:
    fetched = datetime(2024, 9, 1, 12, 0, tzinfo=timezone.utc)
    raw = RawGamePayload.from_dict(
        {
            "id": "r2",
            "game_id": "g1",
            "source": "NFLVERSE",
            "fetched_at": fetched,
            "payload_json": "{}",
        }
    )
    assert raw.source is DataSource.NFLVERSE
    assert raw.fetched_at == fetched


def test_play_smoke_and_validation() -> None:
    p = Play(
        id="p1",
        game_id="g1",
        external_play_id="ep1",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="(15:00) 1-10-KC 25",
        yardline_100=75,
        down=1,
    )
    assert p.yardline_100 == 75

    with pytest.raises(ValueError, match="quarter"):
        Play(
            id="p2",
            game_id="g1",
            external_play_id="ep2",
            play_sequence=2,
            quarter=6,
            score_offense=0,
            score_defense=0,
            play_type=PlayType.PASS,
            play_result=PlayResult.INCOMPLETE,
            first_down=False,
            touchdown=False,
            turnover=False,
            raw_description="bad q",
        )

    with pytest.raises(ValueError, match="yardline"):
        Play(
            id="p3",
            game_id="g1",
            external_play_id="ep3",
            play_sequence=3,
            quarter=1,
            score_offense=0,
            score_defense=0,
            play_type=PlayType.RUN,
            play_result=PlayResult.RUSH_LOSS,
            first_down=False,
            touchdown=False,
            turnover=False,
            raw_description="bad yl",
            yardline_100=101,
        )

    with pytest.raises(ValueError, match="down"):
        Play(
            id="p4",
            game_id="g1",
            external_play_id="ep4",
            play_sequence=4,
            quarter=1,
            score_offense=0,
            score_defense=0,
            play_type=PlayType.PUNT,
            play_result=PlayResult.PUNT_FAIR_CATCH,
            first_down=False,
            touchdown=False,
            turnover=False,
            raw_description="bad down",
            down=5,
        )


def test_derived_play_features_smoke() -> None:
    f = DerivedPlayFeatures(
        play_id="p1",
        red_zone=False,
        goal_to_go=False,
        four_down_territory=False,
        two_minute=False,
        score_diff=0,
        score_diff_bucket="tied",
        field_zone="own",
        distance_bucket="medium",
        game_script="neutral",
        drive_number=1,
        previous_play_type=None,
    )
    assert f.previous_play_type is None
