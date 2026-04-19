"""Snap review lifecycle: Generate → Log pairing, supersede, undo, export."""

from __future__ import annotations

import json

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.game import Game, game_from_dict, game_to_dict
from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY, review_timeline_rows
from playcaller.evaluation.snap_review_lifecycle import (
    apply_undo_last_logged_play_to_snap_review,
    close_snap_review_row_with_logged_actual,
    record_open_snap_review_row_after_generate,
    scoreboard_snapshot_from_game,
    trim_snap_review_opens_for_play_count,
)
from playcaller.state import DriveLogger


def _minimal_ctx() -> GameContext:
    return GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )


def test_record_generate_then_log_closes_row() -> None:
    pred = FootballPlayPredictor()
    dl = DriveLogger()
    g = Game.new_game()
    g.offense_points = 7
    g.defense_points = 3
    res = pred.recommend(_minimal_ctx(), dl, g)
    record_open_snap_review_row_after_generate(
        rows=g.recommendation_audit,
        game=g,
        drive_log=dl,
        recommend_result=res,
        eval_drive_epoch=0,
        session_context={"session_game_id": "sess-1"},
    )
    row = g.recommendation_audit[0]
    assert row["status"] == "open"
    assert row["row_id"]
    assert row["snap_id"] == row["row_id"][:12]
    assert row["scoreboard_at_generate"]["offense_points"] == 7
    assert row["session_game_id"] == "sess-1"

    actual = ActualPlayResult(
        family=str(res["play_family"]),
        concept_name=str(res["play"].get("name", "")),
        play_type="run",
        yards_gained=4,
        result_type="standard",
    )
    dl.log(actual)
    assert close_snap_review_row_with_logged_actual(
        g.recommendation_audit,
        plays_after_log=len(dl.results),
        actual=actual,
    )
    assert g.recommendation_audit[0]["status"] == "closed"
    assert g.recommendation_audit[0].get("linked_actual")


def test_repeated_generate_before_log_supersedes_opens() -> None:
    pred = FootballPlayPredictor()
    dl = DriveLogger()
    g = Game.new_game()
    ctx = _minimal_ctx()
    r1 = pred.recommend(ctx, dl, g)
    record_open_snap_review_row_after_generate(
        rows=g.recommendation_audit,
        game=g,
        drive_log=dl,
        recommend_result=r1,
        eval_drive_epoch=0,
        session_context=None,
    )
    r2 = pred.recommend(ctx, dl, g)
    record_open_snap_review_row_after_generate(
        rows=g.recommendation_audit,
        game=g,
        drive_log=dl,
        recommend_result=r2,
        eval_drive_epoch=0,
        session_context=None,
    )
    assert len(g.recommendation_audit) == 2
    assert g.recommendation_audit[0]["status"] == "superseded"
    assert g.recommendation_audit[1]["status"] == "open"
    tl = review_timeline_rows(g.recommendation_audit)
    assert len(tl) == 1
    actual = ActualPlayResult(
        family=str(r2["play_family"]),
        concept_name=str(r2["play"].get("name", "")),
        play_type="run",
        yards_gained=2,
        result_type="standard",
    )
    dl.log(actual)
    close_snap_review_row_with_logged_actual(
        g.recommendation_audit,
        plays_after_log=len(dl.results),
        actual=actual,
    )
    assert g.recommendation_audit[1]["status"] == "closed"


def test_undo_voids_closed_and_trims_stale_open() -> None:
    rows: list = [
        {"status": "closed", "plays_at_recommend": 0, "linked_actual": {"family": "x"}},
        {"status": "open", "plays_at_recommend": 2},
    ]
    apply_undo_last_logged_play_to_snap_review(rows, plays_on_drive_after_undo=1)
    assert rows[0]["status"] == "void_undone"
    assert "linked_actual" not in rows[0]
    assert len(rows) == 1


def test_trim_after_drive_reset_drops_trailing_open() -> None:
    rows = [
        {"status": "closed", "plays_at_recommend": 0},
        {"status": "open", "plays_at_recommend": 3},
    ]
    trim_snap_review_opens_for_play_count(rows, plays_on_drive=0)
    assert len(rows) == 1


def test_export_snap_review_log_key_before_legacy_audit() -> None:
    g = Game.new_game()
    g.recommendation_audit = [{"snap_id": "onlylegacy", "status": "open"}]
    d = game_to_dict(g)
    keys = list(d.keys())
    assert keys.index(SNAP_REVIEW_LOG_EXPORT_KEY) < keys.index("recommendation_audit")


def test_export_import_round_trip_snap_review_rows() -> None:
    pred = FootballPlayPredictor()
    dl = DriveLogger()
    g = Game.new_game()
    res = pred.recommend(_minimal_ctx(), dl, g)
    record_open_snap_review_row_after_generate(
        rows=g.recommendation_audit,
        game=g,
        drive_log=dl,
        recommend_result=res,
        eval_drive_epoch=1,
        session_context=None,
    )
    blob = json.loads(json.dumps(game_to_dict(g)))
    assert blob[SNAP_REVIEW_LOG_EXPORT_KEY][0]["row_id"]
    g2 = game_from_dict(blob)
    assert len(g2.recommendation_audit) == 1
    assert g2.recommendation_audit[0]["drive_epoch"] == 1


def test_scoreboard_snapshot_matches_game() -> None:
    g = Game.new_game()
    g.offense_points = 14
    g.defense_points = 10
    g.quarter = 2
    g.clock_seconds_remaining = 333
    snap = scoreboard_snapshot_from_game(g)
    assert snap == {
        "offense_points": 14,
        "defense_points": 10,
        "quarter": 2,
        "clock_seconds_remaining": 333,
    }
