"""ESPN calendar date on the live snapshot; honest null when the payload has none."""

import json
from pathlib import Path

from playcaller.game import Game
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_SEEN_PLAY_IDS,
    PENDING_SCOREBOARD_STATUS,
    PENDING_SESSION_GAME_DATE,
    SESSION_SETUP_GAME_DATE,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVENT = "401872657"
LAR = "14"


def _summary() -> dict:
    return json.loads((FIXTURES / "espn_summary_live_401872657.json").read_text(encoding="utf-8"))


def _scoreboard() -> dict:
    return json.loads((FIXTURES / "espn_scoreboard_live_401872657.json").read_text(encoding="utf-8"))


def test_game_date_from_scoreboard_not_invented() -> None:
    snap = parse_espn_summary(
        _summary(), sport="nfl", our_team_id=LAR, scoreboard_payload=_scoreboard()
    )
    assert snap.game_date == "2026-09-11"
    snap_unknown = parse_espn_summary(_summary(), sport="nfl", our_team_id=LAR)
    assert snap_unknown.game_date is None


def test_apply_snapshot_queues_session_date_and_scoreboard_detail() -> None:
    snap = parse_espn_summary(
        _summary(), sport="nfl", our_team_id=LAR, scoreboard_payload=_scoreboard()
    )
    session = {LIVE_FEED_SEEN_PLAY_IDS: [], SESSION_SETUP_GAME_DATE: ""}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(),
    )
    assert session[PENDING_SESSION_GAME_DATE] == "2026-09-11"
    assert session[PENDING_SCOREBOARD_STATUS]["event_id"] == EVENT
    assert session[PENDING_SCOREBOARD_STATUS]["detail"] == snap.status_detail

    session2 = {LIVE_FEED_SEEN_PLAY_IDS: [], SESSION_SETUP_GAME_DATE: "2018-01-01"}
    apply_snapshot(
        game=Game.new_game(),
        session=session2,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(),
    )
    assert PENDING_SESSION_GAME_DATE not in session2
