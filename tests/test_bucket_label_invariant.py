"""Every ``get_bucket`` label is wired into each table keyed by bucket name.

Each table has a silent fallback for an unknown key: baselines return no scores and
``choose_family`` falls back to ``quick_game`` (``heuristic_predictor.py`` ``score_families`` /
``choose_family``), ``play_selection_weight`` falls back to ``medium_fit``
(``play_metadata.py``), and replay shows the generic family label (``replay_taxonomy.py``).
These tests keep a known bucket from ever reaching any of them.
"""

from __future__ import annotations

import pytest

from playcaller.domain import GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.heuristic_predictor import SITUATION_BUCKETS, HeuristicPredictor
from playcaller.play_metadata import BUCKET_FIT_ATTR
from playcaller.replay.replay_taxonomy import REPLAY_PASS_DEPTH_BY_BUCKET


def test_every_bucket_has_a_baselines_row() -> None:
    assert set(HeuristicPredictor().baselines) == SITUATION_BUCKETS


def test_every_bucket_has_a_baselines_row_with_scores() -> None:
    baselines = HeuristicPredictor().baselines
    empty = sorted(b for b in SITUATION_BUCKETS if not baselines[b])
    assert empty == []


def test_every_bucket_has_a_fit_attribute() -> None:
    assert set(BUCKET_FIT_ATTR) == SITUATION_BUCKETS


def test_every_bucket_has_a_replay_pass_depth_entry() -> None:
    assert set(REPLAY_PASS_DEPTH_BY_BUCKET) == SITUATION_BUCKETS


@pytest.mark.parametrize("predictor", [HeuristicPredictor(), FootballPlayPredictor()], ids=["heuristic", "engine"])
def test_get_bucket_returns_only_known_labels(predictor) -> None:
    seen = set()
    for down in (None, 1, 2, 3, 4):
        for distance in range(1, 31):
            for territory in ("own", "opponents"):
                for yardline in range(1, 51):
                    ctx = GameContext(down=down, distance=distance, yardline=yardline, territory=territory)  # type: ignore[arg-type]
                    seen.add(predictor.get_bucket(ctx))
    assert seen <= SITUATION_BUCKETS, seen - SITUATION_BUCKETS
    assert seen == SITUATION_BUCKETS, SITUATION_BUCKETS - seen
