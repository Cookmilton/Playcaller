"""Assert ESPN applied[] situation/score/clock fields reached both ``game_*`` and ``ui_*``."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from playcaller.streamlit_state.keys import (
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_OPP_TOS,
    GAME_OWN_TOS,
    GAME_PERIOD,
    GAME_POSSESSION_SIDE,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    GAME_TERRITORY,
    GAME_YARDLINE,
)

# applied[] token → (game_key, ui_key) or a pair of field-position keys.
_APPLIED_MIRROR: dict[str, tuple[str, str]] = {
    "down": (GAME_DOWN, "ui_down"),
    "distance": (GAME_DISTANCE, "ui_distance"),
    "possession": (GAME_POSSESSION_SIDE, "ui_possession_side"),
    "own_timeouts": (GAME_OWN_TOS, "ui_own_tos"),
    "opp_timeouts": (GAME_OPP_TOS, "ui_opp_tos"),
    "our_score→game.offense_points": (GAME_SCORE_OURS, "ui_score_ours"),
    "opponent_score→game.defense_points": (GAME_SCORE_THEIRS, "ui_score_theirs"),
    "quarter": (GAME_PERIOD, "ui_game_period"),
}

# 401872657 scoreboard + summary (LAR home / our sideline, 2nd & 1 own 34).
EXPECTED_401872657_HOME: dict[str, Any] = {
    "ui_down": 2,
    "ui_distance": 1,
    "ui_territory": "own",
    "ui_yardline": 34,
    "ui_possession_side": "Our team",
    "ui_score_ours": 0,
    "ui_score_theirs": 3,
    "ui_game_period": 1,
    "ui_quarter_clock_mins": 6,
    "ui_quarter_clock_secs": 10,
    "ui_own_tos": 3,
    "ui_opp_tos": 3,
}


def _ss_get(ss: Any, key: str) -> Any:
    try:
        return ss[key]
    except Exception:
        return f"<<missing {key}>>"


def assert_mirrors_equal(ss: Any, game_key: str, ui_key: str) -> None:
    gv, uv = _ss_get(ss, game_key), _ss_get(ss, ui_key)
    assert gv == uv, f"{game_key}={gv!r} != {ui_key}={uv!r}"


def assert_applied_fields_reached_board(ss: Any, applied: Sequence[Any]) -> None:
    """Every situation/score/clock token in ``applied`` has matching ``game_*`` and ``ui_*``."""
    tokens = [str(x) for x in applied]
    for token in tokens:
        if token in _APPLIED_MIRROR:
            gk, uk = _APPLIED_MIRROR[token]
            assert_mirrors_equal(ss, gk, uk)
        elif token == "field_position":
            assert_mirrors_equal(ss, GAME_TERRITORY, "ui_territory")
            assert_mirrors_equal(ss, GAME_YARDLINE, "ui_yardline")
        elif token == "clock" or token == "clock_retained_trusted":
            assert_mirrors_equal(ss, GAME_QUARTER_CLOCK_MINS, "ui_quarter_clock_mins")
            assert_mirrors_equal(ss, GAME_QUARTER_CLOCK_SECS, "ui_quarter_clock_secs")


UI_TO_GAME: dict[str, str] = {
    "ui_down": GAME_DOWN,
    "ui_distance": GAME_DISTANCE,
    "ui_territory": GAME_TERRITORY,
    "ui_yardline": GAME_YARDLINE,
    "ui_possession_side": GAME_POSSESSION_SIDE,
    "ui_score_ours": GAME_SCORE_OURS,
    "ui_score_theirs": GAME_SCORE_THEIRS,
    "ui_game_period": GAME_PERIOD,
    "ui_quarter_clock_mins": GAME_QUARTER_CLOCK_MINS,
    "ui_quarter_clock_secs": GAME_QUARTER_CLOCK_SECS,
    "ui_own_tos": GAME_OWN_TOS,
    "ui_opp_tos": GAME_OPP_TOS,
}


def assert_board_matches(ss: Any, expected: Mapping[str, Any]) -> None:
    for uk, want in expected.items():
        got = _ss_get(ss, uk)
        assert got == want, f"{uk}: expected {want!r}, got {got!r}"
        gk = UI_TO_GAME.get(uk)
        if gk:
            gv = _ss_get(ss, gk)
            assert gv == want, f"{gk}={gv!r} != {uk}={want!r}"
