"""Tests for logged actual play semantics and formatting."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.actual_result import (
    assemble_actual_semantics,
    classify_actual_result_type,
    format_actual_play_result_description,
)
from playcaller.library import PLAY_LIBRARY


def test_format_qb_scramble() -> None:
    a = ActualPlayResult(
        play_type="qb_scramble",
        scramble=True,
        yards_gained=2,
        ball_carrier_or_target="QB",
        target_role_label="QB",
    )
    assert format_actual_play_result_description(a) == "QB scramble for 2 yards"


def test_format_pass_complete_to_z() -> None:
    a = ActualPlayResult(
        play_type="pass",
        pass_result="complete",
        yards_gained=8,
        target_position="Z",
        target_role_label="Z receiver",
    )
    assert format_actual_play_result_description(a) == "Pass complete to Z receiver for 8 yards"


def test_format_pass_incomplete_to_x() -> None:
    a = ActualPlayResult(
        play_type="pass",
        pass_result="incomplete",
        yards_gained=0,
        target_position="X",
        target_role_label="X receiver",
    )
    assert format_actual_play_result_description(a) == "Pass incomplete to X receiver"


def test_format_run_rb() -> None:
    a = ActualPlayResult(
        play_type="run",
        family="inside_zone",
        yards_gained=4,
        ball_carrier_or_target="RB",
        target_role_label="RB",
    )
    assert format_actual_play_result_description(a) == "Run by RB for 4 yards"


def test_format_sack_loss() -> None:
    a = ActualPlayResult(
        play_type="pass",
        pass_result="sack",
        sack=True,
        yards_gained=-7,
    )
    assert format_actual_play_result_description(a) == "Sack for loss of 7"


def test_format_interception_slot() -> None:
    a = ActualPlayResult(
        play_type="pass",
        pass_result="intercepted",
        turnover_kind="interception",
        turnover=True,
        yards_gained=0,
        target_position="H",
        target_role_label="slot",
    )
    assert format_actual_play_result_description(a) == "Interception targeting slot"


def test_format_touchdown_pass_te() -> None:
    a = ActualPlayResult(
        play_type="pass",
        pass_result="complete",
        touchdown=True,
        yards_gained=14,
        target_position="Y",
        target_role_label="TE",
    )
    assert format_actual_play_result_description(a) == "Touchdown pass to TE for 14 yards"


def test_classify_interception_over_sack() -> None:
    assert (
        classify_actual_result_type(
            yards=0,
            to_go=10,
            earned_first_down=False,
            touchdown=False,
            pass_result="intercepted",
            turnover_kind="interception",
            sack=False,
        )
        == "interception"
    )


def test_classify_incomplete() -> None:
    assert (
        classify_actual_result_type(
            yards=0,
            to_go=10,
            earned_first_down=False,
            touchdown=False,
            pass_result="incomplete",
        )
        == "incomplete"
    )


def test_assemble_auto_pass_complete_positive() -> None:
    play = PLAY_LIBRARY["quick_game"][0]
    a = assemble_actual_semantics(
        concept_name="x",
        family="quick_game",
        play=play,
        yards_gained=8,
        target_choice="Z",
        outcome_ui="Auto (from call + yards)",
        sack_from_chip=False,
    )
    assert a.play_type == "pass"
    assert a.pass_result == "complete"
    assert a.target_position == "Z"


def test_custom_description_short_circuit() -> None:
    a = ActualPlayResult(description="Custom recap", yards_gained=0)
    assert format_actual_play_result_description(a) == "Custom recap"
