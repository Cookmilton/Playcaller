"""G2.0: G1 sync-request flag, HTTP timeout, and fetch-error session key."""

from __future__ import annotations

import inspect

from playcaller.game import Game
from playcaller.live_data.http_client import fetch_json_http
from playcaller.live_data.http_util import fetch_json
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import LIVE_FEED_LAST_ERROR, LIVE_SYNC_REQUESTED


def test_http_json_timeout_is_25_seconds() -> None:
    assert inspect.signature(fetch_json).parameters["timeout"].default == 25.0
    assert inspect.signature(fetch_json_http).parameters["timeout"].default == 25.0


def test_live_sync_requested_cleared_in_finally_on_success(monkeypatch) -> None:
    from playcaller.services.live_feed_sync import run_requested_live_sync

    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.sync_readiness_from_session",
        lambda ss: type("R", (), {"can_sync": False, "block_reason": "blocked"})(),
    )
    ss = {
        LIVE_SYNC_REQUESTED: True,
        "game": Game.new_game(),
        "drive_log": DriveLogger(),
    }
    assert run_requested_live_sync(ss) is None
    assert LIVE_SYNC_REQUESTED not in ss
    assert ss[LIVE_FEED_LAST_ERROR] == "blocked"


def test_live_sync_requested_cleared_in_finally_on_exception(monkeypatch) -> None:
    from playcaller.services.live_feed_sync import run_requested_live_sync

    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.sync_readiness_from_session",
        lambda ss: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    ss = {
        LIVE_SYNC_REQUESTED: True,
        "game": Game.new_game(),
        "drive_log": DriveLogger(),
    }
    assert run_requested_live_sync(ss) is None
    assert LIVE_SYNC_REQUESTED not in ss
    assert "boom" in str(ss[LIVE_FEED_LAST_ERROR])


def test_live_sync_skips_when_flag_unset() -> None:
    from playcaller.services.live_feed_sync import run_requested_live_sync

    ss = {"game": Game.new_game(), "drive_log": DriveLogger()}
    assert run_requested_live_sync(ss) is None
    assert LIVE_SYNC_REQUESTED not in ss
