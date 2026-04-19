"""
Fresh-game widget defaults (single source of truth for ``new_game_ui_values``).

Lives outside :mod:`playcaller.streamlit_state.session` so modules imported early from
``live_data.sync`` (e.g. :mod:`playcaller.streamlit_state.widget_backend_bridge`) can
use the same defaults without importing ``session`` while it is still loading.
"""

from __future__ import annotations

from typing import Any

from playcaller.game import DRIVE_END_UI_AUTO
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    LIVE_FEED_TEAM_SCOPE,
    UI_PREVIOUS_DRIVES_FILTER,
)


def new_game_ui_values() -> dict[str, Any]:
    """Widget/session values after ``Game.new_game()`` + fresh drive log (single source of truth)."""
    return {
        "ui_down": 1,
        "ui_distance": 10,
        "ui_territory": "own",
        "ui_yardline": 25,
        "ui_def_personnel": "nickel",
        "ui_box_count": 7,
        "ui_coverage_shell": "cover_3",
        "ui_safeties": "single_high",
        "ui_blitz_likely": False,
        # Football-native: period 1–4 + OT (5); time remaining **in this quarter**
        "ui_game_period": 1,
        "ui_quarter_clock_mins": 15,
        "ui_quarter_clock_secs": 0,
        "ui_score_ours": 0,
        "ui_score_theirs": 0,
        GAME_CONTEXT_QUARTER: 1,
        GAME_CLOCK_TOTAL_SECONDS: 15 * 60,
        "ui_own_tos": 3,
        "ui_opp_tos": 3,
        "ui_weather": "clear",
        "ui_wind_mph": 0,
        "ui_qb_limited": False,
        "ui_game_mode": "normal",
        "ui_mismatch": "",
        "ui_auto_generate": False,
        "ui_drive_end_on_new": DRIVE_END_UI_AUTO,
        "ui_possession_side": "Our team",
        UI_PREVIOUS_DRIVES_FILTER: "our",
        LIVE_FEED_TEAM_SCOPE: "our",
    }
