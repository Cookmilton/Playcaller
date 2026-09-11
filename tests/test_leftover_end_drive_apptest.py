"""E6: leftover open-drive warning sits above Generate; End drive then lets the new feed merge."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import List

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.types import FetchResult
from playcaller.streamlit_state.keys import LIVE_FEED_LAST_AUDIT, LIVE_FEED_SCOREBOARD_ROWS
from tests.test_widget_state_retention import APP_FILE, SCOREBOARD_ROWS, _reset_streamlit_dg_stack, _widget

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIXTURE = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_FIXTURE = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"


def _base_payloads() -> tuple[dict, dict]:
    return (
        json.loads(SUMMARY_FIXTURE.read_text(encoding="utf-8")),
        json.loads(SCOREBOARD_FIXTURE.read_text(encoding="utf-8")),
    )


def _leftover_summary(summary: dict) -> dict:
    sm = copy.deepcopy(summary)
    x = copy.deepcopy(sm["drives"]["current"])
    sm["drives"]["previous"] = list(sm["drives"]["previous"]) + [x]
    sm["drives"]["current"] = {
        "id": "40187265799",
        "team": dict(x["team"]),
        "plays": [
            {**copy.deepcopy(x["plays"][0]), "id": "Y0", "sequenceNumber": "90000"},
            {**copy.deepcopy(x["plays"][1]), "id": "Y1", "sequenceNumber": "90100"},
        ],
    }
    return sm


class _QueuedEspnFetch:
    def __init__(self, summaries: List[dict], scoreboard: dict) -> None:
        self._summaries = list(summaries)
        self._scoreboard = scoreboard
        self.calls = 0

    def __call__(self, event_id: str, *, our_team_id: str) -> FetchResult:
        idx = min(self.calls, len(self._summaries) - 1)
        self.calls += 1
        snap = parse_espn_summary(
            self._summaries[idx],
            sport="nfl",
            our_team_id=str(our_team_id),
            scoreboard_payload=self._scoreboard,
        )
        return FetchResult(ok=True, snapshot=snap, raw_summary=self._summaries[idx])


def _button_keys(at: AppTest) -> List[str]:
    return [str(getattr(w, "key", "") or "") for w in at.button]


def _click(at: AppTest, key: str) -> None:
    at.button(key=key).click().run()
    assert not at.exception, at.exception


@pytest.fixture
def leftover_app(monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, _QueuedEspnFetch]:
    summary, scoreboard = _base_payloads()
    fake = _QueuedEspnFetch([summary, _leftover_summary(summary), _leftover_summary(summary)], scoreboard)
    monkeypatch.setattr("playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot", fake)
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_live_pick_event_id").set_value("401872657")
    _widget(at, "ui_live_home_or_away").set_value("home")
    at.run()
    assert not at.exception, at.exception
    return at, fake


def test_leftover_warning_above_generate_end_drive_then_new_drive_merges(
    leftover_app: tuple[AppTest, _QueuedEspnFetch],
) -> None:
    at, fake = leftover_app
    _click(at, "sidebar_chip_poss_our")
    _click(at, "sidebar_live_sync")
    ids_open = [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id]
    assert ids_open == ["401872657543", "401872657573"]
    n_archived = len(at.session_state.game.drives)

    _click(at, "sidebar_live_sync")
    assert fake.calls >= 2
    try:
        aud = at.session_state[LIVE_FEED_LAST_AUDIT]
    except KeyError:
        aud = {}
    skipped = (aud or {}).get("skipped") or []
    assert PREVIOUS_FEED_DRIVE_OPEN in skipped

    warn_text = " ".join(str(getattr(w, "value", w)) for w in at.warning)
    assert "Previous feed drive still open" in warn_text
    keys = _button_keys(at)
    assert "main_console_end_leftover_drive" in keys
    assert "main_console_generate" in keys
    assert keys.index("main_console_end_leftover_drive") < keys.index("main_console_generate")

    _click(at, "main_console_end_leftover_drive")
    assert [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id] == []
    assert len(at.session_state.game.drives) == n_archived + 1
    archived_ids = [
        p.external_play_id
        for d in at.session_state.game.drives
        for p in (d.plays or [])
        if p.external_play_id
    ]
    assert "401872657543" in archived_ids
    leftover_warn = " ".join(str(getattr(w, "value", w)) for w in at.warning)
    assert "Previous feed drive still open" not in leftover_warn

    _click(at, "sidebar_live_sync")
    assert [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id] == ["Y0", "Y1"]
