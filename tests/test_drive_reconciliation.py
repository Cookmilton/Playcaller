"""Unit tests for :mod:`playcaller.reconciliation.drive_reconciler`."""

from __future__ import annotations

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DriveFeedAuditSnapshot,
    Game,
    complete_drive_from_plays,
)
from playcaller.reconciliation.drive_reconciler import (
    archived_drive_expander_title,
    reconcile_drive,
    scoring_points_for_reconciled_kind,
)


def test_reconcile_agreeing_espn_and_plays_no_warn() -> None:
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        feed_offensive_plays=1,
        feed_yards=7,
        start_period=2,
        start_clock_display="5:00",
        start_field_text="GB 40",
    )
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=7, family="quick_game", play_type="pass", touchdown=True)],
        possessing_team="offense",
        feed_audit=audit,
    )
    rec = reconcile_drive(dr, espn=audit)
    assert rec.outcome_headline
    assert "Touch" in rec.outcome_headline or rec.outcome_headline == "Touchdown"
    assert rec.possession_points == 7
    assert not rec.raw_espn_vs_inferred_disagree


def test_reconcile_espn_overrides_inferred_disagree_info() -> None:
    """ESPN says TD; plays might still classify differently in edge cases — ESPN wins."""
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        start_period=1,
        start_clock_display="15:00",
    )
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=2, family="gap", play_type="run", touchdown=False)],
        possessing_team="offense",
        feed_audit=audit,
    )
    rec = reconcile_drive(dr, espn=audit)
    assert rec.possession_points == 7
    assert rec.raw_espn_vs_inferred_disagree
    assert any(f.field == "outcome" and f.severity == "info" for f in rec.audit_flags)


def test_reconcile_espn_missing_uses_inferred() -> None:
    dr = complete_drive_from_plays(
        [
            ActualPlayResult(yards_gained=0, family="punt", play_type="punt", touchdown=False),
        ],
        possessing_team="offense",
        feed_audit=None,
    )
    rec = reconcile_drive(dr, espn=None)
    assert rec.provenance.get("outcome") == "inferred"
    assert any("ESPN outcome missing" in f.reason for f in rec.audit_flags)


def test_archived_title_matches_reconciled_stats() -> None:
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Field Goal",
        time_elapsed_display="2:34",
        feed_offensive_plays=5,
        feed_yards=42,
        start_period=3,
        start_clock_display="8:12",
    )
    d = complete_drive_from_plays(
        [
            ActualPlayResult(yards_gained=5, family="gap", play_type="run", touchdown=False),
            ActualPlayResult(yards_gained=37, family="quick_game", play_type="pass", touchdown=False),
        ],
        possessing_team="offense",
        feed_team_espn_id="9",
        feed_team_abbr="GB",
        feed_team_display_name="Packers",
        feed_audit=audit,
    )
    rec = reconcile_drive(d, espn=audit)
    title = archived_drive_expander_title(d, 3, rec)
    assert "Packers" in title or "GB" in title
    assert str(rec.plays) in title
    assert str(rec.yards) in title


def test_scoring_points_td_fg() -> None:
    g = Game.new_game()
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=1, family="gap", play_type="run", touchdown=True)],
        possessing_team="offense",
    )
    assert scoring_points_for_reconciled_kind(DRIVE_END_TOUCHDOWN, d) == 7
    assert scoring_points_for_reconciled_kind(DRIVE_END_TOUCHDOWN, d, td_extra_point="pat") == 7
    assert scoring_points_for_reconciled_kind(DRIVE_END_TOUCHDOWN, d, td_extra_point="two_point") == 8
    assert scoring_points_for_reconciled_kind(DRIVE_END_TOUCHDOWN, d, td_extra_point="pat_missed") == 6
    d2 = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=35, family="field_goal", play_type="field_goal", touchdown=False)],
        possessing_team="offense",
    )
    from playcaller.game import DRIVE_END_FIELD_GOAL

    assert scoring_points_for_reconciled_kind(DRIVE_END_FIELD_GOAL, d2) == 3
    d3 = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=0, family="punt", play_type="punt", touchdown=False)],
        possessing_team="offense",
    )
    assert scoring_points_for_reconciled_kind(DRIVE_END_PUNT, d3) == 0


@pytest.mark.parametrize(
    "espn_display,expected_pts",
    [
        ("Touchdown", 7),
    ],
)
def test_reconcile_possession_points_match_espn_scoring(espn_display: str, expected_pts: int) -> None:
    audit = DriveFeedAuditSnapshot(espn_display_result=espn_display, espn_result_code="TD")
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=1, family="gap", play_type="run", touchdown=False)],
        possessing_team="offense",
        feed_audit=audit,
    )
    rec = reconcile_drive(dr, espn=audit)
    assert rec.possession_points == expected_pts


def test_reconcile_td_two_point_eight_points() -> None:
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        espn_td_extra_point="two_point",
        start_period=1,
        start_clock_display="10:00",
    )
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=10, family="quick_game", play_type="pass", touchdown=True)],
        possessing_team="offense",
        feed_audit=audit,
    )
    rec = reconcile_drive(dr, espn=audit)
    assert rec.possession_points == 8


def test_reconcile_td_missed_pat_six_points() -> None:
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        espn_td_extra_point="pat_missed",
        start_period=2,
        start_clock_display="5:00",
    )
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=1, family="gap", play_type="run", touchdown=True)],
        possessing_team="offense",
        feed_audit=audit,
    )
    rec = reconcile_drive(dr, espn=audit)
    assert rec.possession_points == 6


def test_parse_espn_drive_td_extra_point_branches() -> None:
    from playcaller.live_data.espn_drive_audit_parse import parse_drive_feed_audit_from_espn_drive_dict

    two_pt = {
        "result": "TD",
        "plays": [
            {
                "type": {"text": "Passing Touchdown"},
                "text": "J.QB pass to X for 5 yards, TOUCHDOWN.",
            },
            {
                "type": {"text": "Two-Point Conversion"},
                "text": "(Shotgun) TWO-POINT CONVERSION ATTEMPT. J.QB pass to Y is complete. ATTEMPT SUCCEEDS.",
            },
        ],
    }
    assert parse_drive_feed_audit_from_espn_drive_dict(two_pt).espn_td_extra_point == "two_point"

    missed = {
        "result": "TD",
        "plays": [
            {
                "type": {"text": "Rushing Touchdown"},
                "text": "X rush for 1 yard, TOUCHDOWN. B.K extra point is No Good.",
            }
        ],
    }
    assert parse_drive_feed_audit_from_espn_drive_dict(missed).espn_td_extra_point == "pat_missed"

    pat_good = {
        "result": "TD",
        "plays": [
            {
                "type": {"text": "Passing Touchdown"},
                "text": "Pass for TD. B.K extra point is GOOD.",
            }
        ],
    }
    assert parse_drive_feed_audit_from_espn_drive_dict(pat_good).espn_td_extra_point == "pat"


def test_compute_drive_audit_threads_two_point_possession() -> None:
    from playcaller.drive_audit_report import compute_drive_audit

    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        espn_td_extra_point="two_point",
        start_period=1,
        start_clock_display="12:00",
        start_field_text="OPP 10",
    )
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=10, family="quick_game", play_type="pass", touchdown=True)],
        possessing_team="offense",
        feed_audit=audit,
    )
    g = Game.new_game()
    g.drives = [dr]
    g.offense_points = 8
    g.defense_points = 0
    rep = compute_drive_audit(g)
    assert rep.rows[0].inferred_points == 8
    assert rep.rows[0].score_after_us == 8
