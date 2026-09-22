"""K1.1: a drive-ending Log archives the drive through the shared End-drive path.

Defect K1(a): logging ``field_goal_miss`` at 4th & 6, Opp 35 announced "Turnover on
downs", left possession with the offense, moved the board to 1st & 10 Opp 35, opened a
new snap row, and re-enabled Generate. The cause was one overloaded
``SituationSnapshot.turnover_on_downs`` boolean that a field-goal miss, a punt, and a
generic turnover all set to True (``playcaller/situation.py``), plus a Log handler that
never ended the drive.

AppTests here assert the values ARRIVE on the board, not just that helpers return them.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.domain import ActualPlayResult
from playcaller.game import classify_drive_end
from playcaller.situation import (
    COP_FIELD_GOAL_MADE,
    COP_FIELD_GOAL_MISS,
    COP_INTERCEPTION,
    COP_PUNT,
    COP_TURNOVER,
    COP_TURNOVER_ON_DOWNS,
    advance_game_state_after_actual,
    advance_game_state_after_play,
)
from playcaller.streamlit_state.keys import LIVE_FEED_SCOREBOARD_ROWS
from tests.test_widget_state_retention import (
    APP_FILE,
    SCOREBOARD_ROWS,
    _reset_streamlit_dg_stack,
    _widget,
)

# Defect K1's exact board: 4th & 6 at the opponent 35.
BOARD = {"ui_down": 4, "ui_distance": 6, "ui_territory": "opponents", "ui_yardline": 35}

# Log button key -> (change_of_possession reason, expected classify_drive_end kind).
ARCHIVING_LOGS = {
    "main_log_fg_good": (COP_FIELD_GOAL_MADE, "field_goal"),
    "main_log_fg_miss": (COP_FIELD_GOAL_MISS, "field_goal_miss"),
    "main_log_int": (COP_INTERCEPTION, "turnover_interception"),
    # 4th & 6 with a 0-yard Auto log is a genuine fourth-down failure.
    "main_log_yards_0": (COP_TURNOVER_ON_DOWNS, "turnover_on_downs"),
}


# ──────────────────────────────────────────────────────────────────────────────
# Unit: the reason replaces the overloaded boolean
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("result_type", "reason"),
    [
        ("field_goal", COP_FIELD_GOAL_MADE),
        ("field_goal_miss", COP_FIELD_GOAL_MISS),
        ("punt", COP_PUNT),
    ],
)
def test_k11_special_teams_reasons(result_type: str, reason: str) -> None:
    snap = advance_game_state_after_actual(
        territory="opponents",
        yardline=35,
        down=4,
        distance=6,
        actual=ActualPlayResult(result_type=result_type),
    )
    assert snap.change_of_possession == reason
    assert snap.ends_drive is True
    # Only a real fourth-down failure may claim this.
    assert snap.turnover_on_downs is False


def test_k11_interception_and_fumble_are_distinct_reasons() -> None:
    picked = advance_game_state_after_actual(
        territory="own",
        yardline=45,
        down=2,
        distance=7,
        actual=ActualPlayResult(turnover=True, turnover_kind="interception", pass_result="intercepted"),
    )
    assert picked.change_of_possession == COP_INTERCEPTION
    fumbled = advance_game_state_after_actual(
        territory="own",
        yardline=45,
        down=2,
        distance=7,
        actual=ActualPlayResult(turnover=True, turnover_kind="fumble"),
    )
    assert fumbled.change_of_possession == COP_TURNOVER
    assert picked.turnover_on_downs is False
    assert fumbled.turnover_on_downs is False


def test_k11_turnover_on_downs_is_only_the_fourth_down_failure() -> None:
    snap = advance_game_state_after_play(
        territory="own", yardline=45, down=4, distance=1, yards_gained=0, earned_first_down=False
    )
    assert snap.change_of_possession == COP_TURNOVER_ON_DOWNS
    assert snap.turnover_on_downs is True
    assert snap.ends_drive is True


def test_k11_turnover_on_downs_flag_cannot_be_set_independently() -> None:
    """The boolean is derived, so no branch can diverge from the reason again."""
    from playcaller.situation import SituationSnapshot

    assert "turnover_on_downs" not in SituationSnapshot.__dataclass_fields__
    with pytest.raises(TypeError):
        SituationSnapshot("own", 25, 1, 10, turnover_on_downs=True)  # type: ignore[call-arg]


def test_k11_a_gain_does_not_end_the_drive() -> None:
    snap = advance_game_state_after_actual(
        territory="own",
        yardline=25,
        down=1,
        distance=10,
        actual=ActualPlayResult(yards_gained=5),
    )
    assert snap.change_of_possession is None
    assert snap.ends_drive is False


# ──────────────────────────────────────────────────────────────────────────────
# Unit: recap copy — "Turnover on downs" belongs to one reason only
# ──────────────────────────────────────────────────────────────────────────────


def test_k11_fg_miss_recap_never_says_turnover_on_downs() -> None:
    from playcaller.ui.helpers import post_log_summary_and_toast

    actual = ActualPlayResult(result_type="field_goal_miss", description="Field goal missed")
    snap = advance_game_state_after_actual(
        territory="opponents",
        yardline=35,
        down=4,
        distance=6,
        actual=ActualPlayResult(result_type="field_goal_miss"),
    )
    summary, toast = post_log_summary_and_toast(actual, snap)
    assert "Turnover on downs" not in summary
    assert "TOD" not in toast
    assert "Field goal missed" in summary


def test_k11_each_reason_has_its_own_recap_line() -> None:
    from playcaller.situation import change_of_possession_copy

    seen = set()
    for reason in (
        COP_TURNOVER_ON_DOWNS,
        COP_FIELD_GOAL_MADE,
        COP_FIELD_GOAL_MISS,
        COP_INTERCEPTION,
        COP_TURNOVER,
        COP_PUNT,
    ):
        copy = change_of_possession_copy(reason)
        assert copy is not None, reason
        seen.add(copy[0])
    assert len(seen) == 6, "each reason needs distinct operator copy"
    assert change_of_possession_copy(None) is None
    tod = change_of_possession_copy(COP_TURNOVER_ON_DOWNS)
    assert tod is not None and tod[0].startswith("Turnover on downs")
    for reason in (COP_FIELD_GOAL_MISS, COP_FIELD_GOAL_MADE, COP_INTERCEPTION, COP_PUNT, COP_TURNOVER):
        line = change_of_possession_copy(reason)
        assert line is not None and "Turnover on downs" not in line[0]


# ──────────────────────────────────────────────────────────────────────────────
# Unit: archive labels (no result may land on punt or unknown)
# ──────────────────────────────────────────────────────────────────────────────


def test_k11_classify_drive_end_labels_after_archive() -> None:
    cases = [
        (ActualPlayResult(result_type="field_goal"), COP_FIELD_GOAL_MADE, "field_goal"),
        (ActualPlayResult(result_type="field_goal_miss"), COP_FIELD_GOAL_MISS, "field_goal_miss"),
        (
            ActualPlayResult(result_type="interception", turnover=True, turnover_kind="interception"),
            COP_INTERCEPTION,
            "turnover_interception",
        ),
        (ActualPlayResult(result_type="incomplete"), COP_TURNOVER_ON_DOWNS, "turnover_on_downs"),
    ]
    for actual, reason, want_kind in cases:
        res = classify_drive_end(
            [actual],
            last_snap_turnover_on_downs=(reason == COP_TURNOVER_ON_DOWNS),
        )
        assert res.kind == want_kind, (actual.result_type, res.kind)
        assert res.kind not in ("punt", "unknown"), res.kind


# ──────────────────────────────────────────────────────────────────────────────
# AppTest: the board
# ──────────────────────────────────────────────────────────────────────────────


def _ss(at: AppTest, key: str, default=None):
    """``AppTest.session_state`` has no ``.get`` — it would look up a key named "get"."""
    try:
        return at.session_state[key]
    except (KeyError, AttributeError):
        return default


def _boot_manual(board: dict | None = None) -> AppTest:
    _reset_streamlit_dg_stack()
    at = AppTest.from_file(APP_FILE, default_timeout=180)
    at.session_state[LIVE_FEED_SCOREBOARD_ROWS] = SCOREBOARD_ROWS
    at.run()
    assert not at.exception, at.exception
    # Seed the board BEFORE the possession chip: the chip defers its rerun until every
    # widget registers, and widgets set after it never commit.
    seed = dict(BOARD if board is None else board)
    for key, value in seed.items():
        _widget(at, key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    assert {k: at.session_state[k] for k in seed} == seed, "board seeding did not stick"
    at.button(key="sidebar_chip_poss_our").click().run()
    assert not at.exception, at.exception
    return at


def _generate(at: AppTest) -> None:
    for w in list(at.button) + list(getattr(at, "form_submit_button", [])):
        if getattr(w, "key", None) == "sidebar_form_submit_generate":
            w.click().run()
            assert not at.exception, at.exception
            return
    raise AssertionError("Generate submit button did not render")


def _generate_disabled(at: AppTest) -> bool:
    for b in at.button:
        if getattr(b, "key", None) == "main_console_generate":
            return bool(getattr(b, "disabled", False))
    # The whole recommendation panel is gone once possession flips — also "disabled".
    return True


@pytest.mark.parametrize("log_key", sorted(ARCHIVING_LOGS))
def test_k11_drive_ending_log_archives_and_flips_possession(log_key: str) -> None:
    reason, want_kind = ARCHIVING_LOGS[log_key]
    at = _boot_manual()
    _generate(at)
    assert at.session_state.game.drives == []
    rows_after_generate = len(at.session_state.game.recommendation_audit)
    assert rows_after_generate == 1

    at.button(key=log_key).click().run()
    assert not at.exception, at.exception

    # The drive ended through the shared archive path.
    assert len(at.session_state.game.drives) == 1, "drive was not archived"
    assert at.session_state.drive_log.results == [], "logger was not reset"
    archived = at.session_state.game.drives[0]
    assert archived.result is not None
    assert archived.result.kind == want_kind, archived.result.kind
    assert archived.result.kind not in ("punt", "unknown")

    # Possession is the opponent's, on the board and on the Game.
    assert at.session_state.game.possession == "defense"
    assert at.session_state["ui_possession_side"] == "Opponent"

    # Generate is off, and no new snap row was opened for a defense that has the ball.
    assert _ss(at, "ui_auto_generate") is not True
    assert _generate_disabled(at) is True
    assert len(at.session_state.game.recommendation_audit) == rows_after_generate

    # The recap names the actual reason.
    summary = str(_ss(at, "last_play_summary") or "")
    if reason == COP_TURNOVER_ON_DOWNS:
        assert "Turnover on downs" in summary, summary
    else:
        assert "Turnover on downs" not in summary, summary


def test_k11_fg_miss_board_text_is_not_turnover_on_downs() -> None:
    """The exact defect K1(a) report, asserted on the live board."""
    at = _boot_manual()
    _generate(at)
    at.button(key="main_log_fg_miss").click().run()
    assert not at.exception, at.exception
    summary = str(_ss(at, "last_play_summary") or "")
    assert "Turnover on downs" not in summary, summary
    assert "Field goal missed" in summary, summary
    assert at.session_state.game.drives[0].result.kind == "field_goal_miss"


@pytest.mark.parametrize("log_key", sorted(ARCHIVING_LOGS))
def test_k11_one_undo_restores_the_pre_log_board_and_possession(log_key: str) -> None:
    at = _boot_manual()
    _generate(at)
    before = {k: at.session_state[k] for k in BOARD}
    before_possession = at.session_state.game.possession
    assert before == BOARD
    assert before_possession == "offense"

    at.button(key=log_key).click().run()
    assert not at.exception, at.exception
    assert len(at.session_state.game.drives) == 1

    at.button(key="main_console_undo_drive_archive").click().run()
    assert not at.exception, at.exception

    # One Undo: the drive is open again, the logged play is gone, board + possession restored.
    assert at.session_state.game.drives == [], "archive was not undone"
    assert at.session_state.drive_log.results == [], "the logged play was not removed"
    assert at.session_state.game.possession == before_possession
    assert at.session_state["ui_possession_side"] == "Our team"
    assert {k: at.session_state[k] for k in BOARD} == before


def test_k11_non_ending_log_still_advances_the_board() -> None:
    """A gain must keep the old behaviour: board advances, drive stays open."""
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    assert at.session_state.game.drives == [], "a 5-yard gain must not end the drive"
    assert len(at.session_state.drive_log.results) == 1
    assert at.session_state.game.possession == "offense"
    assert at.session_state["ui_down"] == 2
    assert at.session_state["ui_distance"] == 5
    assert at.session_state["ui_yardline"] == 30


def test_k11_auto_generate_cannot_fire_for_opponent_or_unset_possession() -> None:
    """One gate: the button and the auto-generate path share the possession predicates.

    ``run_generate_if_requested`` (game_controller.py:289) calls
    ``generate_skip_debug_reason_for_session``, whose first check is
    ``generate_skip_debug_reason(possession)`` (feed_board_copy.py:102). The button uses
    ``generate_blocked_reason_for_possession`` (possession.py:58). Both read the same two
    predicates in ``playcaller/possession.py``, so they can never disagree.
    """
    from playcaller.possession import (
        generate_blocked_reason_for_possession,
        generate_skip_debug_reason,
    )
    from playcaller.streamlit_state.feed_board_copy import (
        generate_blocked_reason_for_session,
        generate_skip_debug_reason_for_session,
    )

    for possession in (None, "", "defense"):
        assert generate_blocked_reason_for_possession(possession) is not None, possession
        assert generate_skip_debug_reason(possession) is not None, possession
        assert generate_blocked_reason_for_session({}, possession=possession) is not None
        assert generate_skip_debug_reason_for_session({}, possession=possession) is not None
    assert generate_blocked_reason_for_possession("offense") is None
    assert generate_skip_debug_reason("offense") is None


def test_k11_stale_auto_generate_is_cleared_when_possession_is_not_ours() -> None:
    """Even with ``ui_auto_generate`` forced True, a defense board must not generate."""
    at = _boot_manual()
    _generate(at)
    at.button(key="main_log_fg_miss").click().run()
    assert not at.exception, at.exception
    assert at.session_state.game.possession == "defense"
    rows = len(at.session_state.game.recommendation_audit)

    at.session_state["ui_auto_generate"] = True
    at.run()
    assert not at.exception, at.exception
    assert len(at.session_state.game.recommendation_audit) == rows, "generated for the defense"
    assert _ss(at, "ui_auto_generate") is False, "the skip path must clear the trigger"
