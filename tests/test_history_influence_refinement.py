"""Safety / clarity refinements on historical influence (small samples, situation dampener, shared lanes)."""

from __future__ import annotations

import pytest

from playcaller import GameContext
from playcaller.history.influence import lane_success_reliability_scale, situation_dampener_for_history
from playcaller.history.lanes import actual_family_to_history_lane
from playcaller.history.outcome_aggregates import OutcomeTotals
from playcaller.history.recommendation_metadata import build_historical_metadata_for_recommendation


def test_actual_family_to_history_lane_matches_run_pass_buckets() -> None:
    assert actual_family_to_history_lane("inside_zone") == "run_family"
    assert actual_family_to_history_lane("quick_game") == "pass_family"
    assert actual_family_to_history_lane(None) == "unknown"
    assert actual_family_to_history_lane("special_teams") == "other"


def test_lane_success_reliability_full_when_enough_evaluable() -> None:
    t = OutcomeTotals(
        n=12,
        n_unique_games=12,
        success_rate=0.6,
        n_success_evaluable=12,
        n_success_positive=7,
        conversion_rate=0.5,
        n_conversions=6,
        touchdown_rate=0.0,
        explosive_rate=0.0,
        turnover_rate=0.0,
        mean_yards=4.0,
        median_yards=4.0,
    )
    assert lane_success_reliability_scale(t, reference_n=5) == pytest.approx(1.0)


def test_lane_success_reliability_shrinks_when_few_evaluable() -> None:
    t = OutcomeTotals(
        n=12,
        n_unique_games=12,
        success_rate=0.75,
        n_success_evaluable=3,
        n_success_positive=2,
        conversion_rate=0.5,
        n_conversions=6,
        touchdown_rate=0.0,
        explosive_rate=0.0,
        turnover_rate=0.0,
        mean_yards=4.0,
        median_yards=4.0,
    )
    assert lane_success_reliability_scale(t, reference_n=5) == pytest.approx(0.6)
    assert lane_success_reliability_scale(t, reference_n=5) < 1.0


def test_lane_success_reliability_ignores_when_no_success_rate() -> None:
    t = OutcomeTotals(
        n=10,
        n_unique_games=10,
        success_rate=None,
        n_success_evaluable=0,
        n_success_positive=0,
        conversion_rate=0.0,
        n_conversions=0,
        touchdown_rate=0.0,
        explosive_rate=0.0,
        turnover_rate=0.1,
        mean_yards=2.0,
        median_yards=2.0,
    )
    assert lane_success_reliability_scale(t, reference_n=5) == pytest.approx(1.0)


def test_situation_dampener_normal_down_is_one() -> None:
    ctx = GameContext(
        down=1,
        distance=2,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
        score_diff=0,
        quarter=1,
        seconds_remaining=900,
        own_timeouts=3,
        opp_timeouts=3,
        weather="clear",
        wind_mph=0,
        qb_limited=False,
        mismatch=None,
        game_mode="normal",
        plays_this_drive=0,
        shown_concepts=[],
        run_plays_this_drive=0,
    )
    assert situation_dampener_for_history(ctx, "strict") == pytest.approx(1.0)


def test_situation_dampener_fourth_down_reduces() -> None:
    ctx = GameContext(
        down=4,
        distance=2,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
        score_diff=0,
        quarter=1,
        seconds_remaining=900,
        own_timeouts=3,
        opp_timeouts=3,
        weather="clear",
        wind_mph=0,
        qb_limited=False,
        mismatch=None,
        game_mode="normal",
        plays_this_drive=0,
        shown_concepts=[],
        run_plays_this_drive=0,
    )
    assert situation_dampener_for_history(ctx, "strict") < 1.0
    assert situation_dampener_for_history(ctx, "relax_distance") < situation_dampener_for_history(
        ctx, "strict"
    )


def test_situation_dampener_two_minute_stacks() -> None:
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
        score_diff=0,
        quarter=4,
        seconds_remaining=45,
        own_timeouts=1,
        opp_timeouts=3,
        weather="clear",
        wind_mph=0,
        qb_limited=False,
        mismatch=None,
        game_mode="two_minute",
        plays_this_drive=0,
        shown_concepts=[],
        run_plays_this_drive=0,
    )
    assert situation_dampener_for_history(ctx, "strict") == pytest.approx(0.9)


def test_metadata_headline_omits_small_lane_without_success_rate() -> None:
    m = build_historical_metadata_for_recommendation(
        {
            "applied": True,
            "corpus_supplied": True,
            "overall_matches": 20,
            "similarity_tier": "strict",
            "similarity_tier_strength": 1.0,
            "run_lane": {
                "n": 8,
                "adjustment": 0.02,
                "success_rate": None,
                "turnover_rate": 0.05,
                "gated": False,
            },
            "pass_lane": {
                "n": 12,
                "adjustment": 0.01,
                "success_rate": 0.55,
                "turnover_rate": 0.0,
                "gated": False,
            },
            "per_family": {},
        }
    )
    h = m.get("headline") or ""
    assert "Pass" in h
    assert "Run" not in h

