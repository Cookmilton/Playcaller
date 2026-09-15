"""J1.6 — ESPN yards authority, terminal kinds, legacy outcome_source trust."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.domain import ActualPlayResult
from playcaller.drive_audit_report import compute_drive_audit
from playcaller.game import (
    DRIVE_END_END_OF_GAME,
    DRIVE_END_END_OF_HALF,
    OUTCOME_SOURCE_ESPN,
    YARDS_SOURCE_COMPUTED,
    YARDS_SOURCE_ESPN,
    DriveFeedAuditSnapshot,
    Game,
    complete_drive_from_plays,
    game_from_json,
    game_to_json,
)
from playcaller.game_context_features import build_game_context_features, drive_trusted_for_tendencies
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.state import DriveLogger

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"


def _imported() -> Game:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_ID)
    game = Game.new_game()
    merge_completed_espn_drives_into_game(game, {}, feeds, coached_team_id=DEN_ID)
    return game


def test_mnf_espn_yards_authority_and_computed_delta() -> None:
    game = _imported()
    assert len(game.drives) == 24
    for i, dr in enumerate(game.drives, 1):
        assert dr.yards_source == YARDS_SOURCE_ESPN, f"drive {i}"
        assert dr.computed_yards is not None, f"drive {i}"
        assert dr.feed_audit is not None and dr.feed_audit.feed_yards is not None
        assert int(dr.total_yards) == int(dr.feed_audit.feed_yards), f"drive {i}"
        # Soft bound: large deltas are flagged in audit; still record for the report.
        assert isinstance(dr.computed_yards, int)


def test_end_of_half_and_game_kinds_round_trip() -> None:
    game = _imported()
    d12 = game.drives[11]
    d24 = game.drives[23]
    assert d12.result is not None and d12.result.kind == DRIVE_END_END_OF_HALF
    assert d24.result is not None and d24.result.kind == DRIVE_END_END_OF_GAME
    assert d12.outcome_source == OUTCOME_SOURCE_ESPN
    raw = game_to_json(game)
    g2 = game_from_json(raw)
    assert g2.drives[11].result is not None
    assert g2.drives[11].result.kind == DRIVE_END_END_OF_HALF
    assert g2.drives[23].result is not None
    assert g2.drives[23].result.kind == DRIVE_END_END_OF_GAME
    assert g2.drives[11].yards_source == YARDS_SOURCE_ESPN
    assert g2.drives[11].computed_yards == game.drives[11].computed_yards


def test_outcome_source_none_excluded_from_tendencies() -> None:
    g = Game.new_game()
    trusted = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=0,
                result_type="punt",
                play_type="special",
                description="Punt",
            )
        ],
        possessing_team="offense",
    )
    legacy = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=0,
                result_type="punt",
                play_type="special",
                description="Punt",
            )
        ],
        possessing_team="offense",
        end_kind_override="punt",
    )
    from dataclasses import replace

    legacy = replace(legacy, outcome_source=None)
    assert drive_trusted_for_tendencies(trusted) is True
    assert drive_trusted_for_tendencies(legacy) is False
    g.drives = [legacy, trusted]
    g.possession = "offense"
    gcf = build_game_context_features(g, DriveLogger())
    assert gcf["archived_team_drive_count"] == 1
    assert gcf["last_archived_drive_result_kind"] == "punt"
    assert gcf["drive_end_shares"].get("punt") == 1.0


def test_computed_only_yards_when_espn_absent() -> None:
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=12, family="inside_zone", play_type="run")],
        end_kind_override="punt",
    )
    assert d.yards_source == YARDS_SOURCE_COMPUTED
    assert d.total_yards == d.computed_yards == 12


def test_audit_flags_yards_delta_when_computed_diverges() -> None:
    audit = DriveFeedAuditSnapshot(
        espn_result_code="PUNT",
        espn_display_result="Punt",
        feed_yards=10,
        feed_offensive_plays=1,
    )
    d = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=50, family="inside_zone", play_type="run", result_type="punt", description="Punt")],
        feed_audit=audit,
        possessing_team="offense",
    )
    assert d.total_yards == 10
    assert d.computed_yards == 50
    g = Game.new_game()
    g.drives = [d]
    rep = compute_drive_audit(g)
    blob = " ".join(rep.rows[0].flags)
    assert "Computed yards=50 vs ESPN yards=10" in blob
