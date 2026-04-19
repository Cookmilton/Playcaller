"""Play library merge and metadata-weighted selection."""

from __future__ import annotations

import random

from playcaller.domain import GameContext
from playcaller.features import extract_model_input
from playcaller.heuristic_predictor import HeuristicPredictor
from playcaller.library import PLAY_LIBRARY
from playcaller.play_metadata import play_selection_weight


def test_library_includes_expansion_plays() -> None:
    names = {p["name"] for p in PLAY_LIBRARY["quick_game"]}
    assert "Snag" in names
    assert "Mesh" in names
    assert len(PLAY_LIBRARY["dropback_pass"]) >= 5


def test_weighted_choose_respects_blitz() -> None:
    hp = HeuristicPredictor()
    ctx = GameContext(
        down=3,
        distance=6,
        yardline=45,
        territory="opponents",
        blitz_likely=True,
        coverage_shell="cover_3",
    )
    mi = extract_model_input(ctx, None, None)
    jail = next(p for p in PLAY_LIBRARY["screen"] if p["name"] == "Jailbreak Screen")
    bubble = next(p for p in PLAY_LIBRARY["screen"] if p["name"] == "Trips Bubble")
    w_j = play_selection_weight(jail, family="screen", ctx=ctx, bucket="medium_yardage", model_input=mi)
    w_b = play_selection_weight(bubble, family="screen", ctx=ctx, bucket="medium_yardage", model_input=mi)
    assert w_j >= w_b

def test_choose_play_is_deterministic_with_seed() -> None:
    hp = HeuristicPredictor()
    ctx = GameContext(down=2, distance=7, yardline=40, territory="opponents")
    mi = extract_model_input(ctx, None, None)
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    p1 = hp.choose_play("quick_game", ctx, rng1, mi)
    p2 = hp.choose_play("quick_game", ctx, rng2, mi)
    assert p1["name"] == p2["name"]
