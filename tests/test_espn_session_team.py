"""ESPN coached-team name fills empty session team (operator-set wins)."""

import json
from pathlib import Path

from playcaller.game import Game
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.espn_session_team import (
    LIVE_FEED_TEAM_NAME_MISMATCH,
    apply_espn_team_name_to_session,
    team_name_mismatch_warning,
)
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_SEEN_PLAY_IDS,
    PENDING_SESSION_TEAM_NAME,
    SESSION_SETUP_TEAM_NAME,
)
from playcaller.streamlit_state.pending import apply_pending_session_team_name

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LAR = "14"
SF = "25"


def _summary() -> dict:
    return json.loads((FIXTURES / "espn_summary_live_401872657.json").read_text(encoding="utf-8"))


def test_parse_sets_coached_team_display_name() -> None:
    snap = parse_espn_summary(_summary(), sport="nfl", our_team_id=SF)
    assert snap.coached_team_name == "San Francisco 49ers"
    snap_lar = parse_espn_summary(_summary(), sport="nfl", our_team_id=LAR)
    assert snap_lar.coached_team_name == "Los Angeles Rams"


def test_apply_snapshot_queues_team_name_when_session_empty() -> None:
    snap = parse_espn_summary(_summary(), sport="nfl", our_team_id=SF)
    session = {LIVE_FEED_SEEN_PLAY_IDS: [], SESSION_SETUP_TEAM_NAME: ""}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(),
    )
    assert session[PENDING_SESSION_TEAM_NAME] == "San Francisco 49ers"


def test_operator_team_name_wins_with_mismatch_warning() -> None:
    snap = parse_espn_summary(_summary(), sport="nfl", our_team_id=SF)
    session = {LIVE_FEED_SEEN_PLAY_IDS: [], SESSION_SETUP_TEAM_NAME: "East High"}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(),
    )
    assert PENDING_SESSION_TEAM_NAME not in session
    assert session[LIVE_FEED_TEAM_NAME_MISMATCH]["session"] == "East High"
    warn = team_name_mismatch_warning(session) or ""
    assert "East High" in warn and "San Francisco 49ers" in warn


def test_pending_team_name_fills_empty_widget_only() -> None:
    ss = {SESSION_SETUP_TEAM_NAME: "", PENDING_SESSION_TEAM_NAME: "San Francisco 49ers"}
    apply_pending_session_team_name(ss)
    assert ss[SESSION_SETUP_TEAM_NAME] == "San Francisco 49ers"
    assert PENDING_SESSION_TEAM_NAME not in ss

    ss2 = {SESSION_SETUP_TEAM_NAME: "East High", PENDING_SESSION_TEAM_NAME: "San Francisco 49ers"}
    apply_pending_session_team_name(ss2)
    assert ss2[SESSION_SETUP_TEAM_NAME] == "East High"


def test_apply_espn_team_name_empty_feed_clears_mismatch() -> None:
    ss = {LIVE_FEED_TEAM_NAME_MISMATCH: {"session": "A", "espn": "B"}}
    apply_espn_team_name_to_session(ss, "")
    assert LIVE_FEED_TEAM_NAME_MISMATCH not in ss
