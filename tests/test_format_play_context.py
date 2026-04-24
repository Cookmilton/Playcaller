"""Canonical Review Session context line (``format_play_context``)."""

from __future__ import annotations

from playcaller.game import Drive, Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.ui.format_play_context import format_play_context


def test_offense_line_uses_ordinal_down_and_en_dash_score() -> None:
    g = Game.new_game()
    g.offense_points = 24
    g.defense_points = 17
    pre = {
        "quarter": 3,
        "seconds_remaining": 445,
        "down": 1,
        "distance": 10,
        "territory": "own",
        "yardline": 28,
    }
    s = format_play_context(pre, PlayEventSegment.OFFENSE, game=g, drive_id=0)
    assert "Q3 7:25" in s
    assert "1st & 10" in s
    assert "24–17" in s


def test_possession_abbr_from_drive_feed_team() -> None:
    g = Game.new_game()
    g.offense_points = 0
    g.defense_points = 0
    g.drives = [Drive(feed_team_abbr="GB")]
    pre = {
        "quarter": 1,
        "seconds_remaining": 900,
        "down": 2,
        "distance": 7,
        "territory": "own",
        "yardline": 40,
    }
    s = format_play_context(pre, PlayEventSegment.OFFENSE, game=g, drive_id=0)
    assert "GB 40" in s


def test_special_teams_line_omits_down_distance() -> None:
    g = Game.new_game()
    pre = {"quarter": 4, "seconds_remaining": 120, "down": 1, "distance": 10, "territory": "own", "yardline": 35}
    s = format_play_context(pre, PlayEventSegment.PUNT, game=g, drive_id=0)
    assert "Punt" in s
    assert "1st" not in s
