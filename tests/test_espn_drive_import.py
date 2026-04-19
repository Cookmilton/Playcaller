"""ESPN completed-drive extraction, play normalization, and merge dedup."""

import json
from pathlib import Path

import pytest

from playcaller.game import Game
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.live_data.espn_play_normalize import espn_play_to_actual
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.live_data.drive_display import PREVIOUS_DRIVES_FILTER_BOTH, PREVIOUS_DRIVES_FILTER_OPPONENT
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_TEAM_SCOPE,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_extract_completed_drives_from_payload() -> None:
    payload = _load_fixture()
    drives = extract_completed_drives_from_espn_payload(payload, event_id="401test001")
    assert len(drives) == 2
    assert drives[0].stable_key.startswith("401test001|")
    assert drives[0].team_espn_id == "10"
    assert drives[0].team_abbreviation == "NYG"
    assert "Giants" in drives[0].team_display_name
    assert len(drives[0].plays) == 3
    assert len(drives[1].plays) == 1
    d0 = drives[0].plays[0].description or ""
    assert "[ESPN]" in d0
    assert "Singletary" in d0


def test_parse_espn_summary_includes_completed_feed_drives() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    assert snap.coached_team_id == "14"
    assert len(snap.completed_feed_drives) == 2


def test_apply_snapshot_skips_completed_drives_when_toggle_off() -> None:
    """Recorded ESPN-shaped summary: completed drives stay out of ``Game`` when disabled."""
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: []}
    dl = DriveLogger()
    res = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(import_completed_feed_drives=False),
    )
    assert res.drives_imported == 0
    assert len(game.drives) == 0
    assert any("completed feed drives not imported" in s for s in res.skipped_reasons)
    aud = session[LIVE_FEED_LAST_AUDIT]
    assert isinstance(aud, dict)
    so = aud["sync_options"]
    assert so["import_completed_feed_drives"] is False
    assert so["import_current_feed_drive_plays"] is True


def test_apply_snapshot_completed_drives_off_then_on_imports() -> None:
    """Each sync uses the passed ``SyncOptions`` only; enabling later does not miss drives."""
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: []}
    dl = DriveLogger()
    r1 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(import_completed_feed_drives=False),
    )
    assert r1.drives_imported == 0
    assert len(game.drives) == 0
    session[LIVE_FEED_TEAM_SCOPE] = PREVIOUS_DRIVES_FILTER_BOTH
    r2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(import_completed_feed_drives=True),
    )
    assert r2.drives_imported == 2
    assert len(game.drives) == 2
    r3 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(import_completed_feed_drives=True),
    )
    assert r3.drives_imported == 0
    assert len(game.drives) == 2


def test_apply_snapshot_imports_drives_once() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: []}
    dl = DriveLogger()
    res = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(),
    )
    assert res.drives_imported == 1
    assert len(game.drives) == 1
    assert game.drives[0].feed_import_tag == "espn"
    assert game.drives[0].feed_team_espn_id == "14"
    assert game.drives[0].feed_team_abbr == "LAR"
    assert "Rams" in game.drives[0].feed_team_display_name
    assert game.drives[0].result is not None
    res2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(),
    )
    assert res2.drives_imported == 0
    assert len(game.drives) == 1


def test_apply_snapshot_imports_both_teams_when_scope_both() -> None:
    payload = _load_fixture()
    snap = parse_espn_summary(payload, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        LIVE_FEED_MERGED_ESPN_DRIVE_KEYS: [],
        LIVE_FEED_TEAM_SCOPE: PREVIOUS_DRIVES_FILTER_BOTH,
    }
    dl = DriveLogger()
    res = apply_snapshot(game=game, session=session, drive_log=dl, snapshot=snap, options=SyncOptions())
    assert res.drives_imported == 2
    assert len(game.drives) == 2
    assert {d.feed_team_espn_id for d in game.drives} == {"10", "14"}


def test_merge_completed_opponent_scope_imports_non_coached_team_only() -> None:
    payload = _load_fixture()
    drives = extract_completed_drives_from_espn_payload(payload, event_id="401test001")
    game = Game.new_game()
    ss: dict = {}
    n, _ = merge_completed_espn_drives_into_game(
        game, ss, drives, coached_team_id="14", feed_team_scope=PREVIOUS_DRIVES_FILTER_OPPONENT
    )
    assert n == 1
    assert len(game.drives) == 1
    assert game.drives[0].feed_team_espn_id == "10"


def test_merge_completed_drives_dedup_stable_keys() -> None:
    payload = _load_fixture()
    drives = extract_completed_drives_from_espn_payload(payload, event_id="401test001")
    game = Game.new_game()
    ss: dict = {}
    n1, _batch1 = merge_completed_espn_drives_into_game(
        game, ss, drives, coached_team_id="14", feed_team_scope=PREVIOUS_DRIVES_FILTER_BOTH
    )
    n2, _batch2 = merge_completed_espn_drives_into_game(
        game, ss, drives, coached_team_id="14", feed_team_scope=PREVIOUS_DRIVES_FILTER_BOTH
    )
    assert n1 == 2
    assert n2 == 0
    assert len(game.drives) == 2


@pytest.mark.parametrize(
    "text,yds,expect_sub",
    [
        ("Pass complete to tight end for 8 yards", 8, "Pass complete"),
        ("Sacked for -7 yards", -7, "Sack"),
        ("Punt out of bounds", 45, "Punt"),
        ("Field goal is good from 42 yards", 0, "Field goal good"),
        ("Field goal no good", 0, "Field goal missed"),
        ("Pass intercepted at midfield", 0, "Interception"),
    ],
)
def test_espn_play_normalize_categories(text: str, yds: int, expect_sub: str) -> None:
    play = {
        "id": "testp1",
        "type": {"text": "Play"},
        "text": text,
        "statYardage": yds,
    }
    ap = espn_play_to_actual(play)
    assert ap is not None
    desc = (ap.description or "").lower()
    assert expect_sub.lower() in desc
