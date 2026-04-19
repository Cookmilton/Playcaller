"""
Canonical ``st.session_state`` key strings for the Streamlit app.

Widget ``key=`` values must stay identical to these constants so Streamlit binding
and saved sessions remain stable.
"""

from __future__ import annotations

# --- Session game setup (operator metadata → ``Game.session_metadata``) ---
SESSION_SETUP_TEAM_NAME = "session_setup_team_name"
SESSION_SETUP_OPPONENT = "session_setup_opponent"
SESSION_SETUP_GAME_DATE = "session_setup_game_date"
SESSION_SETUP_GAME_LABEL = "session_setup_game_label"
SESSION_SETUP_SEASON = "session_setup_season"
SESSION_SETUP_ROSTER_VERSION = "session_setup_roster_version"
SESSION_SETUP_NOTES = "session_setup_notes"
SESSION_SETUP_IS_SIMULATED = "session_setup_is_simulated"

# --- Main console (view-only toggles; not mirrored to ``game_*``) ---
UI_PREVIOUS_DRIVES_FILTER = "ui_previous_drives_filter"

# --- Pending buffers (apply before widgets render; see ``streamlit_state.pending``) ---
PENDING_LOG_SITUATION = "pending_log_situation"
PENDING_END_DRIVE_UI = "pending_end_drive_ui"
PENDING_NEW_GAME_UI = "pending_new_game_ui"

# --- Snap / undo (not pending dicts; cleared with in-progress log helpers) ---
LAST_DRIVE_SNAP_CONTEXT = "last_drive_snap_context"
UNDO_BUNDLE = "undo_pre_snap_bundle"

# --- Backend game board state (ESPN / load JSON); mirrored to ``ui_*`` before widgets ---
GAME_SCORE_OURS = "game_score_ours"
GAME_SCORE_THEIRS = "game_score_theirs"
GAME_PERIOD = "game_period"
GAME_QUARTER_CLOCK_MINS = "game_quarter_clock_mins"
GAME_QUARTER_CLOCK_SECS = "game_quarter_clock_secs"
GAME_DOWN = "game_down"
GAME_DISTANCE = "game_distance"
GAME_TERRITORY = "game_territory"
GAME_YARDLINE = "game_yardline"
GAME_OWN_TOS = "game_own_tos"
GAME_OPP_TOS = "game_opp_tos"
# Same labels as ``ui_possession_side`` ("Our team" | "Opponent").
GAME_POSSESSION_SIDE = "game_possession_side"
# Set when backend updates require copying ``game_*`` → ``ui_*`` on the *next* run (before widgets).
GAME_WIDGET_HYDRATE_PENDING = "game_widget_hydrate_pending"

# Derived from ``GAME_PERIOD`` + quarter-clock keys (not widget-bound; safe to update after widgets).
GAME_CONTEXT_QUARTER = "game_context_quarter"
GAME_CLOCK_TOTAL_SECONDS = "game_clock_total_seconds"

# --- Live ESPN feed (session-backed; not all are widgets) ---
LIVE_FEED_SCOREBOARD_ROWS = "live_feed_scoreboard_rows"
# Stable keys for ESPN ``drives.previous`` rows already merged into ``game.drives`` (dedup on re-sync).
LIVE_FEED_MERGED_ESPN_DRIVE_KEYS = "live_feed_merged_espn_drive_keys"
LIVE_FEED_SEEN_PLAY_IDS = "live_feed_seen_play_ids"
LIVE_FEED_LAST_POSSESSION_TEAM_ID = "live_feed_last_possession_team_id"
# Persists the operator's **Our team** ESPN id for the current session/game; survives ``clear_live_feed_session_keys``.
LIVE_FEED_COACHED_TEAM_ESPN_ID = "live_feed_coached_team_espn_id"
# Which ESPN feed possessions enter the session: ``our`` | ``opponent`` | ``both`` (see ``drive_display`` constants).
LIVE_FEED_TEAM_SCOPE = "live_feed_team_scope"
LIVE_FEED_LAST_AUDIT = "live_feed_last_audit"
LIVE_FEED_LAST_ERROR = "live_feed_last_error"
LIVE_FEED_LAST_SYNC_EPOCH = "live_feed_last_sync_epoch"
LIVE_FEED_LAST_ORIGIN = "live_feed_last_origin"
# Set True when ESPN HTTP used verify=False (env force or automatic local fallback).
LIVE_FEED_HTTP_INSECURE_WARNING = "live_feed_http_insecure_warning"
LIVE_FEED_MANUAL_NOTE = "live_feed_manual_note"
# Manual Event ID path: cached summary lookup (home/away ids + labels).
LIVE_FEED_MANUAL_EVENT_TEAMS = "live_feed_manual_event_teams"
LIVE_FEED_MANUAL_EVENT_FOR_ID = "live_feed_manual_event_for_id"
LIVE_FEED_MANUAL_EVENT_FETCH_ERROR = "live_feed_manual_event_fetch_error"
# Last Event ID we attempted to load (manual path); clears typed errors when the box changes.
LIVE_FEED_MANUAL_EVENT_LAST_ATTEMPT_ID = "live_feed_manual_event_last_attempt_id"
# Manual path: optional auto-fetch when Event ID looks complete (9+ digits).
LIVE_FEED_MANUAL_AUTO_FETCH = "live_feed_manual_auto_fetch"
# Cursor for auto-fetch: avoids retry loops after a failed automatic fetch.
LIVE_FEED_MANUAL_AUTO_FETCH_CURSOR = "live_feed_manual_auto_fetch_cursor"

# Game library page stores folder-loaded corpus here; optional nudge also reads repository plays.
HV_SESSION_CORPUS_KEY = "hv_validation_corpus"
HV_SESSION_CORPUS_PATH_KEY = "hv_validation_corpus_path"
# ``folder_session`` = load directory into session (legacy). ``repository`` = persistent store.
HV_CORPUS_SOURCE = "hv_corpus_source"
HV_REPO_USE_ALL_GAMES = "hv_repo_use_all_games"
HV_REPO_SELECTED_GAME_IDS = "hv_repo_selected_game_ids"
UI_HISTORICAL_NUDGE_ENABLED = "ui_historical_nudge_enabled"

# Retroactive archived-drive replay: map cache key → list of ``ActualVsReplayComparisonRow``.
# FIFO-capped in ``cached_comparison_rows_for_archived_drive`` (long Streamlit sessions).
ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE = "_archived_drive_comparison_rows_v1"

# ESPN sync: merge feed into ``Game`` / ``DriveLogger`` (sidebar toggles; default on).
UI_LIVE_IMPORT_COMPLETED_FEED_DRIVES = "ui_live_import_completed_feed_drives"
UI_LIVE_IMPORT_CURRENT_FEED_DRIVE_PLAYS = "ui_live_import_current_feed_drive_plays"
