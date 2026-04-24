"""Drive failure copy (``playcaller.review_insights.drive_failure``)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import Drive, DriveResult
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review_insights.drive_failure import explain_drive_failure
from playcaller.review_insights.drive_grading import compute_drive_grade


def _row(*, agree: bool, conf: float) -> UnifiedReviewRow:
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=0,
        play_index_on_drive=1,
        team_side="our",
        pre_snap={"down": 3, "distance": 8},
        actual_headline="Pass",
        actual_detail="",
        actual_structured={"run_pass": "Pass"},
        model_headline="Run",
        model_subline="",
        model_structured={"run_pass": "Run", "family": "inside_zone"},
        comparison=UnifiedComparison(
            run_pass_match=agree,
            summary_bucket_match=agree,
            family_match=agree,
        ),
        confidence=conf,
        is_replay=True,
        is_historical=False,
        event_segment=PlayEventSegment.OFFENSE,
    )


def test_sack_emits_negative_play_bullet() -> None:
    plays = [
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            yards_gained=2,
            feed_presnap_down=1,
            feed_presnap_distance=10,
        ),
        ActualPlayResult(
            family="dropback_pass",
            play_type="pass",
            yards_gained=-7,
            sack=True,
            feed_presnap_down=2,
            feed_presnap_distance=8,
        ),
    ]
    dr = Drive(plays=plays, result=DriveResult(kind="punt", headline="Punt", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    lines = explain_drive_failure(dr, [], rec)
    assert any("2nd" in x.lower() or "negative" in x.lower() for x in lines)


def test_model_disagreement_high_conf_bullet() -> None:
    dr = Drive(
        plays=[
            ActualPlayResult(
                family="inside_zone",
                play_type="run",
                yards_gained=1,
                feed_presnap_down=1,
                feed_presnap_distance=10,
            ),
        ],
        result=DriveResult(kind="punt", headline="Punt", detail_line=""),
    )
    rec = reconcile_drive(dr, espn=None)
    rows = [_row(agree=False, conf=0.85)]
    lines = explain_drive_failure(dr, rows, rec)
    assert any("model" in x.lower() for x in lines)


def test_high_grade_drive_may_have_empty_explanations() -> None:
    plays = [
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=12, first_down=True),
        ActualPlayResult(family="inside_zone", play_type="run", yards_gained=11, first_down=True),
    ]
    dr = Drive(plays=plays, result=DriveResult(kind="touchdown", headline="TD", detail_line=""))
    dr = dr.with_computed_stats(result=DriveResult(kind="touchdown", headline="TD", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    g = compute_drive_grade(dr, [_row(agree=True, conf=0.5), _row(agree=True, conf=0.5)], rec, perspective="possession_offense")
    if g.letter in ("A", "B"):
        assert g.failure_explanations == ()


def test_max_three_bullets() -> None:
    plays = []
    for _ in range(4):
        plays.append(
            ActualPlayResult(
                family="inside_zone",
                play_type="run",
                yards_gained=-5,
                sack=False,
                feed_presnap_down=1,
                feed_presnap_distance=10,
            )
        )
    dr = Drive(plays=plays, result=DriveResult(kind="punt", headline="Punt", detail_line=""))
    rec = reconcile_drive(dr, espn=None)
    lines = explain_drive_failure(dr, [], rec)
    assert len(lines) <= 3
