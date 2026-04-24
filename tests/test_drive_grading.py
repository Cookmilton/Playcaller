"""Drive letter grades (``playcaller.review_insights.drive_grading``)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    Drive,
    DriveResult,
)
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.drive_grading import compute_drive_grade, is_kneel_only_drive
from playcaller.review_insights.scoring_weights import GRADE_A_MIN, GRADE_D_MIN


def _row(drive_id: int, *, agree: bool = True) -> UnifiedReviewRow:
    cmp_u = UnifiedComparison(
        run_pass_match=agree,
        summary_bucket_match=agree,
        family_match=agree,
    )
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=drive_id,
        play_index_on_drive=1,
        team_side="our",
        pre_snap={"down": 1, "distance": 10},
        actual_headline="Run",
        actual_detail="",
        actual_structured={"run_pass": "Run", "family": "inside_zone"},
        model_headline="Run",
        model_subline="",
        model_structured={"run_pass": "Run", "family": "inside_zone"},
        comparison=cmp_u,
        confidence=0.8,
        is_replay=True,
        is_historical=False,
        event_segment=PlayEventSegment.OFFENSE,
    )


def test_td_high_ypp_grades_a_or_b() -> None:
    plays = [
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=8),
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=9),
        ActualPlayResult(family="dropback_pass", play_type="pass", yards_gained=12, first_down=True),
    ]
    dr = Drive(plays=plays, result=DriveResult(kind=DRIVE_END_TOUCHDOWN, headline="TD", detail_line=""))
    dr = dr.with_computed_stats(result=DriveResult(kind=DRIVE_END_TOUCHDOWN, headline="TD", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    rows = [_row(0), _row(0), _row(0)]
    g = compute_drive_grade(dr, rows, rec, perspective="possession_offense")
    assert g.letter in ("A", "B")
    assert g.total_score is not None and g.total_score >= GRADE_A_MIN - 15


def test_punt_low_ypp_sacks_grades_d_or_f() -> None:
    plays = [
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=-4, sack=False),
        ActualPlayResult(family="dropback_pass", play_type="pass", yards_gained=-8, sack=True),
        ActualPlayResult(family="dropback_pass", play_type="pass", yards_gained=3),
    ]
    dr = Drive(plays=plays, result=DriveResult(kind=DRIVE_END_PUNT, headline="Punt", detail_line=""))
    dr = dr.with_computed_stats(result=DriveResult(kind=DRIVE_END_PUNT, headline="Punt", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    rows = [_row(0, agree=False), _row(0, agree=False), _row(0, agree=False)]
    g = compute_drive_grade(dr, rows, rec, perspective="possession_offense")
    assert g.letter in ("D", "F")
    assert g.total_score is not None and g.total_score <= GRADE_D_MIN + 14


def test_kneel_drive_not_applicable() -> None:
    dr = Drive(
        plays=[
            ActualPlayResult(
                family="inside_zone",
                play_type="run",
                yards_gained=0,
                result_type="kneel",
                description="QB kneel",
            )
        ],
    )
    assert is_kneel_only_drive(dr)
    rec = reconcile_drive(dr, espn=None)
    g = compute_drive_grade(dr, [], rec, perspective="possession_offense")
    assert g.letter == "—"
    assert g.total_score is None


def test_opponent_td_grades_poor_for_defense() -> None:
    plays = [ActualPlayResult(family="inside_zone", play_type="run", yards_gained=6, touchdown=True)]
    dr = Drive(plays=plays, possessing_team="defense", result=DriveResult(kind=DRIVE_END_TOUCHDOWN, headline="TD", detail_line=""))
    dr = dr.with_computed_stats(result=DriveResult(kind=DRIVE_END_TOUCHDOWN, headline="TD", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    g = compute_drive_grade(dr, [_row(0)], rec, perspective="defense")
    assert g.outcome_component == 0
    assert g.total_score is not None and g.total_score < 75


def test_components_sum_to_total() -> None:
    plays = [
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=5),
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=5),
    ]
    dr = Drive(plays=plays, result=DriveResult(kind=DRIVE_END_PUNT, headline="Punt", detail_line=""))
    dr = dr.with_computed_stats(result=DriveResult(kind=DRIVE_END_PUNT, headline="Punt", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    g = compute_drive_grade(dr, [_row(0), _row(0)], rec, perspective="possession_offense")
    assert g.total_score is not None
    s = (g.outcome_component or 0) + (g.efficiency_component or 0) + (g.situational_component or 0) + (g.model_component or 0)
    assert s == g.total_score


def test_letter_bucket_thresholds() -> None:
    from playcaller.review_insights.drive_grading import _letter

    assert _letter(90) == "A"
    assert _letter(85) == "A"
    assert _letter(84) == "B"
    assert _letter(70) == "B"
    assert _letter(69) == "C"
    assert _letter(55) == "C"
    assert _letter(54) == "D"
    assert _letter(40) == "D"
    assert _letter(39) == "F"
