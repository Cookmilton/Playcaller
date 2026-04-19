"""
Streamlit widget bridge for :class:`~playcaller.game.Game` session metadata.

Keeps sidebar / main console free of field-by-field duplication.

**Call order (main app):** after :func:`~playcaller.streamlit_state.pending.apply_all_pending`
and before any code reads ``game.session_metadata``, exports JSON, or mutates the game for
audit/sync. Use :func:`apply_session_setup_widgets_to_game` for that sync.

**Multipage:** ``streamlit_app.py`` does this once per run before the sidebar. Other entrypoints
should run :func:`~playcaller.streamlit_state.session.ensure_play_caller_session_defaults` then
``apply_all_pending`` before any live ``Game`` use. Push widgets onto ``game`` via
``apply_session_setup_widgets_to_game`` at the point of use (e.g. review **Current session**)
or inside a shared helper such as ``build_game_context_from_session_state`` (history **Match**).
Upload-only flows load ``game`` from a file and must **not** sync sidebar widgets onto
``st.session_state["game"]``.

**Load / new game:** :func:`hydrate_session_setup_widgets` overwrites widget keys from the
loaded or new ``Game`` (full replace). First visit only: :func:`ensure_session_setup_widget_defaults`
fills missing widget keys from ``game`` without clobbering existing session state.
"""

from __future__ import annotations

from typing import Any, MutableMapping

from playcaller.game import Game
from playcaller.session_game_metadata import SessionGameMetadata
from playcaller.streamlit_state.keys import (
    SESSION_SETUP_GAME_DATE,
    SESSION_SETUP_GAME_LABEL,
    SESSION_SETUP_IS_SIMULATED,
    SESSION_SETUP_NOTES,
    SESSION_SETUP_OPPONENT,
    SESSION_SETUP_ROSTER_VERSION,
    SESSION_SETUP_SEASON,
    SESSION_SETUP_TEAM_NAME,
)


def ensure_session_setup_widget_defaults(ss: MutableMapping[str, Any], game: Game) -> None:
    """Initialize widget keys once from ``game.session_metadata`` (missing keys only)."""
    meta = game.session_metadata if isinstance(game.session_metadata, dict) else {}
    m = SessionGameMetadata.from_storage_dict(meta)
    defaults: dict[str, Any] = {
        SESSION_SETUP_TEAM_NAME: m.team_name,
        SESSION_SETUP_OPPONENT: m.opponent,
        SESSION_SETUP_GAME_DATE: m.game_date,
        SESSION_SETUP_GAME_LABEL: m.game_label,
        SESSION_SETUP_SEASON: m.season,
        SESSION_SETUP_ROSTER_VERSION: m.roster_version,
        SESSION_SETUP_NOTES: m.notes,
        SESSION_SETUP_IS_SIMULATED: m.is_simulated,
    }
    for k, v in defaults.items():
        if k not in ss:
            ss[k] = v


def hydrate_session_setup_widgets(ss: MutableMapping[str, Any], game: Game) -> None:
    """Overwrite widgets from ``game`` (after **New game** or **Load game JSON**)."""
    meta = game.session_metadata if isinstance(game.session_metadata, dict) else {}
    m = SessionGameMetadata.from_storage_dict(meta)
    ss[SESSION_SETUP_TEAM_NAME] = m.team_name
    ss[SESSION_SETUP_OPPONENT] = m.opponent
    ss[SESSION_SETUP_GAME_DATE] = m.game_date
    ss[SESSION_SETUP_GAME_LABEL] = m.game_label
    ss[SESSION_SETUP_SEASON] = m.season
    ss[SESSION_SETUP_ROSTER_VERSION] = m.roster_version
    ss[SESSION_SETUP_NOTES] = m.notes
    ss[SESSION_SETUP_IS_SIMULATED] = m.is_simulated


def apply_session_setup_widgets_to_game(game: Game, ss: MutableMapping[str, Any]) -> None:
    """Persist widget values onto ``game.session_metadata`` (preserves ``session_game_id``).

    Idempotent for a fixed ``ss`` snapshot. Call once per run at the app entry (after pending
    merges) so sidebar export, ESPN sync, and downstream logic see the same identity as the
    main console.
    """
    prev = game.session_metadata if isinstance(game.session_metadata, dict) else {}
    base = SessionGameMetadata.from_storage_dict(prev)
    meta = SessionGameMetadata(
        session_game_id=base.session_game_id,
        team_name=str(ss.get(SESSION_SETUP_TEAM_NAME, "")),
        opponent=str(ss.get(SESSION_SETUP_OPPONENT, "")),
        game_date=str(ss.get(SESSION_SETUP_GAME_DATE, "")),
        game_label=str(ss.get(SESSION_SETUP_GAME_LABEL, "")),
        season=str(ss.get(SESSION_SETUP_SEASON, "")),
        roster_version=str(ss.get(SESSION_SETUP_ROSTER_VERSION, "")),
        notes=str(ss.get(SESSION_SETUP_NOTES, "")),
        is_simulated=bool(ss.get(SESSION_SETUP_IS_SIMULATED, False)),
    )
    game.session_metadata = meta.to_storage_dict()
