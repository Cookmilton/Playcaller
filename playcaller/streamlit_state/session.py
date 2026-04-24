"""
Session defaults and live-feed session cleanup for the Streamlit app.
"""

from __future__ import annotations

from typing import Any, MutableMapping

from playcaller.engine import FootballPlayPredictor
from playcaller.game_situation_input import max_seconds_in_period
from playcaller.evaluation.calibration import load_calibration_profile
from playcaller.game import Game
from playcaller.live_data.drive_display import PREVIOUS_DRIVES_FILTER_OUR
from playcaller.heuristic_predictor import HeuristicPredictor
from playcaller.history.repository_settings import (
    build_historical_influence_config,
    load_history_repository_settings,
)
from playcaller.state import DriveLogger
from playcaller.streamlit_state.session_setup import ensure_session_setup_widget_defaults
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    HV_CORPUS_SOURCE,
    HV_REPO_USE_ALL_GAMES,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_LAST_ERROR,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_POSSESSION_TEAM_ID,
    LIVE_FEED_HTTP_INSECURE_WARNING,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_FEED_TRUSTED_CLOCK,
    LIVE_FEED_MANUAL_AUTO_FETCH,
    LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR,
    LIVE_FEED_MANUAL_EVENT_FETCH_ERROR,
    LIVE_FEED_MANUAL_EVENT_FOR_ID,
    LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID,
    LIVE_FEED_MANUAL_EVENT_TEAMS,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_SCOREBOARD_ROWS,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
    UI_HISTORICAL_NUDGE_ENABLED,
    UI_WAREHOUSE_ADVISORY_ENABLED,
    UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES,
    UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS,
    UI_PREVIOUS_DRIVES_FILTER,
)


def possession_side_radio_label(*, possession: str) -> str:
    """Sidebar radio label for who has the ball (``Game.possession`` is ``offense`` | ``defense``)."""
    return "Our team" if possession == "offense" else "Opponent"


def migrate_legacy_situation_widgets(ss: MutableMapping[str, Any]) -> None:
    """
    One-time migration from pre–quarter-clock widgets (``ui_clock_mins`` up to 60)
    to ``ui_game_period`` + ``ui_quarter_clock_*`` (time left in period).
    """
    if "ui_game_period" not in ss and "ui_quarter" in ss:
        try:
            q = int(ss["ui_quarter"])
        except (TypeError, ValueError):
            q = 1
        ss["ui_game_period"] = max(1, min(5, q))

    if "ui_quarter_clock_mins" not in ss and "ui_clock_mins" in ss:
        try:
            period = int(ss.get("ui_game_period", 1))
            raw = int(ss["ui_clock_mins"]) * 60 + int(ss.get("ui_clock_secs", 0))
            cap = max_seconds_in_period(period)
            raw = min(raw, cap)
            ss["ui_quarter_clock_mins"] = raw // 60
            ss["ui_quarter_clock_secs"] = raw % 60
        except (TypeError, ValueError):
            ss["ui_quarter_clock_mins"] = 15
            ss["ui_quarter_clock_secs"] = 0

    if "ui_score_ours" not in ss:
        try:
            g = ss.get("game")
            ss["ui_score_ours"] = int(getattr(g, "offense_points", 0)) if g is not None else 0
        except (TypeError, ValueError):
            ss["ui_score_ours"] = 0
    if "ui_score_theirs" not in ss:
        try:
            g = ss.get("game")
            ss["ui_score_theirs"] = int(getattr(g, "defense_points", 0)) if g is not None else 0
        except (TypeError, ValueError):
            ss["ui_score_theirs"] = 0


def ensure_play_caller_session_defaults(ss: MutableMapping[str, Any]) -> None:
    """One-time defaults for predictor, game, drive log, and all ui_* widget keys."""
    hist_settings = load_history_repository_settings()
    hi_cfg = build_historical_influence_config(hist_settings)

    # (Re)create when missing, None, or corrupted — e.g. Review Session replay after a partial session clear.
    p = ss.get("predictor")
    if not isinstance(p, FootballPlayPredictor):
        ss["predictor"] = FootballPlayPredictor(
            calibration=load_calibration_profile(),
            historical_influence=hi_cfg,
        )
    else:
        impl = getattr(p, "_impl", None)
        if isinstance(impl, HeuristicPredictor):
            impl.historical_influence = hi_cfg
    if "drive_log" not in ss:
        ss["drive_log"] = DriveLogger()
    if "game" not in ss:
        ss["game"] = Game.new_game()
    if "result" not in ss:
        ss["result"] = None

    _g = ss.get("game")
    if isinstance(_g, Game) and _g.session_metadata is None:
        from playcaller.session_game_metadata import fresh_session_metadata_dict

        _g.session_metadata = fresh_session_metadata_dict()
    if isinstance(_g, Game):
        ensure_session_setup_widget_defaults(ss, _g)

    migrate_legacy_situation_widgets(ss)
    for k, v in new_game_ui_values().items():
        if k not in ss:
            ss[k] = v
    if "last_play_summary" not in ss:
        ss["last_play_summary"] = ""
    if "ui_debug_game_context" not in ss:
        ss["ui_debug_game_context"] = False
    if "sidebar_custom_snap_presets_v1" not in ss:
        ss["sidebar_custom_snap_presets_v1"] = []
    if UI_HISTORICAL_NUDGE_ENABLED not in ss:
        ss[UI_HISTORICAL_NUDGE_ENABLED] = bool(hist_settings.nudge_default_on)
    if UI_WAREHOUSE_ADVISORY_ENABLED not in ss:
        ss[UI_WAREHOUSE_ADVISORY_ENABLED] = False
    if HV_CORPUS_SOURCE not in ss:
        ss[HV_CORPUS_SOURCE] = "folder_session"
    if HV_REPO_USE_ALL_GAMES not in ss:
        ss[HV_REPO_USE_ALL_GAMES] = True
    if "hv_history_dir" not in ss and hist_settings.default_directory:
        ss["hv_history_dir"] = hist_settings.default_directory
    if "hv_history_dir_session" not in ss and ss.get("hv_history_dir"):
        ss["hv_history_dir_session"] = ss["hv_history_dir"]
    if "ui_live_espn_sport" not in ss:
        ss["ui_live_espn_sport"] = "nfl"
    if "ui_live_lock_situation" not in ss:
        ss["ui_live_lock_situation"] = False
    if "ui_live_lock_score" not in ss:
        ss["ui_live_lock_score"] = False
    if "ui_live_auto_plays" not in ss:
        ss["ui_live_auto_plays"] = False
    if UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES not in ss:
        ss[UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES] = True
    if UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS not in ss:
        ss[UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS] = True
    if LIVE_FEED_SCOREBOARD_ROWS not in ss:
        ss[LIVE_FEED_SCOREBOARD_ROWS] = []
    if "ui_live_event_id_manual" not in ss:
        ss["ui_live_event_id_manual"] = ""
    if "ui_live_our_team_manual" not in ss:
        ss["ui_live_our_team_manual"] = ""
    if "ui_live_our_team_advanced" not in ss:
        ss["ui_live_our_team_advanced"] = ""
    if LIVE_FEED_MANUAL_EVENT_TEAMS not in ss:
        ss[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
    if LIVE_FEED_MANUAL_EVENT_FOR_ID not in ss:
        ss[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
    if LIVE_FEED_MANUAL_EVENT_FETCH_ERROR not in ss:
        ss[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = None
    if LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID not in ss:
        ss[LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID] = ""
    if LIVE_FEED_MANUAL_AUTO_FETCH not in ss:
        ss[LIVE_FEED_MANUAL_AUTO_FETCH] = False
    if LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR not in ss:
        ss[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = ""
    if "ui_live_home_or_away" not in ss:
        ss["ui_live_home_or_away"] = "away"
    if LIVE_FEED_LAST_ORIGIN not in ss:
        ss[LIVE_FEED_LAST_ORIGIN] = "manual"
    if "eval_drive_epoch" not in ss:
        ss["eval_drive_epoch"] = 0
    if UI_PREVIOUS_DRIVES_FILTER not in ss:
        ss[UI_PREVIOUS_DRIVES_FILTER] = "our"
    if LIVE_FEED_TEAM_SCOPE not in ss:
        ss[LIVE_FEED_TEAM_SCOPE] = str(ss.get(UI_PREVIOUS_DRIVES_FILTER) or PREVIOUS_DRIVES_FILTER_OUR)


def coached_team_espn_id_for_previous_drives(ss: MutableMapping[str, Any]) -> str:
    """
    **Our team** ESPN id for Previous drives filtering: session persistence first, then last-sync audit.

    Survives ``clear_live_feed_session_keys`` when the persistent key was set by a prior sync.
    """
    tid = str(ss.get(LIVE_FEED_COACHED_TEAM_ESPN_ID) or "").strip()
    if tid:
        return tid
    aud = ss.get(LIVE_FEED_LAST_AUDIT) or {}
    return str(aud.get("coached_team_id") or "").strip()


def clear_coached_team_espn_session_identity(ss: MutableMapping[str, Any]) -> None:
    """Drop persisted coached ESPN id (``New game``, loaded JSON, or explicit matchup reset)."""
    ss.pop(LIVE_FEED_COACHED_TEAM_ESPN_ID, None)


def clear_live_feed_session_keys(ss: MutableMapping[str, Any]) -> None:
    ss.pop(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS, None)
    ss.pop(LIVE_FEED_SEEN_PLAY_IDS, None)
    ss.pop(LIVE_FEED_LAST_POSSESSION_TEAM_ID, None)
    ss.pop(LIVE_FEED_LAST_AUDIT, None)
    ss.pop(LIVE_FEED_LAST_ERROR, None)
    ss.pop(LIVE_FEED_LAST_SYNC_EPOCH, None)
    ss.pop(LIVE_FEED_TRUSTED_CLOCK, None)
    ss.pop(LIVE_FEED_HTTP_INSECURE_WARNING, None)
    ss[LIVE_FEED_MANUAL_EVENT_TEAMS] = None
    ss[LIVE_FEED_MANUAL_EVENT_FOR_ID] = ""
    ss[LIVE_FEED_MANUAL_EVENT_FETCH_ERROR] = None
    ss[LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID] = ""
    ss[LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR] = ""
    ss[LIVE_FEED_LAST_ORIGIN] = "manual"
