"""Pattern detection (``playcaller.review_insights.patterns``)."""

from __future__ import annotations

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.models import Pattern
from playcaller.review_insights.patterns import detect_patterns, related_drive_indices_for_pattern
from playcaller.review_insights.thresholds import MIN_RED_ZONE_ATTEMPTS


def _base_row(
    *,
    drive_id: int = 0,
    play_index_on_drive: int = 1,
    pre_snap: dict,
    run_pass: str | None,
    result_type: str = "first_down",
    summary_bucket: str = "run inside / gap",
) -> UnifiedReviewRow:
    ar = {
        "run_pass": run_pass,
        "result_type": result_type,
        "summary_bucket": summary_bucket,
        "yards_gained": 4,
    }
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=drive_id,
        play_index_on_drive=play_index_on_drive,
        team_side="our",
        pre_snap=pre_snap,
        actual_headline="Test",
        actual_detail="",
        actual_structured=ar,
        model_headline="—",
        model_subline="",
        model_structured={"run_pass": run_pass},
        comparison=UnifiedComparison(None, None, None),
        confidence=None,
        is_replay=True,
        is_historical=False,
        event_segment=PlayEventSegment.OFFENSE,
        offensive_snap_index=1,
    )


def test_first_down_run_tendency_emits_pattern() -> None:
    """Many runs on 1st down produces a skewed 1st-down run-rate line."""
    g = Game.new_game()
    rows: list[UnifiedReviewRow] = []
    # 18 first-down snaps: 15 run, 3 pass — skewed vs 50/50
    for i in range(18):
        rp = "Run" if i < 15 else "Pass"
        rows.append(
            _base_row(
                play_index_on_drive=i + 1,
                pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
                run_pass=rp,
            )
        )
    rows.append(
        _base_row(
            play_index_on_drive=19,
            pre_snap={"down": 2, "distance": 7, "territory": "own", "yardline": 30, "quarter": 1},
            run_pass="Pass",
        )
    )
    rows.append(
        _base_row(
            play_index_on_drive=20,
            pre_snap={"down": 2, "distance": 5, "territory": "own", "yardline": 35, "quarter": 1},
            run_pass="Run",
        )
    )
    pats = detect_patterns(rows, g)
    assert pats
    joined = " ".join(p.summary.lower() for p in pats)
    assert "1st" in joined or "first" in joined
    assert "run" in joined


def test_low_sample_suppresses_patterns() -> None:
    g = Game.new_game()
    rows = [
        _base_row(
            play_index_on_drive=i + 1,
            pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
            run_pass="Run",
        )
        for i in range(3)
    ]
    assert detect_patterns(rows, g) == []


def test_red_zone_suppressed_below_threshold() -> None:
    g = Game.new_game()
    rows: list[UnifiedReviewRow] = []
    # 8 plays total, only 2 in red zone — RZ pattern needs >= MIN_RED_ZONE_ATTEMPTS
    for i in range(6):
        rows.append(
            _base_row(
                play_index_on_drive=i + 1,
                pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
                run_pass="Run",
            )
        )
    for i in range(2):
        rows.append(
            _base_row(
                play_index_on_drive=7 + i,
                pre_snap={"down": 1, "distance": 10, "territory": "opponents", "yardline": 15, "quarter": 2},
                run_pass="Pass",
                result_type="incomplete",
            )
        )
    pats = detect_patterns(rows, g)
    assert not any("red zone" in p.summary.lower() for p in pats)
    assert MIN_RED_ZONE_ATTEMPTS == 3


def test_fifty_fifty_overall_suppressed() -> None:
    g = Game.new_game()
    rows: list[UnifiedReviewRow] = []
    for i in range(20):
        rows.append(
            _base_row(
                play_index_on_drive=i + 1,
                pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
                run_pass="Run" if i % 2 == 0 else "Pass",
                summary_bucket="short pass" if i % 2 else "run inside / gap",
            )
        )
    pats = detect_patterns(rows, g)
    assert not any(p.title == "Overall run/pass" for p in pats)


def test_related_drive_indices_for_pattern_sorts_and_dedupes() -> None:
    """support_plays index the same filtered offense list used by detect_patterns."""
    pre = {"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1}
    rows = [
        _base_row(drive_id=2, play_index_on_drive=1, pre_snap=pre, run_pass="Run"),
        _base_row(drive_id=0, play_index_on_drive=1, pre_snap=pre, run_pass="Run"),
        _base_row(drive_id=0, play_index_on_drive=2, pre_snap=pre, run_pass="Pass"),
    ]
    p = Pattern(
        category="run_pass",
        title="t",
        summary="s",
        support_plays=(0, 2, 1, 999),
        significance=1,
    )
    assert related_drive_indices_for_pattern(p, rows) == (0, 2)
