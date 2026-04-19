"""Build ``GameContext`` from Streamlit session state (same fields as the main Play Caller page)."""

from __future__ import annotations

from typing import Any, MutableMapping

from playcaller import Game, GameContext, DriveLogger
from playcaller.game_situation_input import score_diff_from_board
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_OPP_TOS,
    GAME_OWN_TOS,
    GAME_PERIOD,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    GAME_TERRITORY,
    GAME_YARDLINE,
)
from playcaller.streamlit_state.session_setup import apply_session_setup_widgets_to_game
from playcaller.streamlit_state.widget_backend_bridge import refresh_derived_game_context_cache


def build_game_context_from_session_state(ss: MutableMapping[str, Any]) -> GameContext:
    """Mirror ``streamlit_app.py`` pre-snap context wiring (no sidebar, no recommendation calls).

    **Call order:** the page or script entry must run
    :func:`~playcaller.streamlit_state.session.ensure_play_caller_session_defaults` and
    :func:`~playcaller.streamlit_state.pending.apply_all_pending` before this runs, so widget
    keys and pending merges are current. This function then calls
    :func:`~playcaller.streamlit_state.session_setup.apply_session_setup_widgets_to_game`
    before reading or mutating ``ss[\"game\"]``, so ``session_metadata`` matches session-setup
    widgets (same guarantee as ``streamlit_app.py`` before sidebar export / audit).
    """
    drive_log: DriveLogger = ss["drive_log"]
    game: Game = ss["game"]
    apply_session_setup_widgets_to_game(game, ss)
    game.possession = (
        "offense" if str(ss.get("ui_possession_side", "Our team")) == "Our team" else "defense"
    )

    down = int(ss.get(GAME_DOWN, ss["ui_down"]))
    distance = int(ss.get(GAME_DISTANCE, ss["ui_distance"]))
    territory = str(ss.get(GAME_TERRITORY, ss["ui_territory"]))
    yardline = int(ss.get(GAME_YARDLINE, ss["ui_yardline"]))
    def_personnel = str(ss["ui_def_personnel"])
    box_count = int(ss["ui_box_count"])
    coverage_shell = str(ss["ui_coverage_shell"])
    safeties = str(ss["ui_safeties"])
    blitz_likely = bool(ss["ui_blitz_likely"])
    refresh_derived_game_context_cache(ss)
    quarter = int(ss.get(GAME_CONTEXT_QUARTER, 1))
    seconds_remaining = int(ss.get(GAME_CLOCK_TOTAL_SECONDS, 0))
    game.offense_points = int(ss.get(GAME_SCORE_OURS, ss.get("ui_score_ours", 0)))
    game.defense_points = int(ss.get(GAME_SCORE_THEIRS, ss.get("ui_score_theirs", 0)))
    score_diff = score_diff_from_board(our_score=game.offense_points, their_score=game.defense_points)
    game.quarter = quarter
    game.clock_seconds_remaining = seconds_remaining
    own_timeouts = int(ss.get(GAME_OWN_TOS, ss["ui_own_tos"]))
    opp_timeouts = int(ss.get(GAME_OPP_TOS, ss["ui_opp_tos"]))
    weather = str(ss["ui_weather"])
    wind_mph = int(ss["ui_wind_mph"]) if weather == "wind" else 0
    qb_limited = bool(ss["ui_qb_limited"])
    game_mode = str(ss["ui_game_mode"])
    mismatch = str(ss["ui_mismatch"])

    return GameContext(
        down=down,
        distance=distance,
        yardline=yardline,
        territory=territory,
        def_personnel=def_personnel,
        box_count=box_count,
        coverage_shell=coverage_shell,
        blitz_likely=blitz_likely,
        safeties=safeties,
        score_diff=score_diff,
        quarter=int(quarter),
        seconds_remaining=seconds_remaining,
        own_timeouts=own_timeouts,
        opp_timeouts=opp_timeouts,
        weather=weather,
        wind_mph=wind_mph,
        qb_limited=qb_limited,
        mismatch=mismatch or None,
        game_mode=game_mode,
        plays_this_drive=len(drive_log.results),
        shown_concepts=list(drive_log.family_counts.keys()),
        run_plays_this_drive=drive_log.run_count(),
    )
