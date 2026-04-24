from __future__ import annotations

from collections import Counter
from datetime import date

from warehouse.models import DataSource, Game, GameStatus, GameType, Play
from warehouse.quality import check_quality
from warehouse.taxonomy import PlayResult, PlayType


def test_unexplained_score_jump_and_yardline_out_of_range_fire_once_each() -> None:
    game = Game(
        id="g-quality-1",
        source=DataSource.NFLVERSE,
        external_game_id="ext-q1",
        season=2024,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2024, 9, 5),
        status=GameStatus.FINAL,
    )
    p1 = Play(
        id="p1",
        game_id="g-quality-1",
        external_play_id="1",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="first down run",
        down=1,
        distance=10,
        yardline_100=50,
        possession_team="BUF",
        defense_team="KC",
    )
    p2 = Play(
        id="p2",
        game_id="g-quality-1",
        external_play_id="2",
        play_sequence=2,
        quarter=1,
        score_offense=10,
        score_defense=0,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="mystery ten point jump",
        down=1,
        distance=10,
        yardline_100=50,
        possession_team="BUF",
        defense_team="KC",
    )
    p2.yardline_100 = 101

    issues = check_quality(game, [p1, p2])
    counts = Counter(i.rule for i in issues)
    assert counts["unexplained_score_jump"] == 1
    assert counts["yardline_out_of_range"] == 1
    assert sum(counts.values()) == 2
