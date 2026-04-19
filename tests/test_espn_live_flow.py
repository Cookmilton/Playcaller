"""Tests for ESPN live manual lookup / sync readiness helpers (UI layer, no HTTP)."""

from __future__ import annotations

from playcaller.streamlit_state.keys import (
    LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    LIVE_FEED_MANUAL_EVENT_FOR_ID,
    LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID,
    LIVE_FEED_MANUAL_EVENT_TEAMS,
)
from playcaller.ui.espn_live_flow import (
    ManualEventLookupPhase,
    clear_manual_event_cache_if_event_id_mismatch,
    clear_manual_fetch_error_if_event_id_changed,
    derive_espn_sync_readiness,
    manual_event_lookup_phase,
    manual_lookup_status,
    maybe_auto_fetch_event_id,
    our_team_label_from_manual_teams,
)


def _teams() -> dict:
    return {
        "event_id": "401772988",
        "away_name": "Rams",
        "home_name": "Giants",
        "away_team_id": "14",
        "home_team_id": "10",
    }


def test_manual_phase_no_event() -> None:
    assert (
        manual_event_lookup_phase(eid_typed="", teams=None, teams_for_eid="", fetch_error=None)
        is ManualEventLookupPhase.NO_EVENT_ID
    )


def test_manual_phase_need_fetch() -> None:
    assert (
        manual_event_lookup_phase(eid_typed="401772988", teams=None, teams_for_eid="", fetch_error=None)
        is ManualEventLookupPhase.NEED_FETCH
    )


def test_manual_phase_failed() -> None:
    assert (
        manual_event_lookup_phase(
            eid_typed="401772988",
            teams=None,
            teams_for_eid="",
            fetch_error="HTTP 404",
        )
        is ManualEventLookupPhase.FETCH_FAILED
    )


def test_manual_phase_loaded() -> None:
    t = _teams()
    assert (
        manual_event_lookup_phase(
            eid_typed="401772988",
            teams=t,
            teams_for_eid="401772988",
            fetch_error=None,
        )
        is ManualEventLookupPhase.GAME_LOADED
    )


def test_clear_cache_on_event_id_mismatch() -> None:
    ss: dict = {
        LIVE_FEED_MANUAL_EVENT_TEAMS: _teams(),
        LIVE_FEED_MANUAL_EVENT_FOR_ID: "401772988",
        LIVE_FEED_MANUAL_EVENT_FETCH_ERROR: None,
    }
    clear_manual_event_cache_if_event_id_mismatch(
        ss,
        eid_typed="401772999",
        teams_key=LIVE_FEED_MANUAL_EVENT_TEAMS,
        for_id_key=LIVE_FEED_MANUAL_EVENT_FOR_ID,
        fetch_error_key=LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    )
    assert ss[LIVE_FEED_MANUAL_EVENT_TEAMS] is None
    assert ss[LIVE_FEED_MANUAL_EVENT_FOR_ID] == ""
    assert ss[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] is None


def test_clear_cache_when_event_id_cleared() -> None:
    ss: dict = {
        LIVE_FEED_MANUAL_EVENT_TEAMS: _teams(),
        LIVE_FEED_MANUAL_EVENT_FOR_ID: "401772988",
        LIVE_FEED_MANUAL_EVENT_FETCH_ERROR: None,
    }
    clear_manual_event_cache_if_event_id_mismatch(
        ss,
        eid_typed="   ",
        teams_key=LIVE_FEED_MANUAL_EVENT_TEAMS,
        for_id_key=LIVE_FEED_MANUAL_EVENT_FOR_ID,
        fetch_error_key=LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    )
    assert ss[LIVE_FEED_MANUAL_EVENT_TEAMS] is None


def test_clear_fetch_error_when_event_id_changes() -> None:
    ss: dict = {
        LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID: "401772988",
        LIVE_FEED_MANUAL_EVENT_FETCH_ERROR: "HTTP 404",
    }
    clear_manual_fetch_error_if_event_id_changed(
        ss,
        eid_typed="401772999",
        last_attempt_id_key=LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID,
        fetch_error_key=LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    )
    assert ss[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] is None


def test_sync_readiness_scoreboard() -> None:
    r = derive_espn_sync_readiness(
        uses_scoreboard=True,
        event_id="999",
        our_team_id="14",
        manual=None,
    )
    assert r.can_sync
    assert r.block_reason is None


def test_sync_readiness_manual_blocked_until_loaded() -> None:
    st = manual_lookup_status(eid_typed="401", teams=None, teams_for_eid="", fetch_error=None)
    r = derive_espn_sync_readiness(uses_scoreboard=False, event_id="401", our_team_id="", manual=st)
    assert not r.can_sync
    assert r.block_reason is not None


def test_sync_readiness_manual_requires_manual_status() -> None:
    r = derive_espn_sync_readiness(
        uses_scoreboard=False,
        event_id="401772988",
        our_team_id="14",
        manual=None,
    )
    assert not r.can_sync


def test_sync_readiness_manual_ready() -> None:
    st = manual_lookup_status(
        eid_typed="401772988",
        teams=_teams(),
        teams_for_eid="401772988",
        fetch_error=None,
    )
    r = derive_espn_sync_readiness(
        uses_scoreboard=False,
        event_id="401772988",
        our_team_id="14",
        manual=st,
    )
    assert r.can_sync


def test_our_team_label() -> None:
    assert our_team_label_from_manual_teams(_teams(), home_or_away="away") == "Rams"


def test_maybe_auto_fetch_need_fetch() -> None:
    do, cur = maybe_auto_fetch_event_id(
        eid_typed="401772988",
        auto_fetch_enabled=True,
        lookup_phase=ManualEventLookupPhase.NEED_FETCH,
        session_key_prev="",
    )
    assert do is True
    assert cur == "401772988"


def test_maybe_auto_fetch_no_loop_after_failure() -> None:
    do, _ = maybe_auto_fetch_event_id(
        eid_typed="401772988",
        auto_fetch_enabled=True,
        lookup_phase=ManualEventLookupPhase.FETCH_FAILED,
        session_key_prev="401772988",
    )
    assert do is False


def test_maybe_auto_fetch_new_id_after_failure() -> None:
    do, cur = maybe_auto_fetch_event_id(
        eid_typed="401772999",
        auto_fetch_enabled=True,
        lookup_phase=ManualEventLookupPhase.FETCH_FAILED,
        session_key_prev="401772988",
    )
    assert do is True
    assert cur == "401772999"
