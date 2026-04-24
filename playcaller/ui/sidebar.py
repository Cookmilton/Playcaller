"""Play Caller sidebar — workflow-first: session, live ESPN, play calls, export status, advanced."""

from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime

import streamlit as st

from football_history_warehouse.ingest.from_json import ingest_espn_summary_after_live_fetch

from playcaller import (
    DRIVE_END_UI_LABELS,
    DRIVE_END_UI_OPTIONS,
    DriveLogger,
    Game,
    game_from_dict,
    game_to_json,
)
from playcaller.evaluation.snap_review_lifecycle import ensure_snap_review_list_on_game
from playcaller.session_game_metadata import game_json_export_hint_caption, session_metadata_warnings
from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    DRIVE_END_UI_AUTO,
)
from playcaller.live_data import (
    EspnFootballProvider,
    SyncOptions,
    apply_snapshot,
    list_espn_scoreboard_games,
    session_mark_manual,
)
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
)
from playcaller.live_data.espn_football import fetch_event_teams
from playcaller.game_situation_input import clamp_quarter_clock_seconds, period_display_label
from playcaller.services.game_controller import (
    apply_and_rerun,
    archive_current_drive_and_reset_session,
    on_ui_weather_changed,
    preset_snap_only,
    preset_two_minute_drill,
    undo_last_logged_play,
)
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_PERIOD,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    SESSION_SETUP_GAME_DATE,
    SESSION_SETUP_GAME_LABEL,
    SESSION_SETUP_IS_SIMULATED,
    SESSION_SETUP_NOTES,
    SESSION_SETUP_OPPONENT,
    SESSION_SETUP_ROSTER_VERSION,
    SESSION_SETUP_SEASON,
    SESSION_SETUP_TEAM_NAME,
    UNDO_BUNDLE,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_HTTP_INSECURE_WARNING,
    LIVE_FEED_LAST_ERROR,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_FEED_MANUAL_AUTO_FETCH,
    LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR,
    LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    LIVE_FEED_MANUAL_EVENT_FOR_ID,
    LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID,
    LIVE_FEED_MANUAL_EVENT_TEAMS,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_FEED_TEAM_SCOPE,
    PENDING_END_DRIVE_UI,
    UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES,
    UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS,
    PENDING_LOG_SITUATION,
    PENDING_NEW_GAME_UI,
    UI_HISTORICAL_NUDGE_ENABLED,
    WAREHOUSE_HISTORICAL_SIGNAL,
)
from playcaller.streamlit_state.ui_write_guard import assign_session_state, register_ui_widget_key_bound
from playcaller.streamlit_state.widget_backend_bridge import request_widget_hydrate_from_backend
from playcaller.streamlit_state.pending import clear_in_progress_log_state
from playcaller.streamlit_state.session import (
    clear_coached_team_espn_session_identity,
    clear_live_feed_session_keys,
    possession_side_radio_label,
)
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from playcaller.streamlit_state.session_setup import hydrate_session_setup_widgets
from playcaller.ui.espn_live_flow import (
    EspnLiveSyncReadiness,
    ManualEventLookupPhase,
    clear_manual_event_cache_if_event_id_mismatch,
    clear_manual_fetch_error_if_event_id_changed,
    derive_espn_sync_readiness,
    format_espn_match_pills_html,
    manual_lookup_status,
    maybe_auto_fetch_event_id,
    our_team_label_from_manual_teams,
)
from playcaller.ui.product_copy import (
    SIDEBAR_CAPTION_EXPORT_REVIEW,
    SIDEBAR_SECTION_ADVANCED,
    SIDEBAR_SECTION_DRIVE_SESSION,
    SIDEBAR_SECTION_EXPORT,
    SIDEBAR_SECTION_GAME_SETUP,
    SIDEBAR_SECTION_LIVE_SYNC,
    SIDEBAR_SECTION_PLAY_CALLS,
    SIDEBAR_SECTION_PLAY_CALLS_EXPANDER,
    SIDEBAR_SECTION_PRESETS,
    SIDEBAR_SECTION_QUICK_ADJUST,
    SIDEBAR_SECTION_REVIEW_EXPORT,
    SIDEBAR_SECTION_REVIEW_EXPORT_EXPANDER,
)
from playcaller.ui.sidebar_presets import (
    builtin_opp35_active,
    builtin_own25_active,
    builtin_rz_active,
    builtin_twomin_active,
    render_custom_presets_subsection,
)
from playcaller.ui.warehouse_sidebar import render_sidebar_warehouse_section, render_warehouse_advanced_panel

logger = logging.getLogger(__name__)


def _bind_ui(k: str) -> None:
    """Register a Streamlit widget key for the per-run ``ui_*`` write guard (see ``ui_write_guard``)."""
    register_ui_widget_key_bound(k)


def _sidebar_export_review_status(game: Game) -> None:
    """Single-line export/review summary; full copy in expander."""
    from playcaller.review.snap_review import review_timeline_rows
    from playcaller.review.unified_review import count_logged_plays

    raw_audit = list(game.recommendation_audit or [])
    n_snap = len(review_timeline_rows(raw_audit))
    n_plays = count_logged_plays(game)
    replay_ok = n_plays > 0
    if n_snap:
        mode = "Full review"
    elif replay_ok:
        mode = "Replay-only"
    else:
        mode = "No review yet"
    rp = "✓" if replay_ok else "—"
    st.caption(f"Review rows: **{n_snap}** · Replay: **{rp}** · Mode: **{mode}**")
    with st.expander("ℹ️ Export / review detail", expanded=False):
        st.caption(SIDEBAR_CAPTION_EXPORT_REVIEW)


def render_sidebar(*, game: Game, drive_log: DriveLogger) -> tuple[bool, object]:
    """Returns ``(sidebar_generate_submitted, export_slot)`` — fill ``export_slot`` after main console."""
    generate = False
    export_slot = None
    with st.sidebar:

        st.markdown(
            "### Play Caller — <span style='font-size:0.95em;font-weight:500'>Sideline OC</span>",
            unsafe_allow_html=True,
        )

        with st.expander(SIDEBAR_SECTION_GAME_SETUP, expanded=True):
            st.caption("Session identity — stored on exported JSON.")
            st.text_input("Our team name", key=SESSION_SETUP_TEAM_NAME, placeholder="e.g. East High")
            st.text_input("Opponent", key=SESSION_SETUP_OPPONENT, placeholder="Optional")
            st.text_input("Game date", key=SESSION_SETUP_GAME_DATE, placeholder="YYYY-MM-DD")
            st.text_input("Game label / title", key=SESSION_SETUP_GAME_LABEL, placeholder="Optional short title")
            st.text_input("Season", key=SESSION_SETUP_SEASON, placeholder="e.g. 2026")
            st.text_input("Roster / roster version", key=SESSION_SETUP_ROSTER_VERSION, placeholder="Optional")
            st.text_area("Notes", key=SESSION_SETUP_NOTES, height=56, placeholder="Optional situational notes")
            st.checkbox(
                "This session is simulated (not an actual game)",
                key=SESSION_SETUP_IS_SIMULATED,
                help="Unchecked = real sideline data. Checked = practice or lab.",
            )
            sid = ""
            if isinstance(game.session_metadata, dict):
                sid = str(game.session_metadata.get("session_game_id") or "")
            if sid:
                short = sid if len(sid) <= 12 else (sid[:8] + "…")
                st.markdown(
                    f'<p style="font-size:11px;color:#94a3b8;margin:4px 0 0 0">Session id '
                    f'<code title="{html.escape(sid)}">{html.escape(short)}</code></p>',
                    unsafe_allow_html=True,
                )
            for w in session_metadata_warnings(game.session_metadata or {})[:1]:
                st.caption(w)

            render_sidebar_warehouse_section(game=game)

            up = st.file_uploader(
                "Load game JSON",
                type=["json"],
                key="sidebar_game_json_upload",
                help="Replaces scoreboard and completed drives; clears the in-progress drive log.",
            )
            c_load, c_new = st.columns(2)
            with c_load:
                load_clicked = st.button(
                    "Load JSON",
                    use_container_width=True,
                    type="primary",
                    key="sidebar_btn_load_game_json",
                    disabled=up is None,
                )
            with c_new:
                new_clicked = st.button(
                    "New game", use_container_width=True, type="secondary", key="sidebar_btn_new_game_top"
                )
            if load_clicked and up is not None:
                try:
                    raw = up.getvalue().decode("utf-8")
                except UnicodeDecodeError:
                    st.error("That file is not valid UTF-8 text.")
                else:
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError as e:
                        st.error(f"Invalid JSON (parse error): {e}")
                    else:
                        if not isinstance(payload, dict):
                            st.error('JSON root must be an object (e.g. { "game_id": ... }).')
                        else:
                            try:
                                g_load = game_from_dict(payload)
                                ensure_snap_review_list_on_game(g_load)
                                st.session_state.game = g_load
                            except (TypeError, ValueError, KeyError) as e:
                                st.error(f"JSON shape not compatible with a saved game: {e}")
                            except Exception as e:
                                st.error(f"Could not restore game: {e}")
                            else:
                                g0 = st.session_state.game
                                gq = max(1, min(5, int(getattr(g0, "quarter", 1) or 1)))
                                raw_clk = int(getattr(g0, "clock_seconds_remaining", 0) or 0)
                                sec = clamp_quarter_clock_seconds(gq, raw_clk)
                                st.session_state[GAME_PERIOD] = gq
                                st.session_state[GAME_QUARTER_CLOCK_MINS] = sec // 60
                                st.session_state[GAME_QUARTER_CLOCK_SECS] = sec % 60
                                st.session_state[GAME_SCORE_OURS] = int(g0.offense_points)
                                st.session_state[GAME_SCORE_THEIRS] = int(g0.defense_points)
                                request_widget_hydrate_from_backend(st.session_state)
                                st.session_state[PENDING_END_DRIVE_UI] = {
                                    "ui_possession_side": possession_side_radio_label(
                                        possession=str(g0.possession)
                                    ),
                                }
                                drive_log.reset()
                                st.session_state.result = None
                                st.session_state.pop(WAREHOUSE_HISTORICAL_SIGNAL, None)
                                st.session_state.last_play_summary = ""
                                clear_in_progress_log_state(st.session_state)
                                clear_live_feed_session_keys(st.session_state)
                                clear_coached_team_espn_session_identity(st.session_state)
                                aud = getattr(g0, "recommendation_audit", None) or []
                                mx = max((int(r.get("drive_epoch", 0)) for r in aud), default=-1)
                                st.session_state.eval_drive_epoch = mx + 1
                                hydrate_session_setup_widgets(st.session_state, g0)
                                st.toast("Loaded game from JSON.")
                                st.rerun()
            if new_clicked:
                st.session_state.pop(PENDING_END_DRIVE_UI, None)
                st.session_state.pop(PENDING_LOG_SITUATION, None)
                st.session_state.pop(PENDING_NEW_GAME_UI, None)
                st.session_state.game = Game.new_game()
                drive_log.reset()
                st.session_state[PENDING_NEW_GAME_UI] = new_game_ui_values()
                st.session_state.result = None
                st.session_state.pop(WAREHOUSE_HISTORICAL_SIGNAL, None)
                st.session_state.last_play_summary = ""
                st.session_state.eval_drive_epoch = 0
                clear_in_progress_log_state(st.session_state)
                clear_live_feed_session_keys(st.session_state)
                clear_coached_team_espn_session_identity(st.session_state)
                hydrate_session_setup_widgets(st.session_state, st.session_state.game)
                st.rerun()

        st.divider()

        with st.expander(SIDEBAR_SECTION_LIVE_SYNC, expanded=True):
            st.caption("ESPN Site API — clock, score, field; drive import optional.")
            if st.session_state.get(LIVE_FEED_HTTP_INSECURE_WARNING):
                st.warning("Secure connection failed — using local insecure fallback")
            st.selectbox(
                "Sport",
                ["nfl", "college-football", "ufl"],
                format_func=lambda s: (
                    "NFL"
                    if s == "nfl"
                    else "College football"
                    if s == "college-football"
                    else "UFL"
                ),
                key="ui_live_espn_sport",
            )
            _bind_ui("ui_live_espn_sport")
            with st.expander("Advanced sync", expanded=False):
                st.caption("Scoreboard fetch, feed locks, and import toggles.")
                if st.button("Refresh scoreboard", use_container_width=True, key="sidebar_live_refresh_board"):
                    try:
                        sport = str(st.session_state.ui_live_espn_sport)
                        rows_fb, insecure_http = list_espn_scoreboard_games(sport, limit=40)  # type: ignore[arg-type]
                        st.session_state[LIVE_FEED_SCOREBOARD_ROWS] = rows_fb
                        st.session_state[LIVE_FEED_HTTP_INSECURE_WARNING] = insecure_http
                        st.toast(f"{len(rows_fb)} games loaded.")
                    except Exception as e:
                        st.session_state[LIVE_FEED_LAST_ERROR] = str(e)
                        st.error(str(e))
                st.toggle("Lock situation vs feed", key="ui_live_lock_situation")
                st.toggle("Lock score & timeouts vs feed", key="ui_live_lock_score")
                st.toggle(
                    "Import completed drives from feed",
                    key=UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES,
                    help="Appends new **drives.previous** possessions into **Game** (deduped by ESPN).",
                )
                st.toggle(
                    "Import current possession plays from feed",
                    key=UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS,
                    help="Normalized **drives.current.plays** into the drive log (ESPN id dedup).",
                )
                st.toggle(
                    "Append new feed plays to drive log (deduped)",
                    key="ui_live_auto_plays",
                    help="Coarse play text from the feed when current-drive import is off.",
                )
                _bind_ui("ui_live_lock_situation")
                _bind_ui("ui_live_lock_score")
                _bind_ui(UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES)
                _bind_ui(UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS)
                _bind_ui("ui_live_auto_plays")
                with st.expander("Full ESPN sync help", expanded=False):
                    st.caption(
                        "Uses ESPN’s public **Site API** (not affiliated). Merges **completed drives** and **current possession** "
                        "plays when import toggles are on. **Lock situation** skips bad feed field/down when the feed lags."
                    )
            rows = st.session_state[LIVE_FEED_SCOREBOARD_ROWS] or []
            event_id = ""
            our_tid = ""
            sync_ready = EspnLiveSyncReadiness(
                False, "Load the scoreboard or use manual Event ID.", "", ""
            )
            if rows:
                ids = [r["id"] for r in rows]
                labels = [
                    f"{r.get('away_abbr', '?')} @ {r.get('home_abbr', '?')} — {str(r.get('detail', ''))[:36]}"
                    for r in rows
                ]
                st.selectbox(
                    "Game",
                    ids,
                    format_func=lambda x: labels[ids.index(x)],
                    key="ui_live_pick_event_id",
                )
                _bind_ui("ui_live_pick_event_id")
                pick_id = str(st.session_state.get("ui_live_pick_event_id") or ids[0])
                picked = next(r for r in rows if r["id"] == pick_id)
                event_id = pick_id
                st.caption("Our team (sideline OC)")
                st.radio(
                    "side",
                    ["away", "home"],
                    format_func=lambda x: (
                        f"{picked.get('away_abbr', 'Away')} (away)"
                        if x == "away"
                        else f"{picked.get('home_abbr', 'Home')} (home)"
                    ),
                    horizontal=True,
                    key="ui_live_home_or_away",
                    label_visibility="collapsed",
                )
                _bind_ui("ui_live_home_or_away")
                ho = str(st.session_state.get("ui_live_home_or_away") or "away")
                our_tid = str(picked["away_id"] if ho == "away" else picked["home_id"])
                adv_sb = str(st.session_state.get("ui_live_our_team_advanced") or "").strip()
                if adv_sb:
                    our_tid = adv_sb
                assign_session_state(
                    st.session_state,
                    "ui_live_our_team_manual",
                    our_tid,
                    context="espn_scoreboard_derived_team_id",
                )
                sync_ready = derive_espn_sync_readiness(
                    uses_scoreboard=True,
                    event_id=event_id,
                    our_team_id=our_tid,
                    manual=None,
                )
                away_lbl = str(picked.get("away_abbr") or picked.get("away_name") or "Away")
                home_lbl = str(picked.get("home_abbr") or picked.get("home_name") or "Home")
                oc_desc = f"{away_lbl} (away)" if ho == "away" else f"{home_lbl} (home)"
                st.markdown(
                    format_espn_match_pills_html(
                        away_name=away_lbl,
                        home_name=home_lbl,
                        event_id=event_id,
                        our_team_description=oc_desc,
                        sync_ready=sync_ready.can_sync,
                        sync_block_reason=sync_ready.block_reason,
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.caption(
                    "No scoreboard games in session — use **Event ID** + **Fetch game details** below, "
                    "or load games with **Refresh scoreboard** and pick from the list."
                )
                st.text_input(
                    "Event ID (ESPN game URL)",
                    key="ui_live_event_id_manual",
                    help="Digits from the game URL (gameId / gameId=…), e.g. 401772988",
                )
                _bind_ui("ui_live_event_id_manual")
                eid_cur = str(st.session_state.get("ui_live_event_id_manual") or "").strip()
                clear_manual_event_cache_if_event_id_mismatch(
                    st.session_state,
                    eid_typed=eid_cur,
                    teams_key=LIVE_FEED_MANUAL_EVENT_TEAMS,
                    for_id_key=LIVE_FEED_MANUAL_EVENT_FOR_ID,
                    fetch_error_key=LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
                )
                clear_manual_fetch_error_if_event_id_changed(
                    st.session_state,
                    eid_typed=eid_cur,
                    last_attempt_id_key=LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID,
                    fetch_error_key=LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
                )

                teams_d = st.session_state.get(LIVE_FEED_MANUAL_EVENT_TEAMS)
                for_eid = str(st.session_state.get(LIVE_FEED_MANUAL_EVENT_FOR_ID) or "").strip()
                ferr = st.session_state.get(LIVE_FEED_MANUAL_EVENT_FETCH_ERROR)

                fc1, fc2 = st.columns(2)
                with fc1:
                    fetch_ev = st.button(
                        "Fetch game details", use_container_width=True, key="sidebar_live_fetch_event"
                    )
                with fc2:
                    if st.button("Clear lookup", use_container_width=True, key="sidebar_live_clear_event_lookup"):
                        st.session_state[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
                        st.session_state[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
                        st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = None
                        st.session_state[LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID] = ""
                        st.session_state[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = ""
                        st.rerun()

                st.toggle(
                    "Auto-fetch when Event ID looks complete (9+ digits)",
                    key=LIVE_FEED_MANUAL_AUTO_FETCH,
                    help="Fetches once per id (including after errors) until you change the Event ID or use **Clear lookup**.",
                )

                manual_stat = manual_lookup_status(
                    eid_typed=eid_cur,
                    teams=teams_d,
                    teams_for_eid=for_eid,
                    fetch_error=str(ferr) if ferr else None,
                )
                auto_on = bool(st.session_state.get(LIVE_FEED_MANUAL_AUTO_FETCH))
                cursor_prev = str(st.session_state.get(LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR) or "")
                do_auto, cursor_next = maybe_auto_fetch_event_id(
                    eid_typed=eid_cur,
                    auto_fetch_enabled=auto_on,
                    lookup_phase=manual_stat.phase,
                    session_key_prev=cursor_prev,
                )
                trigger_fetch = bool(fetch_ev or do_auto)

                if trigger_fetch:
                    st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = None
                    st.session_state[LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID] = eid_cur.strip()
                    if not eid_cur.strip():
                        st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = (
                            "Enter an Event ID before fetching."
                        )
                        st.session_state[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = ""
                    else:
                        sport = str(st.session_state.ui_live_espn_sport)
                        try:
                            with st.spinner("Loading game from ESPN…"):
                                et, insecure_http = fetch_event_teams(sport, eid_cur)  # type: ignore[arg-type]
                            st.session_state[LIVE_FEED_HTTP_INSECURE_WARNING] = insecure_http
                            st.session_state[LIVE_FEED_MANUAL_EVENT_TEAMS] = {
                                "event_id": et.event_id,
                                "home_team_id": et.home_team_id,
                                "away_team_id": et.away_team_id,
                                "home_name": et.home_name,
                                "away_name": et.away_name,
                                "matchup_label": et.matchup_label,
                            }
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FOR_ID] = eid_cur.strip()
                        except RuntimeError as exc:
                            st.session_state[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = str(exc)
                        except ValueError as exc:
                            st.session_state[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = (
                                f"Invalid ESPN game payload: {exc}"
                            )
                        except Exception as exc:
                            st.session_state[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
                            st.session_state[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = f"Unexpected: {exc}"
                    st.session_state[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = eid_cur.strip()
                    st.rerun()

                st.session_state[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = cursor_next

                if manual_stat.phase is ManualEventLookupPhase.NO_EVENT_ID:
                    st.caption(manual_stat.hint)
                elif manual_stat.phase is ManualEventLookupPhase.NEED_FETCH:
                    st.warning(manual_stat.hint)
                elif manual_stat.phase is ManualEventLookupPhase.FETCH_FAILED:
                    st.caption(manual_stat.hint)
                else:
                    st.success(manual_stat.hint)

                if ferr:
                    msg = str(ferr)
                    if "HTTP 404" in msg:
                        st.error(
                            f"**Not found:** {msg} — check the Event ID and **Sport** (NFL vs college vs UFL)."
                        )
                    elif "Invalid JSON" in msg:
                        st.error(f"**API / parse:** {msg}")
                    else:
                        st.error(f"**Could not load game:** {msg}")

                event_id = eid_cur
                our_tid = ""
                teams_ok = manual_stat.phase is ManualEventLookupPhase.GAME_LOADED

                if teams_ok and isinstance(teams_d, dict):
                    st.caption("Our team (sideline OC)")
                    st.radio(
                        "side",
                        ["away", "home"],
                        format_func=lambda x: (
                            f"{teams_d['away_name']} (away)"
                            if x == "away"
                            else f"{teams_d['home_name']} (home)"
                        ),
                        horizontal=True,
                        key="ui_live_home_or_away",
                        label_visibility="collapsed",
                    )
                    _bind_ui("ui_live_home_or_away")
                    ho = str(st.session_state.get("ui_live_home_or_away") or "away")
                    our_tid = str(teams_d["away_team_id"] if ho == "away" else teams_d["home_team_id"])
                    st.caption(
                        "Sync maps the selected team to our offense. Override ESPN team id under **Review → Advanced** if needed."
                    )

                adv = str(st.session_state.get("ui_live_our_team_advanced") or "").strip()
                if adv:
                    our_tid = adv

                if our_tid:
                    assign_session_state(
                        st.session_state,
                        "ui_live_our_team_manual",
                        our_tid,
                        context="espn_manual_derived_team_id",
                    )

                ho = str(st.session_state.get("ui_live_home_or_away") or "away")
                if teams_ok and isinstance(teams_d, dict):
                    oc_lbl = our_team_label_from_manual_teams(teams_d, home_or_away=ho)
                    oc_desc = f"{oc_lbl} ({ho})" + (f" · override `{adv}`" if adv else "")
                    sync_ready = derive_espn_sync_readiness(
                        uses_scoreboard=False,
                        event_id=event_id,
                        our_team_id=our_tid,
                        manual=manual_stat,
                    )
                    st.markdown(
                        format_espn_match_pills_html(
                            away_name=str(teams_d.get("away_name") or ""),
                            home_name=str(teams_d.get("home_name") or ""),
                            event_id=eid_cur.strip(),
                            our_team_description=oc_desc,
                            sync_ready=sync_ready.can_sync,
                            sync_block_reason=sync_ready.block_reason,
                        ),
                        unsafe_allow_html=True,
                    )
                else:
                    sync_ready = derive_espn_sync_readiness(
                        uses_scoreboard=False,
                        event_id=event_id,
                        our_team_id=our_tid,
                        manual=manual_stat,
                    )
            st.radio(
                "Feed team scope",
                options=[
                    PREVIOUS_DRIVES_FILTER_OUR,
                    PREVIOUS_DRIVES_FILTER_OPPONENT,
                    PREVIOUS_DRIVES_FILTER_BOTH,
                ],
                format_func=lambda m: {
                    PREVIOUS_DRIVES_FILTER_OUR: "Our team",
                    PREVIOUS_DRIVES_FILTER_OPPONENT: "Opponent",
                    PREVIOUS_DRIVES_FILTER_BOTH: "Both",
                }[m],
                horizontal=True,
                key=LIVE_FEED_TEAM_SCOPE,
                help=(
                    "Which ESPN possessions enter **Game.drives** and the **live drive log** on sync. "
                    "**Our team only** (default) keeps a single sideline. **Unknown** feed team ids are skipped "
                    "unless you choose **Both teams**."
                ),
            )
            do_sync = st.button(
                "Sync from ESPN",
                use_container_width=True,
                type="primary",
                key="sidebar_live_sync",
                disabled=not sync_ready.can_sync,
            )
            if st.button("Mark manual", use_container_width=True, type="secondary", key="sidebar_live_mark_manual"):
                session_mark_manual(st.session_state)
                st.rerun()
            if not sync_ready.can_sync and sync_ready.block_reason:
                st.caption(f"**Sync unavailable:** {sync_ready.block_reason}")
            if do_sync:
                if not sync_ready.can_sync:
                    st.session_state[LIVE_FEED_LAST_ERROR] = sync_ready.block_reason or "Sync is not ready yet."
                    st.error(st.session_state[LIVE_FEED_LAST_ERROR])
                else:
                    sport = str(st.session_state.ui_live_espn_sport)
                    prov = EspnFootballProvider(sport)  # type: ignore[arg-type]
                    fr = prov.fetch_snapshot(sync_ready.event_id, our_team_id=sync_ready.our_team_id)
                    if not fr.ok or fr.snapshot is None:
                        st.session_state[LIVE_FEED_LAST_ERROR] = fr.error or "Fetch failed."
                        st.error(st.session_state[LIVE_FEED_LAST_ERROR])
                    else:
                        st.session_state[LIVE_FEED_LAST_ERROR] = None
                        st.session_state[LIVE_FEED_HTTP_INSECURE_WARNING] = bool(
                            fr.used_insecure_ssl_fallback
                        )
                        opts = SyncOptions(
                            lock_situation=bool(st.session_state.ui_live_lock_situation),
                            lock_score=bool(st.session_state.ui_live_lock_score),
                            auto_append_feed_plays=bool(st.session_state.ui_live_auto_plays),
                            import_completed_feed_drives=bool(
                                st.session_state[UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES]
                            ),
                            import_current_feed_drive_plays=bool(
                                st.session_state[UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS]
                            ),
                        )
                        res = apply_snapshot(
                            game=game,
                            session=st.session_state,
                            drive_log=drive_log,
                            snapshot=fr.snapshot,
                            options=opts,
                        )
                        wh_ingest = None
                        if fr.raw_summary:
                            try:
                                wh_ingest = ingest_espn_summary_after_live_fetch(
                                    fr.raw_summary,
                                    sport=sport,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Warehouse minimal ingest after ESPN sync failed: %s",
                                    exc,
                                    exc_info=True,
                                )
                        extra = []
                        if res.plays_appended:
                            extra.append(f"+{res.plays_appended} feed plays")
                        if res.drives_imported:
                            extra.append(f"+{res.drives_imported} completed drives")
                        if wh_ingest is not None:
                            extra.append(
                                "warehouse "
                                + ("game row created" if wh_ingest.was_new else "game row updated")
                            )
                        st.toast(res.message + (f" · {' · '.join(extra)}" if extra else ""))
                        st.rerun()
            err = st.session_state.get(LIVE_FEED_LAST_ERROR)
            if err:
                st.warning(str(err))
            ts = st.session_state.get(LIVE_FEED_LAST_SYNC_EPOCH)
            if ts:
                origin = str(st.session_state.get(LIVE_FEED_LAST_ORIGIN, "—"))
                lt = datetime.fromtimestamp(float(ts))
                line = f"Synced **{lt.strftime('%H:%M')}** · {origin}"
                st.caption(line)
            aud = st.session_state.get(LIVE_FEED_LAST_AUDIT)
            if aud:
                with st.expander("ℹ️ Full last sync detail", expanded=False):
                    so = aud.get("sync_options")
                    if isinstance(so, dict):
                        lc = so.get("import_current_feed_drive_plays")
                        ld = so.get("import_completed_feed_drives")
                        la = so.get("auto_append_feed_plays")
                        if isinstance(lc, bool) and isinstance(ld, bool) and isinstance(la, bool):
                            st.caption(
                                f"Feed: current drive **{'ON' if lc else 'OFF'}** · "
                                f"completed drives **{'ON' if ld else 'OFF'}** · "
                                f"coarse append **{'ON' if la else 'OFF'}**"
                            )
                    st.caption(
                        "Includes **feed_team_scope**, **sync_options**, merge counters, and skip reasons."
                    )
                    st.json(aud)

        st.divider()
        with st.expander(SIDEBAR_SECTION_PLAY_CALLS_EXPANDER, expanded=True):
            st.markdown(f"#### {SIDEBAR_SECTION_PLAY_CALLS}")
            st.caption("Presets = **this snap** only (not game JSON).")
            st.markdown(f"##### {SIDEBAR_SECTION_PRESETS}")
            _ss = st.session_state
            st.caption("Field position")
            pcols = st.columns(2)
            with pcols[0]:
                if st.button(
                    "Own 25 · 1&10",
                    use_container_width=True,
                    type="primary" if builtin_own25_active(_ss) else "secondary",
                    key="sidebar_chip_preset_own25_1st10",
                ):
                    preset_snap_only(territory="own", yardline=25, down=1, distance=10, rerun=True)
            with pcols[1]:
                if st.button(
                    "Opp 35 · 3&6",
                    use_container_width=True,
                    type="primary" if builtin_opp35_active(_ss) else "secondary",
                    key="sidebar_chip_preset_opp35_3rd6",
                ):
                    preset_snap_only(territory="opponents", yardline=35, down=3, distance=6, rerun=True)
            st.caption("Special")
            pcols2 = st.columns(2)
            with pcols2[0]:
                if st.button(
                    "RZ · 2&7",
                    use_container_width=True,
                    type="primary" if builtin_rz_active(_ss) else "secondary",
                    key="sidebar_chip_preset_rz_2nd7",
                ):
                    preset_snap_only(territory="opponents", yardline=12, down=2, distance=7, rerun=True)
            with pcols2[1]:
                if st.button(
                    "2-min · Q4 1:10",
                    use_container_width=True,
                    type="primary" if builtin_twomin_active(_ss) else "secondary",
                    key="sidebar_chip_preset_twomin_q4_1_10",
                ):
                    preset_two_minute_drill(rerun=True)
            render_custom_presets_subsection()

            st.divider()
            st.markdown(f"#### {SIDEBAR_SECTION_QUICK_ADJUST}")
            st.caption("Most-used tweaks as one-tap chips.")

            st.markdown("**Down / distance**")
            dcols = st.columns(4)
            with dcols[0]:
                if st.button("1st", use_container_width=True, key="sidebar_chip_down_1"):
                    apply_and_rerun(ui_down=1, ui_auto_generate=True)
            with dcols[1]:
                if st.button("2nd", use_container_width=True, key="sidebar_chip_down_2"):
                    apply_and_rerun(ui_down=2, ui_auto_generate=True)
            with dcols[2]:
                if st.button("3rd", use_container_width=True, key="sidebar_chip_down_3"):
                    apply_and_rerun(ui_down=3, ui_auto_generate=True)
            with dcols[3]:
                if st.button("4th", use_container_width=True, key="sidebar_chip_down_4"):
                    apply_and_rerun(ui_down=4, ui_auto_generate=True)

            dist_cols = st.columns(5)
            for i, dist in enumerate([1, 3, 5, 7, 10]):
                with dist_cols[i]:
                    if st.button(f"{dist}", use_container_width=True, key=f"sidebar_chip_to_go_{dist}"):
                        apply_and_rerun(ui_distance=dist, ui_auto_generate=True)

            st.markdown("**Territory / yardline**")
            tcols = st.columns(2)
            with tcols[0]:
                if st.button("Own", use_container_width=True, key="sidebar_chip_territory_own"):
                    apply_and_rerun(ui_territory="own", ui_auto_generate=True)
            with tcols[1]:
                if st.button("Opp", use_container_width=True, key="sidebar_chip_territory_opp"):
                    apply_and_rerun(ui_territory="opponents", ui_auto_generate=True)

            ycols = st.columns(5)
            yard_presets = [10, 25, 35, 40, 45]
            for i, y in enumerate(yard_presets):
                with ycols[i]:
                    if st.button(f"{y}", use_container_width=True, key=f"sidebar_chip_yardline_{y}"):
                        apply_and_rerun(ui_yardline=y, ui_auto_generate=True)

            st.markdown("**Clock**")
            ccols = st.columns(4)
            with ccols[0]:
                if st.button("15:00", use_container_width=True, key="sidebar_chip_clock_15m00s"):
                    apply_and_rerun(
                        ui_quarter_clock_mins=15,
                        ui_quarter_clock_secs=0,
                        **{GAME_CLOCK_TOTAL_SECONDS: 15 * 60},
                        ui_auto_generate=True,
                    )
            with ccols[1]:
                if st.button("10:00", use_container_width=True, key="sidebar_chip_clock_10m00s"):
                    apply_and_rerun(
                        ui_quarter_clock_mins=10,
                        ui_quarter_clock_secs=0,
                        **{GAME_CLOCK_TOTAL_SECONDS: 10 * 60},
                        ui_auto_generate=True,
                    )
            with ccols[2]:
                if st.button("5:00", use_container_width=True, key="sidebar_chip_clock_5m00s"):
                    apply_and_rerun(
                        ui_quarter_clock_mins=5,
                        ui_quarter_clock_secs=0,
                        **{GAME_CLOCK_TOTAL_SECONDS: 5 * 60},
                        ui_auto_generate=True,
                    )
            with ccols[3]:
                if st.button("1:10", use_container_width=True, key="sidebar_chip_clock_1m10s"):
                    apply_and_rerun(
                        ui_quarter_clock_mins=1,
                        ui_quarter_clock_secs=10,
                        **{GAME_CLOCK_TOTAL_SECONDS: 70},
                        ui_auto_generate=True,
                    )

            st.markdown("**Possession**")
            st.caption("Who has the ball for **this** drive (updates when you end a drive or use **New game**).")
            st.radio(
                "Offense",
                ["Our team", "Opponent"],
                horizontal=True,
                key="ui_possession_side",
                label_visibility="collapsed",
            )
            _bind_ui("ui_possession_side")
            sc1, sc2 = st.columns(2)
            with sc1:
                st.number_input(
                    "Our score",
                    min_value=0,
                    max_value=999,
                    step=1,
                    key="ui_score_ours",
                    help=(
                        "First number in **us–them**. **End drive** (TD/FG) bumps these after the next refresh; "
                        "missed FG adds no points."
                    ),
                )
            with sc2:
                st.number_input(
                    "Their score",
                    min_value=0,
                    max_value=999,
                    step=1,
                    key="ui_score_theirs",
                    help="Second number in **us–them** — match the broadcast anytime.",
                )
            _bind_ui("ui_score_ours")
            _bind_ui("ui_score_theirs")

            st.markdown("**Defense shell (fast)**")
            fcols = st.columns(2)
            with fcols[0]:
                if st.button("Nickel · 7 · C3", use_container_width=True, key="sidebar_chip_def_nickel_7_c3"):
                    apply_and_rerun(
                        ui_def_personnel="nickel",
                        ui_box_count=7,
                        ui_coverage_shell="cover_3",
                        ui_safeties="single_high",
                        ui_blitz_likely=False,
                        ui_auto_generate=True,
                    )
            with fcols[1]:
                if st.button("Dime · 6 · Qtrs", use_container_width=True, key="sidebar_chip_def_dime_6_qtrs"):
                    apply_and_rerun(
                        ui_def_personnel="dime",
                        ui_box_count=6,
                        ui_coverage_shell="quarters",
                        ui_safeties="two_high",
                        ui_blitz_likely=False,
                        ui_auto_generate=True,
                    )

            fcols2 = st.columns(2)
            with fcols2[0]:
                if st.button("GL · 9 · C0", use_container_width=True, key="sidebar_chip_def_gl_9_c0"):
                    apply_and_rerun(
                        ui_def_personnel="goal_line",
                        ui_box_count=9,
                        ui_coverage_shell="cover_0",
                        ui_safeties="single_high",
                        ui_blitz_likely=True,
                        ui_auto_generate=True,
                    )
            with fcols2[1]:
                if st.button("Clear defense read", use_container_width=True, key="sidebar_chip_def_clear_read"):
                    apply_and_rerun(
                        ui_def_personnel="unknown",
                        ui_box_count=7,
                        ui_coverage_shell="unknown",
                        ui_safeties="unknown",
                        ui_blitz_likely=False,
                        ui_auto_generate=True,
                    )

            st.markdown("**Generate play call**")
            with st.form("generate_form", clear_on_submit=False):
                generate = st.form_submit_button(
                    "Generate play call",
                    type="primary",
                    use_container_width=True,
                    key="sidebar_form_submit_generate",
                )
            can_undo = bool(drive_log.results) and st.session_state.get(UNDO_BUNDLE) is not None
            if st.button(
                "Undo last play",
                use_container_width=True,
                disabled=not can_undo,
                key="sidebar_undo_last_play",
            ):
                undo_last_logged_play()
                st.rerun()

        st.divider()

        with st.expander(SIDEBAR_SECTION_REVIEW_EXPORT_EXPANDER, expanded=False):
            st.markdown(f"#### {SIDEBAR_SECTION_DRIVE_SESSION}")
            st.caption(
                "**End drive** archives plays to game history, flips possession when appropriate, burns clock, "
                "then starts a fresh series — same as broadcast “next possession.”"
            )
            if st.button(
                "End drive & next series",
                type="primary",
                use_container_width=True,
                key="sidebar_btn_end_drive_next",
            ):
                archive_current_drive_and_reset_session()
                st.rerun()

            st.caption("**One-tap end** (overrides the dropdown for that archive only):")
            er1, er2, er3 = st.columns(3)
            with er1:
                if st.button("End · Auto", use_container_width=True, key="sidebar_quick_end_auto"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_UI_AUTO)
                    st.rerun()
                if st.button("End · Punt", use_container_width=True, key="sidebar_quick_end_punt"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_PUNT)
                    st.rerun()
                if st.button("End · TD", use_container_width=True, key="sidebar_quick_end_td"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_TOUCHDOWN)
                    st.rerun()
            with er2:
                if st.button("End · FG", use_container_width=True, key="sidebar_quick_end_fg"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_FIELD_GOAL)
                    st.rerun()
                if st.button("End · FG miss", use_container_width=True, key="sidebar_quick_end_fg_miss"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_FIELD_GOAL_MISS)
                    st.rerun()
                if st.button("End · INT", use_container_width=True, key="sidebar_quick_end_int"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_TURNOVER_INT)
                    st.rerun()
            with er3:
                if st.button("End · Fum", use_container_width=True, key="sidebar_quick_end_fum"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_TURNOVER_FUMBLE)
                    st.rerun()
                if st.button("End · TOD", use_container_width=True, key="sidebar_quick_end_tod"):
                    archive_current_drive_and_reset_session(end_kind_override=DRIVE_END_TURNOVER_ON_DOWNS)
                    st.rerun()

            st.selectbox(
                "When you use **End drive & next** (not the one-tap row):",
                options=list(DRIVE_END_UI_OPTIONS),
                format_func=lambda k: DRIVE_END_UI_LABELS.get(str(k), str(k)),
                key="ui_drive_end_on_new",
                help=(
                    "**Auto** uses TDs, turnovers, turnover on downs (from last snap), and field goals when obvious; "
                    "otherwise it labels the drive as a punt."
                ),
            )
            _bind_ui("ui_drive_end_on_new")
            snap_hint = (
                f"**{len(drive_log.results)}** play(s) on this drive — end the drive when the series is over."
                if drive_log.results
                else "No plays on this drive yet — **End drive** only clears the call sheet."
            )
            st.caption(snap_hint)

            st.divider()
            st.markdown(f"#### {SIDEBAR_SECTION_REVIEW_EXPORT}")
            _sidebar_export_review_status(game)
            export_slot = st.empty()

            with st.expander(f"{SIDEBAR_SECTION_ADVANCED}", expanded=False):
                st.caption("Overrides **Our team** in Live Sync when set.")
                st.text_input(
                    "ESPN team id (numeric)",
                    key="ui_live_our_team_advanced",
                    help="If set, overrides the away/home radio for sync mapping.",
                )
                _bind_ui("ui_live_our_team_advanced")
                render_warehouse_advanced_panel(game=game)
                st.markdown("##### Fine tune (sliders)")
                st.caption("Down, distance, field, defense read, clock — full precision.")
                c1, c2 = st.columns(2)
                c1.selectbox("Down", [1, 2, 3, 4], key="ui_down")
                c2.selectbox(
                    "Distance",
                    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20],
                    key="ui_distance",
                )
                _bind_ui("ui_down")
                _bind_ui("ui_distance")
                st.radio(
                    "Field side",
                    ["own", "opponents"],
                    horizontal=True,
                    format_func=lambda x: "Our side (own hash → midfield)" if x == "own" else "Their side (toward their goal)",
                    key="ui_territory",
                )
                st.slider(
                    "Yard line (1 = that side's goal line · 50 = midfield)",
                    1,
                    50,
                    key="ui_yardline",
                    help="Same as broadcast: **Own 25** = our 25-yard line; **Opp 37** = their 37.",
                )
                _bind_ui("ui_territory")
                _bind_ui("ui_yardline")
                st.selectbox(
                    "Personnel",
                    ["unknown", "nickel", "base", "dime", "goal_line"],
                    format_func=lambda x: x.replace("_", " ").title(),
                    key="ui_def_personnel",
                )
                st.slider("Box count", 4, 9, key="ui_box_count", format="%d in box")
                st.selectbox(
                    "Coverage",
                    ["unknown", "cover_0", "cover_1", "cover_2", "cover_3", "cover_4", "quarters"],
                    format_func=lambda x: x.replace("_", " ").upper() if x != "unknown" else "Unknown",
                    key="ui_coverage_shell",
                )
                st.selectbox(
                    "Safeties",
                    ["unknown", "single_high", "two_high"],
                    format_func=lambda x: x.replace("_", " ").title(),
                    key="ui_safeties",
                )
                st.toggle("Blitz expected", key="ui_blitz_likely")
                _bind_ui("ui_def_personnel")
                _bind_ui("ui_box_count")
                _bind_ui("ui_coverage_shell")
                _bind_ui("ui_safeties")
                _bind_ui("ui_blitz_likely")
                st.selectbox(
                    "Period",
                    [1, 2, 3, 4, 5],
                    format_func=period_display_label,
                    key="ui_game_period",
                    help="**OT** is stored as period 5.",
                )
                _bind_ui("ui_game_period")
                st.caption("Clock = time remaining in this quarter.")
                cm1, cm2 = st.columns(2)
                with cm1:
                    st.slider("Minutes left in quarter", 0, 15, key="ui_quarter_clock_mins")
                with cm2:
                    st.slider("Seconds (add to minutes)", 0, 59, key="ui_quarter_clock_secs")
                _bind_ui("ui_quarter_clock_mins")
                _bind_ui("ui_quarter_clock_secs")
                c5, c6 = st.columns(2)
                c5.selectbox("Own TOs", [0, 1, 2, 3], key="ui_own_tos")
                c6.selectbox("Opp TOs", [0, 1, 2, 3], key="ui_opp_tos")
                _bind_ui("ui_own_tos")
                _bind_ui("ui_opp_tos")
                st.selectbox(
                    "Weather",
                    ["clear", "wind", "rain", "snow"],
                    key="ui_weather",
                    on_change=on_ui_weather_changed,
                )
                st.slider("Wind (mph)", 0, 40, key="ui_wind_mph")
                st.toggle("QB limited", key="ui_qb_limited")
                st.selectbox(
                    "Override mode",
                    ["normal", "must_score", "drain_clock", "two_minute", "two_point"],
                    format_func=lambda x: x.replace("_", " ").title(),
                    key="ui_game_mode",
                )
                st.text_input("Mismatch note", placeholder="Optional…", key="ui_mismatch")
                _bind_ui("ui_weather")
                _bind_ui("ui_wind_mph")
                _bind_ui("ui_qb_limited")
                _bind_ui("ui_game_mode")
                _bind_ui("ui_mismatch")
                st.toggle(
                    "Show game-context debug",
                    key="ui_debug_game_context",
                    help="When on, surfaces tendencies and history fed into recommendations (model meta).",
                )
                _bind_ui("ui_debug_game_context")

        _dev = str(os.environ.get("PLAYCALLER_DEV_MODE") or "").strip().lower()
        if _dev in ("1", "true", "yes"):
            from pathlib import Path

            from playcaller.debug.env_check import check_warehouse_env

            _repo = Path(__file__).resolve().parents[2]
            _wh = check_warehouse_env(repo_root=_repo)
            with st.expander("Dev: warehouse DB env", expanded=False):
                st.caption("Shown only when `PLAYCALLER_DEV_MODE=1` — not for sideline use.")
                if not _wh["present"]:
                    st.warning("`FOOTBALL_WAREHOUSE_DATABASE_URL` is **not** set in this process.")
                elif _wh.get("source") == "dev_fallback":
                    st.success(
                        "Warehouse URL resolved via **PLAYCALLER_DEV_MODE** dev fallback "
                        "(`FOOTBALL_WAREHOUSE_DATABASE_URL` unset)."
                    )
                else:
                    st.success("`FOOTBALL_WAREHOUSE_DATABASE_URL` is set.")
                _sqlite_path = _wh.get("sqlite_resolved_path")
                st.markdown(
                    f"- **Source:** `{_wh['source']}` (dotenv = matches repo `.env`; env = shell or other; "
                    f"dev_fallback = local SQLite when env unset and dev mode on)\n"
                    f"- **Scheme:** `{_wh.get('scheme') or '—'}`\n"
                    f"- **Masked URL:** `{_wh.get('masked_value') or '—'}`\n"
                    + (
                        f"- **SQLite file (absolute):** `{_sqlite_path}` — confirm with "
                        f"`ls -la` on that path.\n"
                        if _sqlite_path
                        else "- **SQLite file:** — (not applicable or in-memory)\n"
                    )
                )

    return bool(generate), export_slot


def populate_sidebar_export_slot(export_slot: object | None) -> None:
    """
    Fill the **Download game JSON** region after :func:`~playcaller.ui.main_console.render_main_content`.

    When ``export_slot`` is an ``st.empty()`` from :func:`render_sidebar`, renders into that slot;
    otherwise falls back to appending at the bottom of the sidebar.
    """
    from playcaller.evaluation.snap_review_logging import (
        SNAP_REVIEW_SESSION_TRACE_KEY,
        STREAMLIT_DEBUG_STATE_KEY,
        log_before_export,
        merge_streamlit_snap_review_debug,
        streamlit_snap_review_debug_enabled,
    )

    game = st.session_state.game
    n_audit = len(getattr(game, "recommendation_audit", None) or [])

    def _body() -> None:
        st.markdown(f"##### {SIDEBAR_SECTION_EXPORT}")
        merge_streamlit_snap_review_debug(
            st.session_state,
            event="before_export",
            row_count=n_audit,
            game_object_id=id(game),
            game_id=str(getattr(game, "game_id", "")),
            row_status=str((game.recommendation_audit[-1].get("status") or "") if game.recommendation_audit else ""),
        )
        trace = st.session_state.get(SNAP_REVIEW_SESSION_TRACE_KEY) or {}
        st.caption(
            f"Snap audit rows: **{n_audit}** · last `{trace.get('event', '—')}`"
            + (f" · row **{trace.get('row_status', '—')}**" if trace.get("row_status") else "")
        )
        if streamlit_snap_review_debug_enabled():
            with st.expander("Snap review capture (verbose debug)", expanded=False):
                st.json(st.session_state.get(STREAMLIT_DEBUG_STATE_KEY) or {})
                st.caption(f"``st.session_state.game`` id={id(game)} · recommendation_audit len={n_audit}")
        log_before_export(row_count=n_audit)
        j_blob = game_to_json(game)
        st.download_button(
            label="Download game JSON",
            data=j_blob,
            file_name=f"playcaller_game_{game.game_id}.json",
            mime="application/json",
            use_container_width=True,
            type="primary",
            key="sidebar_download_game_json",
        )
        with st.expander("ℹ️ Export hints", expanded=False):
            st.caption(game_json_export_hint_caption())
        if streamlit_snap_review_debug_enabled():
            st.caption("Verbose snap-review debug is on (`PLAYCALLER_SNAP_REVIEW_STREAMLIT_DEBUG`).")

    if export_slot is not None:
        with export_slot.container():
            _body()
    else:
        with st.sidebar:
            st.divider()
            _body()


def render_sidebar_json_export() -> None:
    """Backward compatible: appends export block to sidebar (prefer :func:`populate_sidebar_export_slot`)."""
    populate_sidebar_export_slot(None)
