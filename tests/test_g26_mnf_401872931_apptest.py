"""G2.6: AppTest ESPN sync of MNF 401872931 (DEN @ KC final) from the real capture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.drive_audit_report import implied_points_for_drive
from playcaller.game import OUTCOME_SOURCE_ESPN, YARDS_SOURCE_ESPN
from playcaller.live_data.http_util import JsonFetchResult
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_FEED_TEAM_SCOPE,
)
from playcaller.ui.situation_honesty import (
    NOT_SYNCED_TEXT,
    build_situation_honesty,
    skipped_situation_reasons,
)
from tests.espn_sync_board import assert_applied_fields_reached_board, assert_board_matches
from tests.test_widget_state_retention import APP_FILE, _reset_streamlit_dg_stack, _widget

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_FIXTURE = ROOT / "tests/fixtures/espn_summary_mnf_401872931.json"
EVENT_ID = "401872931"
DEN_ID = "7"
KC_ID = "12"

# Sideline picker only — not an ESPN capture. DEN is away / coached.
SCOREBOARD_ROWS_MNF = [
    {
        "id": EVENT_ID,
        "label": "DEN @ KC",
        "detail": "Final",
        "home_abbr": "KC",
        "away_abbr": "DEN",
        "home_id": KC_ID,
        "away_id": DEN_ID,
    }
]

# Distinct from new-game defaults so a dropped widget cannot hide behind 1st & 10 / 0–0.
SEEDED_BOARD = {
    "ui_down": 3,
    "ui_distance": 14,
    "ui_territory": "opponents",
    "ui_yardline": 37,
    "ui_game_period": 3,
    "ui_quarter_clock_mins": 7,
    "ui_quarter_clock_secs": 21,
    "ui_score_ours": 13,
    "ui_score_theirs": 9,
}

EXPECTED_SCORES = {
    "ui_score_ours": 10,
    "ui_score_theirs": 31,
}


def _fake_fetch(summary: dict, urls: list[str]):
    def fetch(url: str) -> JsonFetchResult:
        urls.append(url)
        if "scoreboard" in url:
            # Final games drop off the live scoreboard; do not invent a situation block.
            return JsonFetchResult(data={"events": []})
        return JsonFetchResult(data=summary)

    return fetch


def _applied(at: AppTest) -> list:
    try:
        aud = at.session_state[LIVE_FEED_LAST_AUDIT]
    except Exception:
        aud = {}
    return list((aud or {}).get("applied") or [])


def _assert_widget_holds(at: AppTest, key: str, want: object) -> None:
    w = _widget(at, key)
    got = w.value
    assert got == want, f"widget {key}: expected {want!r}, got {got!r}"
    assert at.session_state[key] == want, f"session {key}: expected {want!r}, got {at.session_state[key]!r}"


def _is_official_timeout_play(play: object) -> bool:
    blob = " ".join(
        str(getattr(play, attr, "") or "")
        for attr in ("concept_name", "description", "notes", "result_type", "play_type")
    ).lower()
    return "official timeout" in blob


def _boot_and_sync(monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, list[str]]:
    summary = json.loads(SUMMARY_FIXTURE.read_text(encoding="utf-8"))
    urls: list[str] = []
    monkeypatch.setattr("playcaller.live_data.espn_football.fetch_json", _fake_fetch(summary, urls))
    monkeypatch.setattr(
        "playcaller.services.live_feed_sync.ingest_espn_summary_after_live_fetch",
        lambda *a, **k: type("Ingest", (), {"was_new": False})(),
    )
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS_MNF
    at.run()
    assert not at.exception, at.exception
    _widget(at, "ui_live_pick_event_id").set_value(EVENT_ID)
    _widget(at, "ui_live_home_or_away").set_value("away")
    _widget(at, LIVE_FEED_TEAM_SCOPE).set_value("both")
    for key, value in SEEDED_BOARD.items():
        _widget(at, key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    at.button(key="sidebar_chip_poss_our").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_possession_side"] == "Our team"
    at.button(key="sidebar_live_sync").click().run()
    assert not at.exception, at.exception
    return at, urls


def test_g26_mnf_board_widgets_receive_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scores from the capture must land in rendered widgets; situation widgets stay bound."""
    at, urls = _boot_and_sync(monkeypatch)
    assert any("summary?event=401872931" in u for u in urls), urls
    applied = _applied(at)
    assert "our_score→game.offense_points" in applied, applied
    assert "opponent_score→game.defense_points" in applied, applied
    assert_applied_fields_reached_board(at.session_state, applied)
    assert_board_matches(at.session_state, EXPECTED_SCORES)
    _assert_widget_holds(at, "ui_score_ours", 10)
    _assert_widget_holds(at, "ui_score_theirs", 31)
    assert at.session_state.game.offense_points == 10
    assert at.session_state.game.defense_points == 31

    # Final summary has no situation/period/clock — widgets must still render (not drop).
    for key in (
        "ui_down",
        "ui_distance",
        "ui_yardline",
        "ui_territory",
        "ui_game_period",
        "ui_quarter_clock_mins",
        "ui_quarter_clock_secs",
    ):
        _assert_widget_holds(at, key, SEEDED_BOARD[key])
    assert at.session_state["ui_possession_side"] == "Our team"
    assert at.session_state["game_possession_side"] == "Our team"


# Final payload has no situation / period / clock — must skip, not invent Q4 0:00.
G26A_SKIPPED_SITUATION_FIELDS = (
    "down",
    "distance",
    "field_position",
    "possession",
    "quarter",
    "clock",
)


def test_g26a_final_situation_skips_are_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    """G2.6a: skipped fields have audit reasons, HUD says not synced, widgets are not invented."""
    at, _urls = _boot_and_sync(monkeypatch)
    aud = at.session_state[LIVE_FEED_LAST_AUDIT]
    reasons = skipped_situation_reasons(aud)
    for field in G26A_SKIPPED_SITUATION_FIELDS:
        assert field in reasons, (field, reasons, aud.get("skipped"))
        assert reasons[field], f"{field} skip reason is empty"

    src = aud.get("situation_source") if isinstance(aud, dict) else None
    honesty = build_situation_honesty(
        origin="feed",
        situation_source=str(src).strip() if src else None,
        skipped=reasons,
        possession=at.session_state.game.possession,
        down=int(at.session_state["ui_down"]),
        distance=int(at.session_state["ui_distance"]),
        territory=str(at.session_state["ui_territory"]),
        yardline=int(at.session_state["ui_yardline"]),
        own_timeouts=int(at.session_state["ui_own_tos"]),
        opp_timeouts=int(at.session_state["ui_opp_tos"]),
        period=int(at.session_state["ui_game_period"]),
        seconds_in_quarter=int(at.session_state["ui_quarter_clock_mins"]) * 60
        + int(at.session_state["ui_quarter_clock_secs"]),
    )
    for fld in (
        honesty.down,
        honesty.distance,
        honesty.field_position,
        honesty.possession,
        honesty.quarter,
        honesty.clock,
    ):
        assert fld.synced is False
        assert fld.text == NOT_SYNCED_TEXT

    hud = " ".join(str(getattr(m, "value", m)) for m in at.markdown)
    assert NOT_SYNCED_TEXT in hud, hud

    # Seeded Q3 7:21 must survive; Final must not invent Q4 / 0:00.
    assert at.session_state["ui_game_period"] == SEEDED_BOARD["ui_game_period"]
    assert at.session_state["ui_quarter_clock_mins"] == SEEDED_BOARD["ui_quarter_clock_mins"]
    assert at.session_state["ui_quarter_clock_secs"] == SEEDED_BOARD["ui_quarter_clock_secs"]
    assert at.session_state["ui_game_period"] != 4
    assert not (
        int(at.session_state["ui_quarter_clock_mins"]) == 0
        and int(at.session_state["ui_quarter_clock_secs"]) == 0
    )


def test_g26_mnf_scope_both_keeps_logger_coached_only() -> None:
    """c011aca: scope Both still rejects opponent in-progress plays (MNF DEN vs KC ids)."""
    from playcaller.live_data.feed_team_scope import current_feed_plays_merge_allowed

    allowed, msg = current_feed_plays_merge_allowed(
        scope="both",
        coached_team_id=DEN_ID,
        current_drive_team_espn_id=KC_ID,
        possession_team_id=KC_ID,
    )
    assert allowed is False
    assert "coached-team only" in msg


def test_g26_mnf_stored_drives_match_final(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stored drives after sync: ESPN outcomes/yards, DEN 10 / KC 31 implied, 12/12 split."""
    at, _urls = _boot_and_sync(monkeypatch)
    game = at.session_state.game
    assert len(game.drives) == 24
    for i, dr in enumerate(game.drives, 1):
        assert dr.outcome_source == OUTCOME_SOURCE_ESPN, f"drive {i} outcome_source={dr.outcome_source!r}"
        assert dr.yards_source == YARDS_SOURCE_ESPN, f"drive {i} yards_source={dr.yards_source!r}"
    assert max(int(d.total_yards) for d in game.drives) == 80
    den = [d for d in game.drives if d.possessing_team == "offense"]
    kc = [d for d in game.drives if d.possessing_team == "defense"]
    assert len(den) == 12
    assert len(kc) == 12
    den_pts = sum(implied_points_for_drive(d) for d in den)
    kc_pts = sum(implied_points_for_drive(d) for d in kc)
    assert (den_pts, kc_pts) == (10, 31)

    ids = [str(p.external_play_id) for d in game.drives for p in d.plays if p.external_play_id]
    assert ids
    assert len(ids) == len(set(ids))

    timeout_rows = [
        p
        for d in game.drives
        for p in (d.plays or [])
        if _is_official_timeout_play(p)
    ]
    timeout_rows.extend(p for p in at.session_state.drive_log.results if _is_official_timeout_play(p))
    assert timeout_rows == []
    # Final payload has no drives.current — logger stays empty even with scope Both.
    assert [p.external_play_id for p in at.session_state.drive_log.results if p.external_play_id] == []
