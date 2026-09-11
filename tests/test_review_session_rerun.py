"""
Review Session mid-script ``st.rerun()`` must not reset filters / the situational chip.

Sidebar filters instantiate before film-room nav buttons, so they already survive a
mid-script rerun. ``review_situational_chip`` renders *after* story / pattern / mistake
jumps — that is the widget the deferred rerun has to protect.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.game import Game
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.streamlit_state.keys import LIVE_FEED_COACHED_TEAM_ESPN_ID
from tests.test_widget_state_retention import _reset_streamlit_dg_stack, _values, _widget

ROOT = Path(__file__).resolve().parents[1]
REVIEW_PAGE = "pages/Review_session.py"
PACKERS_LIONS = ROOT / "tests/fixtures/espn_summary_packers_lions_401772891.json"
GB_ID = "9"
EVENT_ID = "401772891"

REVIEW_NONDEFAULT: Dict[str, Any] = {
    "review_film_mismatch_only": True,
    "review_film_show_conf": False,
    "review_film_breakdown_expanded": True,
    "review_film_team_scope": "opponent",
    "review_film_play_rp_filter": 2,
    "review_film_event_segments": ["offense"],
    "review_film_drive_result_filter": ["punt"],
    "review_situational_chip": "3rd_down",
}


def _packers_lions_game() -> Game:
    data = json.loads(PACKERS_LIONS.read_text(encoding="utf-8"))
    fds = extract_completed_drives_from_espn_payload(data, event_id=EVENT_ID)
    game = Game.new_game()
    game.offense_points = 31
    game.defense_points = 24
    merge_completed_espn_drives_into_game(
        game, {}, fds, coached_team_id=GB_ID, feed_team_scope="both"
    )
    return game


def _button_with_prefix(at: AppTest, prefix: str):
    for w in at.button:
        key = getattr(w, "key", None)
        if isinstance(key, str) and key.startswith(prefix):
            return w
    raise AssertionError(f"no button with key prefix {prefix!r}")


@pytest.fixture
def seeded_review() -> AppTest:
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(REVIEW_PAGE, default_timeout=180)
    at.session_state["game"] = _packers_lions_game()
    at.session_state[LIVE_FEED_COACHED_TEAM_ESPN_ID] = GB_ID
    at.run()
    assert not at.exception, at.exception
    for key, value in REVIEW_NONDEFAULT.items():
        _widget(at, key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    assert _values(at, REVIEW_NONDEFAULT) == REVIEW_NONDEFAULT, "seeding did not stick"
    return at


@pytest.mark.parametrize(
    "prefix",
    ["story_nav_", "pattern_nav_", "top_mistake_jump_"],
)
def test_review_rerun_path_keeps_filters(seeded_review: AppTest, prefix: str) -> None:
    at = seeded_review
    _button_with_prefix(at, prefix).click().run()
    assert not at.exception, at.exception
    assert _values(at, REVIEW_NONDEFAULT) == REVIEW_NONDEFAULT
