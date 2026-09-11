"""Clock-aware WHY text lives in the predictor, not the UI."""

from playcaller.domain import GameContext
from playcaller.heuristic_predictor import HeuristicPredictor
from playcaller.library import PLAY_LIBRARY
from playcaller.play_rationale import clock_matches_two_minute, situation_aware_why


def _ctx(**kwargs) -> GameContext:
    base = dict(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
        quarter=1,
        seconds_remaining=900,
        game_mode="normal",
    )
    base.update(kwargs)
    return GameContext(**base)


def test_two_minute_clause_dropped_at_q1_kickoff() -> None:
    why = "Boundary shot vs single-high; two-minute boundary throw."
    assert situation_aware_why(why, _ctx()) == "Boundary shot vs single-high"


def test_two_minute_clause_kept_inside_two_minute() -> None:
    why = "Boundary shot vs single-high; two-minute boundary throw."
    ctx = _ctx(quarter=4, seconds_remaining=70, game_mode="two_minute")
    assert clock_matches_two_minute(ctx)
    assert situation_aware_why(why, ctx) == why


def test_predict_does_not_mutate_library_why() -> None:
    before = {id(p): p.get("why") for plays in PLAY_LIBRARY.values() for p in plays}
    rec = HeuristicPredictor().recommend(_ctx())
    after = {id(p): p.get("why") for plays in PLAY_LIBRARY.values() for p in plays}
    assert before == after
    why = str((rec.get("play") or {}).get("why") or "")
    assert "two-minute" not in why.lower()
