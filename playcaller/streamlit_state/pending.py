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
    PENDING_END_DRIVE_UI,
    PENDING_LOG_SITUATION,
    PENDING_NEW_GAME_UI,
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
        ss["ui_possession_side"] = str(pending["ui_possession_side"])


def apply_pending_new_game_ui(ss: MutableMapping[str, Any]) -> None:
    """Apply full **New game** widget defaults; run before any ui_* widgets."""
    pending = ss.pop(PENDING_NEW_GAME_UI, None)
    if not pending:
        return
    for k, v in pending.items():
        ss[str(k)] = v


def apply_all_pending(ss: MutableMapping[str, Any]) -> None:
    """
    Single entrypoint: quick-log advance → end-drive clock/possession → new-game full reset.

    Order matters when multiple buffers are present (last writer wins on overlapping keys).
    """
    apply_pending_log_situation(ss)
    apply_pending_end_drive_ui(ss)
    apply_pending_new_game_ui(ss)


def clear_in_progress_log_state(ss: MutableMapping[str, Any]) -> None:
    """Drop pending snap merge, drive-end hints, and undo snapshot (not the drive log itself)."""
    ss.pop(PENDING_LOG_SITUATION, None)
    ss.pop(LAST_DRIVE_SNAP_CONTEXT, None)
    ss.pop(UNDO_BUNDLE, None)
