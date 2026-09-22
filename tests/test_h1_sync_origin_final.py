"""H.1 / H.4: persist ``is_final``; a poll writes origin ``feed`` unless the board is manual."""

from __future__ import annotations

from typing import Optional

from playcaller.game import Game
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.live_data.types import FetchResult, NormalizedGameSnapshot
from playcaller.services.live_feed_sync import origin_to_write, run_requested_live_sync
from playcaller.state import DriveLogger
from playcaller.streamlit_state.feed_board_copy import (
    GENERATE_UNSYNCED_CLOCK_REASON,
    generate_blocked_reason_for_session,
)
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


def _snap(
    *,
    is_final: bool = False,
    quarter: Optional[int] = 2,
    clock_seconds_in_period: Optional[int] = 600,
) -> NormalizedGameSnapshot:
    return NormalizedGameSnapshot(
        provider="espn",
        external_game_id="401test",
        sport="nfl",
        fetched_at_epoch=1.0,
        status_detail="in" if not is_final else "Final",
        quarter=quarter,
        clock_seconds_in_period=clock_seconds_in_period,
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


def test_origin_to_write_names_poll_intent() -> None:
    """A poll writes feed from unset or feed, and passes manual through. Sync always writes feed."""
    assert origin_to_write(initiator=None, current_origin=None) == ORIGIN_FEED
    assert origin_to_write(initiator=None, current_origin=ORIGIN_MANUAL) == ORIGIN_FEED
    assert origin_to_write(initiator="manual", current_origin=ORIGIN_MANUAL) == ORIGIN_FEED
    assert origin_to_write(initiator="manual", current_origin=None) == ORIGIN_FEED
    assert origin_to_write(initiator="poll", current_origin=None) == ORIGIN_FEED
    assert origin_to_write(initiator="poll", current_origin=ORIGIN_FEED) == ORIGIN_FEED
    assert origin_to_write(initiator="poll", current_origin=ORIGIN_MANUAL) == ORIGIN_MANUAL


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


def test_apply_snapshot_poll_writes_feed_unless_manual() -> None:
    """Second line of defence, at ``apply_snapshot``, with readiness not in the path.

    The origin argument is the value :func:`origin_to_write` resolved for a poll.
    """
    for current, expected in (
        (None, ORIGIN_FEED),
        (ORIGIN_FEED, ORIGIN_FEED),
        (ORIGIN_MANUAL, ORIGIN_MANUAL),
    ):
        session: dict = {LIVE_FEED_LAST_ORIGIN: current}
        apply_snapshot(
            game=Game.new_game(),
            session=session,
            drive_log=DriveLogger(),
            snapshot=_snap(),
            options=SyncOptions(),
            origin=origin_to_write(initiator="poll", current_origin=current),
        )
        assert session[LIVE_FEED_LAST_ORIGIN] == expected


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
    ss[LIVE_SYNC_INITIATOR] = "poll"
    clear_live_feed_session_keys(ss)
    assert ss[LIVE_FEED_LAST_IS_FINAL] is None
    assert LIVE_SYNC_INITIATOR not in ss


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


def _patch_fetch(monkeypatch, snap: NormalizedGameSnapshot) -> None:
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


def test_run_requested_live_sync_poll_origin(monkeypatch) -> None:
    """Poll sync: unset and feed become feed; manual stays manual. Readiness is bypassed."""
    _patch_fetch(monkeypatch, _snap(is_final=True))
    for current, expected in (
        (None, ORIGIN_FEED),
        (ORIGIN_FEED, ORIGIN_FEED),
        (ORIGIN_MANUAL, ORIGIN_MANUAL),
    ):
        ss: dict = {
            LIVE_SYNC_REQUESTED: True,
            LIVE_SYNC_INITIATOR: "poll",
            LIVE_FEED_LAST_ORIGIN: current,
            "game": Game.new_game(),
            "drive_log": DriveLogger(),
        }
        run_requested_live_sync(ss)
        assert ss[LIVE_FEED_LAST_ORIGIN] == expected
        assert ss[LIVE_FEED_LAST_IS_FINAL] is True
        assert LIVE_SYNC_REQUESTED not in ss
        assert LIVE_SYNC_INITIATOR not in ss


def test_poll_only_sync_blocks_generate_when_quarter_clock_unsynced(monkeypatch) -> None:
    """J3's unsynced quarter/clock Generate block must engage after a poll-only sync."""
    _patch_fetch(monkeypatch, _snap(quarter=None, clock_seconds_in_period=None))
    ss: dict = {
        LIVE_SYNC_REQUESTED: True,
        LIVE_SYNC_INITIATOR: "poll",
        LIVE_FEED_LAST_ORIGIN: None,
        "game": Game.new_game(),
        "drive_log": DriveLogger(),
    }
    run_requested_live_sync(ss)
    assert ss[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED
    assert (
        generate_blocked_reason_for_session(ss, possession="offense")
        == GENERATE_UNSYNCED_CLOCK_REASON
    )
