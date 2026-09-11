"""G1: ESPN Sync writes must reach ``game_*`` and ``ui_*`` on the same run (no clobber)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.game import Game, game_to_json
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.types import FetchResult
from playcaller.possession import GENERATE_UNSET_POSSESSION_REASON
from playcaller.streamlit_state.keys import (
    GAME_WIDGET_HYDRATE_PENDING,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_SYNC_REQUESTED,
)
from playcaller.streamlit_state.widget_backend_bridge import sync_backend_from_widgets
from tests.espn_sync_board import (
    EXPECTED_401872657_HOME,
    assert_applied_fields_reached_board,
    assert_board_matches,
)
from tests.test_widget_state_retention import (
    APP_FILE,
    SCOREBOARD_ROWS,
    _reset_streamlit_dg_stack,
    _values,
    _widget,
)
from tests.test_mid_script_rerun import SURVIVE_SYNC, UNMIRRORED, _seed

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIXTURE = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_FIXTURE = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"


def _fake_espn_fetch(self, event_id: str, *, our_team_id: str) -> FetchResult:
    summary = json.loads(SUMMARY_FIXTURE.read_text(encoding="utf-8"))
    scoreboard = json.loads(SCOREBOARD_FIXTURE.read_text(encoding="utf-8"))
    snap = parse_espn_summary(
        summary,
        sport=self.sport,
        our_team_id=str(our_team_id),
        scoreboard_payload=scoreboard,
    )
    return FetchResult(ok=True, snapshot=snap, raw_summary=summary)


def _boot_event(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot",
        _fake_espn_fetch,
    )
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_live_pick_event_id").set_value("401872657")
    _widget(at, "ui_live_home_or_away").set_value("home")
    at.run()
    assert not at.exception, at.exception
    return at


def _applied(at: AppTest) -> list:
    try:
        aud = at.session_state[LIVE_FEED_LAST_AUDIT]
    except Exception:
        aud = {}
    return list((aud or {}).get("applied") or [])


def test_sync_arrives_on_ui_and_game_mirrors(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _boot_event(monkeypatch)
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    applied = _applied(at)
    for token in (
        "down",
        "distance",
        "field_position",
        "possession",
        "our_score→game.offense_points",
        "opponent_score→game.defense_points",
        "quarter",
        "clock",
    ):
        assert token in applied, applied
    assert_applied_fields_reached_board(at.session_state, applied)
    assert_board_matches(at.session_state, EXPECTED_401872657_HOME)
    assert at.session_state.game.offense_points == 0
    assert at.session_state.game.defense_points == 3
    assert at.session_state.game.possession == "offense"


def test_sync_sets_possession_from_feed_without_chip(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _boot_event(monkeypatch)
    assert at.session_state["ui_possession_side"] == "Not set"
    gen = at.button(key="main_console_generate")
    assert gen.disabled
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_possession_side"] == "Our team"
    gen2 = at.button(key="main_console_generate")
    assert not gen2.disabled
    captions = " ".join(str(getattr(c, "value", c)) for c in at.caption)
    assert GENERATE_UNSET_POSSESSION_REASON not in captions


def test_sync_keeps_non_default_defense_weather(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _boot_event(monkeypatch)
    _seed(at, UNMIRRORED)
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    assert _values(at, SURVIVE_SYNC) == SURVIVE_SYNC
    assert_board_matches(at.session_state, EXPECTED_401872657_HOME)


def test_log_after_sync_advances_and_undo_restores(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _boot_event(monkeypatch)
    at.button(key="sidebar_live_sync").click().run()
    assert_board_matches(at.session_state, EXPECTED_401872657_HOME)
    at.button(key="main_console_generate").click().run()
    assert not at.exception, at.exception
    assert at.session_state.result is not None
    at.button(key="main_log_yards_0").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_down"] == 3
    assert at.session_state["game_down"] == 3
    assert at.session_state["ui_distance"] == 1
    at.run()
    assert at.session_state["ui_down"] == 3
    assert at.session_state["game_down"] == 3
    at.button(key="main_console_undo").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_down"] == 2
    assert at.session_state["game_down"] == 2
    assert at.session_state["ui_distance"] == 1


def test_load_json_scores_arrive_on_board() -> None:
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_score_ours").set_value(13)
    _widget(at, "ui_score_theirs").set_value(9)
    at.run()
    g = Game.new_game()
    g.offense_points = 21
    g.defense_points = 17
    g.quarter = 3
    g.clock_seconds_remaining = 5 * 60 + 30
    payload = game_to_json(g)
    at.file_uploader[0].upload("game.json", payload.encode("utf-8"), "application/json")
    at.run()
    at.button(key="sidebar_btn_load_game_json").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_score_ours"] == 21
    assert at.session_state["game_score_ours"] == 21
    assert at.session_state["ui_score_theirs"] == 17
    assert at.session_state["game_score_theirs"] == 17
    assert at.session_state["ui_game_period"] == 3
    assert at.session_state["game_period"] == 3
    assert at.session_state["ui_quarter_clock_mins"] == 5
    assert at.session_state["ui_quarter_clock_secs"] == 30


def test_sync_backend_tripwire_skips_when_hydrate_pending() -> None:
    from unittest.mock import patch

    ss = {
        GAME_WIDGET_HYDRATE_PENDING: True,
        "game_down": 2,
        "ui_down": 1,
    }
    with patch("playcaller.streamlit_state.widget_backend_bridge.logger.warning") as warn:
        sync_backend_from_widgets(ss)
    assert ss["game_down"] == 2
    warn.assert_called()
    assert "GAME_WIDGET_HYDRATE_PENDING" in warn.call_args[0][0]


def test_live_sync_flag_is_plain_session_key() -> None:
    assert LIVE_SYNC_REQUESTED == "live_sync_requested"
