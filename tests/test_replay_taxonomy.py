"""Replay / actual taxonomy buckets for archived-drive comparison."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.replay.comparison import model_replay_structured_from_recommend
from playcaller.replay.replay_taxonomy import (
    actual_play_summary_bucket,
    replay_summary_bucket_from_recommend,
)
from playcaller.state import DriveLogger


def test_replay_bucket_screen_family() -> None:
    pred = FootballPlayPredictor()
    ctx = GameContext(
        down=2,
        distance=6,
        yardline=40,
        territory="opponents",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )
    res = pred.recommend(ctx, DriveLogger(), None)
    res["play_family"] = "screen"
    assert "screen" in replay_summary_bucket_from_recommend(res).lower()


def test_actual_bucket_deep_pass_by_yards() -> None:
    a = ActualPlayResult(
        family="dropback_pass",
        play_type="pass",
        pass_result="complete",
        yards_gained=22,
        result_type="first_down",
    )
    assert actual_play_summary_bucket(a) == "deep pass"


def test_model_replay_structured_includes_summary_bucket() -> None:
    pred = FootballPlayPredictor()
    ctx = GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )
    res = pred.recommend(ctx, DriveLogger(), None)
    s = model_replay_structured_from_recommend(res)
    assert s is not None
    assert s.summary_bucket
