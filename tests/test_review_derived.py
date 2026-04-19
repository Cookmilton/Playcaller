"""Tests for JSON-backed game review derivation (no Streamlit)."""

from __future__ import annotations

from playcaller.domain import GameContext
from playcaller.evaluation.audit import audit_record_from_recommendation
from playcaller.game import Game
from playcaller.review.derived import (
    ReviewFilter,
    build_drive_summaries,
    build_play_snapshots,
    derive_key_moments,
    format_field_position_sentence,
    format_play_result_label,
    format_situation_line,
    linked_actual_to_play,
    matching_audit_indices,
    pattern_bullets_from_snapshots,
    play_by_play_lines,
)


def test_format_situation_line_basic() -> None:
    pre = {
        "down": 2,
        "distance": 7,
        "territory": "opponents",
        "yardline": 32,
        "quarter": 3,
        "seconds_remaining": 245,
    }
    s = format_situation_line(pre)
    assert "2 & 7" in s and "Opponent 32" in s and "Q3" in s


def test_format_field_position_red_zone_goal_to_go() -> None:
    pre = {
        "down": 1,
        "distance": 8,
        "territory": "opponents",
        "yardline": 6,
        "quarter": 2,
        "seconds_remaining": 900,
    }
    fs = format_field_position_sentence(pre)
    assert "red zone" in fs.lower()
    assert "goal-to-go" in fs.lower()


def test_linked_actual_round_trip() -> None:
    d = {
        "concept_name": "Stick",
        "family": "quick_game",
        "play_type": "pass",
        "result_type": "first_down",
        "yards_gained": 12,
        "pass_result": "complete",
        "touchdown": False,
        "turnover": False,
        "sack": False,
    }
    ap = linked_actual_to_play(d)
    assert ap.family == "quick_game"
    label = format_play_result_label(d)
    assert "12" in label or "complete" in label.lower()


def test_build_play_snapshots_flags() -> None:
    g = Game.new_game()
    ctx = GameContext(down=3, distance= 4, yardline= 12, territory="opponents")
    row_open = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"quick_game": 1.0},
            "play": {"name": "Stick"},
            "bucket": "standard",
            "play_family": "quick_game",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
    )
    row_closed = {**row_open, "status": "closed"}
    row_closed["linked_actual"] = {
        "concept_name": "Mesh",
        "family": "quick_game",
        "play_type": "pass",
        "result_type": "touchdown",
        "yards_gained": 18,
        "pass_result": "complete",
        "touchdown": True,
        "turnover": False,
        "sack": False,
    }
    snaps = build_play_snapshots([row_open, row_closed])
    assert snaps[0].is_red_zone
    assert snaps[0].is_third_down
    assert "red_zone" in snaps[0].flags
    assert snaps[1].outcome_line
    assert "touchdown" in snaps[1].flags
    assert "explosive" in snaps[1].flags


def test_matching_audit_indices() -> None:
    g = Game.new_game()
    ctx = GameContext(down=4, distance= 1, yardline= 40, territory="own")
    r = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"power": 1.0},
            "play": {"name": "Power"},
            "bucket": "short",
            "play_family": "power",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=1,
        game_id=g.game_id,
    )
    closed = {
        **r,
        "status": "closed",
        "linked_actual": {
            "family": "power",
            "play_type": "run",
            "result_type": "first_down",
            "yards_gained": 2,
            "touchdown": False,
            "turnover": False,
            "sack": False,
        },
    }
    snaps = build_play_snapshots([r, closed])
    m = matching_audit_indices(snaps, ReviewFilter(tags_any=("4th_down",)))
    assert m == [0, 1]
    m2 = matching_audit_indices(snaps, ReviewFilter(require_closed=True, tags_any=("4th_down",)))
    assert m2 == [1]


def test_build_drive_summaries_links_logged_result() -> None:
    g = Game.new_game()
    from playcaller.game import Drive, drive_result_for_kind, DRIVE_END_TOUCHDOWN
    from playcaller.domain import ActualPlayResult

    g.drives = [
        Drive(
            plays=[ActualPlayResult(family="inside_zone", yards_gained= 4, play_type="run")],
            result=drive_result_for_kind(DRIVE_END_TOUCHDOWN, []),
        )
    ]
    ctx = GameContext(down=1, distance= 10, yardline= 25, territory="own")
    aud = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"inside_zone": 1.0},
            "play": {"name": "IZ"},
            "bucket": "standard",
            "play_family": "inside_zone",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
    )
    summaries = build_drive_summaries(g, [aud])
    assert len(summaries) == 1
    assert summaries[0].drive_epoch == 0
    assert summaries[0].logged_drive_result is not None
    assert "Touchdown" in summaries[0].logged_drive_result


def test_derive_key_moments_turnover() -> None:
    g = Game.new_game()
    ctx = GameContext(down=2, distance= 8, yardline= 45, territory="own")
    aud = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"dropback_pass": 1.0},
            "play": {"name": " verts"},
            "bucket": "standard",
            "play_family": "dropback_pass",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
    )
    closed = {
        **aud,
        "status": "closed",
        "linked_actual": {
            "family": "dropback_pass",
            "play_type": "pass",
            "result_type": "interception",
            "yards_gained": 0,
            "pass_result": "intercepted",
            "turnover": True,
            "turnover_kind": "interception",
        },
    }
    km = derive_key_moments([closed])
    assert any(m.kind == "turnover" for m in km)


def test_play_by_play_lines() -> None:
    g = Game.new_game()
    ctx = GameContext(down=1, distance= 10, yardline= 25, territory="own")
    aud = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"inside_zone": 1.0},
            "play": {"name": "IZ"},
            "bucket": "standard",
            "play_family": "inside_zone",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
    )
    lines = play_by_play_lines([aud])
    assert len(lines) == 1
    assert "Snap 1" in lines[0]


def test_pattern_bullets_red_zone() -> None:
    g = Game.new_game()
    ctx = GameContext(down=1, distance= 10, yardline= 15, territory="opponents")
    base = audit_record_from_recommendation(
        result={
            "ctx": ctx,
            "scores": {"quick_game": 1.0},
            "play": {"name": "Stick"},
            "bucket": "rz",
            "play_family": "quick_game",
            "fourth_down": {},
            "model": {},
        },
        plays_at_recommend=0,
        drive_epoch=0,
        game_id=g.game_id,
    )
    a = {
        **base,
        "status": "closed",
        "linked_actual": {
            "family": "quick_game",
            "play_type": "pass",
            "result_type": "incomplete",
            "yards_gained": 0,
            "pass_result": "incomplete",
        },
    }
    b = {
        **base,
        "snap_id": "otherid12",
        "status": "closed",
        "linked_actual": {
            "family": "inside_zone",
            "play_type": "run",
            "result_type": "first_down",
            "yards_gained": 6,
        },
    }
    snaps = build_play_snapshots([a, b])
    bullets = pattern_bullets_from_snapshots(snaps)
    assert any("Red zone" in b for b in bullets)
