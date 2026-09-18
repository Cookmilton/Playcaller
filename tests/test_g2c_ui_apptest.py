"""Phase 2 UI AppTests: undo-after-auto-close button and stale Log disable."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import List

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.types import FetchResult
from playcaller.streamlit_state.keys import LIVE_FEED_SCOREBOARD_ROWS, LIVE_FEED_TEAM_SCOPE
from tests.test_g22_auto_close import _derived_open_den_current
from tests.test_g23b_undo_after_auto_close import _derived_n_completed_n1_current, _mergeable_play_ids
from tests.test_g26_mnf_401872931_apptest import EVENT_ID, SCOREBOARD_ROWS_MNF
from tests.test_widget_state_retention import APP_FILE, SCOREBOARD_ROWS, _reset_streamlit_dg_stack, _widget

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_657 = ROOT / "tests/fixtures/espn_summary_live_401872657.json"
SCOREBOARD_657 = ROOT / "tests/fixtures/espn_scoreboard_live_401872657.json"

LOG_YARDS_0 = "main_log_yards_0"


class _QueuedEspnFetch:
    def __init__(self, summaries: List[dict], scoreboard: dict | None = None) -> None:
        self._summaries = list(summaries)
        self._scoreboard = scoreboard if scoreboard is not None else {"events": []}
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


def _click(at: AppTest, key: str) -> None:
    at.button(key=key).click().run()
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException


def test_g2c_undo_button_restores_logger_without_hydrate_clobber(monkeypatch: pytest.MonkeyPatch) -> None:
    n_payload = _derived_open_den_current()
    n1_payload = _derived_n_completed_n1_current()
    n_ids = _mergeable_play_ids(n_payload["drives"]["current"])
    fake = _QueuedEspnFetch([n_payload, n1_payload, n1_payload])
    monkeypatch.setattr("playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot", fake)
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS_MNF
    at.run()
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException
    _widget(at, "ui_live_pick_event_id").set_value(EVENT_ID)
    _widget(at, "ui_live_home_or_away").set_value("away")
    at.run()
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException
    _click(at, "sidebar_chip_poss_our")
    _click(at, "sidebar_live_sync")
    open_ids = [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id]
    assert open_ids == n_ids
    captions = " ".join(str(getattr(c, "value", c)) for c in at.caption)
    assert f"**Drive:** {len(n_ids)} logged" in captions or f"{len(n_ids)} logged" in captions.lower()
    expanders = " ".join(str(getattr(e, "label", getattr(e, "value", e))) for e in at.expander)
    assert f"{len(n_ids)} play(s) on this drive" in expanders

    _click(at, "sidebar_live_sync")
    assert fake.calls >= 2
    assert [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id] != n_ids
    assert "main_console_undo_drive_archive" in [str(getattr(b, "key", "") or "") for b in at.button]

    _click(at, "main_console_undo_drive_archive")
    restored = [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id]
    assert restored == n_ids
    captions_u = " ".join(str(getattr(c, "value", c)) for c in at.caption)
    expanders_u = " ".join(str(getattr(e, "label", getattr(e, "value", e))) for e in at.expander)
    assert f"{len(n_ids)} play(s) on this drive" in expanders_u
    assert f"**Drive:** {len(n_ids)} logged" in captions_u or f"{len(n_ids)} logged" in captions_u.lower()
    assert at.session_state.game.drives == []

    src = (ROOT / "playcaller/ui/main_console.py").read_text(encoding="utf-8")
    assert "request_undo_drive_archive()" in src
    assert "st.rerun(" not in src


def test_g2c_stale_log_disabled_after_down_sync_and_cleared_by_regenerate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = json.loads(SUMMARY_657.read_text(encoding="utf-8"))
    scoreboard = json.loads(SCOREBOARD_657.read_text(encoding="utf-8"))
    sb_changed = copy.deepcopy(scoreboard)
    for ev in sb_changed.get("events") or []:
        if str(ev.get("id") or "") != "401872657":
            continue
        for comp in ev.get("competitions") or []:
            sit = comp.get("situation")
            if isinstance(sit, dict):
                sit["down"] = 3
    calls = {"n": 0}

    def fetch(self, event_id: str, *, our_team_id: str) -> FetchResult:
        calls["n"] += 1
        sb = scoreboard if calls["n"] < 2 else sb_changed
        snap = parse_espn_summary(
            summary,
            sport="nfl",
            our_team_id=str(our_team_id),
            scoreboard_payload=sb,
        )
        return FetchResult(ok=True, snapshot=snap, raw_summary=summary)

    monkeypatch.setattr("playcaller.services.live_feed_sync.EspnFootballProvider.fetch_snapshot", fetch)
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException
    _widget(at, "ui_live_pick_event_id").set_value("401872657")
    _widget(at, "ui_live_home_or_away").set_value("home")
    _widget(at, LIVE_FEED_TEAM_SCOPE).set_value("our")
    at.run()
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException
    _click(at, "sidebar_live_sync")
    assert at.session_state["ui_down"] == 2
    _click(at, "main_console_generate")
    assert at.session_state.result is not None
    log0 = at.button(key=LOG_YARDS_0)
    assert not log0.disabled

    _click(at, "sidebar_live_sync")
    assert at.session_state["ui_down"] == 3
    assert at.session_state["game_down"] == 3
    captions = " ".join(str(getattr(c, "value", c)) for c in at.caption)
    assert "down" in captions
    assert "Log is disabled" in captions
    assert at.button(key=LOG_YARDS_0).disabled

    _click(at, "main_console_generate")
    captions2 = " ".join(str(getattr(c, "value", c)) for c in at.caption)
    assert "Log is disabled" not in captions2
    assert not at.button(key=LOG_YARDS_0).disabled
    assert not at.exception, at.exception  # HydrateClobberError / StreamlitAPIException
