"""Recommendation audit, metrics, calibration."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.evaluation import (
    append_open_audit,
    audit_record_from_recommendation,
    evaluate_audit_records,
    link_open_audit_to_actual,
    load_calibration_profile,
    next_review_ordinal,
    summarize_audit_session,
    supersede_open_audits_for_snap,
    trim_stale_open_audits,
    void_last_closed_audit,
)
from playcaller.evaluation.calibration import CalibrationProfile
from playcaller.game import Game, game_from_dict, game_to_json
from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY, review_timeline_rows
from playcaller.evaluation.snap_review_lifecycle import scoreboard_snapshot_from_game
from playcaller.state import DriveLogger


def test_audit_link_and_metrics() -> None:
    pred = FootballPlayPredictor()
    dl = DriveLogger()
    g = Game.new_game()
    ctx = GameContext(
        down=2,
        distance=7,
        yardline=45,
        territory="opponents",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )
    res = pred.recommend(ctx, dl, g)
    audit: list = []
    append_open_audit(
        audit,
        audit_record_from_recommendation(
            result=res,
            plays_at_recommend=len(dl.results),
            drive_epoch=0,
            game_id=g.game_id,
        ),
    )
    actual = ActualPlayResult(
        concept_name=str(res["play"].get("name", "")),
        family=str(res["play_family"]),
        play_type="pass",
        yards_gained=8,
        result_type="first_down",
    )
    dl.log(actual)
    assert link_open_audit_to_actual(audit, plays_after_log=len(dl.results), actual=actual) is not None
    assert audit[0]["status"] == "closed"
    assert audit[0].get("completed") is True
    assert audit[0].get("actual_result") is not None
    assert audit[0]["actual_result"]["yards_gained"] == 8
    assert audit[0].get("model_recommendation", {}).get("play_call") is not None
    ev = evaluate_audit_records(audit)
    assert ev["family_match_count"] == 1
    assert ev["n_closed_vs_actual"] == 1


def test_supersede_open_audits_same_snap() -> None:
    audit: list = [
        {
            "status": "open",
            "drive_epoch": 0,
            "plays_at_recommend": 0,
            "selected_family": "inside_zone",
        }
    ]
    supersede_open_audits_for_snap(audit, drive_epoch=0, plays_at_recommend=0)
    assert audit[0]["status"] == "superseded"
    append_open_audit(
        audit,
        {
            "status": "open",
            "drive_epoch": 0,
            "plays_at_recommend": 0,
            "selected_family": "quick_game",
            "review_ordinal": next_review_ordinal(audit),
        },
    )
    assert len(audit) == 2
    assert audit[1]["status"] == "open"


def test_evaluate_audit_records_ignores_superseded() -> None:
    rows = [
        {
            "status": "superseded",
            "selected_family": "inside_zone",
        },
        {
            "status": "closed",
            "selected_family": "quick_game",
            "linked_actual": {"family": "quick_game"},
        },
    ]
    ev = evaluate_audit_records(rows)
    assert ev["family_match_count"] == 1


def test_void_undo_and_trim() -> None:
    audit = [
        {"status": "closed", "linked_actual": {"family": "inside_zone"}, "plays_at_recommend": 0},
        {"status": "open", "plays_at_recommend": 2},
    ]
    void_last_closed_audit(audit)
    assert audit[0]["status"] == "void_undone"
    assert "linked_actual" not in audit[0]
    trim_stale_open_audits(audit, plays_on_drive=1)
    assert len(audit) == 1


def test_calibration_apply() -> None:
    cal = CalibrationProfile.from_dict({"family_offsets": {"inside_zone": 0.05}})
    ctx = GameContext(
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
    scores = {"inside_zone": 0.5, "quick_game": 0.5}
    out = cal.apply(scores, ctx, "medium_yardage")
    assert out["inside_zone"] > 0.5
    assert out["quick_game"] == 0.5


def test_summarize_audit_session_falls_back_to_game_metadata() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "Owls"
    g.session_metadata["game_date"] = "2026-09-01"
    g.session_metadata["is_simulated"] = True
    lines = summarize_audit_session(
        [{"status": "open", "selected_family": "inside_zone"}],
        session_metadata=g.session_metadata,
    )
    assert "Session game:" in lines
    assert "Owls" in lines


def test_game_json_round_trip_audit() -> None:
    g = Game.new_game()
    g.recommendation_audit = [
        {"snap_id": "abc", "status": "open", "selected_family": "inside_zone"}
    ]
    s = game_to_json(g)
    blob = json.loads(s)
    assert blob["recommendation_audit"] == blob["snap_review_log"]
    g2 = game_from_dict(blob)
    assert len(g2.recommendation_audit) == 1
    assert g2.recommendation_audit[0]["snap_id"] == "abc"


def test_game_from_dict_prefers_snap_review_log() -> None:
    g = game_from_dict(
        {
            "game_id": "x1",
            "recommendation_audit": [{"snap_id": "legacy"}],
            "snap_review_log": [{"snap_id": "primary"}],
            "drives": [],
        }
    )
    assert g.recommendation_audit[0]["snap_id"] == "primary"


def test_export_after_generate_and_log_is_review_timeline_ready() -> None:
    """Normal Generate → Log → JSON matches Review Session expectations (closed row in snap_review_log)."""
    pred = FootballPlayPredictor()
    dl = DriveLogger()
    g = Game.new_game()
    g.possession = "offense"
    ctx = GameContext(
        down=2,
        distance=7,
        yardline=45,
        territory="opponents",
        def_personnel="nickel",
        box_count=7,
        coverage_shell="cover_3",
        blitz_likely=False,
        safeties="single_high",
    )
    res = pred.recommend(ctx, dl, g)
    de = 0
    pat = len(dl.results)
    supersede_open_audits_for_snap(g.recommendation_audit, drive_epoch=de, plays_at_recommend=pat)
    append_open_audit(
        g.recommendation_audit,
        audit_record_from_recommendation(
            result=res,
            plays_at_recommend=pat,
            drive_epoch=de,
            game_id=g.game_id,
            review_ordinal=next_review_ordinal(g.recommendation_audit),
            team_possession=g.possession,
            scoreboard_at_generate=scoreboard_snapshot_from_game(g),
        ),
    )
    actual = ActualPlayResult(
        concept_name=str(res["play"].get("name", "")),
        family=str(res["play_family"]),
        play_type="pass",
        yards_gained=8,
        result_type="first_down",
    )
    dl.log(actual)
    assert link_open_audit_to_actual(
        g.recommendation_audit, plays_after_log=len(dl.results), actual=actual
    ) is not None
    payload = json.loads(game_to_json(g))
    assert payload[SNAP_REVIEW_LOG_EXPORT_KEY] == payload["recommendation_audit"]
    assert len(payload[SNAP_REVIEW_LOG_EXPORT_KEY]) == 1
    assert payload[SNAP_REVIEW_LOG_EXPORT_KEY][0]["status"] == "closed"
    assert payload[SNAP_REVIEW_LOG_EXPORT_KEY][0].get("team_possession") == "offense"
    assert payload[SNAP_REVIEW_LOG_EXPORT_KEY][0].get("row_id")
    assert (
        payload[SNAP_REVIEW_LOG_EXPORT_KEY][0].get("snap_id")
        == payload[SNAP_REVIEW_LOG_EXPORT_KEY][0]["row_id"][:12]
    )
    assert "scoreboard_at_generate" in payload[SNAP_REVIEW_LOG_EXPORT_KEY][0]
    g2 = game_from_dict(payload)
    timeline = review_timeline_rows(g2.recommendation_audit)
    assert len(timeline) == 1
    assert timeline[0]["status"] == "closed"
    assert "linked_actual" in timeline[0]


def test_load_calibration_profile_missing_file() -> None:
    assert load_calibration_profile(Path("/nonexistent/calibration_xyz.json")) is None
