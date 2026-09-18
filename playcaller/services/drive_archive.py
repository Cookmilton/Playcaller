"""
Single archive path for operator **End drive** and G2.2 auto-close leftover.

Callers pass a session mapping (Streamlit ``session_state`` or a test dict). This module
does not write widget-bound ``ui_*`` keys; the operator wrapper queues ``PENDING_END_DRIVE_UI``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, MutableMapping, Optional

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
    sort_game_drives_by_feed_sequence,
)
from playcaller.possession import possessing_team_from_feed_plays
from playcaller.streamlit_state.keys import (
    GAME_POSSESSION_SIDE,
    LAST_DRIVE_SNAP_CONTEXT,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    PENDING_END_DRIVE_UI,
    WAREHOUSE_HISTORICAL_SIGNAL,
)
from playcaller.streamlit_state.pending import clear_in_progress_log_state
from playcaller.streamlit_state.possession import (
    end_drive_blocked_reason,
    possession_side_radio_label,
)

ARCHIVE_KIND_MANUAL = "manual"
ARCHIVE_KIND_AUTO = "auto"


@dataclass(frozen=True)
class ArchiveOpenDriveResult:
    archived: Optional[Drive]
    refused: Optional[str]
    kind: str = ARCHIVE_KIND_MANUAL
    espn_drive_key: str = ""


def _mark_merged_espn_key(ss: MutableMapping[str, Any], key: str) -> None:
    k = str(key or "").strip()
    if not k:
        return
    raw = ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS)
    merged = [str(x) for x in raw] if isinstance(raw, list) else []
    if k not in merged:
        merged.append(k)
    ss[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS] = sorted(merged)


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
    finished = replace(finished, feed_import_tag="espn") if espn_drive_key else finished
    if update_board:
        apply_scoring_after_drive(game, finished)
        flip_possession_after_drive(game, finished)
    game.drives.append(finished)
    sort_game_drives_by_feed_sequence(game)
    _mark_merged_espn_key(ss, espn_drive_key)

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
    return ArchiveOpenDriveResult(
        archived=finished,
        refused=None,
        kind=kind,
        espn_drive_key=str(espn_drive_key or ""),
    )
