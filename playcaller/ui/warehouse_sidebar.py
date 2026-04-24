"""Sidebar: warehouse DB connection pill (Game Setup) and advanced controls (Review)."""

from __future__ import annotations

import html

import streamlit as st

from playcaller.game import Game
from playcaller.history.repository_manifest import list_game_records
from playcaller.history.repository_paths import resolve_history_repository_root
from playcaller.history.repository_settings import load_history_repository_settings
from playcaller.streamlit_state.keys import (
    LIVE_FEED_MANUAL_EVENT_FOR_ID,
    UI_WAREHOUSE_ADVISORY_ENABLED,
    UI_WAREHOUSE_LAST_GENERATE_STATUS,
    HV_CORPUS_SOURCE,
    HV_SESSION_CORPUS_KEY,
    HV_SESSION_CORPUS_PATH_KEY,
    UI_HISTORICAL_NUDGE_ENABLED,
)
from playcaller.streamlit_state.ui_write_guard import register_ui_widget_key_bound
from playcaller.ui.product_copy import WAREHOUSE_ADVISORY_SIDEBAR_CAPTION
from playcaller.ui.warehouse_page_state import detect_warehouse_inventory_state, format_warehouse_sidebar_pill_html
from playcaller.warehouse.binding import build_warehouse_binding


def _bind_ui(k: str) -> None:
    register_ui_widget_key_bound(k)


def render_warehouse_connection_pill() -> None:
    """Warehouse DB readiness (same five states as the Warehouse inventory page)."""
    ctx = detect_warehouse_inventory_state()
    try:
        st.markdown(format_warehouse_sidebar_pill_html(ctx), unsafe_allow_html=True)
    finally:
        if ctx.client is not None:
            ctx.client.dispose()


def render_warehouse_advanced_panel(*, game: Game) -> None:
    """Warehouse advisory, scope, corpus nudge — lives under Review → Advanced."""
    st.caption(WAREHOUSE_ADVISORY_SIDEBAR_CAPTION)
    st.toggle(
        "Show warehouse context on Generate (read-only)",
        key=UI_WAREHOUSE_ADVISORY_ENABLED,
        help="Adds reference counts and samples from the warehouse; does not alter ranked scores.",
    )
    _bind_ui(UI_WAREHOUSE_ADVISORY_ENABLED)

    meta = game.session_metadata if isinstance(getattr(game, "session_metadata", None), dict) else {}
    live_eid = str(st.session_state.get(LIVE_FEED_MANUAL_EVENT_FOR_ID) or "").strip() or None
    binding = build_warehouse_binding(meta, live_event_id=live_eid)

    lines: list[str] = []
    if binding.league_id:
        lines.append(f"League **{html.escape(binding.league_id)}**")
    if binding.season_id:
        lines.append(f"Season **{html.escape(binding.season_id)}**")
    if binding.game_id:
        lines.append(f"Game **{html.escape(binding.game_id)}**")
    if binding.coached_team_id:
        lines.append(f"Our team id **{html.escape(binding.coached_team_id)}**")
    if binding.opponent_team_id:
        lines.append(f"Opponent id **{html.escape(binding.opponent_team_id)}**")

    if lines:
        st.markdown(
            "<div style='font-size:12px;line-height:1.4'>Scope: " + " · ".join(lines) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("Scope: _not set_ — add `warehouse_*` fields to session metadata, env vars, or an ESPN Event ID.")

    if binding.has_query_scope():
        st.caption("**Binding:** scope looks usable for warehouse queries.")
    else:
        st.caption("**Binding:** incomplete — advisory may show “no scope” until league/season/game ids are set.")

    last = st.session_state.get(UI_WAREHOUSE_LAST_GENERATE_STATUS)
    if isinstance(last, dict) and last.get("sought"):
        en = last.get("advisory_enabled")
        if en is True:
            st.caption(f"**Last Generate:** warehouse advisory **on** ({last.get('detail', 'ok')}).")
        elif en is False:
            st.caption(f"**Last Generate:** advisory **disabled** in payload — {last.get('detail', 'see panel')}.")
        else:
            st.caption("**Last Generate:** advisory requested; check recommendation panel for details.")

    switch = getattr(st, "switch_page", None)
    if callable(switch):
        if st.button("Open warehouse inventory…", use_container_width=True, key="sidebar_btn_wh_inventory"):
            st.switch_page("pages/Warehouse.py")
    else:
        st.caption("Use the **Warehouse** page in the Streamlit pages menu to browse loaded games.")

    st.markdown("##### Corpus nudge")
    st.caption(
        "Configure corpus on **Game library** (import to the repository or load a folder into this session). "
        "Applies a **small** run/pass lane adjustment after the base heuristic — not a replacement model."
    )
    _repo = load_history_repository_settings()
    if _repo.history_force_off:
        st.warning("Historical influence is **disabled** for this deployment (`PLAYCALLER_HISTORY_FORCE_OFF`).")
    st.toggle(
        "Apply historical nudge on Generate",
        key=UI_HISTORICAL_NUDGE_ENABLED,
        help="Uses plays from the corpus selected on Game library (**Corpus source**: folder session vs repository).",
        disabled=bool(_repo.history_force_off),
    )
    _pred = st.session_state.get("predictor")
    _hi = getattr(_pred, "historical_influence", None) if _pred is not None else None
    if _hi is not None:
        st.caption(
            f"Influence gates: **min overall n ≥ {_hi.min_overall_matches}** · "
            f"query min matches **{_hi.query_min_matches}** (env or defaults)."
        )
    _src = str(st.session_state.get(HV_CORPUS_SOURCE) or "folder_session")
    _corp = st.session_state.get(HV_SESSION_CORPUS_KEY)
    _loaded = st.session_state.get(HV_SESSION_CORPUS_PATH_KEY)
    if _src == "repository":
        _root = resolve_history_repository_root(_repo)
        _idx = list_game_records(_root)
        st.caption(
            f"Corpus source: **repository** · `{_root}` · **{len(_idx)}** indexed games"
        )
    elif _corp is not None and getattr(_corp, "plays", None):
        st.caption(
            f"Corpus source: **folder (session)** · **{len(_corp.games)}** games · **{len(_corp.plays)}** plays"
            + (f" · from `{_loaded}`" if _loaded else "")
        )
    else:
        st.caption(
            "No **folder** corpus in memory — open **Game library**, load a directory, "
            "or switch **Corpus source** to **Repository** after importing JSON."
        )
    if _repo.default_directory and _src != "repository" and not _loaded:
        st.caption(f"Default folder from env: `{_repo.default_directory}` (pre-fills Game library).")


# Backward-compatible name for imports (thin wrapper).
def render_sidebar_warehouse_section(*, game: Game) -> None:
    render_warehouse_connection_pill()
