"""J3 Phase 1 — ESPN drive timeElapsed is the stored duration; 38s is shadow only."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from playcaller.game import TIME_SOURCE_ESPN, Game
from playcaller.game_context_features import drive_trusted_for_tendencies
from playcaller.live_data.drive_display import chronological_team_drive_indices
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_drive_audit_parse import parse_espn_time_elapsed_display
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.reconciliation.play_context import ESTIMATED_SECONDS_BETWEEN_SNAPS

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"


def _imported(payload: dict | None = None) -> Game:
    raw = payload if payload is not None else json.loads(FIXTURE.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(raw, event_id=EVENT_ID)
    game = Game.new_game()
    n, _, _ = merge_completed_espn_drives_into_game(
        game, {}, feeds, coached_team_id=DEN_ID, feed_team_scope="both"
    )
    assert n == 24
    return game


def test_parse_espn_time_elapsed_display_malformed_is_none() -> None:
    assert parse_espn_time_elapsed_display("2:22") == 142
    assert parse_espn_time_elapsed_display("0:48") == 48
    assert parse_espn_time_elapsed_display("") is None
    assert parse_espn_time_elapsed_display(None) is None
    assert parse_espn_time_elapsed_display("bad") is None
    assert parse_espn_time_elapsed_display("2:99") is None
    assert parse_espn_time_elapsed_display("0:00") == 0


def test_mnf_all_drives_espn_time_not_play_count_times_38() -> None:
    game = _imported()
    assert len(game.drives) == 24
    for i, dr in enumerate(game.drives, 1):
        assert dr.time_source == TIME_SOURCE_ESPN, f"drive {i}"
        assert dr.time_elapsed_seconds is not None, f"drive {i}"
        assert dr.inferred_time_seconds == dr.play_count * 38, f"drive {i}"
        if dr.time_elapsed_seconds == dr.play_count * 38:
            assert dr.feed_audit is not None
            assert dr.feed_audit.time_elapsed_seconds == dr.time_elapsed_seconds


def test_mnf_den_team_drive_11_and_chronological_11() -> None:
    game = _imported()
    seq = chronological_team_drive_indices(game)
    den_11 = [i for i, dr in enumerate(game.drives) if dr.feed_team_abbr == "DEN" and seq[i] == 11]
    assert den_11 == [21]
    assert game.drives[21].time_elapsed_seconds == 142
    assert game.drives[10].time_elapsed_seconds == 48
    assert game.drives[10].feed_team_abbr == "DEN"


def test_time_elapsed_removed_yields_none_source() -> None:
    payload = deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))
    for dr in payload.get("drives", {}).get("previous") or []:
        if isinstance(dr, dict):
            dr.pop("timeElapsed", None)
    game = _imported(payload)
    for i, dr in enumerate(game.drives, 1):
        assert dr.time_elapsed_seconds is None, f"drive {i}"
        assert dr.time_source is None, f"drive {i}"
        assert dr.inferred_time_seconds == dr.play_count * 38, f"drive {i}"


def test_estimated_seconds_between_snaps_does_not_feed_duration() -> None:
    """play_context reconstruction heuristic is a different clock, not drive TOP."""
    assert ESTIMATED_SECONDS_BETWEEN_SNAPS == 38
    import playcaller.game as game_mod

    assert not hasattr(game_mod, "ESTIMATED_SECONDS_BETWEEN_SNAPS")
    game = _imported()
    # Tendencies do not read inferred_time_seconds / the 38s estimate as duration.
    trusted = [dr for dr in game.drives if drive_trusted_for_tendencies(dr)]
    assert trusted
    assert all(dr.time_source == TIME_SOURCE_ESPN for dr in trusted)
    # The 38s shadow is stored separately and is not the duration tendencies would see.
    assert all(dr.inferred_time_seconds == dr.play_count * 38 for dr in trusted)


def test_detail_line_matches_formatter_and_espn_yards() -> None:
    from playcaller.drive_audit_report import archived_drive_expander_title_from_audit, compute_drive_audit
    from playcaller.game import format_drive_detail_line
    from playcaller.live_data.drive_display import chronological_team_drive_indices, prior_drive_heading

    game = _imported()
    seq = chronological_team_drive_indices(game)
    audit = compute_drive_audit(game)
    by_idx = {row.drive_index: row for row in audit.rows}
    for i, dr in enumerate(game.drives):
        assert dr.result is not None
        expected = format_drive_detail_line(
            play_count=dr.play_count,
            total_yards=dr.total_yards,
            time_elapsed_seconds=dr.time_elapsed_seconds,
        )
        assert dr.result.detail_line == expected, f"drive {i + 1}"
        heading = prior_drive_heading(dr, seq[i])
        assert expected in heading, f"drive {i + 1} heading={heading!r}"
        ar = by_idx[i]
        card = archived_drive_expander_title_from_audit(dr, seq[i], ar)
        assert expected in card, f"drive {i + 1} card={card!r}"
    assert "4 yards" in (game.drives[17].result.detail_line or "")
    assert "34 yards" in (game.drives[18].result.detail_line or "")
    assert "5 yards" not in (game.drives[17].result.detail_line or "")
    assert "32 yards" not in (game.drives[18].result.detail_line or "")
