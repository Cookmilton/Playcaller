"""Streamlit rendering for archived drives + model replay (keeps logic out of bare helpers)."""

from __future__ import annotations

import html

import streamlit as st

from playcaller import FootballPlayPredictor, Game, GameContext
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
    chronological_team_drive_indices,
    filter_previous_drive_indices,
    prior_drive_heading,
    previous_drives_empty_filter_message,
)
from playcaller.replay.analysis_types import ActualVsReplayComparisonRow
from playcaller.replay.previous_drive_replay import cached_comparison_rows_for_archived_drive
from playcaller.streamlit_state.keys import LIVE_FEED_TEAM_SCOPE
from playcaller.streamlit_state.session import coached_team_espn_id_for_previous_drives
from playcaller.ui.product_copy import CAPTION_POST_DRIVE_REPLAY, SECTION_DRIVE_ARCHIVE


def _render_comparison_breakdown(
    r: ActualVsReplayComparisonRow,
    *,
    widget_key_prefix: str,
) -> None:
    """Readable fields only (no raw JSON). Nested expanders are avoided — checkbox toggles body."""
    key = f"{widget_key_prefix}_breakdown_p{r.play_index}"
    if not st.checkbox("Breakdown", key=key, value=False):
        return
    pre = r.pre_snap_context
    m = r.model_replay_structured
    conf = m.confidence if m is not None else None
    conf_s = f"{conf:.0%}" if conf is not None else "—"
    st.markdown(
        f"- **actual_bucket:** `{html.escape(r.actual_summary_bucket or '—')}`\n"
        f"- **replay_bucket:** `{html.escape(r.replay_summary_bucket or '—')}`\n"
        f"- **down / distance:** {pre.down} & {pre.distance}\n"
        f"- **field:** {html.escape(pre.territory)} {pre.yardline}\n"
        f"- **quarter / clock:** Q{pre.quarter} · {pre.seconds_remaining // 60}:{pre.seconds_remaining % 60:02d} left in period\n"
        f"- **run/pass:** actual `{r.actual_run_pass or '—'}` · replay `{r.model_run_pass or '—'}`\n"
        f"- **matches:** run/pass `{r.run_pass_match}` · bucket `{r.coarse_bucket_match}` · family `{r.family_match}`\n"
        f"- **replay confidence:** {conf_s}\n"
    )
    st.caption("Replay is **retroactive** only — not stored Generate-time truth.")


def render_drive_archive_with_replay(
    game: Game,
    *,
    predictor: FootballPlayPredictor,
    ambient_ctx: GameContext,
) -> None:
    if not game.drives:
        return
    st.markdown(f"### {SECTION_DRIVE_ARCHIVE}")
    st.caption(
        "Completed possessions this session — Gamecast-style list. Each drive shows **who had the ball** "
        "(feed team name when available)."
    )
    st.caption(CAPTION_POST_DRIVE_REPLAY)
    our_tid = coached_team_espn_id_for_previous_drives(st.session_state)

    st.caption(
        "List filtering follows **Feed team scope** in the sidebar (ESPN / live feed)."
    )

    mode = str(st.session_state.get(LIVE_FEED_TEAM_SCOPE) or PREVIOUS_DRIVES_FILTER_OUR).strip().lower()
    if mode not in (PREVIOUS_DRIVES_FILTER_OUR, PREVIOUS_DRIVES_FILTER_OPPONENT, PREVIOUS_DRIVES_FILTER_BOTH):
        mode = PREVIOUS_DRIVES_FILTER_OUR

    indices = filter_previous_drive_indices(game, mode=mode, our_coached_espn_id=our_tid)
    if not indices:
        st.info(previous_drives_empty_filter_message(mode))
        return

    if (
        mode != PREVIOUS_DRIVES_FILTER_BOTH
        and not our_tid
        and any(str(getattr(dr, "feed_team_espn_id", "") or "").strip() for dr in game.drives)
    ):
        st.caption(
            "Feed drives need the **coached team** from ESPN (sync once). "
            "Until then, use **Both teams** or complete team identification."
        )

    seq = chronological_team_drive_indices(game)
    for chron_i in reversed(indices):
        dr = game.drives[chron_i]
        team_drive_n = seq[chron_i]
        title = prior_drive_heading(dr, team_drive_n)
        with st.expander(title, expanded=False):
            if getattr(dr, "feed_import_tag", None) == "espn":
                st.caption("Source: ESPN completed possession import.")
            if not dr.plays:
                st.caption("No plays recorded.")
            else:
                st.caption(
                    "Pre-snap positions are **reconstructed** from the play sequence (touchback anchors tried: "
                    "own 20–35). Overlay: current defensive read, weather, and clock."
                )
                rows = cached_comparison_rows_for_archived_drive(
                    st.session_state,
                    drive=dr,
                    drive_index=chron_i,
                    game=game,
                    ambient_ctx=ambient_ctx,
                    predictor=predictor,
                    plays=dr.plays,
                )
                _render_comparison_table(rows, widget_key_prefix=f"prev_drv_{chron_i}")


def _render_comparison_table(
    rows: list[ActualVsReplayComparisonRow],
    *,
    widget_key_prefix: str,
) -> None:
    h1, h2, h3 = st.columns([0.45, 5.6, 4])
    with h1:
        st.caption("")
    with h2:
        st.markdown("**Actual**")
    with h3:
        st.markdown("**Model replay (current engine)**")

    for r in rows:
        c0, c1, c2 = st.columns([0.45, 5.6, 4])
        with c0:
            st.markdown(f"{r.play_index}.")
        with c1:
            primary = html.escape(r.actual_play_summary_primary)
            detail = html.escape(r.actual_play_summary_detail) if r.actual_play_summary_detail else ""
            detail_html = (
                f'<div style="font-size:11px;color:#94a3b8;margin-top:2px">{detail}</div>'
                if detail
                else ""
            )
            badges = []
            if r.actual_run_pass:
                badges.append(html.escape(r.actual_run_pass))
            if r.run_pass_match is True:
                badges.append('<span style="color:#4ade80">RP match</span>')
            elif r.run_pass_match is False:
                badges.append('<span style="color:#f87171">RP diff</span>')
            if r.family_match is True:
                badges.append('<span style="color:#4ade80">Family match</span>')
            elif r.family_match is False:
                badges.append('<span style="color:#fbbf24">Family diff</span>')
            if r.coarse_bucket_match is True:
                badges.append('<span style="color:#4ade80">Scheme bucket match</span>')
            elif r.coarse_bucket_match is False:
                badges.append('<span style="color:#fbbf24">Scheme bucket diff</span>')
            ab = html.escape(r.actual_summary_bucket) if r.actual_summary_bucket else ""
            if ab:
                badges.insert(0, f'<span style="color:#94a3b8">Actual: {ab}</span>')
            badge_row = (
                f'<div style="font-size:10px;margin-top:4px">{" · ".join(badges)}</div>' if badges else ""
            )
            st.markdown(
                f'<div style="font-size:13px;line-height:1.35;color:#e2e8f0">{primary}</div>'
                f"{detail_html}{badge_row}",
                unsafe_allow_html=True,
            )
            _render_comparison_breakdown(r, widget_key_prefix=widget_key_prefix)
        with c2:
            if r.replay_error:
                st.markdown(
                    f'<span style="font-size:12px;color:#94a3b8">{html.escape(r.replay_error)}</span>',
                    unsafe_allow_html=True,
                )
            else:
                m = r.model_replay_structured
                bucket = html.escape(m.summary_bucket) if m and m.summary_bucket else ""
                lead = bucket or (html.escape(m.run_pass) if m and m.run_pass else "")
                sub_parts: list[str] = []
                if m:
                    if m.play_family:
                        sub_parts.append(html.escape(m.play_family.replace("_", " ")))
                    if m.play_call_name:
                        sub_parts.append(html.escape(f"“{m.play_call_name}”"))
                    if m.run_pass and bucket:
                        sub_parts.append(html.escape(m.run_pass))
                    if m.confidence is not None:
                        sub_parts.append(html.escape(f"{m.confidence:.0%} conf"))
                sub = " · ".join(sub_parts)
                extra = html.escape(r.model_replay_summary) if r.model_replay_summary and not lead else ""
                st.markdown(
                    f'<div style="font-size:13px;font-weight:600;color:#38bdf8">{lead or extra}</div>'
                    f'<div style="font-size:11px;color:#cbd5e1;margin-top:2px">{sub if lead else (sub or extra)}</div>',
                    unsafe_allow_html=True,
                )
