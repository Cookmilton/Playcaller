"""
Controller-style actions: drive lifecycle, presets, undo, recommendation run, wind sync.

These functions mutate ``st.session_state`` and may ``st.rerun()`` — call from event handlers
or before/after widget blocks per Streamlit rules.
"""

from __future__ import annotations

from typing import Any, MutableMapping, Optional

import streamlit as st

from playcaller import (
    DriveLogger,
    FootballPlayPredictor,
    Game,
    GameContext,
    apply_scoring_after_drive,
    clock_seconds_after_drive_elapsed,
    complete_drive_from_plays,
    flip_possession_after_drive,
)
from playcaller.session_game_metadata import audit_context_from_game_metadata
from playcaller.evaluation.snap_review_lifecycle import (
    apply_undo_last_logged_play_to_snap_review,
    ensure_snap_review_list_on_game,
    record_open_snap_review_row_after_generate,
    trim_snap_review_opens_for_play_count,
)
from playcaller.evaluation.snap_review_logging import merge_streamlit_snap_review_debug
from playcaller.game import DRIVE_END_UI_AUTO
from playcaller.history.repository_corpus import load_repository_plays
from playcaller.history.repository_paths import resolve_history_repository_root
from playcaller.history.repository_settings import load_history_repository_settings
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    HV_CORPUS_SOURCE,
    HV_REPO_SELECTED_GAME_IDS,
    HV_REPO_USE_ALL_GAMES,
    HV_SESSION_CORPUS_KEY,
    LAST_DRIVE_SNAP_CONTEXT,
    PENDING_END_DRIVE_UI,
    PENDING_LOG_SITUATION,
    UI_HISTORICAL_NUDGE_ENABLED,
    UNDO_BUNDLE,
)
from playcaller.streamlit_state.pending import clear_in_progress_log_state
from playcaller.game_situation_input import context_quarter_from_period
from playcaller.streamlit_state.session import possession_side_radio_label
from playcaller.streamlit_state.ui_write_guard import assign_session_state


def archive_current_drive_and_reset_session(*, end_kind_override: Optional[str] = None) -> None:
    """
    Archive the in-progress drive into ``game.drives`` when it has plays, then clear the live log.

    ``end_kind_override``: explicit ``DRIVE_END_*`` kind, or ``None`` / ``DRIVE_END_UI_AUTO`` to use the
    sidebar **How this drive ends** selector (or full auto-inference when that is Auto).
    """
    dl = st.session_state.drive_log
    if dl.results:
        snap_ctx = st.session_state.get(LAST_DRIVE_SNAP_CONTEXT) or {}
        if end_kind_override is not None and str(end_kind_override) != DRIVE_END_UI_AUTO:
            override_kw: dict = {"end_kind_override": str(end_kind_override)}
        else:
            end_mode = str(st.session_state.get("ui_drive_end_on_new", DRIVE_END_UI_AUTO))
            override_kw = (
                {}
                if end_mode == DRIVE_END_UI_AUTO
                else {"end_kind_override": end_mode}
            )
        g = st.session_state.game
        possessing = g.possession
        finished = complete_drive_from_plays(
            list(dl.results),
            last_snap_touchdown=bool(snap_ctx.get("touchdown")),
            last_snap_turnover_on_downs=bool(snap_ctx.get("turnover_on_downs")),
            possessing_team=possessing,
            **override_kw,
        )
        apply_scoring_after_drive(g, finished)
        flip_possession_after_drive(g, finished)
        g.drives.append(finished)
        period = int(st.session_state.get("ui_game_period", 1))
        g.quarter = context_quarter_from_period(period)
        clk = int(st.session_state.get("ui_quarter_clock_mins", 0)) * 60 + int(
            st.session_state.get("ui_quarter_clock_secs", 0)
        )
        new_clk = clock_seconds_after_drive_elapsed(clk, finished)
        g.clock_seconds_remaining = new_clk
        st.session_state[PENDING_END_DRIVE_UI] = {
            "ui_quarter_clock_mins": new_clk // 60,
            "ui_quarter_clock_secs": new_clk % 60,
            "ui_score_ours": int(g.offense_points),
            "ui_score_theirs": int(g.defense_points),
            "ui_possession_side": possession_side_radio_label(
                possession=str(g.possession)
            ),
        }
    g = st.session_state.game
    dl.reset()
    trim_snap_review_opens_for_play_count(g.recommendation_audit, plays_on_drive=len(dl.results))
    st.session_state.result = None
    st.session_state.last_play_summary = ""
    clear_in_progress_log_state(st.session_state)
    st.session_state.eval_drive_epoch = int(st.session_state.get("eval_drive_epoch", 0)) + 1


def apply_and_rerun(**kwargs: Any) -> None:
    for k, v in kwargs.items():
        assign_session_state(st.session_state, k, v, context="apply_and_rerun")
    st.rerun()


def preset_snap_only(
    *,
    territory: str,
    yardline: int,
    down: int,
    distance: int,
    auto_generate: bool = True,
    rerun: bool = False,
) -> None:
    """
    Update **this snap** only (field + down & distance).

    Does not touch ``st.session_state.game``, ``game.drives``, or ``drive_log``.
    """
    assign_session_state(st.session_state, "ui_territory", territory, context="preset_snap_only")
    assign_session_state(st.session_state, "ui_yardline", int(yardline), context="preset_snap_only")
    assign_session_state(st.session_state, "ui_down", int(down), context="preset_snap_only")
    assign_session_state(st.session_state, "ui_distance", int(distance), context="preset_snap_only")
    if auto_generate:
        assign_session_state(st.session_state, "ui_auto_generate", True, context="preset_snap_only")
    if rerun:
        st.rerun()


def preset_two_minute_drill(*, auto_generate: bool = True, rerun: bool = False) -> None:
    """
    Quarter / clock / timeouts / mode for a two-minute scenario.

    Does not change field position, score diff, or any ``Game`` / drive history.
    """
    assign_session_state(st.session_state, "ui_game_period", 4, context="preset_two_minute_drill")
    assign_session_state(st.session_state, "ui_quarter_clock_mins", 1, context="preset_two_minute_drill")
    assign_session_state(st.session_state, "ui_quarter_clock_secs", 10, context="preset_two_minute_drill")
    st.session_state[GAME_CLOCK_TOTAL_SECONDS] = 70
    assign_session_state(st.session_state, "ui_own_tos", 1, context="preset_two_minute_drill")
    assign_session_state(st.session_state, "ui_opp_tos", 3, context="preset_two_minute_drill")
    assign_session_state(st.session_state, "ui_game_mode", "two_minute", context="preset_two_minute_drill")
    if auto_generate:
        assign_session_state(st.session_state, "ui_auto_generate", True, context="preset_two_minute_drill")
    if rerun:
        st.rerun()


def undo_last_logged_play() -> None:
    """Restore the situation to the snap before the last logged play and drop that play from the drive log."""
    bundle = st.session_state.get(UNDO_BUNDLE)
    if not bundle:
        st.toast("Nothing to undo on this drive yet.")
        return
    dl = st.session_state.drive_log
    popped = dl.pop_last()
    if popped is None:
        st.session_state.pop(UNDO_BUNDLE, None)
        st.toast("Drive log was already empty.")
        return
    apply_undo_last_logged_play_to_snap_review(
        st.session_state.game.recommendation_audit,
        plays_on_drive_after_undo=len(dl.results),
    )
    st.session_state[PENDING_LOG_SITUATION] = {
        "territory": str(bundle["territory"]),
        "yardline": int(bundle["yardline"]),
        "down": int(bundle["down"]),
        "distance": int(bundle["distance"]),
    }
    st.session_state.result = None
    assign_session_state(st.session_state, "ui_auto_generate", False, context="undo_last_logged_play")
    st.session_state.last_play_summary = (
        "Undid last logged play — situation restored to that snap. Tap **Generate** when ready."
    )
    st.session_state.pop(UNDO_BUNDLE, None)
    st.session_state.pop(LAST_DRIVE_SNAP_CONTEXT, None)
    st.toast("Removed last play · restored previous snap")


def sync_wind_slider_with_weather_pre_widgets() -> None:
    if str(st.session_state.get("ui_weather", "clear")) != "wind":
        assign_session_state(st.session_state, "ui_wind_mph", 0, context="sync_wind_slider_pre_widgets")


def on_ui_weather_changed() -> None:
    if str(st.session_state.get("ui_weather", "clear")) != "wind":
        assign_session_state(st.session_state, "ui_wind_mph", 0, context="on_ui_weather_changed")


def resolve_historical_plays_for_generate(ss: MutableMapping[str, Any]) -> Optional[Any]:
    """
    Corpus passed to ``recommend`` when the sidebar nudge is on and allowed by env.

    Returns ``None`` when history is off, forced off, or no plays are loaded.
    """
    settings = load_history_repository_settings()
    if settings.history_force_off:
        return None
    if not bool(ss.get(UI_HISTORICAL_NUDGE_ENABLED)):
        return None
    source = str(ss.get(HV_CORPUS_SOURCE) or "folder_session")
    if source == "repository":
        root = resolve_history_repository_root(settings)
        use_all = bool(ss.get(HV_REPO_USE_ALL_GAMES, True))
        raw_ids = ss.get(HV_REPO_SELECTED_GAME_IDS)
        ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else []
        plays = load_repository_plays(
            root,
            repo_game_ids=ids,
            use_all_games=use_all,
        )
        if plays:
            return plays
    corp = ss.get(HV_SESSION_CORPUS_KEY)
    if corp is not None and getattr(corp, "plays", None):
        return corp.plays
    return None


def run_generate_if_requested(
    *,
    ctx: GameContext,
    game: Game,
    drive_log: DriveLogger,
    predictor: FootballPlayPredictor,
    sidebar_generate: bool,
    main_generate: bool,
) -> None:
    """If any generate trigger is set, run ``predictor.recommend`` and append a snap review row."""
    if not (
        bool(sidebar_generate)
        or bool(main_generate)
        or bool(st.session_state.ui_auto_generate)
    ):
        merge_streamlit_snap_review_debug(
            st.session_state,
            event="generate_skipped",
            reason="no_trigger",
            sidebar_generate=bool(sidebar_generate),
            main_generate=bool(main_generate),
            ui_auto_generate=bool(st.session_state.ui_auto_generate),
        )
        return
    # Always mutate the canonical in-session ``Game`` (local ``game`` can diverge if sidebar replaced session state).
    canon = st.session_state.game
    ensure_snap_review_list_on_game(canon)
    hist_plays = resolve_historical_plays_for_generate(st.session_state)
    try:
        st.session_state.result = predictor.recommend(
            ctx, drive_log, canon, historical_plays=hist_plays
        )
    except Exception as e:
        st.session_state.result = None
        st.error(f"Could not generate a play call: {e}")
    assign_session_state(st.session_state, "ui_auto_generate", False, context="run_generate_if_requested")
    if st.session_state.result is not None:
        rec = record_open_snap_review_row_after_generate(
            rows=canon.recommendation_audit,
            game=canon,
            drive_log=drive_log,
            recommend_result=st.session_state.result,
            eval_drive_epoch=int(st.session_state.get("eval_drive_epoch", 0)),
            session_context=audit_context_from_game_metadata(canon.session_metadata),
        )
        merge_streamlit_snap_review_debug(
            st.session_state,
            event="after_generate",
            row_count=len(canon.recommendation_audit),
            snap_id=str(rec.get("snap_id") or ""),
            row_status=str(rec.get("status") or ""),
            completed=rec.get("completed"),
            game_object_id=id(canon),
            session_state_game_id=id(st.session_state.game),
            ids_match=id(canon) == id(st.session_state.game),
        )
    else:
        merge_streamlit_snap_review_debug(
            st.session_state,
            event="after_generate",
            row_count=len(canon.recommendation_audit),
            error="result_is_none",
            game_object_id=id(canon),
        )
