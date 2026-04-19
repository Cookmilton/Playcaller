"""Retroactive model replay for archived drives (drive archive UI)."""

from __future__ import annotations

from unittest.mock import patch

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.game import Drive, Game
from playcaller.replay.previous_drive_replay import (
    REPLAY_UNAVAILABLE,
    _MAX_ARCHIVED_DRIVE_COMPARISON_CACHE_ENTRIES,
    best_presnap_chain_for_drive_plays,
    cached_comparison_rows_for_archived_drive,
    comparison_rows_cache_key,
    map_recommendation_to_run_pass,
    presnap_chain_for_drive_plays,
    replay_rows_for_archived_drive,
    score_diff_for_archived_possession,
)
from playcaller.streamlit_state.keys import ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE


def test_score_diff_flips_for_opponent_possession() -> None:
    g = Game(offense_points=14, defense_points=7)
    assert score_diff_for_archived_possession(g, "offense") == 7
    assert score_diff_for_archived_possession(g, "defense") == -7


def test_map_recommendation_to_run_pass() -> None:
    assert map_recommendation_to_run_pass({"play_family": "inside_zone", "play": {}}) == "Run"
    assert map_recommendation_to_run_pass({"play_family": "quick_game", "play": {}}) == "Pass"
    assert map_recommendation_to_run_pass({"play_family": "two_point", "play": {"name": "x"}}) is None
    assert map_recommendation_to_run_pass({"play_family": "", "play": {}}) is None


def test_presnap_chain_touchback_then_second_down() -> None:
    p1 = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=5,
        result_type="short",
    )
    p2 = ActualPlayResult(
        family="quick_game",
        play_type="pass",
        yards_gained=4,
        result_type="short",
        pass_result="complete",
    )
    chain, err = presnap_chain_for_drive_plays([p1, p2])
    assert err is None
    assert len(chain) == 2
    assert chain[0] == ("own", 25, 1, 10)
    assert chain[1][2] == 2
    assert chain[1][3] == 5


def test_presnap_chain_empty() -> None:
    chain, err = presnap_chain_for_drive_plays([])
    assert chain == []
    assert err is None


def test_presnap_chain_touchdown_mid_drive_errors() -> None:
    p_td = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=75,
        touchdown=True,
        result_type="touchdown",
    )
    p_after = ActualPlayResult(
        family="quick_game",
        play_type="pass",
        yards_gained=5,
        result_type="short",
        pass_result="complete",
    )
    chain, err = presnap_chain_for_drive_plays([p_td, p_after])
    assert err == "touchdown_mid_drive"
    assert len(chain) == 1


def test_best_presnap_chain_returns_anchor_tag() -> None:
    p1 = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=3,
        result_type="short",
    )
    chain, err, tag = best_presnap_chain_for_drive_plays([p1])
    assert len(chain) == 1
    assert tag.startswith("touchback_")


def test_replay_rows_empty_plays() -> None:
    g = Game.new_game()
    dr = Drive(plays=[], possessing_team="offense")
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    pred = FootballPlayPredictor()
    assert replay_rows_for_archived_drive(drive=dr, game=g, ambient_ctx=ctx, predictor=pred, plays=[]) == []


def test_replay_rows_structured_comparison() -> None:
    g = Game.new_game()
    g.offense_points = 0
    g.defense_points = 0
    plays = [
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            yards_gained=2,
            result_type="short",
            description="D.Sampson run for 2",
        ),
    ]
    dr = Drive(plays=plays, possessing_team="offense")
    ctx = GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        safeties="single_high",
        blitz_likely=False,
    )
    pred = FootballPlayPredictor()
    rows = replay_rows_for_archived_drive(drive=dr, game=g, ambient_ctx=ctx, predictor=pred, plays=plays)
    assert len(rows) == 1
    r = rows[0]
    assert r.model_run_pass in ("Run", "Pass")
    assert r.actual_play_summary_primary
    assert r.actual_structured_result.get("family") == "inside_zone"
    d = r.to_dict()
    assert d["play_index"] == 1
    assert "pre_snap_context" in d
    assert d["model_replay_structured"] is not None or d["replay_error"]


def test_replay_rows_marks_unavailable_after_broken_chain() -> None:
    g = Game.new_game()
    p_td = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=75,
        touchdown=True,
        result_type="touchdown",
    )
    p_after = ActualPlayResult(
        family="quick_game",
        play_type="pass",
        yards_gained=5,
        result_type="short",
        pass_result="complete",
    )
    plays = [p_td, p_after]
    dr = Drive(plays=plays, possessing_team="offense")
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    pred = FootballPlayPredictor()
    rows = replay_rows_for_archived_drive(drive=dr, game=g, ambient_ctx=ctx, predictor=pred, plays=plays)
    assert len(rows) == 2
    assert rows[0].model_run_pass in ("Run", "Pass")
    assert rows[1].model_run_pass is None
    assert rows[1].replay_error == REPLAY_UNAVAILABLE


def test_comparison_rows_cache_key_varies_with_weather_overlay() -> None:
    g = Game()
    g.game_id = "cache_test_gid"
    play = ActualPlayResult(family="inside_zone", play_type="run", yards_gained=2)
    pred = FootballPlayPredictor()
    a = GameContext(down=1, distance=10, yardline=25, territory="own", weather="clear")
    b = GameContext(down=1, distance=10, yardline=25, territory="own", weather="rain")
    k1 = comparison_rows_cache_key(game=g, drive_index=0, predictor=pred, ambient_ctx=a, plays=[play])
    k2 = comparison_rows_cache_key(game=g, drive_index=0, predictor=pred, ambient_ctx=b, plays=[play])
    assert k1 != k2


def test_cached_comparison_rows_reuses_session_bucket() -> None:
    g = Game()
    g.game_id = "cache_session_test"
    dr = Drive(
        plays=[ActualPlayResult(family="inside_zone", play_type="run", yards_gained=3)],
        possessing_team="offense",
    )
    ambient = GameContext(down=1, distance=10, yardline=25, territory="own")
    pred = FootballPlayPredictor()
    ss: dict = {}
    r1 = cached_comparison_rows_for_archived_drive(
        ss,
        drive=dr,
        drive_index=0,
        game=g,
        ambient_ctx=ambient,
        predictor=pred,
        plays=dr.plays,
    )
    r2 = cached_comparison_rows_for_archived_drive(
        ss,
        drive=dr,
        drive_index=0,
        game=g,
        ambient_ctx=ambient,
        predictor=pred,
        plays=dr.plays,
    )
    assert r1 is r2
    bucket = ss.get(ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE)
    assert isinstance(bucket, dict)
    assert len(bucket) == 1


def test_cached_comparison_rows_prunes_session_bucket_fifo() -> None:
    """Long sessions should not grow ``ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE`` without bound."""
    g = Game()
    g.game_id = "fifo_prune_test"
    dr = Drive(
        plays=[ActualPlayResult(family="inside_zone", play_type="run", yards_gained=3)],
        possessing_team="offense",
    )
    ambient = GameContext(down=1, distance=10, yardline=25, territory="own")
    pred = FootballPlayPredictor()
    ss: dict = {}
    dummy_rows: list = []

    with patch(
        "playcaller.replay.previous_drive_replay.comparison_rows_for_archived_drive",
        return_value=dummy_rows,
    ):
        n = _MAX_ARCHIVED_DRIVE_COMPARISON_CACHE_ENTRIES + 7
        for drive_index in range(n):
            cached_comparison_rows_for_archived_drive(
                ss,
                drive=dr,
                drive_index=drive_index,
                game=g,
                ambient_ctx=ambient,
                predictor=pred,
                plays=dr.plays,
            )

    bucket = ss.get(ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE)
    assert isinstance(bucket, dict)
    assert len(bucket) == _MAX_ARCHIVED_DRIVE_COMPARISON_CACHE_ENTRIES
