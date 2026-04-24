"""
Warehouse inventory: games loaded in the football history DB (read-only).

Run from repo root: ``streamlit run streamlit_app.py`` → open **Warehouse** in the page menu.
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
from playcaller.ui.product_copy import PAGE_TITLE_WAREHOUSE
from playcaller.ui.warehouse_review import render_warehouse_inventory_page

st.set_page_config(page_title=PAGE_TITLE_WAREHOUSE, layout="wide", page_icon="\U0001f3ed")

reset_ui_write_guard()
ensure_play_caller_session_defaults(st.session_state)
apply_all_pending(st.session_state)
reconcile_widget_and_backend_state(st.session_state)

render_warehouse_inventory_page()
