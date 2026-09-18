"""J3 Phase 4 — serialize time provenance; untrusted duration is not shown as real."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.domain import ActualPlayResult
from playcaller.game import (
    TIME_SOURCE_ESPN,
    Drive,
    DriveResult,
    Game,
    clock_seconds_after_drive_elapsed,
    complete_drive_from_plays,
    display_drive_detail_line,
    game_from_dict,
    game_to_dict,
    trusted_time_elapsed_seconds,
)
from playcaller.live_data.drive_display import prior_drive_heading
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.review.derived import _game_drive_headline
from playcaller.ui.review_film_room import _drive_header

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"


def _imported() -> Game:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(raw, event_id=EVENT_ID)
    game = Game.new_game()
    n, _, _ = merge_completed_espn_drives_into_game(
        game, {}, feeds, coached_team_id=DEN_ID, feed_team_scope="both"
    )
    assert n == 24
    return game


def test_export_serializes_time_source_and_inferred() -> None:
    game = _imported()
    blob = game_to_dict(game)
    for i, row in enumerate(blob["drives"]):
        assert row["time_source"] == TIME_SOURCE_ESPN, i
        assert row["inferred_time_seconds"] == game.drives[i].play_count * 38, i
        assert row["time_elapsed_seconds"] == game.drives[i].time_elapsed_seconds, i
    roundtrip = game_from_dict(blob)
    assert all(dr.time_source == TIME_SOURCE_ESPN for dr in roundtrip.drives)
    assert roundtrip.drives[21].time_elapsed_seconds == 142


def test_legacy_missing_time_source_is_untrusted_and_not_rewritten() -> None:
    payload = {
        "game_id": "legacy",
        "drives": [
            {
                "plays": [],
                "total_yards": 12,
                "play_count": 3,
                "time_elapsed_seconds": 114,
                "possessing_team": "offense",
                "result": {
                    "kind": "punt",
                    "headline": "Punt",
                    "detail_line": "3 plays, 12 yards, 1:54",
                },
            }
        ],
    }
    raw = json.dumps(payload)
    g = game_from_dict(payload)
    assert g.drives[0].time_source is None
    assert g.drives[0].time_elapsed_seconds == 114
    assert "time_source" not in json.loads(raw)["drives"][0]
    assert trusted_time_elapsed_seconds(g.drives[0]) is None
    shown = display_drive_detail_line(g.drives[0])
    assert shown == "3 plays, 12 yards"
    assert "1:54" not in shown
    heading = prior_drive_heading(g.drives[0], 1)
    assert "1:54" not in heading
    rec = reconcile_drive(g.drives[0], espn=None)
    assert rec.time_of_possession_display == "—"
    assert rec.provenance.get("time_of_possession") != "espn"


def test_espn_duration_still_displays() -> None:
    game = _imported()
    dr = game.drives[21]
    shown = display_drive_detail_line(dr)
    assert "2:22" in shown
    assert trusted_time_elapsed_seconds(dr) == 142
    rec = reconcile_drive(dr, espn=dr.feed_audit)
    assert rec.provenance.get("time_of_possession") == "espn"
    assert rec.time_of_possession_display not in ("", "—")


def test_clock_subtract_ignores_untrusted_duration() -> None:
    dr = Drive(
        plays=[],
        play_count=3,
        time_elapsed_seconds=114,
        time_source=None,
        inferred_time_seconds=114,
    )
    assert clock_seconds_after_drive_elapsed(900, dr) == 900
    espn = Drive(
        plays=[],
        play_count=3,
        time_elapsed_seconds=48,
        time_source=TIME_SOURCE_ESPN,
        inferred_time_seconds=114,
    )
    assert clock_seconds_after_drive_elapsed(900, espn) == 852


def test_review_surfaces_omit_untrusted_clock() -> None:
    g = Game.new_game()
    dr = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=4, family="gap", play_type="run")],
        end_kind_override="punt",
        possessing_team="offense",
    )
    dr.time_elapsed_seconds = 38
    dr.time_source = None
    dr.result = DriveResult(kind="punt", headline="Punt", detail_line="1 play, 4 yards, 0:38")
    dr.session_drive_epoch = 0
    g.drives = [dr]
    assert "0:38" not in display_drive_detail_line(dr)
    assert "0:38" not in ( _game_drive_headline(g, 0) or "")
    header = _drive_header(g, 0, [])
    assert "0:38" not in header
    assert "game clock" not in header
    assert "Punt" in header
