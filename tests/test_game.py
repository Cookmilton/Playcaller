"""Game / drive aggregation and drive-end classification."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    Game,
    apply_scoring_after_drive,
    classify_drive_end,
    complete_drive_from_plays,
    flip_possession_after_drive,
    game_from_json,
    game_to_json,
)


def test_classify_touchdown_from_last_play() -> None:
    plays = [
        ActualPlayResult(yards_gained=5, family="inside_zone", play_type="run"),
        ActualPlayResult(yards_gained=10, family="quick_game", play_type="pass", touchdown=True),
    ]
    r = classify_drive_end(plays, last_snap_touchdown=True)
    assert r.kind == DRIVE_END_TOUCHDOWN
    assert r.headline == "Touchdown"
    assert "2 plays" in r.detail_line


def test_classify_interception() -> None:
    plays = [
        ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run"),
        ActualPlayResult(
            yards_gained=0,
            family="dropback_pass",
            play_type="pass",
            result_type="interception",
            pass_result="intercepted",
            turnover_kind="interception",
        ),
    ]
    r = classify_drive_end(plays)
    assert r.kind == DRIVE_END_TURNOVER_INT
    assert r.headline == "Interception"


def test_classify_turnover_on_downs_from_snap() -> None:
    plays = [
        ActualPlayResult(yards_gained=2, family="inside_zone", play_type="run", result_type="short"),
    ]
    r = classify_drive_end(plays, last_snap_turnover_on_downs=True)
    assert r.kind == DRIVE_END_TURNOVER_ON_DOWNS


def test_classify_field_goal_miss_from_result_type() -> None:
    plays = [
        ActualPlayResult(
            yards_gained=0,
            family="dropback_pass",
            play_type="field_goal",
            result_type="field_goal_miss",
        ),
    ]
    r = classify_drive_end(plays)
    assert r.kind == DRIVE_END_FIELD_GOAL_MISS


def test_flip_possession_after_punt_drive() -> None:
    g = Game.new_game()
    assert g.possession == "offense"
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")],
        possessing_team="offense",
    )
    flip_possession_after_drive(g, d)
    assert g.possession == "defense"
    flip_possession_after_drive(g, d)
    assert g.possession == "offense"


def test_scoring_touchdown_for_defense_possession() -> None:
    g = Game.new_game()
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=40,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="defense",
    )
    apply_scoring_after_drive(g, d)
    assert g.defense_points == 6
    assert g.offense_points == 0


def test_missed_field_goal_no_points() -> None:
    g = Game.new_game()
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=0,
                play_type="field_goal",
                result_type="field_goal_miss",
            )
        ],
        possessing_team="offense",
    )
    apply_scoring_after_drive(g, d)
    assert g.offense_points == 0
    assert g.defense_points == 0


def test_classify_default_punt() -> None:
    plays = [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")]
    r = classify_drive_end(plays)
    assert r.kind == DRIVE_END_PUNT
    assert r.headline == "Punt"


def test_end_kind_override_beats_default_punt() -> None:
    plays = [ActualPlayResult(yards_gained=3, family="inside_zone", play_type="run")]
    r = classify_drive_end(plays, end_kind_override=DRIVE_END_FIELD_GOAL)
    assert r.kind == DRIVE_END_FIELD_GOAL
    assert r.headline == "Field goal"


def test_complete_drive_net_yards_includes_penalty() -> None:
    plays = [
        ActualPlayResult(yards_gained=10, family="quick_game", penalty=True, penalty_yards=-5),
    ]
    d = complete_drive_from_plays(plays)
    assert d.total_yards == 5
    assert d.play_count == 1


def test_game_json_roundtrip() -> None:
    g = Game.new_game()
    plays = [ActualPlayResult(yards_gained=12, family="quick_game", play_type="pass", first_down=True)]
    d = complete_drive_from_plays(
        plays,
        end_kind_override=DRIVE_END_FIELD_GOAL,
        possessing_team="offense",
    )
    apply_scoring_after_drive(g, d)
    g.drives.append(d)
    g.quarter = 3

    raw = game_to_json(g)
    g2 = game_from_json(raw)
    assert g2.game_id == g.game_id
    assert g2.offense_points == 3
    assert len(g2.drives) == 1
    assert g2.drives[0].result is not None
    assert g2.drives[0].result.kind == DRIVE_END_FIELD_GOAL
    assert g2.drives[0].total_yards == 12
    assert g2.drives[0].possessing_team == "offense"
    assert g2.drives[0].plays[0].family == "quick_game"
    assert g2.quarter == 3
    assert g2.drives[0].feed_audit is None
