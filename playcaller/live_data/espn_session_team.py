"""Queue ESPN coached-team name onto session setup (operator-set wins, like game date)."""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional

LIVE_FEED_TEAM_NAME_MISMATCH = "live_feed_team_name_mismatch"
LIVE_FEED_APPLIED_ESPN_TEAM_NAME = "live_feed_applied_espn_team_name"


def apply_espn_team_name_to_session(session: MutableMapping[str, Any], feed_name: str) -> None:
    """Queue ESPN team name unless the operator already set a different session name."""
    from playcaller.streamlit_state.keys import (
        PENDING_SESSION_TEAM_NAME,
        PENDING_SESSION_TEAM_NAME_REPLACE,
        SESSION_SETUP_TEAM_NAME,
    )

    feed = str(feed_name or "").strip()
    if not feed:
        session.pop(LIVE_FEED_TEAM_NAME_MISMATCH, None)
        return
    widget = str(session.get(SESSION_SETUP_TEAM_NAME) or "").strip()
    applied = str(session.get(LIVE_FEED_APPLIED_ESPN_TEAM_NAME) or "").strip()
    operator_set = bool(widget) and widget != applied and widget != feed
    if operator_set:
        session[LIVE_FEED_TEAM_NAME_MISMATCH] = {"session": widget, "espn": feed}
        return
    session.pop(LIVE_FEED_TEAM_NAME_MISMATCH, None)
    if widget != feed:
        session[PENDING_SESSION_TEAM_NAME] = feed
        if widget and widget == applied:
            session[PENDING_SESSION_TEAM_NAME_REPLACE] = True
    session[LIVE_FEED_APPLIED_ESPN_TEAM_NAME] = feed


def team_name_mismatch_warning(session: Mapping[str, Any]) -> Optional[str]:
    raw = session.get(LIVE_FEED_TEAM_NAME_MISMATCH)
    if not isinstance(raw, Mapping):
        return None
    sess = str(raw.get("session") or "").strip()
    espn = str(raw.get("espn") or "").strip()
    if not sess or not espn:
        return None
    return (
        f"Session team name ({sess}) differs from ESPN ({espn}). "
        "ESPN name is not applied because the session team was set explicitly."
    )
