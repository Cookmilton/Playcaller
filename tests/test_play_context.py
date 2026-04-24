"""Centralized per-play timing resolution (``playcaller.reconciliation.play_context``)."""

from __future__ import annotations

import pytest

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.reconciliation.drive_reconciler import FieldPosition
from playcaller.reconciliation.play_context import (
    build_pre_snap_record_for_archived_replay,
    parse_espn_clock_display_to_seconds,
    resolve_archived_pre_snap_situation,
    resolve_archived_pre_snap_timing,
)
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.game import Drive, Game


class _Rec:
    start_quarter = 2
    start_clock = "14:52"


def test_parse_clock() -> None:
    assert parse_espn_clock_display_to_seconds("12:56") == 12 * 60 + 56
    assert parse_espn_clock_display_to_seconds("0:00") == 0
    assert parse_espn_clock_display_to_seconds("") is None


def test_espn_direct_wins() -> None:
    p = ActualPlayResult(
        feed_period_number=4,
        feed_clock_display="2:31",
    )
    q, sec, clk, prov = resolve_archived_pre_snap_timing(p, None, 3, _Rec())
    assert q == 4
    assert clk == "2:31"
    assert sec == 2 * 60 + 31
    assert prov.get("quarter") == "espn"
    assert prov.get("clock") == "espn"


def test_no_default_q1_when_missing() -> None:
    p = ActualPlayResult()
    q, sec, clk, prov = resolve_archived_pre_snap_timing(p, None, 5, _Rec())
    assert q is None
    assert sec is None
    assert clk is None
    assert "quarter" not in prov or prov.get("quarter") != "default"


def test_drive_fallback_first_play_only() -> None:
    p = ActualPlayResult()
    q, sec, clk, prov = resolve_archived_pre_snap_timing(p, None, 0, _Rec())
    assert q == 2
    assert clk == "14:52"
    assert prov.get("quarter") == "drive_fallback"


def test_reconstructed_clock_from_prior() -> None:
    prior = ActualPlayResult(feed_period_number=3, feed_clock_display="1:00")
    cur = ActualPlayResult(feed_period_number=3)  # clock omitted
    q, sec, clk, prov = resolve_archived_pre_snap_timing(cur, prior, 1, _Rec())
    assert q == 3
    assert prov.get("clock") == "reconstructed"
    assert sec == 60 - 38
    assert clk == "0:22"


def test_reconcile_drive_smoke_with_plays() -> None:
    g = Game.new_game()
    dr = Drive(
        plays=[ActualPlayResult(family="inside_zone", play_type="run", yards_gained=4)],
        possessing_team="offense",
    )
    r = reconcile_drive(dr, espn=None)
    assert r.start_quarter >= 0


class _RecField:
    start_field_position = FieldPosition(display="GB 17", yard_line=83)


def test_situation_espn_beats_chain() -> None:
    p = ActualPlayResult(
        feed_presnap_down=2,
        feed_presnap_distance=7,
        feed_presnap_territory="opponents",
        feed_presnap_yardline=42,
        feed_possession_team_abbr="GB",
        feed_home_score=7,
        feed_away_score=3,
    )
    d, dist, t, yl, g2g, hs, aw, poss, opp, prov = resolve_archived_pre_snap_situation(
        p,
        2,
        ("own", 25, 1, 10),
        _RecField(),
        offense_team_abbr="GB",
        defense_team_abbr="DET",
    )
    assert d == 2 and dist == 7 and t == "opponents" and yl == 42
    assert prov.get("down") == "espn" and prov.get("distance") == "espn"
    assert prov.get("territory") == "espn"
    assert poss == "GB" and opp == "DET"
    assert hs == 7 and aw == 3


def test_situation_special_teams_not_applicable_down() -> None:
    p = ActualPlayResult(
        family="special_teams",
        play_type="special",
        result_type="punt",
        feed_presnap_territory="own",
        feed_presnap_yardline=17,
        feed_home_score=0,
        feed_away_score=0,
    )
    d, dist, _, _, _, _, _, _, _, prov = resolve_archived_pre_snap_situation(
        p, 0, ("own", 25, 1, 10), _RecField(), offense_team_abbr="GB"
    )
    assert d is None and dist is None
    assert prov.get("down") == "not_applicable"


def test_situation_first_play_drive_fallback_when_empty() -> None:
    p = ActualPlayResult()
    d, dist, t, yl, _, _, _, _, _, prov = resolve_archived_pre_snap_situation(
        p, 0, None, _RecField(), offense_team_abbr="GB"
    )
    assert d == 1 and dist == 10
    assert t == "own" and yl == 17
    assert prov.get("down") == "drive_fallback"
    assert prov.get("territory") == "drive_fallback"


def test_situation_play_five_unknown_without_chain_or_espn() -> None:
    p = ActualPlayResult()
    d, dist, t, yl, _, _, _, _, _, prov = resolve_archived_pre_snap_situation(
        p, 5, None, _RecField(), offense_team_abbr="GB"
    )
    assert d is None and dist is None and t is None and yl is None
    assert prov.get("down") == "unknown"


def test_situation_scores_threaded_from_prior_when_missing() -> None:
    prior = ActualPlayResult(
        feed_home_score=7,
        feed_away_score=3,
        feed_period_number=2,
        feed_clock_display="10:00",
    )
    cur = ActualPlayResult(
        feed_presnap_down=1,
        feed_presnap_distance=10,
        feed_presnap_territory="own",
        feed_presnap_yardline=25,
        feed_period_number=2,
        feed_clock_display="9:45",
    )
    _, _, _, _, _, hs, aw, _, _, prov = resolve_archived_pre_snap_situation(
        cur, 1, ("own", 25, 1, 10), _RecField(), prior_play=prior, offense_team_abbr="GB"
    )
    assert hs == 7 and aw == 3
    assert prov.get("home_score") == "computed"
    assert prov.get("away_score") == "computed"


def test_situation_scores_partial_fill_from_prior() -> None:
    prior = ActualPlayResult(feed_home_score=14, feed_away_score=10)
    cur = ActualPlayResult(feed_home_score=14, feed_away_score=None)
    _, _, _, _, _, hs, aw, _, _, prov = resolve_archived_pre_snap_situation(
        cur, 2, ("own", 25, 1, 10), _RecField(), prior_play=prior, offense_team_abbr="GB"
    )
    assert hs == 14 and aw == 10
    assert prov.get("home_score") == "espn"
    assert prov.get("away_score") == "computed"


def test_build_pre_snap_record_merges_computed_score_provenance() -> None:
    prior = ActualPlayResult(
        feed_home_score=0,
        feed_away_score=0,
        feed_period_number=1,
        feed_clock_display="14:00",
    )
    cur = ActualPlayResult(feed_period_number=1, feed_clock_display="13:30")
    ambient = GameContext(down=1, distance=10, yardline=25, territory="own")
    rec = build_pre_snap_record_for_archived_replay(
        chain_tuple=("own", 25, 1, 10),
        play_idx0=1,
        play=cur,
        prior_play=prior,
        ambient_ctx=ambient,
        score_diff=0,
        plays_before=1,
        reconciled=_RecField(),
        reconstruction_anchor="test",
        reconstruction_notes="",
        offense_team_abbr="GB",
    )
    assert rec.home_score_snap == 0 and rec.away_score_snap == 0
    prov = dict(rec.snap_provenance)
    assert prov.get("home_score") == "computed"
    assert prov.get("away_score") == "computed"
