"""Archived drives ↔ drive audit lens mapping, explanations, reconciliation copy."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.drive_audit_report import (
    audit_actionable_explanation_lines,
    audit_status_header_tag,
    audit_status_kind,
    compute_drive_audit,
    filter_archived_indices_by_audit_lens,
    filter_audit_rows_for_lens,
    score_reconciliation_summary_lines,
)
from playcaller.game import DriveFeedAuditSnapshot, Game, complete_drive_from_plays


def test_filter_archived_indices_respects_feed_and_lens() -> None:
    g = Game.new_game()
    d_our = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=6,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="offense",
    )
    d_opp = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=0, family="punt", play_type="special", touchdown=False)],
        possessing_team="defense",
    )
    g.drives = [d_our, d_opp]
    g.offense_points = 7
    g.defense_points = 0
    rep = compute_drive_audit(g)
    # Feed scope "our" → index 0 only; lens "all" + show_all True → both rows pass if in base
    base = [0]
    assert filter_archived_indices_by_audit_lens(base_indices=base, report=rep, show_all=True, chip="all") == [0]
    # Flagged-only: first row may be clean — filter drops clean drives
    flagged_only = filter_archived_indices_by_audit_lens(
        base_indices=[0, 1], report=rep, show_all=False, chip="all"
    )
    assert all(rep.rows[i].severity != "clean" for i in flagged_only)


def test_audit_status_kind_and_header_tag() -> None:
    g = Game.new_game()
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Punt",
        espn_result_code="PUNT",
        start_period=1,
        start_clock_display="12:00",
        start_field_text="NYG 25",
    )
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=40,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="offense",
        feed_audit=audit,
    )
    g.drives = [d]
    g.offense_points = 7
    g.defense_points = 0
    rep = compute_drive_audit(g)
    r0 = rep.rows[0]
    assert r0.outcome_mismatch is True
    assert audit_status_kind(r0) == "outcome_mismatch"
    assert audit_status_header_tag(r0) == "ESPN≠model"
    assert r0.inferred_outcome_code == "TD"
    assert r0.espn_outcome_code == "PUNT"


def test_actionable_lines_for_outcome_mismatch() -> None:
    g = Game.new_game()
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Field Goal",
        espn_result_code="FG",
        start_period=2,
        start_clock_display="8:00",
        start_field_text="OPP 30",
    )
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=3, family="inside_run", play_type="run", touchdown=False)],
        possessing_team="offense",
        feed_audit=audit,
    )
    g.drives = [d]
    g.offense_points = 3
    g.defense_points = 0
    rep = compute_drive_audit(g)
    lines = audit_actionable_explanation_lines(rep.rows[0])
    assert lines
    assert any("FG" in x or "inferred" in x for x in lines)


def test_score_reconciliation_summary_global_mismatch() -> None:
    g = Game.new_game()
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=1,
                family="inside_run",
                play_type="run",
                touchdown=True,
            )
        ],
        possessing_team="offense",
    )
    g.drives = [d]
    g.offense_points = 0
    g.defense_points = 0
    rep = compute_drive_audit(g)
    summ = score_reconciliation_summary_lines(g, rep)
    assert any("Session scoreboard" in s for s in summ)
    assert any("First **score conflict**" in s for s in summ)


def test_filter_audit_rows_lens_chip_score() -> None:
    g = Game.new_game()
    g.offense_points = 10
    g.defense_points = 0
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=10,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="offense",
    )
    g.drives = [d]
    rep = compute_drive_audit(g)
    crit = filter_audit_rows_for_lens(rep, show_all=True, chip="score")
    assert len(crit) == 1
    assert crit[0].severity == "critical"
