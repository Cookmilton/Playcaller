"""Rich actual-play formatting for analysis / drive archive UI."""

from __future__ import annotations

from playcaller.actual_result import (
    actual_play_structured_dict,
    format_actual_play_analysis_detail,
    format_actual_play_analysis_primary,
)
from playcaller.domain import ActualPlayResult


def test_analysis_primary_pass_complete() -> None:
    a = ActualPlayResult(
        family="quick_game",
        play_type="pass",
        pass_result="complete",
        yards_gained=5,
        result_type="short",
        feed_passer_label="J.Flacco",
        feed_receiver_label="H.Fannin",
        feed_target_role="TE",
    )
    s = format_actual_play_analysis_primary(a)
    assert "Pass complete" in s
    assert "Flacco" in s
    assert "Fannin" in s


def test_analysis_primary_run() -> None:
    a = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=4,
        result_type="short",
        feed_rusher_label="D.Sampson",
    )
    s = format_actual_play_analysis_primary(a)
    assert "Run" in s
    assert "Sampson" in s


def test_structured_dict_round_trip_keys() -> None:
    a = ActualPlayResult(family="quick_game", concept_name="Stick", yards_gained=3)
    d = actual_play_structured_dict(a)
    assert d["family"] == "quick_game"
    assert d["concept_name"] == "Stick"


def test_analysis_detail_includes_family() -> None:
    a = ActualPlayResult(
        family="dropback_pass",
        concept_name="Dagger",
        touchdown=True,
    )
    d = format_actual_play_analysis_detail(a)
    assert "dropback pass" in d.lower() or "dropback_pass" in d
    assert "TD" in d or "touchdown" in d.lower()
