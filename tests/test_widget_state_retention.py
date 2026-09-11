"""
Sidebar chips must not cost the operator any other widget's value.

``apply_and_rerun`` used to call ``st.rerun()`` in the middle of the sidebar.
Streamlit treats that ``RerunException`` as a completed run
(``premature_stop=False`` in ``exec_func_with_error_handling``), so
``SessionState.on_script_finished`` removes widget state for every widget below
the chip that never instantiated. Values ``apply_and_rerun`` wrote survived;
everything else silently reverted to ``new_game_ui_values``. Chips now set
``PENDING_RERUN_AFTER_WIDGETS``; ``maybe_rerun_after_widgets`` runs only after
sidebar and main widgets have registered.
"""

from typing import Any, Dict

import pytest
from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
from streamlit.testing.v1 import AppTest

from playcaller.streamlit_state.keys import LIVE_FEED_SCOREBOARD_ROWS, LIVE_FEED_TEAM_SCOPE

APP_FILE = "streamlit_app.py"

# Real SF @ LAR ids (event 401872657) so the "Our team" away/home radio renders.
SCOREBOARD_ROWS = [
    {
        "id": "401872657",
        "label": "SF @ LAR",
        "detail": "1st Quarter",
        "home_abbr": "LAR",
        "away_abbr": "SF",
        "home_id": "14",
        "away_id": "25",
    }
]

# Every situation / session widget the operator can set, with a non-default value.
NON_DEFAULT_VALUES: Dict[str, Any] = {
    "ui_territory": "opponents",
    "ui_yardline": 37,
    "ui_distance": 14,
    "ui_game_period": 3,
    "ui_own_tos": 1,
    "ui_opp_tos": 2,
    "ui_quarter_clock_mins": 7,
    "ui_quarter_clock_secs": 21,
    "ui_def_personnel": "dime",
    "ui_coverage_shell": "cover_2",
    "ui_safeties": "two_high",
    "ui_box_count": 8,
    "ui_blitz_likely": True,
    "ui_weather": "rain",
    "ui_game_mode": "must_score",
    "ui_qb_limited": True,
    "ui_score_ours": 13,
    "ui_score_theirs": 9,
    LIVE_FEED_TEAM_SCOPE: "both",
    "ui_live_home_or_away": "home",
    "ui_live_espn_sport": "college-football",
    "ui_live_pick_event_id": "401872657",
}

WIDGET_KINDS = ("radio", "selectbox", "slider", "number_input", "toggle", "multiselect")


def _widget(at: AppTest, key: str):
    for kind in WIDGET_KINDS:
        for w in getattr(at, kind):
            if w.key == key:
                return w
    raise AssertionError(f"widget {key!r} did not render")


def _values(at: AppTest, keys) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        try:
            out[k] = at.session_state[k]
        except KeyError:
            out[k] = "<<dropped from session_state>>"
    return out


def _reset_streamlit_dg_stack() -> None:
    """``test_boot_smoke`` imports ``streamlit_app``, which can leave a form on the DG stack."""
    context_dg_stack.set(get_default_dg_stack_value())


@pytest.fixture
def seeded_app() -> AppTest:
    """App with every situation widget set away from its default."""
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    for key, value in NON_DEFAULT_VALUES.items():
        _widget(at, key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    assert _values(at, NON_DEFAULT_VALUES) == NON_DEFAULT_VALUES, "seeding did not stick"
    return at


def test_down_chip_keeps_every_other_widget(seeded_app: AppTest) -> None:
    at = seeded_app
    at.button(key="sidebar_chip_down_2").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_down"] == 2
    assert _values(at, NON_DEFAULT_VALUES) == NON_DEFAULT_VALUES


def test_possession_chip_keeps_every_other_widget(seeded_app: AppTest) -> None:
    at = seeded_app
    at.button(key="sidebar_chip_poss_our").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_possession_side"] == "Our team"
    assert _values(at, NON_DEFAULT_VALUES) == NON_DEFAULT_VALUES


def test_chip_value_survives_the_next_chip_click(seeded_app: AppTest) -> None:
    """A down set by chip must not be wiped by the possession chip below it."""
    at = seeded_app
    at.button(key="sidebar_chip_down_3").click().run()
    assert at.session_state["ui_down"] == 3
    at.button(key="sidebar_chip_poss_opp").click().run()
    assert not at.exception, at.exception
    assert at.session_state["ui_down"] == 3
    assert at.session_state["ui_possession_side"] == "Opponent"


def test_territory_and_clock_chips_keep_the_rest(seeded_app: AppTest) -> None:
    at = seeded_app
    at.button(key="sidebar_chip_territory_own").click().run()
    assert not at.exception, at.exception
    expected = dict(NON_DEFAULT_VALUES, ui_territory="own")
    assert _values(at, expected) == expected

    at.button(key="sidebar_chip_clock_5m00s").click().run()
    assert not at.exception, at.exception
    expected.update(ui_quarter_clock_mins=5, ui_quarter_clock_secs=0)
    assert _values(at, expected) == expected
