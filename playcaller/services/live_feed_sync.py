"""Pre-widget ESPN sync: set ``LIVE_SYNC_REQUESTED``, then fetch/apply before widgets hydrate."""

from __future__ import annotations

import logging
from typing import Any, MutableMapping, Optional

from football_history_warehouse.ingest.from_json import ingest_espn_summary_after_live_fetch

from playcaller.game import Game
from playcaller.live_data import EspnFootballProvider, SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_HTTP_INSECURE_WARNING,
    LIVE_FEED_LAST_ERROR,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    LIVE_FEED_MANUAL_EVENT_FOR_ID,
    LIVE_FEED_MANUAL_EVENT_TEAMS,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_SYNC_INITIATOR,
    LIVE_SYNC_REQUESTED,
    LIVE_SYNC_TOAST,
    UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES,
    UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS,
)
from playcaller.streamlit_state.possession import ORIGIN_FEED, ORIGIN_MANUAL

_POLL_INITIATOR = "poll"
logger = logging.getLogger(__name__)


def request_live_sync(*, initiator: str = "manual") -> None:
    """Widget ``on_click``: queue a feed sync for the start of this script run (no ``st.rerun``).

    The default ``initiator="manual"`` writes only ``LIVE_SYNC_REQUESTED`` (today's Sync
    button and Force sync). A poll passes ``initiator="poll"`` so
    :func:`origin_to_write` can persist ``"feed"`` without overriding a manual board.
    """
    import streamlit as st

    st.session_state[LIVE_SYNC_REQUESTED] = True
    if initiator != "manual":
        st.session_state[LIVE_SYNC_INITIATOR] = initiator


def origin_to_write(*, initiator: Optional[str], current_origin: Optional[str]) -> str:
    """Origin value ``apply_snapshot`` should persist on ``LIVE_FEED_LAST_ORIGIN``.

    A manual or Force sync (initiator unset or ``"manual"``) always writes ``"feed"``.
    A poll writes ``"feed"`` when the board has no origin yet or is already ``"feed"``,
    and passes ``"manual"`` through when the board is already manual so that write
    leaves the operator's choice in place. The poll intent is this function — not
    ``origin=None``.
    """
    if initiator == _POLL_INITIATOR and current_origin == ORIGIN_MANUAL:
        return ORIGIN_MANUAL
    return ORIGIN_FEED


def sync_readiness_from_session(ss: MutableMapping[str, Any]):
    """Resolve event id + coached team from the last committed widget/session values."""
    from playcaller.ui.espn_live_flow import derive_espn_sync_readiness, manual_lookup_status

    adv = str(ss.get("ui_live_our_team_advanced") or "").strip()
    rows = ss.get(LIVE_FEED_SCOREBOARD_ROWS) or []
    if isinstance(rows, list) and rows:
        ids = [str(r.get("id") or "") for r in rows if isinstance(r, dict)]
        ids = [i for i in ids if i]
        if not ids:
            return derive_espn_sync_readiness(uses_scoreboard=True, event_id="", our_team_id="")
        pick_id = str(ss.get("ui_live_pick_event_id") or ids[0]).strip() or ids[0]
        picked = next((r for r in rows if isinstance(r, dict) and str(r.get("id") or "") == pick_id), rows[0])
        ho = str(ss.get("ui_live_home_or_away") or "away")
        our_tid = str(picked.get("away_id") if ho == "away" else picked.get("home_id") or "")
        if adv:
            our_tid = adv
        return derive_espn_sync_readiness(uses_scoreboard=True, event_id=pick_id, our_team_id=our_tid)

    event_id = str(ss.get("ui_live_event_id_manual") or "").strip()
    teams_d = ss.get(LIVE_FEED_MANUAL_EVENT_TEAMS)
    for_eid = str(ss.get(LIVE_FEED_MANUAL_EVENT_FOR_ID) or "").strip()
    ferr = ss.get(LIVE_FEED_MANUAL_EVENT_FETCH_ERROR)
    manual = manual_lookup_status(
        eid_typed=event_id,
        teams=teams_d if isinstance(teams_d, dict) else None,
        teams_for_eid=for_eid,
        fetch_error=str(ferr) if ferr else None,
    )
    ho = str(ss.get("ui_live_home_or_away") or "away")
    our_tid = ""
    if isinstance(teams_d, dict):
        our_tid = str(teams_d["away_team_id"] if ho == "away" else teams_d["home_team_id"])
    if adv:
        our_tid = adv
    return derive_espn_sync_readiness(
        uses_scoreboard=False,
        event_id=event_id,
        our_team_id=our_tid,
        manual=manual,
    )


def sync_options_from_session(ss: MutableMapping[str, Any]) -> SyncOptions:
    return SyncOptions(
        lock_situation=bool(ss.get("ui_live_lock_situation")),
        lock_score=bool(ss.get("ui_live_lock_score")),
        auto_append_feed_plays=bool(ss.get("ui_live_auto_plays")),
        import_completed_feed_drives=bool(ss.get(UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES, True)),
        import_current_feed_drive_plays=bool(ss.get(UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS, True)),
    )


def run_requested_live_sync(ss: MutableMapping[str, Any]) -> Optional[str]:
    """
    If ``LIVE_SYNC_REQUESTED``, fetch ESPN and ``apply_snapshot`` before widgets.

    Returns a toast string for the caller (or ``None``). Sets ``LIVE_FEED_LAST_ERROR`` on failure.
    Polling can set the same flag. The request flag is always cleared in ``finally``.
    """
    if not ss.get(LIVE_SYNC_REQUESTED):
        return None
    try:
        return _run_live_sync_body(ss)
    except Exception as exc:
        logger.exception("Live ESPN sync failed")
        ss[LIVE_FEED_LAST_ERROR] = str(exc) or "Fetch failed."
        return None
    finally:
        ss.pop(LIVE_SYNC_REQUESTED, None)
        ss.pop(LIVE_SYNC_INITIATOR, None)


def _run_live_sync_body(ss: MutableMapping[str, Any]) -> Optional[str]:
    game = ss.get("game")
    drive_log = ss.get("drive_log")
    if not isinstance(game, Game) or not isinstance(drive_log, DriveLogger):
        ss[LIVE_FEED_LAST_ERROR] = "Session is not ready to sync yet."
        return None

    ready = sync_readiness_from_session(ss)
    if not ready.can_sync:
        ss[LIVE_FEED_LAST_ERROR] = ready.block_reason or "Sync is not ready yet."
        return None

    sport = str(ss.get("ui_live_espn_sport") or "nfl")
    prov = EspnFootballProvider(sport)  # type: ignore[arg-type]
    fr = prov.fetch_snapshot(ready.event_id, our_team_id=ready.our_team_id)
    if not fr.ok or fr.snapshot is None:
        ss[LIVE_FEED_LAST_ERROR] = fr.error or "Fetch failed."
        return None

    ss[LIVE_FEED_LAST_ERROR] = None
    ss[LIVE_FEED_HTTP_INSECURE_WARNING] = bool(fr.used_insecure_ssl_fallback)
    res = apply_snapshot(
        game=game,
        session=ss,
        drive_log=drive_log,
        snapshot=fr.snapshot,
        options=sync_options_from_session(ss),
        origin=origin_to_write(
            initiator=ss.get(LIVE_SYNC_INITIATOR),
            current_origin=ss.get(LIVE_FEED_LAST_ORIGIN),
        ),
    )
    extra: list[str] = []
    if fr.raw_summary:
        try:
            wh_ingest = ingest_espn_summary_after_live_fetch(fr.raw_summary, sport=sport)
        except Exception as exc:
            logger.warning("Warehouse minimal ingest after ESPN sync failed: %s", exc, exc_info=True)
            wh_ingest = None
        else:
            extra.append("warehouse " + ("game row created" if wh_ingest.was_new else "game row updated"))
    if res.plays_appended:
        extra.append(f"+{res.plays_appended} feed plays")
    if res.drives_imported:
        extra.append(f"+{res.drives_imported} completed drives")
    msg = res.message + (f" · {' · '.join(extra)}" if extra else "")
    ss[LIVE_SYNC_TOAST] = msg
    return msg
