"""H.1: persist ``is_final``; poll-initiated sync must not clobber manual origin."""

from __future__ import annotations

from playcaller.game import Game
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.live_data.types import FetchResult, NormalizedGameSnapshot
from playcaller.services.live_feed_sync import origin_for_sync_initiator, run_requested_live_sync
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_IS_FINAL,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_SYNC_INITIATOR,
    LIVE_SYNC_REQUESTED,
)
from playcaller.streamlit_state.possession import ORIGIN_FEED, ORIGIN_MANUAL
from playcaller.streamlit_state.session import (
    clear_live_feed_session_keys,
    ensure_play_caller_session_defaults,
)


def _snap(*, is_final: bool = False) -> NormalizedGameSnapshot:
    return NormalizedGameSnapshot(
        provider="espn",
        external_game_id="401test",
        sport="nfl",
        fetched_at_epoch=1.0,
        status_detail="in" if not is_final else "Final",
        quarter=2,
        clock_seconds_in_period=600,
        down=1,
        distance=10,
        abs_yards_from_own_goal=50,
        possession_team_id="14",
        possession_is_our_team=True,
        our_score=0,
        opponent_score=0,
        our_timeouts=3,
        opponent_timeouts=3,
        is_final=is_final,
        coached_team_id="14",
    )


def test_origin_for_sync_initiator_threads_poll_as_none() -> None:
    assert origin_for_sync_initiator(None) == ORIGIN_FEED
    assert origin_for_sync_initiator("manual") == ORIGIN_FEED
    assert origin_for_sync_initiator("poll") is None


def test_apply_snapshot_default_origin_is_feed() -> None:
    session: dict = {LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=_snap(),
        options=SyncOptions(),
    )
    assert session[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED


def test_apply_snapshot_poll_origin_none_leaves_manual() -> None:
    session: dict = {LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=_snap(),
        options=SyncOptions(),
        origin=None,
    )
    assert session[LIVE_FEED_LAST_ORIGIN] == ORIGIN_MANUAL


def test_is_final_persists_true_and_false() -> None:
    session: dict = {}
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=_snap(is_final=True),
        options=SyncOptions(),
    )
    assert session[LIVE_FEED_LAST_IS_FINAL] is True

    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=_snap(is_final=False),
        options=SyncOptions(),
    )
    assert session[LIVE_FEED_LAST_IS_FINAL] is False


def test_is_final_is_none_when_unknown() -> None:
    ss: dict = {}
    ensure_play_caller_session_defaults(ss)
    assert ss[LIVE_FEED_LAST_IS_FINAL] is None

    ss[LIVE_FEED_LAST_IS_FINAL] = True
    clear_live_feed_session_keys(ss)
    assert ss[LIVE_FEED_LAST_IS_FINAL] is None


def test_request_live_sync_default_sets_flag_only(monkeypatch) -> None:
    import playcaller.services.live_feed_sync as lfs

    ss: dict = {}

    class _St:
        session_state = ss

    monkeypatch.setitem(__import__("sys").modules, "streamlit", _St)
    lfs.request_live_sync()
    assert ss[LIVE_SYNC_REQUESTED] is True
    assert LIVE_SYNC_INITIATOR not in ss
    lfs.request_live_sync(initiator="poll")
    assert ss[LIVE_SYNC_INITIATOR] == "poll"


def _ready():
    return type("R", (), {"can_sync": True, "block_reason": None, "event_id": "1", "our_team_id": "14"})()


def test_run_requested_live_sync_manual_sets_origin_feed(monkeypatch) -> None:
    snap = _snap(is_final=False)
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.sync_readiness_from_session",
        lambda ss: _ready(),
    )
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot",
        lambda self, event_id, *, our_team_id: FetchResult(ok=True, snapshot=snap),
    )
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    ss: dict = {
        LIVE_SYNC_REQUESTED: True,
        LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL,
        "game": Game.new_game(),
        "drive_log": DriveLogger(),
    }
    run_requested_live_sync(ss)
    assert ss[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED
    assert ss[LIVE_FEED_LAST_IS_FINAL] is False
    assert LIVE_SYNC_REQUESTED not in ss
    assert LIVE_SYNC_INITIATOR not in ss


def test_run_requested_live_sync_poll_does_not_clear_manual(monkeypatch) -> None:
    snap = _snap(is_final=True)
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.sync_readiness_from_session",
        lambda ss: _ready(),
    )
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot",
        lambda self, event_id, *, our_team_id: FetchResult(ok=True, snapshot=snap),
    )
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    ss: dict = {
        LIVE_SYNC_REQUESTED: True,
        LIVE_SYNC_INITIATOR: "poll",
        LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL,
        "game": Game.new_game(),
        "drive_log": DriveLogger(),
    }
    run_requested_live_sync(ss)
    assert ss[LIVE_FEED_LAST_ORIGIN] == ORIGIN_MANUAL
    assert ss[LIVE_FEED_LAST_IS_FINAL] is True
    assert LIVE_SYNC_REQUESTED not in ss
    assert LIVE_SYNC_INITIATOR not in ss
