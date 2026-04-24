from __future__ import annotations

from unittest.mock import patch

import pytest

from warehouse.taxonomy import (
    PlayResult,
    PlayType,
    normalize_play_result,
)


def test_pass_complete_mahomes_example() -> None:
    assert (
        normalize_play_result(
            "(14:22) (Shotgun) P.Mahomes pass short right to T.Kelce for 12 yards"
        )
        == PlayResult.COMPLETE
    )


def test_pass_incomplete_messy_whitespace_and_case() -> None:
    assert (
        normalize_play_result(
            "  (Q3  7:12)  j.allen PASS   incomplete   intended for s.diggs  "
        )
        == PlayResult.INCOMPLETE
    )


def test_pass_intercepted_embedded_names() -> None:
    assert (
        normalize_play_result(
            "(2:00) (No Huddle) D.Prescott pass deep left INTERCEPTED by J.Alexander at GB 40."
        )
        == PlayResult.INTERCEPTION
    )


def test_run_rush_gain_mixed_case() -> None:
    assert (
        normalize_play_result(
            "  (Shotgun)  D.Henry  rushes  RIGHT  tackle  for  8  yards  "
        )
        == PlayResult.RUSH_GAIN
    )


def test_run_fallback_rush_no_gain_when_no_regex_match() -> None:
    assert (
        normalize_play_result(
            "  (12:01) weird legacy marker — no standard phrasing  ",
            play_type=PlayType.RUN,
        )
        == PlayResult.RUSH_NO_GAIN
    )


def test_sack_taken() -> None:
    assert (
        normalize_play_result(
            "(8:44) (Shotgun) J.Burrow sacked at CIN 22 for -9 yards (T.Watt)."
        )
        == PlayResult.SACK_TAKEN
    )


def test_scramble_gain() -> None:
    assert (
        normalize_play_result(
            "(1:12) (No Huddle, Shotgun) J.Hurts scrambles up the middle for 6 yards."
        )
        == PlayResult.SCRAMBLE_GAIN
    )


def test_punt_normal_yards() -> None:
    assert (
        normalize_play_result(
            "(4:22) T.Morstead punts 51 yards to KC 9, fair catch by M.Hardman."
        )
        == PlayResult.PUNT_NORMAL
    )


def test_punt_blocked() -> None:
    assert (
        normalize_play_result(
            "PUNT blocked by DEF team — special teams chaos  "
        )
        == PlayResult.PUNT_BLOCKED
    )


def test_kickoff_touchback() -> None:
    assert (
        normalize_play_result(
            "H.Butker kicks 65 yards from KC 35 to end zone, Touchback."
        )
        == PlayResult.KICKOFF_TOUCHBACK
    )


def test_kickoff_onside() -> None:
    assert (
        normalize_play_result(
            "ONSIDE kick attempt by BUF — ball bounces at 45."
        )
        == PlayResult.KICKOFF_ONSIDE
    )


def test_field_goal_good_bad_and_blocked() -> None:
    assert (
        normalize_play_result(
            "  (0:03) M.Crosby 52 yard FIELD GOAL is GOOD, Center-J.Snap, Holder-P.Hold  "
        )
        == PlayResult.FIELD_GOAL_MADE
    )
    assert (
        normalize_play_result(
            "FIELD GOAL is NO GOOD, wide right from 48 yards"
        )
        == PlayResult.FIELD_GOAL_MISSED
    )
    assert (
        normalize_play_result(
            "FIELD GOAL attempt BLOCKED at the line"
        )
        == PlayResult.FIELD_GOAL_BLOCKED
    )


def test_extra_point_and_two_point() -> None:
    assert (
        normalize_play_result(
            "EXTRA POINT IS GOOD"
        )
        == PlayResult.EXTRA_POINT_MADE
    )
    assert (
        normalize_play_result(
            "Extra Point MISSED — doink"
        )
        == PlayResult.EXTRA_POINT_MISSED
    )
    assert (
        normalize_play_result(
            "TWO-POINT conversion is GOOD (pass)"
        )
        == PlayResult.TWO_POINT_GOOD
    )
    assert (
        normalize_play_result(
            "Two-point try NO GOOD"
        )
        == PlayResult.TWO_POINT_FAILED
    )


def test_penalty_no_play_and_play_type_fallback() -> None:
    assert (
        normalize_play_result(
            "Penalty: holding on offense, NO PLAY — previous play negated"
        )
        == PlayResult.NO_PLAY
    )
    assert (
        normalize_play_result(
            "???",
            play_type=PlayType.PENALTY_NO_PLAY,
        )
        == PlayResult.NO_PLAY
    )


def test_spike_and_kneel() -> None:
    assert (
        normalize_play_result(
            "  (0:28)  (Shotgun)  P.MAHOMES  SPIKED THE BALL  "
        )
        == PlayResult.SPIKE
    )
    assert (
        normalize_play_result(
            "J.Love kneels to run out the clock."
        )
        == PlayResult.KNEEL
    )


def test_timeout_is_no_play() -> None:
    assert (
        normalize_play_result(
            "Timeout #2 by DAL at 01:40."
        )
        == PlayResult.NO_PLAY
    )


def test_unknown_empty_raw_text() -> None:
    with patch("warehouse.taxonomy.logger.debug") as mock_debug:
        assert normalize_play_result(None) is PlayResult.UNKNOWN
        assert normalize_play_result("   ") is PlayResult.UNKNOWN
        assert normalize_play_result("", play_type=PlayType.RUN) is PlayResult.UNKNOWN
    assert mock_debug.call_count == 3
    assert all("raw_text" in str(c.args[0]).lower() for c in mock_debug.call_args_list)


def test_fumble_parenthetical_patterns() -> None:
    assert (
        normalize_play_result(
            "FUMBLE recovered by J.Smith (same team) at KC 44"
        )
        == PlayResult.FUMBLE_RECOVERED_OWN
    )
    assert (
        normalize_play_result(
            "fumble ... recovered by defense player (other team)"
        )
        == PlayResult.FUMBLE_LOST
    )


def test_pass_fallback_unknown_without_play_type() -> None:
    assert normalize_play_result("completely nonstandard feed line xyz") is PlayResult.UNKNOWN


def test_pass_fallback_incomplete_when_play_type_pass() -> None:
    assert (
        normalize_play_result(
            "nonstandard",
            play_type=PlayType.PASS,
        )
        == PlayResult.UNKNOWN
    )


def test_kickoff_return_touchdown() -> None:
    assert (
        normalize_play_result(
            "C.Patterson 102 yard KICKOFF RETURN TOUCHDOWN"
        )
        == PlayResult.KICKOFF_RETURN_TD
    )


def test_punt_touchback_fair_catch_downed() -> None:
    assert (
        normalize_play_result(
            "A.Lee punts 48 yards, touchback (ball into end zone)"
        )
        == PlayResult.PUNT_TOUCHBACK
    )
    assert (
        normalize_play_result(
            "Fair catch by returner at the 12"
        )
        == PlayResult.PUNT_FAIR_CATCH
    )
    assert (
        normalize_play_result(
            "Punt downed at the 2 yard line"
        )
        == PlayResult.PUNT_DOWNED
    )


def test_touchdown_pass_run_return_and_safety() -> None:
    assert (
        normalize_play_result(
            "J.Allen pass deep right TOUCHDOWN to S.Diggs"
        )
        == PlayResult.TOUCHDOWN_PASS
    )
    assert (
        normalize_play_result(
            "N.Chubb rushes for a TOUCHDOWN"
        )
        == PlayResult.TOUCHDOWN_RUN
    )
    assert (
        normalize_play_result(
            "M.Hardman punt RETURN for a TOUCHDOWN"
        )
        == PlayResult.TOUCHDOWN_RETURN
    )
    assert (
        normalize_play_result(
            "SAFETY — intentional grounding in end zone"
        )
        == PlayResult.SAFETY
    )


def test_penalty_offense_defense_offsetting() -> None:
    assert (
        normalize_play_result(
            "PENALTY on offense: false start"
        )
        == PlayResult.PENALTY_OFFENSE
    )
    assert (
        normalize_play_result(
            "Defensive penalty: pass interference"
        )
        == PlayResult.PENALTY_DEFENSE
    )
    assert (
        normalize_play_result(
            "Offsetting penalties — replay down"
        )
        == PlayResult.PENALTY_OFFSETTING
    )


def test_unknown_play_type_fallback() -> None:
    assert (
        normalize_play_result("???", play_type=PlayType.UNKNOWN)
        is PlayResult.UNKNOWN
    )
