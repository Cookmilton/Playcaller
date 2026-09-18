"""G2.4 stale-log: fingerprint on Generate; Log disabled when situation fields change."""

from __future__ import annotations

from dataclasses import replace

from playcaller.domain import GameContext
from playcaller.recommendation_freshness import (
    attach_situation_fingerprint,
    is_recommendation_stale,
    stale_recommendation_reason,
)


def _ctx(**kwargs) -> GameContext:
    base = GameContext(down=1, distance=10, yardline=25, territory="own", quarter=2, score_diff=0, seconds_remaining=500)
    return replace(base, **kwargs)


def test_g24_down_change_marks_stale_and_blocks_log() -> None:
    rec = attach_situation_fingerprint({"play": {"name": "Inside Zone"}}, _ctx(), possession="offense")
    now = _ctx(down=2)
    assert is_recommendation_stale(rec, now, possession="offense") is True
    reason = stale_recommendation_reason(rec, now, possession="offense")
    assert reason is not None
    assert "down" in reason
    assert "Log is disabled" in reason


def test_g24_clock_only_change_is_not_stale() -> None:
    rec = attach_situation_fingerprint({"play": {"name": "Inside Zone"}}, _ctx(seconds_remaining=500), possession="offense")
    now = _ctx(seconds_remaining=12)
    assert is_recommendation_stale(rec, now, possession="offense") is False
    assert stale_recommendation_reason(rec, now, possession="offense") is None


def test_g24_regenerate_unblocks() -> None:
    rec = attach_situation_fingerprint({"play": {"name": "Inside Zone"}}, _ctx(), possession="offense")
    now = _ctx(down=3, distance=7)
    assert is_recommendation_stale(rec, now, possession="offense") is True
    rec2 = attach_situation_fingerprint({"play": {"name": "Inside Zone"}}, now, possession="offense")
    assert is_recommendation_stale(rec2, now, possession="offense") is False
    assert stale_recommendation_reason(rec2, now, possession="offense") is None
