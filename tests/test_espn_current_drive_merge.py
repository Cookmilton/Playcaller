"""ESPN in-progress drive merge into ``DriveLogger`` (dedup, manual link, completed transition)."""

import copy
import json
from pathlib import Path

from playcaller.game import Game
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.live_data.drive_display import PREVIOUS_DRIVES_FILTER_BOTH
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_parse_includes_full_current_drive_rows() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    assert len(snap.current_feed_drive_plays) == 2
    assert snap.current_feed_drive_plays[0]["id"] == "401test001p1"


def test_import_current_off_skips_normalized_current_drive_merge() -> None:
    """Recorded ESPN summary: no current-drive rows in log when import toggle is off."""
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    res = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(
            import_current_feed_drive_plays=False,
            import_completed_feed_drives=False,
        ),
    )
    assert res.current_drive_plays_merged == 0
    assert len(dl.results) == 0
    aud = session[LIVE_FEED_LAST_AUDIT]
    assert aud["sync_options"]["import_current_feed_drive_plays"] is False


def test_current_drive_merge_idempotent_resync() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    r1 = apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert r1.current_drive_plays_merged == 2
    assert len(dl.results) == 2
    assert dl.results[0].external_play_id == "401test001p1"
    r2 = apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert r2.current_drive_plays_merged == 0
    assert len(dl.results) == 2


def test_seen_play_id_skips_duplicate_without_double_logging() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [],
        LIVE_FEED_SEEN_PLAY_IDS: ["401test001p1"],
    }
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert len(dl.results) == 1
    assert dl.results[0].external_play_id == "401test001p2"


def test_manual_play_linked_then_no_duplicate_on_sync() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    from playcaller.domain import ActualPlayResult

    dl.log(
        ActualPlayResult(
            concept_name="IZ",
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=6,
            description="Manual six",
        )
    )
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert len(dl.results) == 2
    assert dl.results[0].external_play_id == "401test001p1"
    assert dl.results[0].description == "Manual six"
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert len(dl.results) == 2


def test_lock_situation_skips_current_drive_merge() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    r = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(lock_situation=True),
    )
    assert r.current_drive_plays_merged == 0
    assert len(dl.results) == 0


def test_completed_drive_import_clears_matching_drive_log() -> None:
    payload = _load_fixture()
    snap1 = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [],
        LIVE_FEED_SEEN_PLAY_IDS: [],
        LIVE_FEED_TEAM_SCOPE: PREVIOUS_DRIVES_FILTER_BOTH,
    }
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap1, options=SyncOptions())
    assert len(dl.results) == 2
    assert len(game.drives) == 2

    payload2 = copy.deepcopy(payload)
    cur_plays = payload2["drives"]["current"]["plays"]
    payload2["drives"]["previous"].append(
        {
            "id": "401test001d_cur",
            "team": {"id": "14"},
            "plays": copy.deepcopy(cur_plays),
        }
    )
    payload2["drives"]["current"] = {"plays": []}
    snap2 = parse_espn_summary(payload2, sport="nfl", our_team_id="14")
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap2, options=SyncOptions())
    assert len(game.drives) == 3
    assert len(dl.results) == 0


def test_current_drive_merge_closes_open_snap_review_row() -> None:
    """Feed-appended play runs the same audit linkage as manual **Log result**."""
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    game.recommendation_audit = [
        {
            "status": "open",
            "drive_epoch": 0,
            "plays_at_recommend": 0,
            "selected_family": "quick_game",
        }
    ]
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert len(dl.results) == 2
    row0 = game.recommendation_audit[0]
    assert row0["status"] == "closed"
    assert isinstance(row0.get("linked_actual"), dict)


def test_import_current_off_uses_legacy_feed_auto_append() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [], LIVE_FEED_SEEN_PLAY_IDS: []}
    dl = DriveLogger()
    apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(import_current_feed_drive_plays=False, auto_append_feed_plays=True),
    )
    assert len(dl.results) == 2
    assert dl.results[0].description.startswith("[Feed]")
