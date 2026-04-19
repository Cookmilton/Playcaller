"""
Game library: import, browse, and validate historical game JSON.

Run the app from the repo root:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from playcaller.streamlit_state.pending import apply_all_pending
from playcaller.streamlit_state.session import ensure_play_caller_session_defaults
from playcaller.streamlit_state.ui_write_guard import reset_ui_write_guard
from playcaller.streamlit_state.widget_backend_bridge import reconcile_widget_and_backend_state
from playcaller.ui.history_validation import render_history_validation_page
from playcaller.ui.product_copy import HISTORY_PAGE_TITLE

st.set_page_config(page_title=HISTORY_PAGE_TITLE, layout="wide", page_icon="\U0001f4ca")

# Live session: defaults + pending merges before any code touches widgets or the in-session Game.
# Match-tab uses ``build_game_context_from_session_state``, which syncs session-setup widgets
# onto ``st.session_state["game"]`` before reading it (see ``live_session_context.py``).
reset_ui_write_guard()
ensure_play_caller_session_defaults(st.session_state)
apply_all_pending(st.session_state)
reconcile_widget_and_backend_state(st.session_state)

render_history_validation_page()
