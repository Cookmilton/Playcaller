"""F4.1: situation bucketing is down-aware, so 1st & 10 is not long yardage.

``get_bucket`` decided the last two buckets on distance alone, so every
``distance >= 7`` was ``long_yardage`` — including 1st & 10, the most common snap
in football. Those snaps then scored against the behind-schedule, pass-heavy
``long_yardage`` baselines. Confirmed on a real export: 1st & 10 at Opp 27
produced ``bucket="long_yardage"``.
"""

from __future__ import annotations

import pytest

from playcaller.domain import GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.heuristic_predictor import HeuristicPredictor


def _ctx(down: int, distance: int, *, territory: str = "own", yardline: int = 25) -> GameContext:
    return GameContext(down=down, distance=distance, yardline=yardline, territory=territory)


@pytest.fixture(params=["engine", "heuristic"])
def predictor(request: pytest.FixtureRequest):
    """Both the façade (engine.py:93) and the implementation must agree."""
    return FootballPlayPredictor() if request.param == "engine" else HeuristicPredictor()


# ──────────────────────────────────────────────────────────────────────────────
# The defect
# ──────────────────────────────────────────────────────────────────────────────


def test_f41_first_and_ten_is_not_long_yardage(predictor) -> None:
    assert predictor.get_bucket(_ctx(1, 10)) != "long_yardage"
    assert predictor.get_bucket(_ctx(1, 10)) == "medium_yardage"


def test_f41_reported_export_case_first_and_ten_at_opp_27(predictor) -> None:
    """The exact snap from the export that surfaced F4.1."""
    bucket = predictor.get_bucket(_ctx(1, 10, territory="opponents", yardline=27))
    assert bucket == "medium_yardage", bucket


@pytest.mark.parametrize("distance", [7, 8, 9, 10])
def test_f41_first_down_on_schedule_is_medium(predictor, distance: int) -> None:
    """1st & <=10 generally: on schedule, never long yardage."""
    assert predictor.get_bucket(_ctx(1, distance)) == "medium_yardage"


# ──────────────────────────────────────────────────────────────────────────────
# The new boundaries, stated
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("distance", [1, 2])
def test_f41_short_yardage_unchanged(predictor, distance: int) -> None:
    assert predictor.get_bucket(_ctx(1, distance)) == "short_yardage"
    assert predictor.get_bucket(_ctx(3, distance)) == "short_yardage"


@pytest.mark.parametrize("distance", [3, 4, 5, 6])
def test_f41_medium_yardage_unchanged_on_every_down(predictor, distance: int) -> None:
    for down in (1, 2, 3, 4):
        assert predictor.get_bucket(_ctx(down, distance)) == "medium_yardage"


@pytest.mark.parametrize("distance", [11, 15, 20, 25])
def test_f41_first_down_pushed_past_ten_is_still_long(predictor, distance: int) -> None:
    """A first down behind the chains (penalty) is genuinely long yardage."""
    assert predictor.get_bucket(_ctx(1, distance)) == "long_yardage"


@pytest.mark.parametrize("down", [2, 3, 4])
@pytest.mark.parametrize("distance", [7, 10, 15])
def test_f41_later_downs_unchanged(predictor, down: int, distance: int) -> None:
    """2nd & 10 and 3rd & 10 stay long yardage — this change is first-down only."""
    assert predictor.get_bucket(_ctx(down, distance)) == "long_yardage"


# ──────────────────────────────────────────────────────────────────────────────
# Field position still wins first
# ──────────────────────────────────────────────────────────────────────────────


def test_f41_field_position_still_takes_precedence(predictor) -> None:
    assert predictor.get_bucket(_ctx(1, 10, territory="opponents", yardline=15)) == "red_zone"
    assert predictor.get_bucket(_ctx(1, 10, territory="own", yardline=8)) == "backed_up"
    # Boundaries of those overrides are untouched by F4.1.
    assert predictor.get_bucket(_ctx(1, 10, territory="opponents", yardline=21)) == "medium_yardage"
    assert predictor.get_bucket(_ctx(1, 10, territory="own", yardline=11)) == "medium_yardage"


def test_f41_bucket_reaches_the_recommendation(predictor) -> None:
    """The bucket the operator sees on the card, not just the helper's return."""
    from playcaller.state import DriveLogger

    if not isinstance(predictor, FootballPlayPredictor):
        pytest.skip("recommend() is the engine façade's entrypoint")
    res = predictor.recommend(_ctx(1, 10, territory="opponents", yardline=27), DriveLogger(), None)
    assert res["bucket"] == "medium_yardage", res["bucket"]


def test_f41_missing_down_does_not_silently_become_a_first_down() -> None:
    """``get_bucket`` never assumes a down it was not given."""
    pred = HeuristicPredictor()
    ctx = _ctx(1, 10)
    ctx.down = None  # type: ignore[assignment]
    # No crash, and no free promotion out of long_yardage.
    assert pred.get_bucket(ctx) == "long_yardage"
