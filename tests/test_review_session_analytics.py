"""Pattern + model diagnostics aggregates for Review Session."""

from __future__ import annotations

from playcaller.review.session_analytics import (
    build_model_diagnostics,
    build_pattern_analysis,
)
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow


def _row(
    *,
    pre: dict,
    model_rp: str | None,
    actual_rp: str | None,
    drive_id: int = 0,
    conf: float | None = 0.75,
    rp_match: bool | None = True,
    bk_match: bool | None = True,
) -> UnifiedReviewRow:
    return UnifiedReviewRow(
        review_mode=ReviewMode.TRUE_STORED,
        audit_index=0,
        drive_id=drive_id,
        play_index_on_drive=1,
        team_side="our",
        pre_snap=pre,
        actual_headline="Run",
        actual_detail="",
        actual_structured={"run_pass": actual_rp},
        model_headline="Pass",
        model_subline="",
        model_structured={"run_pass": model_rp},
        comparison=UnifiedComparison(rp_match, bk_match, True),
        confidence=conf,
        is_replay=False,
        is_historical=True,
    )


def test_pattern_analysis_by_down_and_distance() -> None:
    rows = [
        _row(pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25}, model_rp="Pass", actual_rp="Run"),
        _row(pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25}, model_rp="Pass", actual_rp="Pass"),
        _row(pre={"down": 3, "distance": 2, "territory": "opponents", "yardline": 15}, model_rp="Run", actual_rp="Run"),
    ]
    rep = build_pattern_analysis(rows)
    m1, a1 = rep.by_down[1]
    assert m1.n == 2 and m1.pass_n == 2
    assert a1.n == 2 and a1.pass_n == 1
    assert "Short (1–3)" in rep.by_dist_bucket


def test_pattern_analysis_red_zone() -> None:
    rows = [
        _row(
            pre={"down": 2, "distance": 8, "territory": "opponents", "yardline": 18},
            model_rp="Pass",
            actual_rp="Pass",
        ),
        _row(
            pre={"down": 1, "distance": 10, "territory": "opponents", "yardline": 19},
            model_rp="Run",
            actual_rp="Pass",
        ),
    ]
    rz_m, rz_a = build_pattern_analysis(rows).red_zone
    assert rz_m.n == 2 and rz_m.pass_n == 1
    assert rz_a.n == 2 and rz_a.pass_n == 2


def test_model_diagnostics_high_conf_mismatch() -> None:
    rows = [
        _row(
            pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25},
            model_rp="Pass",
            actual_rp="Run",
            conf=0.8,
            rp_match=False,
            bk_match=False,
        ),
        _row(
            pre={"down": 1, "distance": 10, "territory": "own", "yardline": 25},
            model_rp="Pass",
            actual_rp="Pass",
            conf=0.8,
            rp_match=True,
            bk_match=True,
        ),
    ]
    md = build_model_diagnostics(rows)
    assert md.high_conf_total == 2
    assert md.high_conf_mismatch == 1
