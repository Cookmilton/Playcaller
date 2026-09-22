"""H.2: polling guards, inline fragment no-op, and poll-flag consumption.

Does not claim to exercise Streamlit ``run_every`` cadence (AppTest has no frontend).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.game import Game
from playcaller.services.live_polling import (
    IDLE_GAME_FINAL,
    IDLE_OPEN_SNAP,
    IDLE_ORIGIN_MANUAL,
    IDLE_POLLING_OFF,
    POLL_INITIATOR,
    POLL_INTERVAL_SECONDS,
    maybe_request_live_poll,
    polling_readiness_from_session,
    polling_status_caption,
)
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_IS_FINAL,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_SYNC_INITIATOR,
    LIVE_SYNC_REQUESTED,
    UI_LIVE_POLLING_ENABLED,
)
from playcaller.streamlit_state.possession import ORIGIN_FEED, ORIGIN_MANUAL
from playcaller.streamlit_state.session import ensure_play_caller_session_defaults
from tests.test_g2c_ui_apptest import _QueuedEspnFetch
from tests.test_widget_state_retention import APP_FILE, SCOREBOARD_ROWS, _reset_streamlit_dg_stack, _widget

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_657 = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_657 = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"

EVENT_ID = "401872657"


def _ss(at: AppTest, key: str):
    try:
        return at.session_state[key]
    except Exception:
        return None


def _ready_session(**overrides) -> dict:
    ss: dict = {
        UI_LIVE_POLLING_ENABLED: True,
        LIVE_FEED_LAST_IS_FINAL: False,
        LIVE_FEED_LAST_ORIGIN: ORIGIN_FEED,
        LIVE_FEED_SCOREBOARD_ROWS: SCOREBOARD_ROWS,
        "ui_live_pick_event_id": EVENT_ID,
        "ui_live_home_or_away": "away",
        "game": Game.new_game(),
    }
    ss.update(overrides)
    return ss


def test_poll_interval_is_one_named_constant() -> None:
    assert POLL_INTERVAL_SECONDS == 15


def test_polling_default_is_off() -> None:
    ss: dict = {}
    ensure_play_caller_session_defaults(ss)
    assert ss[UI_LIVE_POLLING_ENABLED] is False
    ready = polling_readiness_from_session(ss)
    assert ready.should_poll is False
    assert ready.idle_reason == IDLE_POLLING_OFF


def test_guard_toggle_off_blocks() -> None:
    ready = polling_readiness_from_session(_ready_session(**{UI_LIVE_POLLING_ENABLED: False}))
    assert ready.should_poll is False
    assert ready.idle_reason == IDLE_POLLING_OFF


def test_guard_cannot_sync_blocks_and_reuses_block_reason() -> None:
    ready = polling_readiness_from_session(
        _ready_session(**{LIVE_FEED_SCOREBOARD_ROWS: [], "ui_live_pick_event_id": ""})
    )
    assert ready.should_poll is False
    assert ready.idle_reason
    assert "Event ID" in ready.idle_reason or "scoreboard" in ready.idle_reason.lower()


def test_guard_game_final_blocks() -> None:
    ready = polling_readiness_from_session(_ready_session(**{LIVE_FEED_LAST_IS_FINAL: True}))
    assert ready.should_poll is False
    assert ready.idle_reason == IDLE_GAME_FINAL


def test_guard_origin_manual_blocks() -> None:
    ready = polling_readiness_from_session(_ready_session(**{LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL}))
    assert ready.should_poll is False
    assert ready.idle_reason == IDLE_ORIGIN_MANUAL


def test_guard_tail_open_blocks() -> None:
    game = Game.new_game()
    game.recommendation_audit = [
        {"status": "closed"},
        {"status": "open"},
    ]
    ready = polling_readiness_from_session(_ready_session(game=game))
    assert ready.should_poll is False
    assert ready.idle_reason == IDLE_OPEN_SNAP


def test_tail_closed_or_empty_does_not_block() -> None:
    game = Game.new_game()
    game.recommendation_audit = [{"status": "closed"}, {"status": "superseded"}]
    assert polling_readiness_from_session(_ready_session(game=game)).should_poll is True
    assert polling_readiness_from_session(_ready_session()).should_poll is True


def test_is_final_none_does_not_block() -> None:
    assert polling_readiness_from_session(_ready_session(**{LIVE_FEED_LAST_IS_FINAL: None})).should_poll is True


def test_maybe_request_live_poll_inline_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("playcaller.services.live_polling.is_fragment_timer_tick", lambda: False)
    ss = _ready_session()
    assert maybe_request_live_poll(ss) is False
    assert LIVE_SYNC_REQUESTED not in ss


def test_maybe_request_live_poll_timer_tick_sets_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("playcaller.services.live_polling.is_fragment_timer_tick", lambda: True)
    ss = _ready_session()
    assert maybe_request_live_poll(ss) is True
    assert ss[LIVE_SYNC_REQUESTED] is True
    assert ss[LIVE_SYNC_INITIATOR] == POLL_INITIATOR


def test_maybe_request_live_poll_timer_respects_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("playcaller.services.live_polling.is_fragment_timer_tick", lambda: True)
    ss = _ready_session(**{UI_LIVE_POLLING_ENABLED: False})
    assert maybe_request_live_poll(ss) is False
    assert LIVE_SYNC_REQUESTED not in ss


def test_polling_status_caption_includes_interval_and_idle() -> None:
    cap = polling_status_caption(_ready_session(**{UI_LIVE_POLLING_ENABLED: False}))
    assert "off" in cap
    assert "15s" in cap
    cap_idle = polling_status_caption(_ready_session(**{LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL}))
    assert "on" in cap_idle
    assert IDLE_ORIGIN_MANUAL in cap_idle
    cap_fresh = polling_status_caption(_ready_session(**{LIVE_FEED_LAST_SYNC_EPOCH: 1_700_000_000.0}))
    assert "last fetch" in cap_fresh


def _boot_poll_app(monkeypatch: pytest.MonkeyPatch, summaries: list[dict]) -> tuple[AppTest, _QueuedEspnFetch]:
    scoreboard = json.loads(SCOREBOARD_657.read_text(encoding="utf-8"))
    fake = _QueuedEspnFetch(summaries, scoreboard=scoreboard)
    monkeypatch.setattr("playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot", fake)
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_live_pick_event_id").set_value(EVENT_ID)
    _widget(at, "ui_live_home_or_away").set_value("away")
    at.run()
    assert not at.exception, at.exception
    return at, fake


def test_fragment_inline_full_app_run_does_not_set_live_sync_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = json.loads(SUMMARY_657.read_text(encoding="utf-8"))
    at, fake = _boot_poll_app(monkeypatch, [summary])
    _widget(at, UI_LIVE_POLLING_ENABLED).set_value(True)
    at.session_state[LIVE_FEED_LAST_ORIGIN] = ORIGIN_FEED
    at.session_state[LIVE_FEED_LAST_IS_FINAL] = False
    at.run()
    assert not at.exception, at.exception
    assert _ss(at, LIVE_SYNC_REQUESTED) is None
    assert fake.calls == 0


def test_queued_poll_is_consumed_by_pre_widget_path(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = json.loads(SUMMARY_657.read_text(encoding="utf-8"))
    at, fake = _boot_poll_app(monkeypatch, [summary])
    at.session_state[LIVE_FEED_LAST_ORIGIN] = ORIGIN_MANUAL
    at.session_state[LIVE_SYNC_REQUESTED] = True
    at.session_state[LIVE_SYNC_INITIATOR] = POLL_INITIATOR
    at.run()
    assert not at.exception, at.exception
    assert fake.calls == 1
    assert _ss(at, LIVE_SYNC_REQUESTED) is None
    assert _ss(at, LIVE_SYNC_INITIATOR) is None
    assert at.session_state[LIVE_FEED_LAST_ORIGIN] == ORIGIN_MANUAL
