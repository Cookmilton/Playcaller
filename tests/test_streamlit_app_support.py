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
    assert d["ui_possession_side"] == "Our team"
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
    assert ss["ui_possession_side"] == "Our team"


def test_possession_side_radio_label():
    assert possession_side_radio_label(possession="offense") == "Our team"
    assert possession_side_radio_label(possession="defense") == "Opponent"


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
    assert ss["ui_possession_side"] == "Our team"
