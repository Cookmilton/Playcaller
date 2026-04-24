"""Deterministic call-quality labels."""

from __future__ import annotations

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.call_quality import label_call_quality


def _game() -> Game:
    return Game.new_game()


def _offense_row(
    *,
    pre: dict,
    actual_struct: dict,
    model_struct: dict,
    comparison: UnifiedComparison,
    confidence: float | None,
) -> UnifiedReviewRow:
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=0,
        play_index_on_drive=1,
        team_side="our",
        pre_snap=pre,
        actual_headline="Run",
        actual_detail="",
        actual_structured=actual_struct,
        model_headline="—",
        model_subline="—",
        model_structured=model_struct,
        comparison=comparison,
        confidence=confidence,
        is_replay=True,
        is_historical=False,
        event_segment=PlayEventSegment.OFFENSE,
        offensive_snap_index=1,
    )


def test_actual_top1_positive_is_good() -> None:
    g = _game()
    row = _offense_row(
        pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25},
        actual_struct={
            "family": "inside_zone",
            "run_pass": "Run",
            "result_type": "first_down",
            "yards_gained": 6,
        },
        model_struct={
            "top_families": [{"family": "inside_zone", "score": 0.9}, {"family": "quick_game", "score": 0.1}]
        },
        comparison=UnifiedComparison(True, True, True),
        confidence=0.9,
    )
    lab = label_call_quality(g, row, top_mistake_play_ids=set())
    assert lab.symbol == "✅"
    assert lab.category == "good"
    # Determinism
    assert label_call_quality(g, row, top_mistake_play_ids=set()) == lab


def test_top3_negative_outcome_questionable() -> None:
    g = _game()
    row = _offense_row(
        pre={"down": 3, "distance": 10, "territory": "own", "yardline": 25},
        actual_struct={
            "family": "play_action",
            "run_pass": "Pass",
            "result_type": "incomplete",
            "yards_gained": 0,
        },
        model_struct={
            "top_families": [
                {"family": "quick_game", "score": 0.5},
                {"family": "inside_zone", "score": 0.3},
                {"family": "play_action", "score": 0.2},
            ]
        },
        comparison=UnifiedComparison(False, False, True),
        confidence=0.5,
    )
    lab = label_call_quality(g, row, top_mistake_play_ids=set())
    assert lab.symbol == "⚠️"
    assert "top 3" in lab.reason.lower()


def test_not_in_top3_high_conf_poor() -> None:
    g = _game()
    row = _offense_row(
        pre={"down": 3, "distance": 12, "territory": "own", "yardline": 25},
        actual_struct={
            "family": "screen",
            "run_pass": "Pass",
            "result_type": "incomplete",
            "yards_gained": 0,
        },
        model_struct={
            "top_families": [
                {"family": "quick_game", "score": 0.85},
                {"family": "inside_zone", "score": 0.1},
                {"family": "play_action", "score": 0.05},
            ]
        },
        comparison=UnifiedComparison(False, False, False),
        confidence=0.85,
    )
    lab = label_call_quality(g, row, top_mistake_play_ids=set())
    assert lab.symbol == "❌"
    assert "top 3" in lab.reason.lower()


def test_top_mistake_set_forces_poor() -> None:
    g = _game()
    row = _offense_row(
        pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25},
        actual_struct={"family": "inside_zone", "run_pass": "Run", "result_type": "first_down", "yards_gained": 4},
        model_struct={"top_families": [{"family": "inside_zone", "score": 1.0}]},
        comparison=UnifiedComparison(True, True, True),
        confidence=0.99,
    )
    lab = label_call_quality(g, row, top_mistake_play_ids={f"{row.drive_id}:{row.play_index_on_drive}"})
    assert lab.symbol == "❌"
    assert "top mistakes" in lab.reason.lower()
