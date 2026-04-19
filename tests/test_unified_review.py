"""Unified review rows, mode resolution, filters, and metrics."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import Drive, Game
from playcaller.replay.replay_taxonomy import model_summary_bucket_from_audit_row
from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY
from playcaller.review.unified_review import (
    ReviewMode,
    ReviewRowFilter,
    build_unified_rows_from_audit,
    compute_review_summary_metrics,
    filter_unified_rows,
    group_unified_rows_by_drive,
    resolve_review_mode,
)


def test_resolve_mode_true_stored_from_snap_key() -> None:
    g = Game()
    payload = {SNAP_REVIEW_LOG_EXPORT_KEY: [{"status": "open", "drive_epoch": 0, "plays_at_recommend": 0}]}
    g.recommendation_audit = list(payload[SNAP_REVIEW_LOG_EXPORT_KEY])
    t = g.recommendation_audit
    assert resolve_review_mode(g, upload_payload=payload, timeline=t) == ReviewMode.TRUE_STORED


def test_resolve_mode_legacy_from_audit_only_payload() -> None:
    g = Game()
    rows = [{"status": "open", "drive_epoch": 0, "plays_at_recommend": 0}]
    g.recommendation_audit = list(rows)
    payload = {"recommendation_audit": rows}
    assert resolve_review_mode(g, upload_payload=payload, timeline=g.recommendation_audit) == ReviewMode.LEGACY_STORED


def test_resolve_mode_session_defaults_to_true_when_timeline() -> None:
    g = Game()
    g.recommendation_audit = [{"status": "closed", "drive_epoch": 0}]
    assert resolve_review_mode(g, upload_payload=None, timeline=g.recommendation_audit) == ReviewMode.TRUE_STORED


def test_resolve_mode_replay_when_no_timeline_but_plays() -> None:
    g = Game()
    g.recommendation_audit = []
    g.drives = [
        Drive(
            plays=[ActualPlayResult(family="inside_zone", play_type="run", yards_gained=2)],
            possessing_team="offense",
        )
    ]
    assert resolve_review_mode(g, upload_payload=None, timeline=[]) == ReviewMode.REPLAY_ONLY


def test_resolve_mode_not_reviewable() -> None:
    g = Game()
    assert resolve_review_mode(g, upload_payload=None, timeline=[]) == ReviewMode.NOT_REVIEWABLE


def test_model_summary_bucket_from_audit_row_smoke() -> None:
    row = {"selected_family": "quick_game", "bucket": "short_yardage", "selected_play_name": "Stick"}
    b = model_summary_bucket_from_audit_row(row)
    assert "pass" in b.lower() or "short" in b.lower()


def test_build_unified_rows_from_audit_family_match() -> None:
    g = Game()
    g.drives = [Drive(plays=[], possessing_team="offense")]
    pre = {"down": 1, "distance": 10, "yardline": 25, "territory": "own", "quarter": 1, "seconds_remaining": 900}
    audit_row = {
        "status": "closed",
        "drive_epoch": 0,
        "plays_at_recommend": 0,
        "pre_snap": pre,
        "selected_family": "inside_zone",
        "selected_play_name": "Inside zone",
        "bucket": "medium_yardage",
        "linked_actual": {
            "family": "inside_zone",
            "play_type": "run",
            "yards_gained": 4,
            "result_type": "positive",
        },
    }
    rows = build_unified_rows_from_audit(g, [audit_row], ReviewMode.TRUE_STORED, our_coached_espn_id="")
    assert len(rows) == 1
    assert rows[0].comparison.family_match is True
    assert rows[0].is_historical is True
    assert rows[0].is_replay is False


def test_filter_mismatch_only() -> None:
    g = Game()
    pre = {"down": 3, "distance": 2, "yardline": 40, "territory": "own", "quarter": 2, "seconds_remaining": 600}
    open_row = {
        "status": "open",
        "drive_epoch": 0,
        "plays_at_recommend": 0,
        "pre_snap": pre,
        "selected_family": "dropback_pass",
        "bucket": "short_yardage",
    }
    closed_mismatch = {
        "status": "closed",
        "drive_epoch": 0,
        "plays_at_recommend": 1,
        "pre_snap": pre,
        "selected_family": "dropback_pass",
        "bucket": "short_yardage",
        "linked_actual": {
            "family": "inside_zone",
            "play_type": "run",
            "yards_gained": 3,
            "result_type": "first_down",
        },
    }
    u = build_unified_rows_from_audit(g, [open_row, closed_mismatch], ReviewMode.TRUE_STORED)
    flt = ReviewRowFilter(mismatch_only=True)
    out = filter_unified_rows(u, flt)
    assert len(out) == 1
    assert out[0].comparison.family_match is False


def test_group_unified_rows_by_drive() -> None:
    g = Game()
    rows = build_unified_rows_from_audit(
        g,
        [
            {"status": "open", "drive_epoch": 1, "plays_at_recommend": 0, "pre_snap": {}},
            {"status": "open", "drive_epoch": 0, "plays_at_recommend": 0, "pre_snap": {}},
        ],
        ReviewMode.TRUE_STORED,
    )
    g = group_unified_rows_by_drive(rows)
    assert list(g.keys()) == [0, 1]


def test_summary_metrics_rates() -> None:
    g = Game()
    pre = {"down": 1, "distance": 10, "yardline": 25, "territory": "own", "quarter": 1, "seconds_remaining": 900}
    a = {
        "status": "closed",
        "drive_epoch": 0,
        "plays_at_recommend": 0,
        "pre_snap": pre,
        "selected_family": "inside_zone",
        "bucket": "medium_yardage",
        "linked_actual": {
            "family": "inside_zone",
            "play_type": "run",
            "yards_gained": 3,
            "result_type": "positive",
        },
    }
    u = build_unified_rows_from_audit(g, [a, a], ReviewMode.TRUE_STORED)
    m = compute_review_summary_metrics(u)
    assert m.total_rows == 2
    assert m.drives_with_rows == 1
    assert m.family_match_rate == 1.0
