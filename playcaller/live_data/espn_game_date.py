"""Parse ESPN event / competition timestamps into an honest ``YYYY-MM-DD`` (or None)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping, Optional
from zoneinfo import ZoneInfo

_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_EASTERN = ZoneInfo("America/New_York")

LIVE_FEED_GAME_DATE_MISMATCH = "live_feed_game_date_mismatch"
LIVE_FEED_APPLIED_ESPN_GAME_DATE = "live_feed_applied_espn_game_date"


def calendar_date_from_espn_iso(raw: Any) -> Optional[str]:
    """America/New_York calendar date from an ESPN ISO-8601 timestamp. Unknown → None."""
    s = str(raw or "").strip()
    m = _ISO_DATE_PREFIX.match(s)
    if not m:
        return None
    if len(s) == 10:
        return m.group(1)
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_EASTERN).date().isoformat()


def resolve_espn_game_date(
    summary_payload: Optional[Mapping[str, Any]],
    scoreboard_payload: Optional[Mapping[str, Any]],
    *,
    event_id: str,
) -> Optional[str]:
    """Prefer the scoreboard event matching ``event_id``, then summary header / competition."""
    eid = str(event_id or "").strip()
    blobs: list[Any] = []
    if isinstance(scoreboard_payload, Mapping):
        for ev in scoreboard_payload.get("events") or []:
            if not isinstance(ev, Mapping):
                continue
            if eid and str(ev.get("id") or "").strip() != eid:
                continue
            blobs.append(ev.get("date"))
            comps = ev.get("competitions") or []
            if comps and isinstance(comps[0], Mapping):
                blobs.append(comps[0].get("date"))
            if eid:
                break
    if isinstance(summary_payload, Mapping):
        header = summary_payload.get("header")
        if isinstance(header, Mapping):
            blobs.append(header.get("date"))
            comps = header.get("competitions") or []
            if comps and isinstance(comps[0], Mapping):
                blobs.append(comps[0].get("date"))
    for blob in blobs:
        parsed = calendar_date_from_espn_iso(blob)
        if parsed:
            return parsed
    return None


def apply_espn_game_date_to_session(session: MutableMapping[str, Any], feed_date: str) -> None:
    """Queue ESPN date unless the operator already set a different session date."""
    from playcaller.streamlit_state.keys import (
        PENDING_SESSION_GAME_DATE,
        PENDING_SESSION_GAME_DATE_REPLACE,
        SESSION_SETUP_GAME_DATE,
    )

    feed = str(feed_date or "").strip()
    if not feed:
        session.pop(LIVE_FEED_GAME_DATE_MISMATCH, None)
        return
    widget = str(session.get(SESSION_SETUP_GAME_DATE) or "").strip()
    applied = str(session.get(LIVE_FEED_APPLIED_ESPN_GAME_DATE) or "").strip()
    operator_set = bool(widget) and widget != applied and widget != feed
    if operator_set:
        session[LIVE_FEED_GAME_DATE_MISMATCH] = {"session": widget, "espn": feed}
        return
    session.pop(LIVE_FEED_GAME_DATE_MISMATCH, None)
    if widget != feed:
        session[PENDING_SESSION_GAME_DATE] = feed
        if widget and widget == applied:
            session[PENDING_SESSION_GAME_DATE_REPLACE] = True
    session[LIVE_FEED_APPLIED_ESPN_GAME_DATE] = feed


def game_date_mismatch_warning(session: Mapping[str, Any]) -> Optional[str]:
    raw = session.get(LIVE_FEED_GAME_DATE_MISMATCH)
    if not isinstance(raw, Mapping):
        return None
    sess = str(raw.get("session") or "").strip()
    espn = str(raw.get("espn") or "").strip()
    if not sess or not espn:
        return None
    return (
        f"Session game date ({sess}) differs from ESPN ({espn}). "
        "ESPN date is not applied because the session date was set explicitly."
    )
