"""Top mistake ranking and suppression."""

from __future__ import annotations

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.thresholds import MIN_TOP_MISTAKE_SEVERITY
from playcaller.review_insights.top_mistakes import rank_top_mistakes


def _row(
    *,
    drive_id: int = 0,
    play_index_on_drive: int = 1,
    pre_snap: dict,
    actual_struct: dict,
    model_struct: dict,
    comparison: UnifiedComparison,
    confidence: float | None = 0.82,
) -> UnifiedReviewRow:
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=drive_id,
        play_index_on_drive=play_index_on_drive,
        team_side="our",
        pre_snap=pre_snap,
        actual_headline="Pass incomplete",
        actual_detail="Pressure",
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


def test_turnover_rz_disagree_high_severity() -> None:
    g = Game.new_game()
    rows = [
        _row(
            pre_snap={
                "down": 3,
                "distance": 8,
                "territory": "opponents",
                "yardline": 15,
                "quarter": 2,
                "seconds_remaining": 900,
                "score_diff": -7,
            },
            actual_struct={
                "family": "dropback_pass",
                "run_pass": "Pass",
                "result_type": "interception",
                "yards_gained": 0,
                "turnover": True,
            },
            model_struct={
                "top_families": [
                    {"family": "quick_game", "score": 0.88},
                    {"family": "inside_zone", "score": 0.08},
                    {"family": "screen", "score": 0.04},
                ]
            },
            comparison=UnifiedComparison(False, False, False),
            confidence=0.88,
        )
    ]
    out = rank_top_mistakes(g, rows, our_coached_espn_id="", limit=5, min_severity=MIN_TOP_MISTAKE_SEVERITY)
    assert len(out) >= 1
    assert out[0].severity >= MIN_TOP_MISTAKE_SEVERITY
    assert out[0].drive_number == 1
    assert "interception" in out[0].actual_summary.lower() or "pass" in out[0].actual_summary.lower()


def test_good_alignment_low_severity_not_listed() -> None:
    g = Game.new_game()
    rows = [
        _row(
            pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
            actual_struct={
                "family": "inside_zone",
                "run_pass": "Run",
                "result_type": "first_down",
                "yards_gained": 5,
            },
            model_struct={"top_families": [{"family": "inside_zone", "score": 0.95}]},
            comparison=UnifiedComparison(True, True, True),
            confidence=0.95,
        )
    ]
    assert rank_top_mistakes(g, rows, our_coached_espn_id="", min_severity=MIN_TOP_MISTAKE_SEVERITY) == []


def test_clean_session_empty_mistakes() -> None:
    g = Game.new_game()
    rows = [
        _row(
            pre_snap={"down": 2, "distance": 6, "territory": "own", "yardline": 30, "quarter": 1},
            actual_struct={
                "family": "inside_zone",
                "run_pass": "Run",
                "result_type": "first_down",
                "yards_gained": 4,
            },
            model_struct={"top_families": [{"family": "inside_zone", "score": 0.55}]},
            comparison=UnifiedComparison(True, True, True),
            confidence=0.55,
        )
    ]
    assert rank_top_mistakes(g, rows, our_coached_espn_id="", min_severity=MIN_TOP_MISTAKE_SEVERITY) == []


def test_top_five_ordering_by_severity() -> None:
    g = Game.new_game()
    rows: list[UnifiedReviewRow] = []
    for i in range(6):
        rows.append(
            _row(
                drive_id=0,
                play_index_on_drive=i + 1,
                pre_snap={"down": 3, "distance": 10, "territory": "opponents", "yardline": 12, "quarter": 4},
                actual_struct={
                    "family": "screen",
                    "run_pass": "Pass",
                    "result_type": "incomplete",
                    "yards_gained": 0,
                },
                model_struct={
                    "top_families": [{"family": "quick_game", "score": 0.9 - i * 0.01}],
                },
                comparison=UnifiedComparison(False, False, False),
                confidence=0.9 - i * 0.01,
            )
        )
    out = rank_top_mistakes(g, rows, our_coached_espn_id="", limit=5, min_severity=40)
    assert len(out) == 5
    sev = [m.severity for m in out]
    assert sev == sorted(sev, reverse=True)
