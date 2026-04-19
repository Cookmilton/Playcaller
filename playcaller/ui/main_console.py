"""Main page: header, live console, generate, HUD, evaluation, drive lists, recommendation panel, charts."""

from __future__ import annotations

import html

import streamlit as st

from playcaller import FootballPlayPredictor, Game, GameContext, DriveLogger, format_actual_play_result_description
from playcaller.game_situation_input import (
    format_ball_spot,
    format_clock_left_in_quarter,
    format_live_situation_summary,
)
from playcaller.evaluation import evaluate_audit_records, summarize_audit_session
from playcaller.services.game_controller import run_generate_if_requested, undo_last_logged_play
from playcaller.session_game_metadata import (
    compact_session_summary_line,
    session_metadata_is_identified,
    session_metadata_warnings,
)
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_SYNC_EPOCH,
    SESSION_SETUP_GAME_DATE,
    SESSION_SETUP_GAME_LABEL,
    SESSION_SETUP_IS_SIMULATED,
    SESSION_SETUP_NOTES,
    SESSION_SETUP_OPPONENT,
    SESSION_SETUP_ROSTER_VERSION,
    SESSION_SETUP_SEASON,
    SESSION_SETUP_TEAM_NAME,
    UNDO_BUNDLE,
)
from playcaller.ui.helpers import (
    fmt_local_epoch,
    net_yards_to_endzone,
    render_current_series_live,
    render_previous_drives,
    safe_summary_html,
)
from playcaller.ui.product_copy import EXPANDER_SESSION_RECORD, HEADLINE_LIVE_CONSOLE, HEADLINE_MAIN
from playcaller.ui.recommendations import render_recommendation_panel
from playcaller.ui_components import FAM_COLOR, drive_chart, drive_momentum_chart, run_pass_donut

MODE_BANNERS = {
    "two_minute":  ("\U0001f6a8 Two-Minute Drill",     "#ef4444"),
    "must_score":  ("\U0001f6a8 Must Score",            "#ef4444"),
    "drain_clock": ("\U000023f1 Drain the Clock",       "#22c55e"),
    "two_point":   ("\U0001f3af Two-Point Conversion",  "#f59e0b"),
}


def render_main_content(
    *,
    ctx: GameContext,
    game: Game,
    drive_log: DriveLogger,
    predictor: FootballPlayPredictor,
    sidebar_generate: bool,
) -> None:
    territory = str(ctx.territory)
    yardline = int(ctx.yardline)
    down = int(ctx.down)
    distance = int(ctx.distance)
    def_personnel = str(ctx.def_personnel)
    box_count = int(ctx.box_count)
    coverage_shell = str(ctx.coverage_shell)
    safeties = str(ctx.safeties)
    blitz_likely = bool(ctx.blitz_likely)
    quarter = int(ctx.quarter)
    seconds_remaining = int(ctx.seconds_remaining)
    own_timeouts = int(ctx.own_timeouts)
    opp_timeouts = int(ctx.opp_timeouts)

    st.markdown(f"## {HEADLINE_MAIN}")
    st.caption("**Live console** — quick log below; full controls stay in the sidebar.")

    sum_line = compact_session_summary_line(game.session_metadata)
    st.markdown(
        f'<p style="font-size:0.98rem;font-weight:600;color:#cbd5e1;margin:0 0 0.35rem 0">'
        f"{html.escape(sum_line)}</p>",
        unsafe_allow_html=True,
    )
    if not session_metadata_is_identified(game.session_metadata):
        for w in session_metadata_warnings(game.session_metadata):
            st.warning(w)

    with st.expander(EXPANDER_SESSION_RECORD, expanded=False):
        st.caption(
            "Set **once per game**. Stored on **game JSON** and copied into each **snap review** row."
        )
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Our team name", key=SESSION_SETUP_TEAM_NAME, placeholder="e.g. East High")
            st.text_input("Opponent", key=SESSION_SETUP_OPPONENT, placeholder="Optional")
            st.text_input("Game date", key=SESSION_SETUP_GAME_DATE, placeholder="YYYY-MM-DD")
            st.text_input("Game label / title", key=SESSION_SETUP_GAME_LABEL, placeholder="Optional short title")
        with c2:
            st.text_input("Season", key=SESSION_SETUP_SEASON, placeholder="e.g. 2026")
            st.text_input("Roster / roster version", key=SESSION_SETUP_ROSTER_VERSION, placeholder="Optional")
            st.text_area("Notes", key=SESSION_SETUP_NOTES, height=68, placeholder="Optional situational notes")
        st.checkbox(
            "This session is simulated (not an actual game)",
            key=SESSION_SETUP_IS_SIMULATED,
            help="Unchecked = **real / actual** sideline data. Checked = practice, what-if, or lab session.",
        )
        sid = ""
        if isinstance(game.session_metadata, dict):
            sid = str(game.session_metadata.get("session_game_id") or "")
        if sid:
            st.caption(f"Stable **session game id** (for linkage): `{sid}`")

    period_ui = int(st.session_state.get("ui_game_period", quarter))
    ours = int(game.offense_points)
    theirs = int(game.defense_points)
    sit_line = format_live_situation_summary(
        period=period_ui,
        seconds_in_quarter=seconds_remaining,
        our_score=ours,
        their_score=theirs,
        territory=territory,
        yardline=yardline,
        down=down,
        distance=distance,
    )
    st.markdown(
        f'<p style="font-size:1.05rem;font-weight:600;color:#e2e8f0;margin:0 0 0.75rem 0">{html.escape(sit_line)}</p>',
        unsafe_allow_html=True,
    )

    st.markdown(f"##### {HEADLINE_LIVE_CONSOLE}")
    op1, op2, op3 = st.columns([2, 1, 1])
    with op1:
        main_generate = st.button(
            "Generate play call",
            type="primary",
            use_container_width=True,
            help="Same as the sidebar — use whichever is closer on broadcast.",
            key="main_console_generate",
        )
    with op2:
        can_undo = bool(drive_log.results) and st.session_state.get(UNDO_BUNDLE) is not None
        undo_clicked = st.button(
            "Undo last play",
            use_container_width=True,
            disabled=not can_undo,
            help="Restores down/distance/field to the snap before the last quick-log (one step).",
            key="main_console_undo",
        )
    with op3:
        st.caption(f"**Drive:** {len(drive_log.results)} logged")

    if undo_clicked:
        undo_last_logged_play()
        st.rerun()

    run_generate_if_requested(
        ctx=ctx,
        game=game,
        drive_log=drive_log,
        predictor=predictor,
        sidebar_generate=sidebar_generate,
        main_generate=bool(main_generate),
    )

    result = st.session_state.result

    eff_mode = result["ctx"].game_mode if result else predictor.derive_game_mode(ctx)
    if eff_mode in MODE_BANNERS:
        bt, bc = MODE_BANNERS[eff_mode]
        st.markdown(f'<div style="background:{bc}18;border:1px solid {bc}44;border-radius:6px;padding:8px 14px;margin-bottom:12px;color:{bc};font-weight:600;font-size:16px">{bt}</div>', unsafe_allow_html=True)

    if quarter >= 4 and seconds_remaining <= 120 and seconds_remaining > 0:
        st.markdown(
            '<div style="background:#f59e0b18;border:1px solid #f59e0b55;border-radius:6px;padding:8px 12px;'
            'margin-bottom:10px;color:#fbbf24;font-weight:600;font-size:14px">'
            "Late game: clock inside two minutes. Confirm time matches the broadcast.</div>",
            unsafe_allow_html=True,
        )

    sc_lbl = f"{game.offense_points}–{game.defense_points}"
    margin = int(game.offense_points) - int(game.defense_points)
    margin_lbl = f"+{margin}" if margin > 0 else str(margin)
    pos_lbl = "Our ball" if game.possession == "offense" else "Opponent ball"
    terr_short = "Opp." if territory == "opponents" else "Own"
    ytg_hud = net_yards_to_endzone(territory, yardline)
    def_lbl = def_personnel.replace("_", " ").title() if def_personnel != "unknown" else "Def ?"
    cov_hud = coverage_shell.replace("_", " ").upper() if coverage_shell != "unknown" else "Cov ?"
    saf_hud = safeties.replace("_", " ").title() if safeties != "unknown" else "S ?"
    blitz_chip = " · BLITZ" if blitz_likely else ""
    def_strip = html.escape(f"{def_lbl} · {box_count} box · {cov_hud} · {saf_hud}{blitz_chip}", quote=True)
    ball_spot = format_ball_spot(territory=territory, yardline=yardline)
    clock_phrase = format_clock_left_in_quarter(period=period_ui, seconds_in_quarter=seconds_remaining)
    st.markdown(
        f'<div style="background:linear-gradient(180deg,#0c1222 0%,#0f172a 100%);border:1px solid #334155;'
        f'border-radius:10px;padding:14px 18px;margin-bottom:6px">'
        f'<div style="font-size:1.5rem;font-weight:800;color:#f8fafc;letter-spacing:-0.02em">'
        f'{down}&{distance} <span style="color:#64748b;font-weight:500">·</span> {html.escape(ball_spot)}</div>'
        f'<div style="margin-top:6px;font-size:0.92rem;color:#cbd5e1">'
        f'<strong style="color:#94a3b8">To goal</strong> {ytg_hud} yds'
        f' &nbsp;·&nbsp; <strong style="color:#94a3b8">Defense</strong> {def_strip}</div>'
        f'<div style="margin-top:8px;font-size:0.95rem;color:#94a3b8;line-height:1.5">'
        f'<strong style="color:#e2e8f0">Score</strong> {sc_lbl} '
        f'<span style="color:#475569">(margin {margin_lbl})</span>'
        f' &nbsp;·&nbsp; <strong style="color:#e2e8f0">Clock</strong> {html.escape(clock_phrase)}'
        f' &nbsp;·&nbsp; <strong style="color:#e2e8f0">{html.escape(pos_lbl)}</strong>'
        f' &nbsp;·&nbsp; <strong style="color:#e2e8f0">TOs</strong> {own_timeouts}–{opp_timeouts}'
        f' &nbsp;·&nbsp; <strong style="color:#e2e8f0">This drive</strong> {len(drive_log.results)} play(s)'
        f'</div>'
        f'<div style="margin-top:6px;font-size:0.78rem;color:#64748b">Scoreboard session '
        f'{html.escape(str(game.game_id))}'
        + (
            f' · game record {html.escape(str((game.session_metadata or {}).get("session_game_id") or "")[:8])}…'
            if isinstance(game.session_metadata, dict) and (game.session_metadata.get("session_game_id"))
            else ""
        )
        + "</div></div>",
        unsafe_allow_html=True,
    )
    if st.session_state.get("last_play_summary"):
        st.markdown(
            '<p style="font-size:0.88rem;color:#94a3b8;margin:0.35rem 0 0 0;line-height:1.35">'
            + safe_summary_html(str(st.session_state.last_play_summary))
            + "</p>",
            unsafe_allow_html=True,
        )
    lf_ts = st.session_state.get(LIVE_FEED_LAST_SYNC_EPOCH)
    lf_org = str(st.session_state.get(LIVE_FEED_LAST_ORIGIN) or "")
    if lf_ts and lf_org == "feed":
        st.caption(
            f"**Live data:** ESPN sync at {fmt_local_epoch(float(lf_ts))} — situation locks in the sidebar are respected."
        )
    elif lf_org == "manual":
        st.caption("**Live data:** Operating as **manual** (or after **Mark manual**). Use **Sync from ESPN** to pull the broadcast again.")
    st.caption(
        "**Live ops:** End the possession from the sidebar **End drive & next series** (or one-tap **End ·** buttons) — "
        "scoreboard & prior drives stay intact."
    )
    st.divider()

    with st.expander("Session evaluation (quick)", expanded=False):
        st.caption(
            "Use **Generate** to record calls for export, then open **Post-game review** for snap-by-snap analysis."
        )
        _aud = game.recommendation_audit
        if not _aud:
            st.info("No audit rows yet. Generate calls and log results to measure family match, diversity, and weak spots.")
        else:
            st.text(summarize_audit_session(_aud, session_metadata=game.session_metadata))
            with st.expander("Full metrics (JSON)", expanded=False):
                st.json(evaluate_audit_records(_aud))

    render_current_series_live(drive_log)
    render_previous_drives(game, predictor=predictor, ambient_ctx=ctx)

    render_recommendation_panel(ctx=ctx, game=game, drive_log=drive_log, result=result)

    with st.expander("Drive charts (this series)", expanded=False):
        if not drive_log.results:
            st.caption("No plays logged yet.")
        else:
            dm, rp, dc = drive_momentum_chart(drive_log), run_pass_donut(drive_log), drive_chart(drive_log)
            c1, c2 = st.columns(2, gap="small")
            with c1:
                if dm:
                    st.plotly_chart(dm, use_container_width=True, config={"displayModeBar": False})
            with c2:
                if rp:
                    st.plotly_chart(rp, use_container_width=True, config={"displayModeBar": False})
            if dc:
                st.plotly_chart(dc, use_container_width=True, config={"displayModeBar": False})
            chip_spans: list[str] = []
            for r in drive_log.results:
                d = r.description or format_actual_play_result_description(r)
                chip_spans.append(
                    f'<span style="padding:2px 8px;border-radius:3px;background:{FAM_COLOR.get(r.family,"#6b7280")}22;'
                    f'border:1px solid {FAM_COLOR.get(r.family,"#6b7280")}55;color:{FAM_COLOR.get(r.family,"#9ca3af")};font-size:11px">'
                    f'{html.escape(d[:48])}{"…" if len(d) > 48 else ""}</span>'
                )
            chips = " ".join(chip_spans)
            st.markdown(f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:8px">{chips}</div>', unsafe_allow_html=True)
            runs_c, passes_c = drive_log.run_pass_split()
            st.caption(f"{len(drive_log.results)} plays · {runs_c} run / {passes_c} pass")
