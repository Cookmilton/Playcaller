"""
Mid-script ``st.rerun()`` must not wipe unmirrored sidebar widgets.

Mirrored ``game_*`` fields come back via hydrate. Defense look, weather, wind, mode,
blitz, QB, and feed scope have no backend mirror — stale-widget cleanup resets them
to ``new_game_ui_values``.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from typing import Any, Dict

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.game import Game, game_to_json
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.types import FetchResult
from playcaller.streamlit_state.keys import LIVE_FEED_SCOREBOARD_ROWS, LIVE_FEED_TEAM_SCOPE
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from tests.test_widget_state_retention import (
    APP_FILE,
    SCOREBOARD_ROWS,
    WIDGET_KINDS,
    _reset_streamlit_dg_stack,
    _values,
    _widget,
)

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIXTURE = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_FIXTURE = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"

# Unmirrored (or operator-owned) widgets that mid-script rerun used to reset.
UNMIRRORED: Dict[str, Any] = {
    "ui_territory": "opponents",
    "ui_def_personnel": "dime",
    "ui_coverage_shell": "cover_2",
    "ui_safeties": "two_high",
    "ui_box_count": 8,
    "ui_blitz_likely": True,
    "ui_weather": "wind",
    "ui_wind_mph": 18,
    "ui_qb_limited": True,
    "ui_game_mode": "must_score",
    LIVE_FEED_TEAM_SCOPE: "both",
}

# Sync overwrites mirrored board fields from the feed; these must still survive.
SURVIVE_SYNC = {
    k: v
    for k, v in UNMIRRORED.items()
    if k
    not in {
        "ui_territory",  # feed field position
    }
}


def _seed(at: AppTest, values: Dict[str, Any]) -> None:
    for key, value in values.items():
        _widget(at, key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    assert _values(at, values) == values, "seeding did not stick"


@pytest.fixture
def seeded_unmirrored() -> AppTest:
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    _seed(at, UNMIRRORED)
    return at


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


def test_mark_manual_keeps_unmirrored(seeded_unmirrored: AppTest) -> None:
    at = seeded_unmirrored
    at.button(key="sidebar_live_mark_manual").click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED


def test_sync_keeps_unmirrored(seeded_unmirrored: AppTest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Feed hydrate may change territory/down/score; defense look and mode must stay."""
    monkeypatch.setattr(
        "playcaller.ui.sidebar.EspnFootballProvider.fetch_snapshot",
        _fake_espn_fetch,
    )
    at = seeded_unmirrored
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    assert _values(at, SURVIVE_SYNC) == SURVIVE_SYNC


def test_new_game_resets_via_pending_defaults(seeded_unmirrored: AppTest) -> None:
    """New game is *supposed* to reset widgets; it must do so via PENDING_NEW_GAME_UI."""
    at = seeded_unmirrored
    at.button(key="sidebar_btn_new_game_top").click().run()
    assert not at.exception, at.exception
    defaults = new_game_ui_values()
    for key, seeded in UNMIRRORED.items():
        expected = defaults.get(key, seeded)
        try:
            actual = at.session_state[key]
        except KeyError:
            actual = "<<dropped from session_state>>"
        assert actual == expected, f"{key}: expected new-game {expected!r}, got {actual!r}"


def test_load_json_keeps_unmirrored(seeded_unmirrored: AppTest) -> None:
    """Load JSON hydrates board + session setup; it must not wipe defense/weather/mode."""
    at = seeded_unmirrored
    payload = game_to_json(Game.new_game())
    at.file_uploader[0].upload("game.json", payload.encode("utf-8"), "application/json")
    at.run()
    assert not at.exception, at.exception
    at.button(key="sidebar_btn_load_game_json").click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED


def test_end_drive_keeps_unmirrored(seeded_unmirrored: AppTest) -> None:
    at = seeded_unmirrored
    at.button(key="sidebar_chip_poss_our").click().run()
    assert not at.exception, at.exception
    at.button(key="sidebar_btn_end_drive_next").click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED


def test_generate_keeps_unmirrored(seeded_unmirrored: AppTest) -> None:
    at = seeded_unmirrored
    at.button(key="sidebar_chip_poss_our").click().run()
    assert not at.exception, at.exception
    submit = None
    for w in list(at.button) + list(getattr(at, "form_submit_button", [])):
        if getattr(w, "key", None) == "sidebar_form_submit_generate":
            submit = w
            break
    assert submit is not None, "Generate submit button did not render"
    submit.click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED


def test_log_and_undo_keep_unmirrored(seeded_unmirrored: AppTest) -> None:
    at = seeded_unmirrored
    at.button(key="sidebar_chip_poss_our").click().run()
    submit = None
    for w in list(at.button) + list(getattr(at, "form_submit_button", [])):
        if getattr(w, "key", None) == "sidebar_form_submit_generate":
            submit = w
            break
    assert submit is not None
    submit.click().run()
    assert not at.exception, at.exception
    at.button(key="main_log_yards_0").click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED
    at.button(key="sidebar_undo_last_play").click().run()
    assert not at.exception, at.exception
    assert _values(at, UNMIRRORED) == UNMIRRORED


def test_seeding_weather_rain_does_not_warn_on_wind_write(caplog: pytest.LogCaptureFixture) -> None:
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    with caplog.at_level(logging.WARNING, logger="playcaller.streamlit_state.ui_write_guard"):
        at.run()
        _widget(at, "ui_weather").set_value("rain")
        at.run()
    assert not at.exception, at.exception
    assert at.session_state["ui_weather"] == "rain"
    illegal = [r for r in caplog.records if "ui_wind_mph" in r.getMessage()]
    assert illegal == [], [r.getMessage() for r in illegal]


# Files that still call ``st.rerun()`` on purpose: the post-widget helper, plus other
# Streamlit pages / the legacy ``app.py`` that are not on the live-console deferred path.
_RERUN_ALLOWLIST = {
    ("playcaller/services/game_controller.py", "maybe_rerun_after_widgets"),
    ("playcaller/ui/review_film_room.py", None),
    ("playcaller/ui/warehouse_review.py", None),
    ("playcaller/ui/history_validation.py", None),
    ("app.py", None),
}


def _enclosing_function(tree: ast.AST, node: ast.AST) -> str | None:
    parent_fn = None
    for ancestor in ast.walk(tree):
        if not isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.lineno < ancestor.lineno:
            continue
        end = getattr(ancestor, "end_lineno", None)
        if end is not None and node.lineno > end:
            continue
        if node.lineno >= ancestor.lineno and (end is None or node.lineno <= end):
            if parent_fn is None or ancestor.lineno >= parent_fn.lineno:
                parent_fn = ancestor
    return parent_fn.name if parent_fn else None


def test_no_new_bare_st_rerun_outside_allowlist() -> None:
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(".") or "/__pycache__/" in f"/{rel}/":
            continue
        if rel.startswith("tests/") or rel.startswith(".pytest_vendor"):
            continue
        src = path.read_text(encoding="utf-8")
        if "st.rerun(" not in src:
            continue
        tree = ast.parse(src, filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "rerun"):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "st"):
                continue
            fn = _enclosing_function(tree, node)
            allowed = False
            for file_pat, fn_pat in _RERUN_ALLOWLIST:
                if rel != file_pat:
                    continue
                if fn_pat is None or fn == fn_pat:
                    allowed = True
                    break
            if not allowed:
                offenders.append(f"{rel}:{node.lineno} in {fn or '<module>'}")
    assert offenders == [], "bare st.rerun() outside allowlist:\n" + "\n".join(offenders)
