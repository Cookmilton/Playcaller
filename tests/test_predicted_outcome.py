"""Tests for heuristic play projection (deterministic RNG)."""

from __future__ import annotations

from playcaller.domain import GameContext
from playcaller.library import PLAY_LIBRARY
from playcaller.predicted_outcome import compute_predicted_play_result, enrich_recommendation_dict
from playcaller.state import DriveLogger


def _ctx(**kwargs) -> GameContext:
    base = dict(
        down=2,
        distance=7,
        yardline=35,
        territory="own",
        coverage_shell="cover_3",
        blitz_likely=False,
    )
    base.update(kwargs)
    return GameContext(**base)  # type: ignore[arg-type]


def test_projection_deterministic() -> None:
    play = PLAY_LIBRARY["quick_game"][0]
    ctx = _ctx()
    log = DriveLogger()
    a = compute_predicted_play_result(ctx, "quick_game", play, log)
    b = compute_predicted_play_result(ctx, "quick_game", play, log)
    assert a.description == b.description
    assert a.yards == b.yards
    assert a.result_type == b.result_type
    assert a.headline == b.headline


def test_enrich_recommendation_dict_adds_key() -> None:
    play = PLAY_LIBRARY["inside_zone"][0]
    ctx = _ctx(down=1, distance=10)
    result = {
        "ctx": ctx,
        "play_family": "inside_zone",
        "play": play,
    }
    enrich_recommendation_dict(result, None)
    assert "predicted_play_result" in result
    pred = result["predicted_play_result"]
    assert "description" in pred
    assert pred["play_type"] == "run"
    assert pred["yards"] >= 1
    assert pred.get("headline", "").startswith("Result:")


def test_pass_projection_has_structure() -> None:
    play = PLAY_LIBRARY["dropback_pass"][0]
    ctx = _ctx(distance=8)
    p = compute_predicted_play_result(ctx, "dropback_pass", play, DriveLogger())
    assert p.play_type in ("pass", "qb_run")
    assert p.target_position in ("X", "H", "Y", "Z", "RB", None)
    assert isinstance(p.description, str) and len(p.description) > 3
