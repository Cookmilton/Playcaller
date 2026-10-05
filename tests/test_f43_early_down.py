"""F4.3: on-schedule early downs get their own ``early_down`` bucket.

Property tests on the recommendation, not exact scores — the ``early_down`` row is an
authored prior and may be retuned without rewriting these.

Neutral situation: own 40, 7 in the box, unknown coverage, Q2, tied, 0 runs this drive.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.heuristic_predictor import HeuristicPredictor
from playcaller.state import DriveLogger


def _neutral(down: int, distance: int, *, box_count: int = 7) -> GameContext:
    return GameContext(
        down=down,
        distance=distance,
        territory="own",
        yardline=40,
        box_count=box_count,
        coverage_shell="unknown",
        safeties="unknown",
        quarter=2,
        score_diff=0,
        run_plays_this_drive=0,
    )


def _recommend(ctx: GameContext) -> Dict[str, Any]:
    return FootballPlayPredictor().recommend(ctx, DriveLogger(), None)


def _top3(scores: Dict[str, float]) -> list[str]:
    return [f for f, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]


@pytest.mark.parametrize(("down", "distance"), [(1, 10), (2, 3)])
def test_neutral_early_down_has_a_run_family_in_top_three(down: int, distance: int) -> None:
    res = _recommend(_neutral(down, distance))
    assert res["bucket"] == "early_down"
    top3 = _top3(res["scores"])
    assert any(f in RUN_FAMILIES for f in top3), top3


def test_every_early_down_baseline_family_is_scored() -> None:
    row = HeuristicPredictor().baselines["early_down"]
    res = _recommend(_neutral(1, 10))
    missing = sorted(set(row) - set(res["scores"]))
    assert missing == []


@pytest.mark.parametrize(
    ("down", "distance", "family"),
    [(3, 3, "quick_game"), (3, 5, "dropback_pass")],
)
def test_neutral_third_and_medium_picks_unchanged(down: int, distance: int, family: str) -> None:
    """Same picks as 8b52720: 3rd & medium still scores against ``medium_yardage``."""
    res = _recommend(_neutral(down, distance))
    assert res["bucket"] == "medium_yardage"
    assert res["play_family"] == family


def test_first_and_ten_box_count_moves_the_pick_the_right_way() -> None:
    heavy = _recommend(_neutral(1, 10, box_count=8))["play_family"]
    light = _recommend(_neutral(1, 10, box_count=6))["play_family"]
    assert heavy in PASS_FAMILIES, heavy
    assert light in RUN_FAMILIES, light


@pytest.mark.parametrize("distance", [3, 4, 5, 6])
def test_current_missing_down_three_to_six_is_long_yardage_pending_f44(distance: int) -> None:
    """CURRENT behaviour, not intended design.

    With no down, 3-6 to go can no longer land in a down-specific bucket, so it falls
    to ``long_yardage`` (F4.3). F4.4 should make a missing down an explicit unknown;
    update this test then.
    """
    ctx = _neutral(1, distance)
    ctx.down = None  # type: ignore[assignment]
    assert HeuristicPredictor().get_bucket(ctx) == "long_yardage"
