"""Tests for :mod:`playcaller.ui.review_session_ux` pure helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_INT,
    Drive,
    DriveResult,
    Game,
)
from playcaller.reconciliation.drive_reconciler import FieldPosition, ReconciledDrive
from playcaller.review.unified_review import ReviewMode
from playcaller.ui.review_session_ux import (
    compact_drive_label,
    compute_reliability_context,
    rank_insights,
    reliability_label,
    score_confidence,
    select_key_drives,
    team_label_mode,
)
from warehouse.review_loader import (
    WAREHOUSE_AUDIT_META_OUTLIER_FLAGS,
    WAREHOUSE_AUDIT_META_QUALITY_ISSUES,
    WAREHOUSE_AUDIT_META_REQUIRED_FIELD_GAP_PCT,
    WAREHOUSE_AUDIT_META_VALIDATION_ISSUES,
)


def _rec(
    outcome_kind: str,
    possession_points: int,
    plays: int = 3,
    yards: int = 10,
) -> ReconciledDrive:
    return ReconciledDrive(
        outcome_kind=outcome_kind,
        outcome_headline="x",
        plays=plays,
        yards=yards,
        time_of_possession_display="1:00",
        start_field_position=FieldPosition(display="own 25"),
        start_quarter=1,
        start_clock="",
        end_reason=None,
        possession_points=possession_points,
        espn_coarse_bucket="",
        provenance={},
        audit_flags=(),
        raw_espn_vs_inferred_disagree=False,
        resolution_notes=(),
    )


class TestReliability:
    @pytest.mark.parametrize(
        "kwargs, want",
        [
            (
                dict(
                    validation_issues=0,
                    quality_issues=0,
                    outlier_flags=0,
                    required_field_gap_pct=0.0,
                    score_gap=None,
                    drive_coverage_ok=True,
                ),
                "Healthy",
            ),
            (
                dict(
                    validation_issues=1,
                    quality_issues=0,
                    outlier_flags=0,
                    required_field_gap_pct=0.0,
                    score_gap=0,
                    drive_coverage_ok=True,
                ),
                "Caution",
            ),
            (
                dict(
                    validation_issues=0,
                    quality_issues=0,
                    outlier_flags=0,
                    required_field_gap_pct=0.0,
                    score_gap=5,
                    drive_coverage_ok=True,
                ),
                "Low confidence",
            ),
            (
                dict(
                    validation_issues=0,
                    quality_issues=0,
                    outlier_flags=0,
                    required_field_gap_pct=0.0,
                    score_gap=1,
                    drive_coverage_ok=False,
                ),
                "Low confidence",
            ),
        ],
    )
    def test_reliability_label_thresholds(self, kwargs, want) -> None:
        assert reliability_label(**kwargs) == want


def test_compute_reliability_context_reads_warehouse_audit_meta() -> None:
    g = Game(drives=[], offense_points=0, defense_points=0)
    g.session_metadata = {
        "warehouse_processed": True,
        "warehouse_home_team": "H",
        "warehouse_away_team": "A",
        WAREHOUSE_AUDIT_META_VALIDATION_ISSUES: 4,
        WAREHOUSE_AUDIT_META_QUALITY_ISSUES: 0,
        WAREHOUSE_AUDIT_META_OUTLIER_FLAGS: 0,
        WAREHOUSE_AUDIT_META_REQUIRED_FIELD_GAP_PCT: 0.0,
    }
    lab, cov, gap = compute_reliability_context(g)
    assert lab == "Caution" and cov is True and gap == 0


def test_compute_reliability_context_explicit_args_override_meta() -> None:
    g = Game(drives=[], offense_points=0, defense_points=0)
    g.session_metadata = {
        "warehouse_processed": True,
        "warehouse_home_team": "H",
        "warehouse_away_team": "A",
        WAREHOUSE_AUDIT_META_VALIDATION_ISSUES: 0,
        WAREHOUSE_AUDIT_META_QUALITY_ISSUES: 0,
        WAREHOUSE_AUDIT_META_OUTLIER_FLAGS: 0,
        WAREHOUSE_AUDIT_META_REQUIRED_FIELD_GAP_PCT: 0.0,
    }
    lab, _, _ = compute_reliability_context(g, validation_issues=5)
    assert lab == "Low confidence"


class TestScoreConfidence:
    @pytest.mark.parametrize(
        "ah,aa,ih,ia, want_label, want_gap_pfx",
    [
        (10, 7, 10, 7, "High", 0),
        (10, 7, 10, 3, "Medium", 4),
        (10, 7, 0, 7, "Low", 10),
        (10, 7, 9, 7, "High", 1),
    ],
    )
    def test_bands(self, ah, aa, ih, ia, want_label, want_gap_pfx) -> None:
        lb, g, _ = score_confidence(
            actual_home=ah, actual_away=aa, implied_home=ih, implied_away=ia
        )
        assert lb == want_label
        if want_gap_pfx is not None:
            assert g == want_gap_pfx

    def test_unknown(self) -> None:
        lb, g, e = score_confidence(
            actual_home=None, actual_away=7, implied_home=7, implied_away=7
        )
        assert lb == "Unknown" and g is None and "reconcile" in e.lower()


@patch("playcaller.ui.review_session_ux.reconcile_drive")
def test_select_key_drives_inclusion_rules(mock_reconcile) -> None:
    """6 drives: scoring, TO, explosive, 2 routine, 1 at half boundary; routine excluded."""
    mock_reconcile.side_effect = [
        _rec(DRIVE_END_TOUCHDOWN, 6),
        _rec(DRIVE_END_TURNOVER_INT, 0),
        _rec(DRIVE_END_PUNT, 0, plays=3),
        _rec(DRIVE_END_PUNT, 0),
        _rec(DRIVE_END_PUNT, 0),
        _rec(DRIVE_END_PUNT, 0),
    ]
    drs = [Drive(plays=[ActualPlayResult()]) for _ in range(6)]
    drs[2].plays = [ActualPlayResult(yards_gained=25, feed_period_number=2)]
    drs[2].possessing_team = "offense"
    for i, dr in enumerate(drs):
        if i != 2:
            dr.plays = [ActualPlayResult(yards_gained=3, feed_period_number=1 if i < 3 else 3)]
    # Drive 2 end half: drive 3 starts Q3
    drs[3].plays[0] = ActualPlayResult(yards_gained=1, feed_period_number=3)
    g = Game(drives=drs, offense_points=20, defense_points=10)
    g.session_metadata = {"warehouse_processed": True, "warehouse_home_team": "H", "warehouse_away_team": "A"}
    got = set(select_key_drives(g, outlier_game_flag=False))
    assert 0 in got and 1 in got and 2 in got
    assert 3 not in got and 4 not in got
    assert (len(g.drives) - 1) in got


@patch("playcaller.ui.review_session_ux.reconcile_drive")
def test_select_key_drives_caps_at_15(mock_reconcile) -> None:
    n = 20
    sc = [_rec(DRIVE_END_TOUCHDOWN, 6) for _ in range(n)]
    sc[-1] = _rec(DRIVE_END_PUNT, 0)
    mock_reconcile.side_effect = sc
    drs = [Drive(plays=[ActualPlayResult(yards_gained=0)]) for _ in range(n)]
    g = Game(drives=drs, offense_points=3, defense_points=0)
    g.session_metadata = {"warehouse_processed": True, "warehouse_home_team": "H", "warehouse_away_team": "A"}
    got = select_key_drives(g, outlier_game_flag=False)
    assert len(got) == 15
    assert 19 in got
    assert 0 in got


def test_team_label_mode() -> None:
    assert team_label_mode(mode="warehouse_historical", coached_team_set=False) == "home_away"
    assert team_label_mode(mode="warehouse_historical", coached_team_set=True) == "us_them"
    assert team_label_mode(mode="current_session", coached_team_set=False) == "us_them"


def test_compact_drive_label_falls_back() -> None:
    dr = Drive(
        result=DriveResult(kind="weird_value", headline="x", detail_line=""),
    )
    assert compact_drive_label(dr) == "Drive ended"
    dr2 = Drive(
        result=DriveResult(kind="punt", headline="Punt", detail_line="x"),
    )
    assert compact_drive_label(dr2) == "Punt"


def test_rank_insights_skips_unqualified() -> None:
    g = Game(
        drives=[Drive(plays=[ActualPlayResult(yards_gained=3, feed_warehouse_play_type="run")])],
        offense_points=0,
        defense_points=0,
    )
    g.session_metadata = {
        "warehouse_processed": True,
        "warehouse_home_team": "H",
        "warehouse_away_team": "A",
    }
    out = rank_insights(
        g,
        reliability="Healthy",
        score_label="High",
        max_score_gap=0,
        validation_issue_ct=0,
        quality_issue_ct=0,
        outlier_issue_ct=0,
    )
    assert out == []


def test_rank_insights_surfaces_critical_validation_despite_healthy_high() -> None:
    g = Game(
        drives=[Drive(plays=[ActualPlayResult(yards_gained=3, feed_warehouse_play_type="run")])],
        offense_points=0,
        defense_points=0,
    )
    g.session_metadata = {
        "warehouse_processed": True,
        "warehouse_home_team": "H",
        "warehouse_away_team": "A",
    }
    out = rank_insights(
        g,
        reliability="Healthy",
        score_label="High",
        max_score_gap=0,
        validation_issue_ct=1,
        quality_issue_ct=0,
        outlier_issue_ct=2,
    )
    assert len(out) >= 1
    assert "2 critical validation" in out[0]
    assert "1 validation / 0 quality" in out[0]


def test_is_wh_import() -> None:
    from playcaller.ui.review_session_ux import is_warehouse_historical
    assert is_warehouse_historical(ReviewMode.WAREHOUSE_HISTORICAL) is True
    assert is_warehouse_historical(ReviewMode.REPLAY_ONLY) is False
