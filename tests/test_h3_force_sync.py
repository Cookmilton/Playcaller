"""H.3: Force sync uses ``request_live_sync`` and bypasses polling guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_IS_FINAL,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_SYNC_REQUESTED,
    UI_LIVE_POLLING_ENABLED,
)
from playcaller.streamlit_state.possession import ORIGIN_FEED, ORIGIN_MANUAL
from tests.test_g2c_ui_apptest import _QueuedEspnFetch, _click
from tests.test_widget_state_retention import APP_FILE, SCOREBOARD_ROWS, _reset_streamlit_dg_stack, _widget

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_657 = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_657 = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"
MAIN_CONSOLE = ROOT / "playcaller/ui/main_console.py"
EVENT_ID = "401872657"
FORCE_KEY = "main_console_force_sync"


def test_force_sync_uses_existing_request_live_sync_path() -> None:
    src = MAIN_CONSOLE.read_text(encoding="utf-8")
    assert "on_click=request_live_sync" in src
    assert 'key="main_console_force_sync"' in src
    assert "st.rerun(" not in src


def _boot(monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, _QueuedEspnFetch]:
    summary = json.loads(SUMMARY_657.read_text(encoding="utf-8"))
    scoreboard = json.loads(SCOREBOARD_657.read_text(encoding="utf-8"))
    fake = _QueuedEspnFetch([summary, summary], scoreboard=scoreboard)
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


def test_force_sync_works_with_polling_off(monkeypatch: pytest.MonkeyPatch) -> None:
    at, fake = _boot(monkeypatch)
    assert at.session_state[UI_LIVE_POLLING_ENABLED] is False
    _click(at, FORCE_KEY)
    assert fake.calls == 1
    assert at.session_state[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED


def test_force_sync_works_with_polling_on(monkeypatch: pytest.MonkeyPatch) -> None:
    at, fake = _boot(monkeypatch)
    _widget(at, UI_LIVE_POLLING_ENABLED).set_value(True)
    at.run()
    assert not at.exception, at.exception
    _click(at, FORCE_KEY)
    assert fake.calls == 1
    assert at.session_state[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED


def test_force_sync_bypasses_polling_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    at, fake = _boot(monkeypatch)
    at.session_state[UI_LIVE_POLLING_ENABLED] = False
    at.session_state[LIVE_FEED_LAST_ORIGIN] = ORIGIN_MANUAL
    at.session_state[LIVE_FEED_LAST_IS_FINAL] = True
    at.session_state.game.recommendation_audit = [{"status": "open"}]
    at.run()
    assert not at.exception, at.exception
    _click(at, FORCE_KEY)
    assert fake.calls == 1
    assert at.session_state[LIVE_FEED_LAST_ORIGIN] == ORIGIN_FEED
    try:
        queued = at.session_state[LIVE_SYNC_REQUESTED]
    except Exception:
        queued = None
    assert not queued
