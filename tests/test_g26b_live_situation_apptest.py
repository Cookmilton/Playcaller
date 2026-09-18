"""G2.6b: live 401872657 situation values must land in ui_* and game_* widgets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.espn_sync_board import EXPECTED_401872657_HOME, UI_TO_GAME, assert_board_matches
from tests.test_g1_sync_board import _applied, _boot_event
from tests.test_widget_state_retention import _widget

ROOT = Path(__file__).resolve().parents[1]
SCOREBOARD = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"

SITUATION_UI_KEYS = (
    "ui_down",
    "ui_distance",
    "ui_territory",
    "ui_yardline",
    "ui_possession_side",
    "ui_game_period",
    "ui_quarter_clock_mins",
    "ui_quarter_clock_secs",
)


def test_g26b_live_situation_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    401872657 carries a live situation. JSON paths in the fixtures:

    Scoreboard (authoritative):
      events[].competitions[0].situation.down
      events[].competitions[0].situation.distance
      events[].competitions[0].situation.yardLine + possessionText (field)
      events[].competitions[0].situation.possession
      events[].competitions[0].status.period
      events[].competitions[0].status.displayClock

    Summary (clock/period echo; last-play-end fallback):
      header.competitions[0].status.period
      header.competitions[0].status.displayClock
      drives.current.plays[-1].end.down
      drives.current.plays[-1].end.distance
      drives.current.plays[-1].end.yardLine
      drives.current.plays[-1].end.possessionText
    """
    sb = json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    sit = None
    period = None
    clock = None
    for ev in sb.get("events") or []:
        if str(ev.get("id") or "") != "401872657":
            continue
        comp = (ev.get("competitions") or [None])[0] or {}
        sit = comp.get("situation") or {}
        status = comp.get("status") or {}
        period = status.get("period")
        clock = status.get("displayClock")
        break
    assert isinstance(sit, dict)
    assert sit.get("down") == 2
    assert sit.get("distance") == 1
    assert sit.get("yardLine") == 34
    assert sit.get("possessionText") == "LAR 34"
    assert str(sit.get("possession")) == "14"
    assert period == 1
    assert clock == "6:10"

    at = _boot_event(monkeypatch)
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    applied = _applied(at)
    for token in ("down", "distance", "field_position", "possession", "quarter", "clock"):
        assert token in applied, applied
    assert_board_matches(at.session_state, EXPECTED_401872657_HOME)
    for ui_key in SITUATION_UI_KEYS:
        want = EXPECTED_401872657_HOME[ui_key]
        if ui_key != "ui_possession_side":
            _widget(at, ui_key)
        assert at.session_state[ui_key] == want
        assert at.session_state[UI_TO_GAME[ui_key]] == want
