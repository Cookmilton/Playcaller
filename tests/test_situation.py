"""Tests for ``playcaller.situation`` (field progression, outcomes, hooks)."""

from __future__ import annotations

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.situation import (
    ProgressionTags,
    SituationSnapshot,
    advance_game_state_after_actual,
    advance_game_state_after_play,
    classify_logged_outcome,
    invoke_post_play_hook,
    play_progression_tags,
    register_post_play_hook,
    yards_from_own_goal,
    yards_to_opponent_goal_from_abs,
)


def test_yards_from_own_goal_own_and_opp() -> None:
    assert yards_from_own_goal("own", 1) == 1
    assert yards_from_own_goal("own", 50) == 50
    assert yards_from_own_goal("opponents", 1) == 99
    assert yards_from_own_goal("opponents", 50) == 50


def test_yards_to_opponent_goal_from_abs() -> None:
    assert yards_to_opponent_goal_from_abs(1) == 99
    assert yards_to_opponent_goal_from_abs(50) == 50
    assert yards_to_opponent_goal_from_abs(99) == 1


def test_advance_actual_matches_low_level_for_simple_gain() -> None:
    actual = ActualPlayResult(yards_gained=5, first_down=False)
    a = advance_game_state_after_actual(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        actual=actual,
    )
    b = advance_game_state_after_play(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        yards_gained=5,
        earned_first_down=False,
    )
    assert a == b


def test_advance_actual_respects_penalty_net_yards() -> None:
    snap = advance_game_state_after_actual(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        actual=ActualPlayResult(yards_gained=12, penalty=True, penalty_yards=-10, first_down=False),
    )
    ref = advance_game_state_after_play(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        yards_gained=2,
        earned_first_down=False,
    )
    assert snap == ref


def test_advance_actual_turnover_parks_new_possession() -> None:
    snap = advance_game_state_after_actual(
        territory="own",
        yardline=45,
        down=2,
        distance=7,
        actual=ActualPlayResult(yards_gained=0, first_down=False, turnover=True),
    )
    assert snap.turnover_on_downs
    assert snap.down == 1
    assert snap.territory == "own"
    assert snap.yardline == 45


def test_advance_simple_gain_no_first() -> None:
    snap = advance_game_state_after_play(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        yards_gained=5,
        earned_first_down=False,
    )
    assert snap.territory == "own"
    assert snap.yardline == 30
    assert snap.down == 2
    assert snap.distance == 5
    assert not snap.touchdown
    assert not snap.turnover_on_downs


def test_advance_first_down_resets_distance_cap() -> None:
    snap = advance_game_state_after_play(
        territory="own",
        yardline=20,
        down=2,
        distance=8,
        yards_gained=8,
        earned_first_down=True,
    )
    assert snap.down == 1
    assert snap.distance == 10
    assert snap.yardline == 28


def test_advance_goal_to_go_cap() -> None:
    snap = advance_game_state_after_play(
        territory="opponents",
        yardline=8,
        down=2,
        distance=8,
        yards_gained=3,
        earned_first_down=True,
    )
    assert snap.territory == "opponents"
    assert snap.down == 1
    assert snap.distance == 5  # yards to goal from opp 5


def test_advance_touchdown() -> None:
    snap = advance_game_state_after_play(
        territory="opponents",
        yardline=5,
        down=1,
        distance=5,
        yards_gained=5,
        earned_first_down=True,
    )
    assert snap.touchdown
    assert snap.territory == "opponents"
    assert snap.yardline == 1
    assert snap.down == 1
    assert snap.distance == 1


def test_advance_turnover_on_downs() -> None:
    snap = advance_game_state_after_play(
        territory="own",
        yardline=45,
        down=4,
        distance=1,
        yards_gained=0,
        earned_first_down=False,
    )
    assert snap.turnover_on_downs
    assert snap.down == 1
    assert snap.distance == 10
    assert snap.yardline == 45


def test_advance_cross_midfield_territory_flip() -> None:
    snap = advance_game_state_after_play(
        territory="own",
        yardline=48,
        down=1,
        distance=10,
        yards_gained=5,
        earned_first_down=False,
    )
    assert snap.territory == "opponents"
    assert snap.yardline == 47  # 53 abs -> opp 47
    assert snap.down == 2


def test_advance_clamp_behind_own_goal_line() -> None:
    snap = advance_game_state_after_play(
        territory="own",
        yardline=3,
        down=3,
        distance=10,
        yards_gained=-15,
        earned_first_down=False,
    )
    assert snap.territory == "own"
    assert snap.yardline == 1


def test_classify_logged_outcome() -> None:
    assert classify_logged_outcome(yards=5, to_go=8, earned_first_down=False, touchdown=False) == "short"
    assert classify_logged_outcome(yards=0, to_go=10, earned_first_down=False, touchdown=False) == "no_gain"
    assert classify_logged_outcome(yards=-2, to_go=10, earned_first_down=False, touchdown=False) == "negative"
    assert classify_logged_outcome(yards=-5, to_go=10, earned_first_down=False, touchdown=False) == "sack"
    assert classify_logged_outcome(yards=8, to_go=8, earned_first_down=True, touchdown=False) == "first_down_exact"
    assert classify_logged_outcome(yards=10, to_go=8, earned_first_down=True, touchdown=False) == "first_down"
    assert classify_logged_outcome(yards=1, to_go=10, earned_first_down=True, touchdown=True) == "touchdown"


def test_play_progression_tags_touchdown_crossed() -> None:
    tags = play_progression_tags(
        start_abs=40,
        abs_after_clamped=99,
        gain=60,
        pre_distance=10,
        earned_first_down=True,
        touchdown=True,
    )
    assert tags.crossed_midfield
    assert tags.explosive_play


def test_play_progression_tags_no_gain() -> None:
    tags = play_progression_tags(
        start_abs=30,
        abs_after_clamped=30,
        gain=0,
        pre_distance=10,
        earned_first_down=False,
        touchdown=False,
    )
    assert tags.no_gain
    assert not tags.negative_play


def test_post_play_hook_register_and_invoke() -> None:
    seen: list[tuple[SituationSnapshot, dict]] = []

    def hook(snap: SituationSnapshot, payload: dict) -> None:
        seen.append((snap, dict(payload)))

    register_post_play_hook(hook)
    try:
        snap = SituationSnapshot(
            territory="own",
            yardline=25,
            down=2,
            distance=7,
            tags=ProgressionTags(),
        )
        invoke_post_play_hook(snap, {"yards": 3})
        assert len(seen) == 1
        assert seen[0][0] == snap
        assert seen[0][1] == {"yards": 3}

        register_post_play_hook(None)
        invoke_post_play_hook(snap, {})
        assert len(seen) == 1
    finally:
        register_post_play_hook(None)


def test_post_play_hook_swallows_exceptions() -> None:
    def boom(_snap: SituationSnapshot, _payload: dict) -> None:
        raise RuntimeError("hook error")

    register_post_play_hook(boom)
    try:
        invoke_post_play_hook(SituationSnapshot("own", 25, 1, 10), {})
    finally:
        register_post_play_hook(None)


def test_advance_actual_field_goal_good_parks_next_series() -> None:
    a = ActualPlayResult(
        yards_gained=0,
        play_type="field_goal",
        result_type="field_goal",
    )
    snap = advance_game_state_after_actual(
        territory="opponents",
        yardline=15,
        down=4,
        distance=5,
        actual=a,
    )
    assert snap.territory == "own"
    assert snap.yardline == 25
    assert snap.down == 1
    assert snap.distance == 10


def test_advance_actual_field_goal_miss_change_of_possession_hint() -> None:
    a = ActualPlayResult(
        yards_gained=0,
        play_type="field_goal",
        result_type="field_goal_miss",
    )
    snap = advance_game_state_after_actual(
        territory="opponents",
        yardline=22,
        down=4,
        distance=5,
        actual=a,
    )
    assert snap.turnover_on_downs is True
    assert snap.down == 1
