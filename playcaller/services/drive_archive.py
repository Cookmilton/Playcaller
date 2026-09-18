"""
Single archive path for operator **End drive** and G2.2 auto-close leftover.

Callers pass a session mapping (Streamlit ``session_state`` or a test dict). This module
does not write widget-bound ``ui_*`` keys; the operator wrapper queues ``PENDING_END_DRIVE_UI``.
Undo restores via a non-widget stack and is applied pre-widget.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any, Dict, List, MutableMapping, Optional

from playcaller.evaluation.snap_review_lifecycle import trim_snap_review_opens_for_play_count
from playcaller.game import (
    DRIVE_END_UI_AUTO,
    Drive,
    apply_scoring_after_drive,
    clock_seconds_after_drive_elapsed,
    complete_drive_from_plays,
    flip_possession_after_drive,
)
from playcaller.game_situation_input import context_quarter_from_period
from playcaller.live_data.drive_boundaries import (
    PREVIOUS_FEED_DRIVE_OPEN,
    espn_play_ids_from_plays,
    sort_game_drives_by_feed_sequence,
)
from playcaller.possession import possessing_team_from_feed_plays
from playcaller.streamlit_state.keys import (
    DRIVE_ARCHIVE_UNDO_STACK,
    GAME_PERIOD,
    GAME_POSSESSION_SIDE,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    LAST_DRIVE_SNAP_CONTEXT,
    LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_LAST_CURRENT_DRIVE_ID,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
    PENDING_END_DRIVE_UI,
    WAREHOUSE_HISTORICAL_SIGNAL,
)
from playcaller.streamlit_state.pending import clear_in_progress_log_state
from playcaller.streamlit_state.possession import (
    end_drive_blocked_reason,
    possession_side_radio_label,
)
from playcaller.streamlit_state.widget_backend_bridge import request_widget_hydrate_from_backend

ARCHIVE_KIND_MANUAL = "manual"
ARCHIVE_KIND_AUTO = "auto"


@dataclass(frozen=True)
class ArchiveOpenDriveResult:
    archived: Optional[Drive]
    refused: Optional[str]
    kind: str = ARCHIVE_KIND_MANUAL
    espn_drive_key: str = ""


def resolve_open_espn_drive_key(ss: MutableMapping[str, Any], drive_log: Any) -> str:
    """``{event_id}|drive:{last_current_id}`` when the logger still holds ESPN play ids."""
    if not espn_play_ids_from_plays(getattr(drive_log, "results", None)):
        return ""
    aud = ss.get(LIVE_FEED_LAST_AUDIT)
    eid = str((aud or {}).get("game_id") or "").strip() if isinstance(aud, dict) else ""
    last = str(ss.get(LIVE_FEED_LAST_CURRENT_DRIVE_ID) or "").strip()
    if eid and last:
        return f"{eid}|drive:{last}"
    return ""


def _mark_merged_espn_key(ss: MutableMapping[str, Any], key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    raw = ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS)
    merged = [str(x) for x in raw] if isinstance(raw, list) else []
    if k not in merged:
        merged.append(k)
    ss[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS] = sorted(merged)


def _list_copy(raw: Any) -> List[Any]:
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return []


def _snapshot_archive_state(ss: MutableMapping[str, Any]) -> Dict[str, Any]:
    game = ss["game"]
    dl = ss["drive_log"]
    aud = ss.get(LIVE_FEED_LAST_AUDIT)
    return {
        "drives": copy.deepcopy(list(game.drives or [])),
        "logger_results": copy.deepcopy(list(dl.results)),
        "seen_play_ids": list(_list_copy(ss.get(LIVE_FEED_SEEN_PLAY_IDS))),
        "merged_espn_drive_keys": list(_list_copy(ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS))),
        "eval_drive_epoch": int(ss.get("eval_drive_epoch", 0)),
        "possession": game.possession,
        "game_possession_side": ss.get(GAME_POSSESSION_SIDE),
        "offense_points": int(game.offense_points),
        "defense_points": int(game.defense_points),
        "quarter": int(game.quarter),
        "clock_seconds_remaining": game.clock_seconds_remaining,
        "game_score_ours": ss.get(GAME_SCORE_OURS),
        "game_score_theirs": ss.get(GAME_SCORE_THEIRS),
        "game_period": ss.get(GAME_PERIOD),
        "game_clock_mins": ss.get(GAME_QUARTER_CLOCK_MINS),
        "game_clock_secs": ss.get(GAME_QUARTER_CLOCK_SECS),
        "last_current_drive_id": ss.get(LIVE_FEED_LAST_CURRENT_DRIVE_ID),
        "last_audit": copy.deepcopy(aud) if isinstance(aud, dict) else aud,
    }


def _push_undo(ss: MutableMapping[str, Any], *, kind: str, espn_drive_key: str) -> None:
    entry = _snapshot_archive_state(ss)
    entry["kind"] = str(kind or ARCHIVE_KIND_MANUAL)
    entry["espn_drive_key"] = str(espn_drive_key or "")
    stack = _list_copy(ss.get(DRIVE_ARCHIVE_UNDO_STACK))
    stack.append(entry)
    ss[DRIVE_ARCHIVE_UNDO_STACK] = stack


def _add_suppress_key(ss: MutableMapping[str, Any], key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    raw = ss.get(LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS)
    keys = [str(x) for x in raw] if isinstance(raw, list) else []
    if k not in keys:
        keys.append(k)
    ss[LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS] = keys


def clear_auto_close_suppress_key(ss: MutableMapping[str, Any], key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    raw = ss.get(LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS)
    if not isinstance(raw, list):
        return
    ss[LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS] = [x for x in raw if str(x) != k]


def restore_last_drive_archive(ss: MutableMapping[str, Any]) -> bool:
    """
    Pop one archive undo entry and restore DriveLogger / ``game.drives`` / feed keys.

    AUTO undos add the ESPN drive key to the auto-close suppress set. Does not write ``ui_*``.
    """
    stack = _list_copy(ss.get(DRIVE_ARCHIVE_UNDO_STACK))
    if not stack:
        return False
    entry = stack.pop()
    ss[DRIVE_ARCHIVE_UNDO_STACK] = stack
    if not isinstance(entry, dict):
        return False

    game = ss["game"]
    dl = ss["drive_log"]
    game.drives = copy.deepcopy(list(entry.get("drives") or []))
    dl.reset()
    for play in list(entry.get("logger_results") or []):
        dl.log(play)
    ss[LIVE_FEED_SEEN_PLAY_IDS] = list(entry.get("seen_play_ids") or [])
    ss[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS] = list(entry.get("merged_espn_drive_keys") or [])
    ss["eval_drive_epoch"] = int(entry.get("eval_drive_epoch", 0))
    game.possession = entry.get("possession")
    side = entry.get("game_possession_side")
    if side is None:
        ss[GAME_POSSESSION_SIDE] = possession_side_radio_label(possession=game.possession)
    else:
        ss[GAME_POSSESSION_SIDE] = side
    game.offense_points = int(entry.get("offense_points", 0))
    game.defense_points = int(entry.get("defense_points", 0))
    game.quarter = int(entry.get("quarter", game.quarter))
    game.clock_seconds_remaining = entry.get("clock_seconds_remaining")
    if entry.get("game_score_ours") is not None:
        ss[GAME_SCORE_OURS] = int(entry["game_score_ours"])
    if entry.get("game_score_theirs") is not None:
        ss[GAME_SCORE_THEIRS] = int(entry["game_score_theirs"])
    if entry.get("game_period") is not None:
        ss[GAME_PERIOD] = int(entry["game_period"])
    if entry.get("game_clock_mins") is not None:
        ss[GAME_QUARTER_CLOCK_MINS] = int(entry["game_clock_mins"])
    if entry.get("game_clock_secs") is not None:
        ss[GAME_QUARTER_CLOCK_SECS] = int(entry["game_clock_secs"])
    ss[LIVE_FEED_LAST_CURRENT_DRIVE_ID] = entry.get("last_current_drive_id")
    if "last_audit" in entry:
        ss[LIVE_FEED_LAST_AUDIT] = entry.get("last_audit")
    ss.pop(PENDING_END_DRIVE_UI, None)
    request_widget_hydrate_from_backend(ss)

    if str(entry.get("kind") or "") == ARCHIVE_KIND_AUTO:
        _add_suppress_key(ss, str(entry.get("espn_drive_key") or ""))
    return True


def archive_open_drive(
    ss: MutableMapping[str, Any],
    *,
    kind: str = ARCHIVE_KIND_MANUAL,
    end_kind_override: Optional[str] = None,
    feed_audit: Any = None,
    espn_drive_key: str = "",
    feed_team_espn_id: str = "",
    feed_team_abbr: str = "",
    feed_team_display_name: str = "",
    update_board: bool = True,
) -> ArchiveOpenDriveResult:
    """
    Archive DriveLogger plays into ``game.drives`` and reset the live log.

    ``update_board`` (operator End drive) applies scoring, flips possession, and queues
    pre-widget clock/score/possession. Auto-close passes ``False`` — sync owns the board.
    """
    game = ss["game"]
    dl = ss["drive_log"]
    blocked = end_drive_blocked_reason(game.possession)
    if blocked:
        return ArchiveOpenDriveResult(archived=None, refused=blocked, kind=kind, espn_drive_key=espn_drive_key)
    if not dl.results:
        return ArchiveOpenDriveResult(archived=None, refused=None, kind=kind, espn_drive_key=espn_drive_key)

    snap_ctx = ss.get(LAST_DRIVE_SNAP_CONTEXT) or {}
    if end_kind_override is not None and str(end_kind_override) != DRIVE_END_UI_AUTO:
        override_kw: dict = {"end_kind_override": str(end_kind_override)}
    else:
        end_mode = str(ss.get("ui_drive_end_on_new", DRIVE_END_UI_AUTO))
        override_kw = {} if end_mode == DRIVE_END_UI_AUTO else {"end_kind_override": end_mode}

    coached_id = str(ss.get(LIVE_FEED_COACHED_TEAM_ESPN_ID) or "").strip()
    possessing, refuse = possessing_team_from_feed_plays(
        list(dl.results),
        coached_team_id=coached_id,
        fallback_possession=game.possession,
    )
    if refuse:
        return ArchiveOpenDriveResult(archived=None, refused=refuse, kind=kind, espn_drive_key=espn_drive_key)

    key = str(espn_drive_key or "").strip() or resolve_open_espn_drive_key(ss, dl)
    _push_undo(ss, kind=kind, espn_drive_key=key)

    finished = complete_drive_from_plays(
        list(dl.results),
        last_snap_touchdown=bool(snap_ctx.get("touchdown")),
        last_snap_turnover_on_downs=bool(snap_ctx.get("turnover_on_downs")),
        possessing_team=possessing,
        feed_team_espn_id=str(feed_team_espn_id or ""),
        feed_team_abbr=str(feed_team_abbr or ""),
        feed_team_display_name=str(feed_team_display_name or ""),
        feed_audit=feed_audit,
        **override_kw,
    )
    finished.session_drive_epoch = int(ss.get("eval_drive_epoch", 0))
    finished = replace(finished, feed_import_tag="espn") if key else finished
    if update_board:
        apply_scoring_after_drive(game, finished)
        flip_possession_after_drive(game, finished)
    game.drives.append(finished)
    sort_game_drives_by_feed_sequence(game)
    _mark_merged_espn_key(ss, key)

    if update_board:
        period = int(ss.get("ui_game_period", 1))
        game.quarter = context_quarter_from_period(period)
        clk = int(ss.get("ui_quarter_clock_mins", 0)) * 60 + int(ss.get("ui_quarter_clock_secs", 0))
        new_clk = clock_seconds_after_drive_elapsed(clk, finished)
        game.clock_seconds_remaining = new_clk
        ss[PENDING_END_DRIVE_UI] = {
            "ui_quarter_clock_mins": new_clk // 60,
            "ui_quarter_clock_secs": new_clk % 60,
            "ui_score_ours": int(game.offense_points),
            "ui_score_theirs": int(game.defense_points),
            "ui_possession_side": possession_side_radio_label(possession=game.possession),
        }
        ss[GAME_POSSESSION_SIDE] = possession_side_radio_label(possession=game.possession)

    dl.reset()
    trim_snap_review_opens_for_play_count(game.recommendation_audit, plays_on_drive=len(dl.results))
    ss["result"] = None
    ss.pop(WAREHOUSE_HISTORICAL_SIGNAL, None)
    ss["last_play_summary"] = ""
    clear_in_progress_log_state(ss)
    aud = ss.get(LIVE_FEED_LAST_AUDIT)
    if isinstance(aud, dict):
        skipped = [s for s in (aud.get("skipped") or []) if s != PREVIOUS_FEED_DRIVE_OPEN]
        ss[LIVE_FEED_LAST_AUDIT] = {**aud, "skipped": skipped}
    ss["eval_drive_epoch"] = int(ss.get("eval_drive_epoch", 0)) + 1
    if kind == ARCHIVE_KIND_MANUAL:
        clear_auto_close_suppress_key(ss, key)
    return ArchiveOpenDriveResult(
        archived=finished,
        refused=None,
        kind=kind,
        espn_drive_key=key,
    )
