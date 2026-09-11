"""Queue Load-JSON onto the pre-widget pending path (same run as hydrate)."""

from __future__ import annotations

import json
from typing import Any, MutableMapping

from playcaller.evaluation.snap_review_lifecycle import ensure_snap_review_list_on_game
from playcaller.game import game_from_dict
from playcaller.game_situation_input import clamp_quarter_clock_seconds
from playcaller.possession import possession_side_radio_label
from playcaller.streamlit_state.keys import (
    GAME_PERIOD,
    GAME_POSSESSION_SIDE,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    LAST_DRIVE_SNAP_CONTEXT,
    LOAD_GAME_ERROR,
    PENDING_END_DRIVE_UI,
    PENDING_LOAD_GAME,
    PENDING_LOG_SITUATION,
    PENDING_SESSION_SETUP_HYDRATE,
    UNDO_BUNDLE,
    WAREHOUSE_HISTORICAL_SIGNAL,
)
from playcaller.streamlit_state.session import (
    clear_coached_team_espn_session_identity,
    clear_live_feed_session_keys,
)
from playcaller.streamlit_state.widget_backend_bridge import request_widget_hydrate_from_backend


def request_load_game_json() -> None:
    """Widget ``on_click``: parse the uploader and queue ``PENDING_LOAD_GAME`` (no ``st.rerun``)."""
    import streamlit as st

    up = st.session_state.get("sidebar_game_json_upload")
    if up is None:
        st.session_state[LOAD_GAME_ERROR] = "Choose a JSON file first."
        return
    try:
        raw = up.getvalue().decode("utf-8")
    except UnicodeDecodeError:
        st.session_state[LOAD_GAME_ERROR] = "That file is not valid UTF-8 text."
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        st.session_state[LOAD_GAME_ERROR] = f"Invalid JSON (parse error): {e}"
        return
    if not isinstance(payload, dict):
        st.session_state[LOAD_GAME_ERROR] = 'JSON root must be an object (e.g. { "game_id": ... }).'
        return
    st.session_state[LOAD_GAME_ERROR] = None
    st.session_state[PENDING_LOAD_GAME] = payload


def apply_pending_load_game(ss: MutableMapping[str, Any]) -> None:
    """Restore ``Game`` + ``game_*`` mirrors before widgets; hydrate copies them to ``ui_*``."""
    payload = ss.pop(PENDING_LOAD_GAME, None)
    if not isinstance(payload, dict):
        return
    try:
        g_load = game_from_dict(payload)
        ensure_snap_review_list_on_game(g_load)
        ss["game"] = g_load
    except (TypeError, ValueError, KeyError) as e:
        ss[LOAD_GAME_ERROR] = f"JSON shape not compatible with a saved game: {e}"
        return
    except Exception as e:
        ss[LOAD_GAME_ERROR] = f"Could not restore game: {e}"
        return

    g0 = ss["game"]
    gq = max(1, min(5, int(getattr(g0, "quarter", 1) or 1)))
    raw_clk = int(getattr(g0, "clock_seconds_remaining", 0) or 0)
    sec = clamp_quarter_clock_seconds(gq, raw_clk)
    ss[GAME_PERIOD] = gq
    ss[GAME_QUARTER_CLOCK_MINS] = sec // 60
    ss[GAME_QUARTER_CLOCK_SECS] = sec % 60
    ss[GAME_SCORE_OURS] = int(g0.offense_points)
    ss[GAME_SCORE_THEIRS] = int(g0.defense_points)
    ss[GAME_POSSESSION_SIDE] = possession_side_radio_label(possession=g0.possession)
    request_widget_hydrate_from_backend(ss)
    ss[PENDING_END_DRIVE_UI] = {
        "ui_possession_side": ss[GAME_POSSESSION_SIDE],
    }
    drive_log = ss.get("drive_log")
    if drive_log is not None and hasattr(drive_log, "reset"):
        drive_log.reset()
    ss["result"] = None
    ss.pop(WAREHOUSE_HISTORICAL_SIGNAL, None)
    ss["last_play_summary"] = ""
    ss.pop(PENDING_LOG_SITUATION, None)
    ss.pop(LAST_DRIVE_SNAP_CONTEXT, None)
    ss.pop(UNDO_BUNDLE, None)
    clear_live_feed_session_keys(ss)
    clear_coached_team_espn_session_identity(ss)
    aud = getattr(g0, "recommendation_audit", None) or []
    mx = max((int(r.get("drive_epoch", 0)) for r in aud), default=-1)
    ss["eval_drive_epoch"] = mx + 1
    ss[PENDING_SESSION_SETUP_HYDRATE] = True
    ss[LOAD_GAME_ERROR] = None
    ss["_load_game_toast"] = "Loaded game from JSON."
