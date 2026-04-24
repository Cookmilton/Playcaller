from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from playcaller import FootballPlayPredictor, Game, GameContext
from playcaller.state import DriveLogger
from playcaller.services.predictor_with_history import get_recommendation_with_history
from warehouse.recommender import clear_cached_pool


@pytest.fixture(autouse=True)
def _reset_pool():
    clear_cached_pool()
    yield
    clear_cached_pool()


def test_flag_off_historical_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WAREHOUSE_RECOMMENDER_ENABLED", raising=False)
    pred = FootballPlayPredictor()
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    g = Game.new_game()
    dl = DriveLogger()
    r_no, h_no = get_recommendation_with_history(pred, ctx, dl, g)
    assert h_no is None
    direct = pred.recommend(ctx, dl, g)
    assert r_no["play"]["name"] == direct["play"]["name"]
    assert r_no["bucket"] == direct["bucket"]


def test_flag_on_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    pred = FootballPlayPredictor()
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    g = Game.new_game()
    dl = DriveLogger()
    r_on, h_on = get_recommendation_with_history(pred, ctx, dl, g)
    r_off = pred.recommend(ctx, dl, g)
    assert r_on["play"]["name"] == r_off["play"]["name"]
    assert h_on is not None
    assert h_on.status in ("confident", "fallback", "insufficient")


def test_wrapper_uses_cached_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    calls: list[int] = []
    import warehouse.recommender as wr

    real = wr.get_cached_pool

    def _track(root=None):
        calls.append(1)
        return real(root)

    monkeypatch.setattr(wr, "get_cached_pool", _track)
    pred = FootballPlayPredictor()
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    g = Game.new_game()
    dl = DriveLogger()
    get_recommendation_with_history(pred, ctx, dl, g)
    get_recommendation_with_history(pred, ctx, dl, g)
    assert len(calls) == 2


@patch("warehouse.recommender.match", side_effect=RuntimeError("boom"))
def test_match_error_isolates_rule_based(
    _mock_match: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAREHOUSE_RECOMMENDER_ENABLED", "1")
    pred = FootballPlayPredictor()
    ctx = GameContext(down=1, distance=10, yardline=25, territory="own")
    g = Game.new_game()
    dl = DriveLogger()
    r_err, h_err = get_recommendation_with_history(pred, ctx, dl, g)
    assert h_err is None
    assert r_err["play"]["name"]
