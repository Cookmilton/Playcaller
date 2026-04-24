"""
End-to-end archived replay: per-play quarter/game clock from ESPN feed.

Loads a real multi-play drive from the Packers @ Lions summary fixture, builds
``ActualPlayResult`` rows via the same ``espn_play_to_actual`` path as ingest,
then runs ``comparison_rows_for_archived_drive``. Regresses against a single
ambient Q/clock being copied onto every row.
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.domain import GameContext
from playcaller.engine import FootballPlayPredictor
from playcaller.game import Game
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.replay.previous_drive_replay import comparison_rows_for_archived_drive
from playcaller.ui.previous_drives_render import _compact_snap_context_line

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"
EVENT_ID = "401772891"
GB_ID = "9"


def _load_game_with_merged_feed() -> Game:
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    fds = extract_completed_drives_from_espn_payload(data, event_id=EVENT_ID)
    g = Game.new_game()
    g.offense_points = 31
    g.defense_points = 24
    merge_completed_espn_drives_into_game(g, {}, fds, coached_team_id=GB_ID, feed_team_scope="both")
    assert g.drives, "fixture should yield merged drives"
    return g


def test_packers_lions_drive0_distinct_presnap_timing_in_comparison_rows() -> None:
    g = _load_game_with_merged_feed()
    dr = g.drives[0]
    assert len(dr.plays) >= 5

    ambient = GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        quarter=4,
        seconds_remaining=60,
    )
    rows = comparison_rows_for_archived_drive(
        drive=dr,
        game=g,
        ambient_ctx=ambient,
        predictor=FootballPlayPredictor(),
        plays=dr.plays,
    )
    assert len(rows) == len(dr.plays)

    timing = [
        (r.pre_snap_context.quarter, r.pre_snap_context.clock_display)
        for r in rows
        if r.pre_snap_context.quarter and r.pre_snap_context.clock_display
    ]
    assert len(timing) >= 5
    distinct_timing = {(q, c) for q, c in timing}
    assert len(distinct_timing) >= 3, f"expected varied feed Q/clock, got {distinct_timing!r}"

    lines = [_compact_snap_context_line(r) for r in rows if _compact_snap_context_line(r)]
    assert len(set(lines)) >= 3

    wrong = [r for r in rows if r.pre_snap_context.quarter == ambient.quarter and r.pre_snap_context.seconds_remaining == ambient.seconds_remaining]
    assert not wrong, "rows should not all mirror ambient GameContext quarter/seconds_remaining"


def test_packers_lions_drive0_situation_canary_no_silent_defaults() -> None:
    """Down, distance, and field position must vary (not every row 1 & 10 @ own 25)."""
    g = _load_game_with_merged_feed()
    dr = g.drives[0]
    ambient = GameContext(
        down=1,
        distance=10,
        yardline=25,
        territory="own",
        quarter=1,
        seconds_remaining=900,
    )
    rows = comparison_rows_for_archived_drive(
        drive=dr,
        game=g,
        ambient_ctx=ambient,
        predictor=FootballPlayPredictor(),
        plays=dr.plays,
    )
    downs = {r.pre_snap_context.down for r in rows if r.pre_snap_context.down is not None}
    dists = {r.pre_snap_context.distance for r in rows if r.pre_snap_context.distance is not None}
    yls = {r.pre_snap_context.yardline for r in rows if r.pre_snap_context.yardline is not None}
    assert len(downs) > 1, f"expected multiple downs, got {downs!r}"
    assert len(dists) > 1, f"expected multiple distances, got {dists!r}"
    assert len(yls) > 1, f"expected multiple yard lines, got {yls!r}"
    assert any(r.pre_snap_context.territory == "opponents" for r in rows), "drive should reach opponent territory"
