"""
Session-aware possession helpers on top of :mod:`playcaller.possession`.

The rules themselves (mapping, gating, flipping) live in ``playcaller/possession.py`` so
``playcaller/game.py`` can import them at module level. This module adds the two helpers
that need ``st.session_state`` and re-exports the rest for existing call sites.

``Game.possession`` is ``offense`` | ``defense`` | ``None``. A fresh / new-game board
starts unset. Sidebar possession is three chips (``Not set`` | ``Our team`` |
``Opponent``) that write ``ui_possession_side`` via ``apply_and_rerun``. That key
is not widget-bound (a radio here used to reset when another chip called
``st.rerun()`` mid-sidebar). Chip clicks now defer the rerun until every widget
has registered. ``Game.possession`` stays ``None`` while the chip shows ``Not set``.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from playcaller.possession import (
    END_DRIVE_UNSET_POSSESSION_REASON,
    GENERATE_OPPONENT_REASON,
    GENERATE_UNSET_POSSESSION_REASON,
    LOG_RESULT_UNSET_POSSESSION_REASON,
    POSSESSION_DEFENSE,
    POSSESSION_OFFENSE,
    POSSESSION_RADIO_OPTIONS,
    UI_POSSESSION_OPPONENT,
    UI_POSSESSION_OUR,
    UI_POSSESSION_UNSET,
    end_drive_blocked_reason,
    flipped_possession,
    generate_blocked_reason_for_possession,
    generate_skip_debug_reason,
    log_result_blocked_reason,
    possession_from_ui_label,
    possession_is_opponent,
    possession_is_unset,
    possession_side_radio_label,
)
from playcaller.streamlit_state.keys import LIVE_FEED_LAST_ORIGIN

ORIGIN_FEED = "feed"
ORIGIN_MANUAL = "manual"

__all__ = [
    "END_DRIVE_UNSET_POSSESSION_REASON",
    "GENERATE_OPPONENT_REASON",
    "GENERATE_UNSET_POSSESSION_REASON",
    "LOG_RESULT_UNSET_POSSESSION_REASON",
    "ORIGIN_FEED",
    "ORIGIN_MANUAL",
    "POSSESSION_DEFENSE",
    "POSSESSION_OFFENSE",
    "POSSESSION_RADIO_OPTIONS",
    "UI_POSSESSION_OPPONENT",
    "UI_POSSESSION_OUR",
    "UI_POSSESSION_UNSET",
    "apply_possession_from_ui",
    "end_drive_blocked_reason",
    "flipped_possession",
    "generate_blocked_reason_for_possession",
    "generate_skip_debug_reason",
    "log_result_blocked_reason",
    "mark_board_origin_manual",
    "possession_from_ui_label",
    "possession_is_opponent",
    "possession_is_unset",
    "possession_side_radio_label",
]


def apply_possession_from_ui(game: Any, ss: Mapping[str, Any]) -> None:
    """Copy the possession chip into ``game.possession`` (may be ``None``)."""
    game.possession = possession_from_ui_label(ss.get("ui_possession_side"))


def mark_board_origin_manual(session: MutableMapping[str, Any]) -> None:
    """Operator changed a board field — chip becomes Manual."""
    session[LIVE_FEED_LAST_ORIGIN] = ORIGIN_MANUAL
