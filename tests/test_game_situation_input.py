"""Football-native situation helpers (quarter clock, field labels, score diff)."""

from playcaller.game import Game
from playcaller.game_situation_input import (
    PERIOD_OT,
    clamp_quarter_clock_seconds,
    context_quarter_from_period,
    format_ball_spot,
    format_clock_left_in_quarter,
    format_live_situation_summary,
    max_seconds_in_period,
    score_diff_from_board,
    split_clock,
)
from playcaller.streamlit_state.session import migrate_legacy_situation_widgets


def test_context_quarter_ot_maps_to_four() -> None:
    assert context_quarter_from_period(PERIOD_OT) == 4
    assert context_quarter_from_period(2) == 2


def test_clamp_quarter_clock() -> None:
    assert clamp_quarter_clock_seconds(1, 20 * 60) == 15 * 60
    assert clamp_quarter_clock_seconds(PERIOD_OT, 15 * 60) == 10 * 60


def test_split_clock_clamps() -> None:
    total, m, s = split_clock(20, 0, period=1)
    assert total == 15 * 60
    assert m == 15 and s == 0


def test_format_clock_left() -> None:
    assert "Q2" in format_clock_left_in_quarter(period=2, seconds_in_quarter=9 * 60 + 32)
    assert "9:32" in format_clock_left_in_quarter(period=2, seconds_in_quarter=9 * 60 + 32)


def test_format_ball_spot() -> None:
    assert format_ball_spot(territory="opponents", yardline=37) == "Opp 37"
    assert format_ball_spot(territory="own", yardline=25) == "Own 25"


def test_live_summary_shape() -> None:
    line = format_live_situation_summary(
        period=2,
        seconds_in_quarter=9 * 60 + 32,
        our_score=17,
        their_score=21,
        territory="opponents",
        yardline=37,
        down=2,
        distance=6,
    )
    assert "Q2" in line and "9:32" in line
    assert "Opp 37" in line
    assert "17–21" in line
    assert "2nd & 6" in line


def test_score_diff_from_board() -> None:
    assert score_diff_from_board(our_score=17, their_score=21) == -4


def test_migrate_legacy_clock_to_quarter_clock() -> None:
    g = Game.new_game()
    g.offense_points = 3
    g.defense_points = 7
    ss: dict = {
        "game": g,
        "ui_quarter": 2,
        "ui_clock_mins": 9,
        "ui_clock_secs": 32,
    }
    migrate_legacy_situation_widgets(ss)
    assert ss["ui_game_period"] == 2
    assert ss["ui_quarter_clock_mins"] == 9
    assert ss["ui_quarter_clock_secs"] == 32
    assert ss["ui_score_ours"] == 3
    assert ss["ui_score_theirs"] == 7


def test_max_seconds_ot_vs_reg() -> None:
    assert max_seconds_in_period(1) == 15 * 60
    assert max_seconds_in_period(PERIOD_OT) == 10 * 60
