"""
Pending UI application: merge queued field/situation/widget state before any
``key="ui_*"`` widgets render on the next run.

This module is an **approved** early writer to mirrored ``ui_*`` keys (see
``widget_backend_bridge`` and ``ui_write_guard``). Feed/load paths should prefer
``game_*`` + hydrate instead of extending direct ``ui_*`` writes here.
"""

from __future__ import annotations

from typing import Any, MutableMapping

from playcaller.streamlit_state.keys import (
    LAST_DRIVE_SNAP_CONTEXT,
    LIVE_FEED_SCOREBOARD_ROWS,
    PENDING_END_DRIVE_UI,
    PENDING_LOG_SITUATION,
    PENDING_NEW_GAME_UI,
    PENDING_SCOREBOARD_STATUS,
    PENDING_SESSION_GAME_DATE,
    PENDING_SESSION_GAME_DATE_REPLACE,
    PENDING_SESSION_SETUP_HYDRATE,
    SESSION_SETUP_GAME_DATE,
    UNDO_BUNDLE,
)


def apply_pending_log_situation(ss: MutableMapping[str, Any]) -> None:
    """Apply auto-advance from the last logged play; run before any ui_* widgets."""
    pending = ss.pop(PENDING_LOG_SITUATION, None)
    if not pending:
        return
    ss["ui_territory"] = str(pending["territory"])
    ss["ui_yardline"] = int(pending["yardline"])
    ss["ui_down"] = int(pending["down"])
    ss["ui_distance"] = int(pending["distance"])


def apply_pending_end_drive_ui(ss: MutableMapping[str, Any]) -> None:
    """Apply clock + possession after archiving a drive; run before any ui_* widgets."""
    pending = ss.pop(PENDING_END_DRIVE_UI, None)
    if not pending:
        return
    if "ui_quarter_clock_mins" in pending:
        ss["ui_quarter_clock_mins"] = int(pending["ui_quarter_clock_mins"])
    if "ui_quarter_clock_secs" in pending:
        ss["ui_quarter_clock_secs"] = int(pending["ui_quarter_clock_secs"])
    # Legacy keys (pre quarter-clock UI)
    if "ui_clock_mins" in pending:
        ss["ui_clock_mins"] = int(pending["ui_clock_mins"])
    if "ui_clock_secs" in pending:
        ss["ui_clock_secs"] = int(pending["ui_clock_secs"])
    if "ui_score_ours" in pending:
        ss["ui_score_ours"] = int(pending["ui_score_ours"])
    if "ui_score_theirs" in pending:
        ss["ui_score_theirs"] = int(pending["ui_score_theirs"])
    if "ui_possession_side" in pending:
        ss["ui_possession_side"] = pending["ui_possession_side"]


def apply_pending_new_game_ui(ss: MutableMapping[str, Any]) -> None:
    """Apply full **New game** widget defaults; run before any ui_* widgets."""
    pending = ss.pop(PENDING_NEW_GAME_UI, None)
    if not pending:
        return
    for k, v in pending.items():
        ss[str(k)] = v


def apply_pending_session_setup_hydrate(ss: MutableMapping[str, Any]) -> None:
    """Copy ``game.session_metadata`` onto session-setup widgets; run before those widgets."""
    if not ss.pop(PENDING_SESSION_SETUP_HYDRATE, None):
        return
    game = ss.get("game")
    if game is None:
        return
    from playcaller.streamlit_state.session_setup import hydrate_session_setup_widgets

    hydrate_session_setup_widgets(ss, game)


def apply_pending_session_game_date(ss: MutableMapping[str, Any]) -> None:
    """Set the game-date widget from ESPN when the operator has not typed one."""
    val = ss.pop(PENDING_SESSION_GAME_DATE, None)
    replace = bool(ss.pop(PENDING_SESSION_GAME_DATE_REPLACE, False))
    if not val:
        return
    if str(ss.get(SESSION_SETUP_GAME_DATE) or "").strip() and not replace:
        return
    ss[SESSION_SETUP_GAME_DATE] = str(val).strip()


def apply_pending_scoreboard_status(ss: MutableMapping[str, Any]) -> None:
    """Refresh the Game dropdown's scoreboard ``detail`` from the last successful sync."""
    patch = ss.pop(PENDING_SCOREBOARD_STATUS, None)
    if not isinstance(patch, dict):
        return
    eid = str(patch.get("event_id") or "").strip()
    detail = str(patch.get("detail") or "")
    if not eid:
        return
    rows = ss.get(LIVE_FEED_SCOREBOARD_ROWS)
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "") == eid:
            row["detail"] = detail
            break


def apply_all_pending(ss: MutableMapping[str, Any]) -> None:
    """
    Single entrypoint: load-JSON → quick-log advance → end-drive clock/possession →
    new-game full reset → session-setup hydrate → ESPN session date → scoreboard status.

    Order matters when multiple buffers are present (last writer wins on overlapping keys).
    Load JSON runs first so it can queue possession/session-setup pendings for this same call.
    """
    from playcaller.streamlit_state.load_game import apply_pending_load_game

    apply_pending_load_game(ss)
    apply_pending_log_situation(ss)
    apply_pending_end_drive_ui(ss)
    apply_pending_new_game_ui(ss)
    apply_pending_session_setup_hydrate(ss)
    apply_pending_session_game_date(ss)
    apply_pending_scoreboard_status(ss)


def clear_in_progress_log_state(ss: MutableMapping[str, Any]) -> None:
    """Drop pending snap merge, drive-end hints, and undo snapshot (not the drive log itself)."""
    ss.pop(PENDING_LOG_SITUATION, None)
    ss.pop(LAST_DRIVE_SNAP_CONTEXT, None)
    ss.pop(UNDO_BUNDLE, None)
