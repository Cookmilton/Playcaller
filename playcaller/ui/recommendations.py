"""Recommendation columns: field / charts / play card / quick log."""

from __future__ import annotations

from dataclasses import asdict
import html
import json
from typing import Optional

import streamlit as st

from playcaller import (
    Game,
    GameContext,
    DriveLogger,
    advance_game_state_after_actual,
    assemble_actual_semantics,
    build_play_art_figure,
    earned_first_down_for_actual_play,
    finalize_actual_after_snap,
    format_actual_play_result_description,
    invoke_post_play_hook,
)
from playcaller.evaluation.snap_review_lifecycle import close_snap_review_row_with_logged_actual
from playcaller.evaluation.snap_review_logging import merge_streamlit_snap_review_debug
from playcaller.game_situation_input import format_ball_spot, format_clock_left_in_quarter
from playcaller.streamlit_state.keys import (
    LAST_DRIVE_SNAP_CONTEXT,
    PENDING_LOG_SITUATION,
    UNDO_BUNDLE,
    WAREHOUSE_HISTORICAL_SIGNAL,
)
from playcaller.streamlit_state.ui_write_guard import assign_session_state
from playcaller.ui.historical_signal import render_historical_signal_panel
from playcaller.ui.helpers import (
    LOG_OUTCOME_AUTO,
    LOG_OUTCOME_OPTIONS,
    LOG_TARGET_AUTO,
    LOG_TARGET_OPTIONS,
    _LOG_COMPLETE,
    _LOG_FG_GOOD,
    _LOG_FG_MISS,
    _LOG_RUN,
    net_yards_to_endzone,
    post_log_summary_and_toast,
    safe_summary_html,
)
from playcaller.ui_components import FAM_COLOR, FAM_LABEL, render_field, score_chart


def _render_historical_context_note(result: dict) -> None:
    """One-line summary + expander; hidden when no corpus was supplied for this call."""
    hm = result.get("historical_metadata")
    if not isinstance(hm, dict) or not hm.get("corpus_supplied"):
        return

    def _detail_block(*, tech_checkbox_key: str) -> None:
        if hm.get("context_blurb"):
            st.markdown(str(hm["context_blurb"]))
        if hm.get("summary"):
            st.caption(str(hm["summary"]))
        rl = hm.get("run_lane")
        pl = hm.get("pass_lane")
        if isinstance(rl, dict) and rl.get("n"):
            _rs = rl.get("success_rate")
            _sr_s = f"{int(round(100 * float(_rs)))}%" if _rs is not None else "n/a"
            _adj = float(rl.get("adjustment") or 0.0)
            st.markdown(
                f"- **Run families (actual results):** n={rl['n']}, success ~{_sr_s}, "
                f"turnovers {100 * float(rl.get('turnover_rate') or 0):.0f}%, score nudge **{_adj:+.3f}**"
            )
        if isinstance(pl, dict) and pl.get("n"):
            _ps = pl.get("success_rate")
            _sp_s = f"{int(round(100 * float(_ps)))}%" if _ps is not None else "n/a"
            _adjp = float(pl.get("adjustment") or 0.0)
            st.markdown(
                f"- **Pass families (actual results):** n={pl['n']}, success ~{_sp_s}, "
                f"turnovers {100 * float(pl.get('turnover_rate') or 0):.0f}%, score nudge **{_adjp:+.3f}**"
            )
        if hm.get("status") == "not_applied":
            st.caption("Family scores were **not** changed; the sample was too thin or not lane-balanced enough.")
        tech = hm.get("technical")
        if isinstance(tech, dict) and tech:
            # Do not nest ``st.expander`` inside the outer historical-context expander (Streamlit limitation).
            try:
                payload = json.dumps(tech, indent=2, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                payload = None
            if not payload:
                st.caption("Technical detail unavailable.")
                return
            popover = getattr(st, "popover", None)
            if callable(popover):
                with popover("Technical detail"):
                    st.caption("Corpus nudge diagnostics (debug).")
                    st.code(payload, language="json")
            else:
                if st.checkbox("Technical detail (JSON)", key=tech_checkbox_key, value=False):
                    st.caption("Corpus nudge diagnostics (debug).")
                    st.code(payload, language="json")

    if hm.get("status") == "not_applied":
        with st.expander("Historical context — scores unchanged", expanded=False):
            st.markdown(str(hm.get("headline") or ""))
            _detail_block(tech_checkbox_key="hist_ctx_technical_detail_not_applied")
        return

    st.markdown("**Similar situations**")
    st.markdown(str(hm.get("headline") or ""))
    with st.expander("Why this note?", expanded=False):
        _detail_block(tech_checkbox_key="hist_ctx_technical_detail_why_note")


def _render_warehouse_advisory_note(result: dict) -> None:
    """Warehouse DB context (read-only); omitted when Generate did not request advisory."""
    wa = result.get("warehouse_advisory")
    if not isinstance(wa, dict):
        return
    if not wa.get("enabled"):
        with st.expander("Warehouse history (advisory — off or unavailable)", expanded=False):
            st.caption(str(wa.get("disclaimer") or ""))
            for n in wa.get("notes") or []:
                st.markdown(f"- {n}")
            for e in wa.get("errors") or []:
                st.markdown(f"- **Error:** {e}")
        return

    st.markdown("**Warehouse history (advisory)**")
    st.caption(str(wa.get("disclaimer") or ""))
    st.caption(str(wa.get("situation_summary") or ""))
    sc = wa.get("scope_binding") or {}
    if any(sc.get(k) for k in ("league_id", "season_id", "game_id")):
        st.caption(
            f"Scope: league `{sc.get('league_id') or '—'}` · season `{sc.get('season_id') or '—'}` · "
            f"game `{sc.get('game_id') or '—'}`"
        )

    def _outcome_metrics(label: str, blob: object) -> None:
        if not isinstance(blob, dict):
            return
        n = int(blob.get("total_plays") or 0)
        if n <= 0:
            st.caption(f"{label}: no plays in this slice.")
            return
        td = blob.get("touchdowns")
        to = blob.get("turnovers")
        st.caption(
            f"{label}: **n={n}** plays · TD **{td}** · turnovers **{to}** "
            "(from normalized `result_category`; small samples are noisy)."
        )

    _outcome_metrics("League/season (or broad scope) outcomes", wa.get("outcome_league_season"))
    _outcome_metrics("Same imported game (when `warehouse_game_id` / Event ID)", wa.get("outcome_game"))

    tend = wa.get("offense_team_tendency")
    if isinstance(tend, dict) and int(tend.get("total_plays") or 0) > 0:
        fams = tend.get("play_family_counts") or {}
        top = sorted(fams.items(), key=lambda kv: (-int(kv[1]), kv[0]))[:5]
        top_s = ", ".join(f"{k} {v}" for k, v in top) if top else "—"
        st.caption(
            f"**Offense on field** tendency (warehouse id `{tend.get('team_id')}`): "
            f"n={tend.get('total_plays')} · top families: {top_s}"
        )

    sp = wa.get("similar_plays")
    if isinstance(sp, dict) and sp.get("plays"):
        n = len(sp["plays"])
        more = " (more available)" if sp.get("has_more") else ""
        with st.expander(f"Sample similar plays (warehouse, first {n}){more}", expanded=False):
            st.caption("Canonical plays from the warehouse — inspect `play_family` / `outcome` for each row.")
            st.json(sp)

    notes = wa.get("notes") or []
    if notes:
        with st.expander("Warehouse advisory notes", expanded=False):
            for n in notes:
                st.markdown(f"- {n}")
    errs = wa.get("errors") or []
    if errs:
        with st.expander("Warehouse query errors (debug)", expanded=False):
            for e in errs:
                st.code(str(e))


def render_recommendation_panel(
    *,
    ctx: GameContext,
    game: Game,
    drive_log: DriveLogger,
    result: object,
) -> None:

    left, right = st.columns([1,1], gap="large")

    with left:
        st.markdown("**Field position**")
        display_ctx = result["ctx"] if result else ctx
        st.markdown(render_field(display_ctx), unsafe_allow_html=True)
        if result:
            bkt = result["bucket"].replace("_"," ").title()
            cov = result["ctx"].coverage_shell.replace("_"," ").upper() if result["ctx"].coverage_shell!="unknown" else "Coverage unknown"
            blz = " · Blitz expected" if result["ctx"].blitz_likely else ""
            st.caption(f"Bucket: {bkt}  ·  {cov}{blz}")
            if result["bucket"] == "red_zone" and result["ctx"].territory == "opponents" and result["ctx"].yardline <= 20:
                rz = result["ctx"]
                if rz.distance <= 3:
                    rz_note = "Short edges → quicker throws / condensed run answers."
                elif rz.distance >= 8:
                    rz_note = "Long RZ → screens + outlets to stay ahead of sticks."
                elif rz.yardline <= 5:
                    rz_note = "Goal-line-ish → heavier condensed run profile."
                else:
                    rz_note = "RZ spacing → slight lean to PA + quick game."
                st.caption(f"Red-zone shift: {rz_note}")

        # 4th down
        if result and result.get("fourth_down"):
            fd = result["fourth_down"]
            fd_clrs = {"GO FOR IT":"#22c55e","FIELD GOAL":"#3b82f6","PUNT":"#9ca3af"}
            fc = fd_clrs.get(fd.get("recommendation","PUNT"),"#9ca3af")
            fgd = f"  <span style='font-size:12px;color:#9ca3af'>(~{fd['fg_distance']} yds)</span>" if fd.get("fg_distance") else ""
            st.markdown(
                f'<div style="margin-top:12px;padding:10px 14px;border-radius:6px;background:{fc}10;border:1px solid {fc}33">'
                f'<div style="color:{fc};font-size:16px;font-weight:600">4th down: {fd.get("recommendation","")}{fgd}</div>'
                f'<div style="color:#9ca3af;font-size:13px;margin-top:3px">{fd.get("reasoning","")}</div></div>',
                unsafe_allow_html=True)

        # Score chart
        if result and result.get("scores"):
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**Family scores**")
            st.plotly_chart(score_chart(result["scores"]), use_container_width=True, config={"displayModeBar":False})

        if st.session_state.get("ui_debug_game_context") and result and result.get("model_input"):
            mi = result["model_input"]
            gcf = mi.meta.get("game_context_features") if hasattr(mi, "meta") else None
            if gcf:
                with st.expander("Game-context features (debug)", expanded=False):
                    top = gcf.get("target_role_top") or []
                    top_s = ", ".join(f"{r}: {p:.0%}" for r, p in top[:3]) if top else "—"
                    st.caption(
                        f"Last archived drive: **{gcf.get('last_archived_drive_result_kind') or '—'}** · "
                        f"Plays in sample: **{gcf.get('sample_size_plays', 0)}** · "
                        f"Top roles: {top_s}"
                    )
                    st.json(gcf)

    with right:
        if not result:
            if st.session_state.get("last_play_summary"):
                st.markdown(
                    '<div style="border-left:3px solid #22c55e;background:rgba(34,197,94,0.08);'
                    'padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:10px">'
                    '<div style="color:#86efac;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;margin-bottom:4px">'
                    "Last logged play</div>"
                    '<div style="color:#e2e8f0;font-size:14px;line-height:1.45">'
                    + safe_summary_html(str(st.session_state.last_play_summary))
                    + "</div></div>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    "**Situation** and **Position** in the row above match the next snap. "
                    "Tap **Generate play call** when you want the next recommendation."
                )
            else:
                st.info("Use the sidebar **presets / quick adjust** chips, then tap **Generate play call**.")
        else:
            play   = result["play"]
            family = result["play_family"]
            fctx   = result["ctx"]
            fc     = FAM_COLOR.get(family,"#6b7280")

            # Header
            td_badge = f"  ·  TD {round(play['td_pct']*100)}%" if "td_pct" in play else ""
            conf = result.get("model", {}).get("confidence")
            if conf is None and result.get("model_output") is not None:
                conf = getattr(result["model_output"], "confidence", None)
            conf_badge = ""
            if isinstance(conf, (int, float)):
                pct = int(round(float(conf) * 100))
                conf_badge = f"  ·  Conf {pct}%"
            st.markdown(
                f'<div style="background:{fc}12;border:1px solid {fc}33;border-radius:6px;padding:12px 16px;margin-bottom:12px">'
                f'<div style="font-size:22px;font-weight:700;color:#f0f4f8">{play.get("name","")}</div>'
                f'<div style="font-size:11px;color:{fc};text-transform:uppercase;letter-spacing:0.1em;margin-top:2px">'
                f'{FAM_LABEL.get(family,family)}{td_badge}{conf_badge}</div></div>',
                unsafe_allow_html=True)

            render_historical_signal_panel(st.session_state.get(WAREHOUSE_HISTORICAL_SIGNAL))

            # Situation strip (read at a glance)
            ball = format_ball_spot(territory=fctx.territory, yardline=int(fctx.yardline))
            period_ui = int(st.session_state.get("ui_game_period", fctx.quarter))
            clk = format_clock_left_in_quarter(period=period_ui, seconds_in_quarter=int(fctx.seconds_remaining))
            cov_lbl = fctx.coverage_shell.replace("_", " ").upper() if fctx.coverage_shell != "unknown" else "Cov ?"
            st.caption(
                f"{fctx.down}&{fctx.distance} · {ball} · {clk} · "
                f"{cov_lbl} · {fctx.box_count} box"
                + (" · BLITZ" if fctx.blitz_likely else "")
            )

            _render_historical_context_note(result)
            _render_warehouse_advisory_note(result)

            # Pre-snap projection + diagram (collapsed by default for live entry — not logged).
            pred = result.get("predicted_play_result") or {}
            with st.expander("Model projection & play diagram (optional)", expanded=False):
                if pred.get("headline") or pred.get("description"):
                    st.markdown("**Projected outcome (pre-snap)**")
                    st.caption("Model guess only — **Log result (quick)** below records actual yards.")
                    lead = pred.get("headline") or pred.get("description", "")
                    st.markdown(
                        f'<div style="border:1px solid #334155;border-radius:8px;padding:12px 14px;'
                        f'background:linear-gradient(180deg,#1e293b 0%,#0f172a 100%);margin-bottom:10px">'
                        f'<div style="font-size:1.08rem;color:#f8fafc;line-height:1.45;font-weight:600">{lead}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                    pm1, pm2, pm3, pm4, pm5 = st.columns(5)
                    _py = pred.get("yards")
                    pm1.metric("Proj. type", str(pred.get("play_type", "—")).replace("_", " ").title())
                    pm2.metric("Proj. target", pred.get("target_player_or_role") or "—")
                    _route_show = (pred.get("route") or "—")[:22]
                    pm3.metric("Proj. route", _route_show + ("…" if pred.get("route") and len(pred["route"]) > 22 else ""))
                    pm4.metric("Proj. yards", "—" if _py is None else str(int(_py)))
                    _flags: list[str] = []
                    if pred.get("success"):
                        _flags.append("Sticks")
                    if pred.get("explosive"):
                        _flags.append("Explosive")
                    pm5.metric("Proj. flags", " · ".join(_flags) if _flags else "—")
                else:
                    st.caption("No projection headline for this call.")

                try:
                    pri = pred.get("target_position") if pred else None
                    _hint = pred.get("result_type") if pred else None
                    fig = build_play_art_figure(
                        play,
                        family,
                        str(pri) if pri else None,
                        result_type_hint=str(_hint) if _hint else None,
                    )
                    if fig is not None:
                        st.markdown("**Play art**")
                        st.caption(
                            "Compact LOS · gold = primary · gray = secondary · dashed = PA sell (when applicable)."
                        )
                        st.pyplot(fig, clear_figure=True)
                except Exception:
                    pass

            with st.expander("Install / mechanics (formation, protection, routes)", expanded=False):
                fi = st.columns(3)
                if play.get("formation"):
                    fi[0].caption("Formation")
                    fi[0].markdown(f"`{play['formation']}`")
                if play.get("protection") or play.get("blocking"):
                    fi[1].caption("Protection / Blocking")
                    fi[1].markdown(f"`{play.get('protection') or play.get('blocking')}`")
                if play.get("run_scheme"):
                    fi[2].caption("Scheme")
                    fi[2].markdown(f"`{play['run_scheme']}`")

                if play.get("routes"):
                    st.markdown("**Routes**")
                    ritems = list(play["routes"].items())
                    rc1, rc2 = st.columns(2)
                    for i, (pos, route) in enumerate(ritems):
                        (rc1 if i < (len(ritems) + 1) // 2 else rc2).markdown(f"**`{pos}`** {route}")

            # Why
            st.markdown(
                f'<div style="border-left:2px solid {fc};background:rgba(255,255,255,0.025);padding:6px 10px;'
                f'border-radius:0 4px 4px 0;margin:10px 0;font-size:13px;color:#d1d5db">'
                f'<strong style="color:#9ca3af;font-size:10px;text-transform:uppercase">Why:</strong> {play.get("why","")}</div>',
                unsafe_allow_html=True)

            # Coaching notes helper
            def note(icon, label, text, color="#9ca3af"):
                st.markdown(
                    f'<div style="display:flex;gap:6px;padding:5px 8px;border-radius:4px;background:rgba(255,255,255,0.02);margin-bottom:4px;font-size:12px">'
                    f'<span style="color:{color};min-width:70px;font-size:10px;text-transform:uppercase;letter-spacing:0.06em;padding-top:1px">{icon} {label}</span>'
                    f'<span style="color:#d1d5db">{text}</span></div>',
                    unsafe_allow_html=True)

            is_man   = fctx.coverage_shell in ("cover_0","cover_1")
            cov_note = (play.get("vs_man") if is_man else play.get("vs_zone")) if fctx.coverage_shell!="unknown" else None
            shell_l  = fctx.coverage_shell.replace("_"," ").upper() if fctx.coverage_shell!="unknown" else ""

            if cov_note:                                             note(">",f"vs. {shell_l}",cov_note,"#3b82f6")
            else:
                if play.get("vs_man"):                               note(">","vs. Man",play["vs_man"],"#3b82f6")
                if play.get("vs_zone"):                              note(">","vs. Zone",play["vs_zone"],"#60a5fa")
            if play.get("kill_look"):                                note("X","Kill look",play["kill_look"],"#ef4444")
            if play.get("post_snap_alert"):                          note("*","Post-snap",play["post_snap_alert"],"#8b5cf6")
            if family=="play_action" and fctx.run_plays_this_drive<3:
                note("!","PA warn",f"Run not established ({fctx.run_plays_this_drive} runs) — fake may not freeze LBs.","#f59e0b")
            if fctx.weather in ("wind","rain","snow") and family in ("dropback_pass","play_action"):
                wx = (f"Wind {fctx.wind_mph}mph — shorten the route tree." if fctx.weather=="wind"
                      else "Wet conditions — prioritize short throws." if fctx.weather=="rain"
                      else "Snow — consider running instead.")
                note("~","Weather",wx,"#60a5fa")
            if fctx.mismatch:                                        note("*","Mismatch",fctx.mismatch,"#f59e0b")
            if fctx.game_mode=="two_minute":                         note(">","Tempo",f"Hurry-up — {fctx.own_timeouts} TOs left. Spike or go OOB.","#f59e0b")
            if fctx.game_mode=="drain_clock":                        note(">","Tempo","Milk it — long cadence, stay in bounds.","#22c55e")
            if fctx.blitz_likely:                                    note(">","Snap count","Hard count — see if they jump before the snap.","#f59e0b")

            if result.get("overuse_warning"):
                st.warning(f"**Tendency:** {result['overuse_warning']}")

            # Log result (broadcast-style quick entry)
            st.divider()
            st.markdown("**Log result (quick)**")
            st.caption(
                "Each button logs **this call** with the shown yards/outcome and advances the chains. "
                "Use **Advanced** only when you need a non-default target or rare outcome label."
            )
            gen_distance = int(result["ctx"].distance)
            ytg = net_yards_to_endzone(str(fctx.territory), int(fctx.yardline))

            with st.expander("Advanced: outcome dropdown & primary target", expanded=False):
                st.selectbox("What happened?", LOG_OUTCOME_OPTIONS, index=0, key="main_log_semantic_outcome")
                st.selectbox("Primary / target", LOG_TARGET_OPTIONS, index=0, key="main_log_semantic_target")

            def _log_play(
                yards: int,
                *,
                sack_from_chip: bool = False,
                forced_interception: bool = False,
                forced_incomplete: bool = False,
                outcome_ui_override: Optional[str] = None,
            ) -> None:
                st.session_state[UNDO_BUNDLE] = {
                    "territory": str(fctx.territory),
                    "yardline": int(fctx.yardline),
                    "down": int(fctx.down),
                    "distance": int(fctx.distance),
                }
                if forced_interception:
                    outcome_ui = "Interception"
                elif forced_incomplete:
                    outcome_ui = "Incomplete pass"
                elif outcome_ui_override is not None:
                    outcome_ui = outcome_ui_override
                else:
                    outcome_ui = str(st.session_state.get("main_log_semantic_outcome", LOG_OUTCOME_AUTO))
                target_choice = str(st.session_state.get("main_log_semantic_target", LOG_TARGET_AUTO))
                sem = assemble_actual_semantics(
                    concept_name=play.get("name", ""),
                    family=family,
                    play=play,
                    yards_gained=int(yards),
                    target_choice=target_choice,
                    outcome_ui=outcome_ui,
                    sack_from_chip=sack_from_chip,
                    forced_interception=forced_interception,
                    forced_incomplete=forced_incomplete,
                )
                snap = advance_game_state_after_actual(
                    territory=str(fctx.territory),
                    yardline=int(fctx.yardline),
                    down=int(fctx.down),
                    distance=int(fctx.distance),
                    actual=sem,
                )
                earned_fd = earned_first_down_for_actual_play(sem, sem.yards_gained, gen_distance) or bool(
                    snap.touchdown
                )

                actual = finalize_actual_after_snap(
                    sem,
                    snap=snap,
                    to_go=gen_distance,
                    earned_first_down=earned_fd,
                )
                drive_log.log(actual)
                sg = st.session_state.game
                close_ok = close_snap_review_row_with_logged_actual(
                    sg.recommendation_audit,
                    plays_after_log=len(drive_log.results),
                    actual=actual,
                )
                last = sg.recommendation_audit[-1] if sg.recommendation_audit else None
                merge_streamlit_snap_review_debug(
                    st.session_state,
                    event="after_log_result",
                    row_count=len(sg.recommendation_audit),
                    close_ok=close_ok,
                    latest_snap_id=str(last.get("snap_id") or "") if last else "",
                    latest_status=str(last.get("status") or "") if last else "",
                    row_status=str(last.get("status") or "") if last else "",
                    latest_completed=last.get("completed") if last else None,
                    has_actual_result=bool(last and last.get("actual_result")) if last else False,
                    game_object_id=id(sg),
                )
                st.session_state[LAST_DRIVE_SNAP_CONTEXT] = {
                    "touchdown": bool(snap.touchdown),
                    "turnover_on_downs": bool(snap.turnover_on_downs),
                }
                st.session_state[PENDING_LOG_SITUATION] = {
                    "territory": str(snap.territory),
                    "yardline": int(snap.yardline),
                    "down": int(snap.down),
                    "distance": int(snap.distance),
                }
                st.session_state.result = None
                st.session_state.pop(WAREHOUSE_HISTORICAL_SIGNAL, None)
                assign_session_state(st.session_state, "ui_auto_generate", True, context="quick_log_play")
                invoke_post_play_hook(
                    snap,
                    {
                        "actual_play_result": asdict(actual),
                        "yards": int(actual.yards_gained),
                        "result_type": actual.result_type,
                        "family": family,
                        "concept": play.get("name", ""),
                        "description": actual.description,
                        "tags": snap.tags,
                    },
                )
                summary, toast_parts = post_log_summary_and_toast(actual, snap)
                st.session_state.last_play_summary = summary
                st.toast(" · ".join(toast_parts))
                st.rerun()

            st.markdown("**Auto / mixed (uses Advanced dropdown if not overridden)**")
            a1, a2, a3, a4, a5, a6, a7, a8 = st.columns(8)
            with a1:
                if st.button("0", use_container_width=True, key="main_log_yards_0"):
                    _log_play(0)
            with a2:
                if st.button("+2", use_container_width=True, key="main_log_yards_plus2"):
                    _log_play(2)
            with a3:
                if st.button("+3", use_container_width=True, key="main_log_yards_plus3"):
                    _log_play(3)
            with a4:
                if st.button("+5", use_container_width=True, key="main_log_yards_plus5"):
                    _log_play(5)
            with a5:
                if st.button("+8", use_container_width=True, key="main_log_yards_plus8"):
                    _log_play(8)
            with a6:
                if st.button("+10", use_container_width=True, key="main_log_yards_plus10"):
                    _log_play(10)
            with a7:
                if st.button("FD", use_container_width=True, help="First down at the sticks", key="main_log_yards_first_down"):
                    _log_play(gen_distance)
            with a8:
                if st.button(
                    "TD",
                    use_container_width=True,
                    help=f"Score — logs {ytg} yds (to goal)",
                    key="main_log_td_score",
                ):
                    _log_play(ytg)

            st.markdown("**Complete pass + yards (one tap each)**")
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                if st.button("C +3", use_container_width=True, key="main_log_c3"):
                    _log_play(3, outcome_ui_override=_LOG_COMPLETE)
            with c2:
                if st.button("C +5", use_container_width=True, key="main_log_c5"):
                    _log_play(5, outcome_ui_override=_LOG_COMPLETE)
            with c3:
                if st.button("C +8", use_container_width=True, key="main_log_c8"):
                    _log_play(8, outcome_ui_override=_LOG_COMPLETE)
            with c4:
                if st.button("C +10", use_container_width=True, key="main_log_c10"):
                    _log_play(10, outcome_ui_override=_LOG_COMPLETE)
            with c5:
                if st.button("C FD", use_container_width=True, key="main_log_c_fd"):
                    _log_play(gen_distance, outcome_ui_override=_LOG_COMPLETE)

            st.markdown("**Run + yards (one tap each)**")
            r1, r2, r3, r4 = st.columns(4)
            with r1:
                if st.button("R +3", use_container_width=True, key="main_log_r3"):
                    _log_play(3, outcome_ui_override=_LOG_RUN)
            with r2:
                if st.button("R +6", use_container_width=True, key="main_log_r6"):
                    _log_play(6, outcome_ui_override=_LOG_RUN)
            with r3:
                if st.button("R FD", use_container_width=True, key="main_log_r_fd"):
                    _log_play(gen_distance, outcome_ui_override=_LOG_RUN)
            with r4:
                if st.button("R −2", use_container_width=True, key="main_log_r_loss2"):
                    _log_play(-2, outcome_ui_override=_LOG_RUN)

            st.markdown("**Defense / special**")
            d1, d2, d3, d4, d5, d6 = st.columns(6)
            with d1:
                if st.button("INC", use_container_width=True, help="Incomplete (0)", key="main_log_inc"):
                    _log_play(0, forced_incomplete=True)
            with d2:
                if st.button("INT", use_container_width=True, help="Interception", key="main_log_int"):
                    _log_play(0, forced_interception=True)
            with d3:
                if st.button("SACK", use_container_width=True, key="main_log_yards_sack"):
                    _log_play(-8, sack_from_chip=True)
            with d4:
                if st.button("FG made", use_container_width=True, key="main_log_fg_good"):
                    _log_play(0, outcome_ui_override=_LOG_FG_GOOD)
            with d5:
                if st.button("FG miss", use_container_width=True, key="main_log_fg_miss"):
                    _log_play(0, outcome_ui_override=_LOG_FG_MISS)
            with d6:
                if st.button("TFL", use_container_width=True, help="Run loss −3", key="main_log_tfl"):
                    _log_play(-3, outcome_ui_override=_LOG_RUN)

            lc1, lc2 = st.columns([3, 1])
            yards_input = lc1.number_input("Custom yards", value=0, step=1, key="main_log_custom_yards_value")
            if lc2.button("Log custom", use_container_width=True, key="main_log_yards_custom_submit"):
                yv = int(yards_input)
                _log_play(yv, sack_from_chip=yv <= -4)

