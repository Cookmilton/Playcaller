"""J3 Phase 3 — unsynced feed quarter/clock stay None on Game and in the export."""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.game import Game, game_from_json, game_to_dict, game_to_json
from playcaller.streamlit_state.feed_board_copy import (
    GENERATE_UNSYNCED_CLOCK_REASON,
    copy_derived_clock_to_game,
    generate_blocked_reason_for_session,
)
from playcaller.streamlit_state.keys import LIVE_FEED_LAST_AUDIT, LIVE_FEED_LAST_ORIGIN
from playcaller.streamlit_state.possession import ORIGIN_FEED, ORIGIN_MANUAL


def test_copy_skips_feed_quarter_clock_when_audit_skipped() -> None:
    g = Game.new_game()
    g.quarter = 3
    g.clock_seconds_remaining = 441
    ss = {
        LIVE_FEED_LAST_ORIGIN: ORIGIN_FEED,
        LIVE_FEED_LAST_AUDIT: {
            "skipped": [
                {"field": "quarter", "reason": "absent_in_source"},
                {"field": "clock", "reason": "absent_in_source"},
            ]
        },
    }
    copy_derived_clock_to_game(g, ss, quarter=1, seconds_remaining=900)
    assert g.quarter is None
    assert g.clock_seconds_remaining is None
    blob = game_to_dict(g)
    assert blob["quarter"] is None
    assert blob["clock_seconds_remaining"] is None


def test_copy_manual_origin_writes_operator_clock() -> None:
    g = Game.new_game()
    ss = {LIVE_FEED_LAST_ORIGIN: ORIGIN_MANUAL, LIVE_FEED_LAST_AUDIT: {}}
    copy_derived_clock_to_game(g, ss, quarter=2, seconds_remaining=420)
    assert g.quarter == 2
    assert g.clock_seconds_remaining == 420


def test_copy_feed_applies_when_not_skipped() -> None:
    g = Game.new_game()
    ss = {LIVE_FEED_LAST_ORIGIN: ORIGIN_FEED, LIVE_FEED_LAST_AUDIT: {"skipped": []}}
    copy_derived_clock_to_game(g, ss, quarter=1, seconds_remaining=370)
    assert g.quarter == 1
    assert g.clock_seconds_remaining == 370


def test_generate_blocked_when_feed_clock_skipped() -> None:
    ss = {
        LIVE_FEED_LAST_ORIGIN: ORIGIN_FEED,
        LIVE_FEED_LAST_AUDIT: {
            "skipped": [
                {"field": "quarter", "reason": "absent_in_source"},
                {"field": "clock", "reason": "absent_in_source"},
            ]
        },
    }
    assert generate_blocked_reason_for_session(ss, possession="offense") == GENERATE_UNSYNCED_CLOCK_REASON
    ss[LIVE_FEED_LAST_ORIGIN] = ORIGIN_MANUAL
    assert generate_blocked_reason_for_session(ss, possession="offense") is None


def test_legacy_json_quarter_one_still_loads() -> None:
    raw = json.dumps({"game_id": "x", "quarter": 1, "clock_seconds_remaining": 900, "drives": []})
    g = game_from_json(raw)
    assert g.quarter == 1
    assert g.clock_seconds_remaining == 900


def test_null_quarter_clock_roundtrip() -> None:
    g = Game.new_game()
    raw = game_to_json(g)
    g2 = game_from_json(raw)
    assert g2.quarter is None
    assert g2.clock_seconds_remaining is None
    assert json.loads(raw)["quarter"] is None
    assert json.loads(raw)["clock_seconds_remaining"] is None


def test_apptest_final_mnf_export_null_quarter_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_g26_mnf_401872931_apptest import _boot_and_sync

    at, _urls = _boot_and_sync(monkeypatch)
    at.run()
    assert not at.exception, at.exception
    g = at.session_state.game
    assert g.quarter is None
    assert g.clock_seconds_remaining is None
    blob = json.loads(game_to_json(g))
    assert blob["quarter"] is None
    assert blob["clock_seconds_remaining"] is None


def test_apptest_live_401872657_clock_reaches_game(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_g1_sync_board import _boot_event

    at = _boot_event(monkeypatch)
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    at.run()
    assert not at.exception, at.exception
    g = at.session_state.game
    assert g.quarter == 1
    assert g.clock_seconds_remaining == 370
    blob = json.loads(game_to_json(g))
    assert blob["quarter"] == 1
    assert blob["clock_seconds_remaining"] == 370


def test_apptest_manual_operator_clock_reaches_export() -> None:
    from tests.test_widget_state_retention import APP_FILE, _reset_streamlit_dg_stack, _widget

    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_game_period").set_value(2)
    _widget(at, "ui_quarter_clock_mins").set_value(7)
    _widget(at, "ui_quarter_clock_secs").set_value(0)
    at.run()
    assert not at.exception, at.exception
    g = at.session_state.game
    assert g.quarter == 2
    assert g.clock_seconds_remaining == 7 * 60
    blob = json.loads(game_to_json(g))
    assert blob["quarter"] == 2
    assert blob["clock_seconds_remaining"] == 420
