"""Alignment helpers: snap_review_log rows vs retroactive replay ``play_index``."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.game import Drive, Game
from playcaller.replay.analysis_types import ActualVsReplayComparisonRow, ModelReplayStructuredResult, PreSnapContextRecord
from playcaller.review.archived_replay_juxtapose import (
    audit_rows_for_drive_epoch,
    drive_epochs_eligible_for_replay_compare,
    juxtapose_snap_review_and_replay,
    play_index_from_audit_row,
)


def test_play_index_from_audit_row() -> None:
    assert play_index_from_audit_row({"plays_at_recommend": 0}) == 1
    assert play_index_from_audit_row({"plays_at_recommend": 2}) == 3
    assert play_index_from_audit_row({}) is None
    assert play_index_from_audit_row({"plays_at_recommend": None}) is None


def test_audit_rows_for_drive_epoch_filters_and_preserves_order() -> None:
    audit = [
        {"drive_epoch": 0, "plays_at_recommend": 0, "x": 1},
        {"drive_epoch": 1, "plays_at_recommend": 0, "x": 2},
        {"drive_epoch": 0, "plays_at_recommend": 1, "x": 3},
    ]
    got = audit_rows_for_drive_epoch(audit, 0)
    assert [r["x"] for r in got] == [1, 3]


def test_drive_epochs_eligible_for_replay_compare() -> None:
    g = Game.new_game()
    g.drives = [
        Drive(plays=[], possessing_team="offense"),
        Drive(plays=[ActualPlayResult(family="inside_zone", play_type="run", yards_gained=1)], possessing_team="offense"),
    ]
    audit = [{"drive_epoch": 1, "plays_at_recommend": 0}]
    assert drive_epochs_eligible_for_replay_compare(g, audit) == [1]


def test_juxtapose_aligns_replay_by_play_index() -> None:
    pre = PreSnapContextRecord(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        quarter=1,
        seconds_remaining=900,
        score_diff=0,
        own_timeouts=3,
        opp_timeouts=3,
        plays_this_drive_before_snap=0,
        reconstruction_anchor="touchback_own_25",
    )
    structured = ModelReplayStructuredResult(
        play_family="inside_zone",
        play_call_name="test",
        bucket="standard",
        run_pass="Run",
        confidence=0.5,
        summary_bucket="run inside / gap",
    )
    replay_row = ActualVsReplayComparisonRow(
        play_index=1,
        pre_snap_context=pre,
        actual_play_summary_primary="Run",
        actual_play_summary_detail="",
        actual_structured_result={"family": "inside_zone"},
        model_replay_summary="iz",
        model_replay_structured=structured,
        actual_run_pass="Run",
        model_run_pass="Run",
        run_pass_match=True,
        family_match=True,
    )
    audit = [{"drive_epoch": 0, "plays_at_recommend": 0, "selected_family": "inside_zone"}]
    j = juxtapose_snap_review_and_replay(audit, [replay_row])
    assert len(j) == 1
    assert j[0]["play_index"] == 1
    assert j[0]["retroactive_model_replay"] == replay_row.to_dict()
    assert j[0]["snap_review_log_row"]["plays_at_recommend"] == 0


def test_juxtapose_missing_play_index_skips_replay_lookup() -> None:
    replay_row = ActualVsReplayComparisonRow(
        play_index=1,
        pre_snap_context=PreSnapContextRecord(
            territory="own",
            yardline=25,
            down=1,
            distance=10,
            quarter=1,
            seconds_remaining=900,
            score_diff=0,
            own_timeouts=3,
            opp_timeouts=3,
            plays_this_drive_before_snap=0,
            reconstruction_anchor="x",
        ),
        actual_play_summary_primary="",
        actual_play_summary_detail="",
        actual_structured_result={},
        model_replay_summary="",
        model_replay_structured=None,
        actual_run_pass=None,
        model_run_pass=None,
        run_pass_match=None,
        family_match=None,
    )
    audit = [{"drive_epoch": 0, "selected_family": "x"}]
    j = juxtapose_snap_review_and_replay(audit, [replay_row])
    assert j[0]["play_index"] is None
    assert j[0]["retroactive_model_replay"] is None


def test_build_ambient_context_uses_session_keys() -> None:
    from playcaller.review.archived_replay_juxtapose import build_ambient_context_for_model_replay
    from playcaller.streamlit_state.keys import (
        GAME_CLOCK_TOTAL_SECONDS,
        GAME_CONTEXT_QUARTER,
        GAME_SCORE_OURS,
        GAME_SCORE_THEIRS,
    )

    g = Game.new_game()
    g.offense_points = 7
    g.defense_points = 3
    ss = {
        "ui_down": 2,
        "ui_distance": 7,
        "ui_territory": "opp",
        "ui_yardline": 40,
        "ui_def_personnel": "nickel",
        "ui_box_count": 6,
        "ui_coverage_shell": "cover_2",
        "ui_safeties": "two_high",
        "ui_blitz_likely": False,
        "ui_game_period": 2,
        GAME_CONTEXT_QUARTER: 3,
        GAME_CLOCK_TOTAL_SECONDS: 120,
        GAME_SCORE_OURS: 10,
        GAME_SCORE_THEIRS: 10,
        "ui_own_tos": 2,
        "ui_opp_tos": 3,
        "ui_weather": "clear",
        "ui_qb_limited": False,
        "ui_game_mode": "normal",
        "ui_mismatch": "",
    }
    ctx = build_ambient_context_for_model_replay(ss, g)
    assert isinstance(ctx, GameContext)
    assert ctx.down == 2
    assert ctx.quarter == 3
    assert ctx.score_diff == 0
    assert ctx.plays_this_drive == 0
