"""Snap vs yards predicates and Official Timeout ingest skip (J1.4)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import complete_drive_from_plays
from playcaller.live_data.espn_play_normalize import should_skip_espn_play
from playcaller.play_event_segment import (
    PlayEventSegment,
    counts_as_offensive_snap,
    counts_toward_offensive_yards,
    segment_from_actual,
)


def test_should_skip_official_timeout_without_apostrophe() -> None:
    assert should_skip_espn_play(
        {"text": "Official Timeout at 08:11.", "type": {"text": "Official Timeout"}}
    )
    assert should_skip_espn_play({"text": "official timeout at 12:00.", "type": {"text": "Timeout"}})
    assert not should_skip_espn_play(
        {"text": "(Shotgun) K.Walker left end for 60 yards, TOUCHDOWN.", "type": {"text": "Rushing Touchdown"}}
    )


def test_kickoff_and_fg_excluded_from_yards_not_snaps() -> None:
    ko = ActualPlayResult(
        yards_gained=24,
        result_type="kickoff",
        play_type="special",
        family="special_teams",
        description="[ESPN] Kickoff · +24 yds",
    )
    fg = ActualPlayResult(
        yards_gained=28,
        result_type="field_goal",
        play_type="special",
        concept_name="Field goal",
        description="[ESPN] Field goal good · +28 yds",
    )
    run = ActualPlayResult(yards_gained=59, result_type="complete", play_type="pass", family="dropback_pass")
    assert counts_toward_offensive_yards(ko) is False
    assert counts_toward_offensive_yards(fg) is False
    assert counts_toward_offensive_yards(run) is True
    assert counts_as_offensive_snap(ko) is True
    assert counts_as_offensive_snap(fg) is True
    d = complete_drive_from_plays([ko, run, fg], end_kind_override="field_goal")
    assert d.total_yards == 59
    assert d.play_count == 3


def test_admin_timeout_excluded_from_snaps_and_yards() -> None:
    admin = ActualPlayResult(
        yards_gained=0,
        result_type="unknown",
        concept_name="official timeout",
        description="[ESPN] official timeout · 0 yds — Official Timeout at 08:11.",
    )
    assert segment_from_actual(admin) == PlayEventSegment.ADMIN
    assert counts_as_offensive_snap(admin) is False
    assert counts_toward_offensive_yards(admin) is False
