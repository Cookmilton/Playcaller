"""
Game review: post-game / post-drive analysis from saved JSON or current session.

Run the app from the repo root:
    streamlit run streamlit_app.py

**Session state:** shared with the main app. Entry uses the same live-session prep as
``streamlit_app.py`` (defaults + ``apply_all_pending``). **Current session** then syncs
session-setup widgets onto the in-session ``game`` before any review UI reads
``session_metadata``. **Upload JSON** loads a separate ``Game`` into a local variable only;
it does not call ``apply_session_setup_widgets_to_game`` so the in-session game is not
overwritten by sidebar widgets or review rendering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from playcaller.evaluation import evaluate_audit_records, summarize_audit_session
from playcaller.evaluation.snap_review_lifecycle import ensure_snap_review_list_on_game
from playcaller.game import Game, game_from_dict
from playcaller.streamlit_state.pending import apply_all_pending
from playcaller.streamlit_state.session import (
    coached_team_espn_id_for_previous_drives,
    ensure_play_caller_session_defaults,
)
from playcaller.streamlit_state.ui_write_guard import reset_ui_write_guard
from playcaller.streamlit_state.session_setup import apply_session_setup_widgets_to_game
from playcaller.streamlit_state.widget_backend_bridge import reconcile_widget_and_backend_state
from playcaller.review.archived_replay_juxtapose import build_ambient_context_for_model_replay
from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY, review_timeline_rows
from playcaller.review.unified_review import (
    ReviewMode,
    build_unified_rows_from_audit,
    build_unified_rows_from_replay,
    count_logged_plays,
    export_review_capability_bullets,
    resolve_review_mode,
)
from playcaller.session_game_metadata import (
    format_session_metadata_markdown,
    session_audit_identity_warning,
)
from playcaller.ui.product_copy import PAGE_TITLE_REVIEW, REVIEW_PAGE_TITLE, REVIEW_SECTION_SESSION_RECORD
from playcaller.ui.review_film_room import render_film_room, render_review_sidebar_controls

try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
except ImportError:  # pragma: no cover
    get_script_run_ctx = None  # type: ignore[misc, assignment]


def _review_session_should_execute() -> bool:
    if __name__ == "__main__":
        return True
    if get_script_run_ctx is not None and get_script_run_ctx() is not None:
        return True
    return False


def run_review_session_page() -> None:
    st.set_page_config(page_title=PAGE_TITLE_REVIEW, layout="wide")

    reset_ui_write_guard()
    ensure_play_caller_session_defaults(st.session_state)
    apply_all_pending(st.session_state)
    reconcile_widget_and_backend_state(st.session_state)

    st.title(REVIEW_PAGE_TITLE)
    st.caption(
        "**Film-room review:** compares **actual** plays to **model** recommendations. "
        "When **`snap_review_log`** exists, the model side is **Generate-time history**. "
        "Otherwise the page uses **replay review** (current engine vs actual) — never treated as historical truth."
    )

    st.markdown("### Review source")
    source = st.radio(
        "Load game from",
        ["Current session", "Upload game JSON"],
        horizontal=True,
        key="review_page_source",
        help="Session mode uses whatever is in memory on the main page. Upload uses an exported JSON file.",
    )

    game = None
    upload_payload: dict | None = None
    _review_upload_filename: str | None = None
    if source == "Current session":
        game = st.session_state.get("game")
        if game is None:
            st.warning("No session yet — open the main **Play Caller** console first, or switch to **Upload game JSON**.")
            st.stop()
        if isinstance(game, Game):
            ensure_snap_review_list_on_game(game)
            apply_session_setup_widgets_to_game(game, st.session_state)
    else:
        up = st.file_uploader("Game JSON", type=["json"], key="review_page_upload")
        if up is None:
            st.info(
                f"Upload a file from **Download game JSON** on the main page. "
                f"Exports list **`{SNAP_REVIEW_LOG_EXPORT_KEY}`** first when you used **Generate** during the session."
            )
            st.stop()
        try:
            payload = json.loads(up.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            st.error(f"**Invalid JSON** — the file could not be parsed as JSON: {e}")
            st.stop()
        if not isinstance(payload, dict):
            st.error("**Unsupported JSON** — the root value must be a JSON object (game export shape).")
            st.stop()
        try:
            game = game_from_dict(payload)
            ensure_snap_review_list_on_game(game)
            upload_payload = payload
            _review_upload_filename = str(getattr(up, "name", "") or "").strip() or None
        except Exception as e:
            st.error(f"**Could not load game** — JSON parsed, but this object is not a valid exported game: {e}")
            st.stop()

    assert game is not None
    raw_audit = list(game.recommendation_audit or [])
    timeline = review_timeline_rows(raw_audit)
    mode = resolve_review_mode(game, upload_payload=upload_payload, timeline=timeline)

    if mode == ReviewMode.NOT_REVIEWABLE:
        st.error("**Nothing to review** — this game has no logged plays and no snap review timeline.")
        st.stop()

    if source == "Upload game JSON":
        st.success("**Game JSON loaded successfully.**")
        if _review_upload_filename:
            st.caption(f"File: `{_review_upload_filename}`")

    st.markdown(f"### {REVIEW_SECTION_SESSION_RECORD}")
    st.markdown(format_session_metadata_markdown(game.session_metadata))
    for line in export_review_capability_bullets(game, mode=mode):
        st.caption(line)

    _id_warn = session_audit_identity_warning(game.session_metadata, raw_audit)
    if _id_warn:
        st.warning(_id_warn)

    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    if mode in (ReviewMode.TRUE_STORED, ReviewMode.LEGACY_STORED):
        unified_rows = build_unified_rows_from_audit(game, timeline, mode, our_coached_espn_id=our_id)
    else:
        predictor = st.session_state.get("predictor")
        ambient = build_ambient_context_for_model_replay(st.session_state, game)
        unified_rows = build_unified_rows_from_replay(
            game,
            st.session_state,
            predictor=predictor,
            ambient_ctx=ambient,
            our_coached_espn_id=our_id,
        )
        if predictor is None and count_logged_plays(game) > 0:
            st.warning(
                "**Predictor not loaded** — open the main **Play Caller** page once (defaults + engine), then return here for replay rows."
            )

    flt, show_conf, breakdown_expanded = render_review_sidebar_controls()
    render_film_room(
        game,
        unified_rows,
        mode=mode,
        flt=flt,
        show_conf=show_conf,
        breakdown_expanded=breakdown_expanded,
    )

    if timeline and mode in (ReviewMode.TRUE_STORED, ReviewMode.LEGACY_STORED):
        st.divider()
        with st.expander("Session evaluation (audit metrics)", expanded=False):
            ev = evaluate_audit_records(timeline)
            st.text(summarize_audit_session(timeline, session_metadata=game.session_metadata))
            st.json(ev)


if _review_session_should_execute():
    run_review_session_page()
