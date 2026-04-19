"""Shared Streamlit display helpers (text, drive lists, post-log copy)."""

from __future__ import annotations

import html
import time

import streamlit as st

from playcaller import (
    ActualPlayResult,
    DriveLogger,
    FootballPlayPredictor,
    Game,
    GameContext,
    format_actual_play_result_description,
)
from playcaller.situation import yards_from_own_goal, yards_to_opponent_goal_from_abs
from playcaller.ui.previous_drives_render import render_drive_archive_with_replay
from playcaller.ui.product_copy import SECTION_CURRENT_SERIES
from playcaller.ui_components import FAM_COLOR

LOG_OUTCOME_AUTO = "Auto (from call + yards)"
_LOG_COMPLETE = "Complete pass"
_LOG_RUN = "Run"
_LOG_FG_GOOD = "Field goal good"
_LOG_FG_MISS = "Field goal missed"
LOG_OUTCOME_OPTIONS = [
    LOG_OUTCOME_AUTO,
    "Complete pass",
    "Incomplete pass",
    "QB scramble",
    "Run",
    "Sack",
    "Interception",
    _LOG_FG_GOOD,
    _LOG_FG_MISS,
]
LOG_TARGET_AUTO = "Auto from play"
LOG_TARGET_OPTIONS = [
    LOG_TARGET_AUTO,
    "X",
    "Z",
    "H (slot)",
    "Y (TE)",
    "RB",
    "QB",
]


def net_yards_to_endzone(territory: str, yardline: int) -> int:
    """Yards needed for a touchdown from the current spot (offense perspective)."""
    a = yards_from_own_goal(territory, yardline)
    return int(yards_to_opponent_goal_from_abs(a))


def fmt_local_epoch(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))


def ordinal_down(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(max(1, min(4, int(n))), f"{int(n)}th")


def render_previous_drives(
    game: Game,
    *,
    predictor: FootballPlayPredictor,
    ambient_ctx: GameContext,
) -> None:
    render_drive_archive_with_replay(game, predictor=predictor, ambient_ctx=ambient_ctx)


def render_current_series_live(drive_log: DriveLogger) -> None:
    """Always-available view of the active drive (broadcast-style)."""
    n = len(drive_log.results)
    label = f"{n} play(s) on this drive" if n else "No plays logged on this drive yet"
    with st.expander(f"**{SECTION_CURRENT_SERIES}** — {label}", expanded=bool(n)):
        if not drive_log.results:
            st.caption("Use **Log result (quick)** below after a recommendation. Game history is never cleared except **New game**.")
            return
        tail = drive_log.results[-12:]
        start_i = len(drive_log.results) - len(tail) + 1
        for i, r in enumerate(tail, start=start_i):
            line = (r.description or "").strip() or format_actual_play_result_description(r)
            fc = FAM_COLOR.get(r.family, "#6b7280")
            st.markdown(
                f'<div style="border-left:3px solid {fc};padding:5px 0 5px 10px;margin:5px 0;'
                f'font-size:13px;line-height:1.4;color:#e2e8f0">'
                f'<span style="color:#64748b;font-weight:600;margin-right:6px">{i}.</span>'
                f"{html.escape(line)}</div>",
                unsafe_allow_html=True,
            )
        if len(drive_log.results) > 12:
            st.caption(f"Showing last 12 of {len(drive_log.results)} plays on this series.")


def safe_summary_html(text: str) -> str:
    """Escape user-facing recap lines for ``unsafe_allow_html`` inserts."""
    return html.escape(str(text), quote=True).replace("\n", "<br/>")


def post_log_summary_and_toast(actual: ActualPlayResult, snap) -> tuple[str, list[str]]:
    """
    Build (1) a multi-line recap for ``last_play_summary`` / UI and (2) short
    fragments joined for ``st.toast``. ``snap`` is the **next** snap after the play.
    """
    desc = (actual.description or "").strip() or format_actual_play_result_description(actual)
    pos = "Own" if snap.territory == "own" else "Opp."
    pos_toast = "Opp." if snap.territory == "opponents" else "Own"
    line1 = (
        f"Logged: {desc} — next: {ordinal_down(snap.down)} & {int(snap.distance)} "
        f"at {pos} {int(snap.yardline)}"
    )
    toast = [
        desc[:72] + ("…" if len(desc) > 72 else ""),
        f"→ {snap.down}&{snap.distance} @ {pos_toast} {snap.yardline}",
    ]
    extras: list[str] = []
    if snap.touchdown:
        extras.append("TD — parked at GL (New drive when ready).")
        toast.append("TD")
    if snap.turnover_on_downs:
        extras.append("Turnover on downs — next 1st at this spot.")
        toast.append("TOD")
    tg = snap.tags
    if tg.first_down_exact:
        extras.append("First down — exact sticks.")
        toast.append("FD — exact sticks")
    if tg.crossed_midfield:
        extras.append("Crossed midfield.")
        toast.append("Crossed 50")
    if tg.explosive_midfield:
        extras.append("Explosive + midfield.")
        toast.append("Explosive + midfield")
    elif tg.explosive_play:
        extras.append("Explosive play.")
        toast.append("Explosive")
    if tg.no_gain:
        extras.append("No gain.")
        toast.append("No gain")
    if tg.negative_play:
        extras.append("Behind LOS.")
        toast.append("Behind LOS")
    summary = line1 if not extras else line1 + "\n" + " ".join(extras)
    return summary, toast
