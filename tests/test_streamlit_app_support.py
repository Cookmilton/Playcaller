"""Session-state helpers for the Streamlit app (no Streamlit runtime)."""

from playcaller.streamlit_app_support import (
    PENDING_END_DRIVE_UI,
    PENDING_LOG_SITUATION,
    PENDING_NEW_GAME_UI,
    apply_pending_end_drive_ui,
    apply_pending_log_situation,
    apply_pending_new_game_ui,
    new_game_ui_values,
    possession_side_radio_label,
)


def test_new_game_ui_values_is_complete_snapshot():
    d = new_game_ui_values()
    assert d["ui_down"] == 1
    assert d["ui_possession_side"] == "Not set"
    assert "ui_quarter_clock_mins" in d and "ui_game_period" in d
    assert "ui_score_ours" in d and "ui_mismatch" in d


def test_apply_pending_new_game_ui():
    ss: dict = {"ui_down": 4, "ui_distance": 99}
    ss[PENDING_NEW_GAME_UI] = new_game_ui_values()
    apply_pending_new_game_ui(ss)
    assert ss["ui_down"] == 1
    assert ss["ui_distance"] == 10
    assert PENDING_NEW_GAME_UI not in ss


def test_apply_order_end_drive_then_new_game_uses_new_game_for_overlap():
    ss: dict = {
        "ui_quarter_clock_mins": 0,
        "ui_quarter_clock_secs": 0,
        "ui_possession_side": "Opponent",
    }
    ss[PENDING_END_DRIVE_UI] = {
        "ui_quarter_clock_mins": 5,
        "ui_quarter_clock_secs": 30,
        "ui_possession_side": "Our team",
    }
    ss[PENDING_NEW_GAME_UI] = new_game_ui_values()
    apply_pending_end_drive_ui(ss)
    apply_pending_new_game_ui(ss)
    assert ss["ui_quarter_clock_mins"] == 15
    assert ss["ui_quarter_clock_secs"] == 0
    assert ss["ui_possession_side"] == "Not set"


def test_possession_side_radio_label():
    assert possession_side_radio_label(possession="offense") == "Our team"
    assert possession_side_radio_label(possession="defense") == "Opponent"
    assert possession_side_radio_label(possession=None) == "Not set"


def test_apply_pending_log_situation_undo_shape():
    ss: dict = {}
    ss[PENDING_LOG_SITUATION] = {
        "territory": "opponents",
        "yardline": 40,
        "down": 2,
        "distance": 7,
    }
    apply_pending_log_situation(ss)
    assert ss["ui_territory"] == "opponents"
    assert ss["ui_yardline"] == 40
    assert ss["ui_down"] == 2
    assert ss["ui_distance"] == 7


def test_apply_all_pending_matches_sequential_apply():
    """``apply_all_pending`` must mirror log → end-drive → new-game order."""
    from playcaller.streamlit_state.pending import apply_all_pending

    ss: dict = {
        "ui_quarter_clock_mins": 0,
        "ui_quarter_clock_secs": 0,
        "ui_possession_side": "Opponent",
    }
    ss[PENDING_END_DRIVE_UI] = {
        "ui_quarter_clock_mins": 5,
        "ui_quarter_clock_secs": 30,
        "ui_possession_side": "Our team",
    }
    ss[PENDING_NEW_GAME_UI] = new_game_ui_values()
    apply_all_pending(ss)
    assert ss["ui_quarter_clock_mins"] == 15
    assert ss["ui_quarter_clock_secs"] == 0
    assert ss["ui_possession_side"] == "Not set"


def test_apply_pending_session_setup_hydrate_clears_team_name():
    from playcaller.game import Game
    from playcaller.streamlit_state.keys import PENDING_SESSION_SETUP_HYDRATE, SESSION_SETUP_TEAM_NAME
    from playcaller.streamlit_state.pending import apply_all_pending

    ss: dict = {
        "game": Game.new_game(),
        SESSION_SETUP_TEAM_NAME: "Keepers",
        PENDING_SESSION_SETUP_HYDRATE: True,
    }
    apply_all_pending(ss)
    assert ss[SESSION_SETUP_TEAM_NAME] == ""
    assert PENDING_SESSION_SETUP_HYDRATE not in ss


def test_pending_session_game_date_fills_empty_widget_only():
    from playcaller.streamlit_state.keys import PENDING_SESSION_GAME_DATE, SESSION_SETUP_GAME_DATE
    from playcaller.streamlit_state.pending import apply_all_pending

    ss: dict = {SESSION_SETUP_GAME_DATE: "", PENDING_SESSION_GAME_DATE: "2026-09-11"}
    apply_all_pending(ss)
    assert ss[SESSION_SETUP_GAME_DATE] == "2026-09-11"
    assert PENDING_SESSION_GAME_DATE not in ss

    ss2: dict = {SESSION_SETUP_GAME_DATE: "2018-01-01", PENDING_SESSION_GAME_DATE: "2026-09-11"}
    apply_all_pending(ss2)
    assert ss2[SESSION_SETUP_GAME_DATE] == "2018-01-01"


def test_pending_session_game_date_replace_overwrites_espn_owned_widget():
    from playcaller.streamlit_state.keys import (
        PENDING_SESSION_GAME_DATE,
        PENDING_SESSION_GAME_DATE_REPLACE,
        SESSION_SETUP_GAME_DATE,
    )
    from playcaller.streamlit_state.pending import apply_all_pending

    ss: dict = {
        SESSION_SETUP_GAME_DATE: "2026-09-11",
        PENDING_SESSION_GAME_DATE: "2026-09-10",
        PENDING_SESSION_GAME_DATE_REPLACE: True,
    }
    apply_all_pending(ss)
    assert ss[SESSION_SETUP_GAME_DATE] == "2026-09-10"


def test_pending_scoreboard_status_refreshes_row_detail():
    from playcaller.streamlit_state.keys import LIVE_FEED_SCOREBOARD_ROWS, PENDING_SCOREBOARD_STATUS
    from playcaller.streamlit_state.pending import apply_all_pending

    ss: dict = {
        LIVE_FEED_SCOREBOARD_ROWS: [
            {"id": "401872657", "detail": "Scheduled", "home_abbr": "LAR", "away_abbr": "SF"}
        ],
        PENDING_SCOREBOARD_STATUS: {"event_id": "401872657", "detail": "1st Quarter 8:12"},
    }
    apply_all_pending(ss)
    assert ss[LIVE_FEED_SCOREBOARD_ROWS][0]["detail"] == "1st Quarter 8:12"
    assert PENDING_SCOREBOARD_STATUS not in ss
