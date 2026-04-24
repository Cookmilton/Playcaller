"""Replay context line formatting (no fake Q1 / 15:00 for every row)."""

from __future__ import annotations

from playcaller.replay.analysis_types import ActualVsReplayComparisonRow, PreSnapContextRecord


def test_compact_line_shows_feed_quarter_clock() -> None:
    from playcaller.ui.previous_drives_render import _compact_snap_context_line

    pre = PreSnapContextRecord(
        territory="own",
        yardline=28,
        down=1,
        distance=10,
        quarter=4,
        seconds_remaining=12 * 60 + 56,
        score_diff=0,
        own_timeouts=3,
        opp_timeouts=3,
        plays_this_drive_before_snap=0,
        reconstruction_anchor="x",
        clock_display="12:56",
        home_score_snap=24,
        away_score_snap=31,
        snap_provenance=(("quarter", "espn"), ("clock", "espn")),
        possession_team_abbrev="GB",
    )
    row = ActualVsReplayComparisonRow(
        play_index=1,
        pre_snap_context=pre,
        actual_play_summary_primary="Run",
        actual_play_summary_detail="",
        actual_structured_result={},
        model_replay_summary="",
        model_replay_structured=None,
        actual_run_pass="Run",
        model_run_pass="Run",
        run_pass_match=True,
        family_match=True,
        replay_error=None,
    )
    line = _compact_snap_context_line(row)
    assert "Q4" in line
    assert "12:56" in line
    assert "GB 28" in line
    assert "Q1" not in line or "Q4" in line  # must not read as Q1


def test_not_all_plays_identical_context_canary() -> None:
    """Regression: distinct feed quarters/clocks must not all collapse to the same string."""
    from playcaller.ui.previous_drives_render import _compact_snap_context_line

    lines = []
    for q, clk in ((1, "15:00"), (2, "8:12"), (4, "12:56")):
        pre = PreSnapContextRecord(
            territory="own",
            yardline=25,
            down=1,
            distance=10,
            quarter=q,
            seconds_remaining=None,
            score_diff=0,
            own_timeouts=3,
            opp_timeouts=3,
            plays_this_drive_before_snap=0,
            reconstruction_anchor="x",
            clock_display=clk,
            snap_provenance=(),
        )
        row = ActualVsReplayComparisonRow(
            play_index=1,
            pre_snap_context=pre,
            actual_play_summary_primary="x",
            actual_play_summary_detail="",
            actual_structured_result={},
            model_replay_summary="",
            model_replay_structured=None,
            actual_run_pass=None,
            model_run_pass=None,
            run_pass_match=None,
            family_match=None,
            replay_error=None,
        )
        lines.append(_compact_snap_context_line(row))
    assert len(set(lines)) == 3


def test_goal_to_go_segment() -> None:
    from playcaller.ui.previous_drives_render import _compact_snap_context_line

    pre = PreSnapContextRecord(
        territory="opponents",
        yardline=6,
        down=1,
        distance=6,
        quarter=3,
        seconds_remaining=400,
        score_diff=0,
        own_timeouts=3,
        opp_timeouts=3,
        plays_this_drive_before_snap=2,
        reconstruction_anchor="x",
        clock_display="7:25",
        opponent_team_abbrev="DET",
        goal_to_go=True,
        snap_provenance=(("quarter", "espn"), ("clock", "espn"), ("down", "espn")),
    )
    row = ActualVsReplayComparisonRow(
        play_index=2,
        pre_snap_context=pre,
        actual_play_summary_primary="Run",
        actual_play_summary_detail="",
        actual_structured_result={"result_type": "run"},
        model_replay_summary="",
        model_replay_structured=None,
        actual_run_pass="Run",
        model_run_pass="Run",
        run_pass_match=True,
        family_match=True,
        replay_error=None,
    )
    line = _compact_snap_context_line(row)
    assert "1st & Goal" in line
    assert "DET 6" in line


def test_special_teams_compact_line_uses_label() -> None:
    from playcaller.ui.previous_drives_render import _compact_snap_context_line

    pre = PreSnapContextRecord(
        territory="own",
        yardline=17,
        down=None,
        distance=None,
        quarter=1,
        seconds_remaining=800,
        score_diff=0,
        own_timeouts=3,
        opp_timeouts=3,
        plays_this_drive_before_snap=0,
        reconstruction_anchor="x",
        clock_display="14:51",
        possession_team_abbrev="GB",
        snap_provenance=(("down", "not_applicable"), ("distance", "not_applicable")),
    )
    row = ActualVsReplayComparisonRow(
        play_index=1,
        pre_snap_context=pre,
        actual_play_summary_primary="Punt",
        actual_play_summary_detail="",
        actual_structured_result={"result_type": "punt"},
        model_replay_summary="",
        model_replay_structured=None,
        actual_run_pass=None,
        model_run_pass=None,
        run_pass_match=None,
        family_match=None,
        replay_error="Special teams — no offensive model call",
    )
    line = _compact_snap_context_line(row)
    assert "Punt from GB 17" in line
    assert "& 10" not in line
