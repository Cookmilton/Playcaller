"""Formatting for model vs actual comparison lines."""

from __future__ import annotations

from dataclasses import replace

from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.comparison_format import (
    build_model_top_three_lines,
    comparison_block_markdown_lines,
    format_actual_comparison_line,
    match_indicator_phrase,
    normalized_top_families,
)


def _row(
    *,
    pre_snap: dict,
    actual_struct: dict,
    model_struct: dict,
    comparison: UnifiedComparison | None = None,
    confidence: float | None = 0.82,
    segment: PlayEventSegment = PlayEventSegment.OFFENSE,
) -> UnifiedReviewRow:
    c = comparison or UnifiedComparison(True, True, True)
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=0,
        play_index_on_drive=3,
        team_side="our",
        pre_snap=pre_snap,
        actual_headline="Run",
        actual_detail="RB1, 5 yd",
        actual_structured=actual_struct,
        model_headline="Short pass",
        model_subline="—",
        model_structured=model_struct,
        comparison=c,
        confidence=confidence,
        is_replay=True,
        is_historical=False,
        event_segment=segment,
        offensive_snap_index=2,
    )


def test_format_actual_line_joins_headline_detail() -> None:
    r = _row(
        pre_snap={},
        actual_struct={"family": "inside_zone"},
        model_struct={"top_families": [{"family": "inside_zone", "score": 0.9}]},
    )
    r = replace(r, actual_headline="Pass complete", actual_detail="WR1, 12 yd")
    assert "Pass complete" in format_actual_comparison_line(r)
    assert "12 yd" in format_actual_comparison_line(r)


def test_normalized_top_families_reads_audit_shape() -> None:
    ms = {"top_families": [{"family": "quick_game", "score": 0.78}, {"family": "inside_zone", "score": 0.54}]}
    assert normalized_top_families(ms)[0][0] == "quick_game"


def test_build_model_top_three_lines_and_match_rank() -> None:
    r = _row(
        pre_snap={"down": 3, "distance": 8},
        actual_struct={"family": "inside_zone", "run_pass": "Run", "result_type": "first_down"},
        model_struct={
            "summary_bucket": "run inside / gap",
            "family": "quick_game",
            "play_name": "Stick",
            "run_pass": "Pass",
            "top_families": [
                {"family": "quick_game", "score": 0.78},
                {"family": "inside_zone", "score": 0.54},
                {"family": "play_action", "score": 0.41},
            ],
        },
        comparison=UnifiedComparison(False, False, False),
    )
    lines, rank, phrase = build_model_top_three_lines(r)
    assert len(lines) == 3
    assert "78%" in lines[0] or "78" in lines[0]
    assert rank == 2
    assert "2nd" in phrase


def test_match_phrase_without_ranked_list() -> None:
    assert "no ranked" in match_indicator_phrase(None, has_ranked_list=False).lower()


def test_comparison_block_special_teams_no_model_error() -> None:
    r = _row(
        pre_snap={"quarter": 1, "seconds_remaining": 900},
        actual_struct={"family": ""},
        model_struct={},
        segment=PlayEventSegment.KICKOFF,
    )
    lines = comparison_block_markdown_lines(r)
    assert any("special" in x.lower() or "kickoff" in x.lower() for x in lines)
    assert lines  # no exception


def test_missing_model_data_no_crash() -> None:
    r = _row(
        pre_snap={},
        actual_struct={"family": "inside_zone"},
        model_struct={"summary_bucket": "", "family": "", "play_name": "", "run_pass": None},
        confidence=None,
    )
    lines, _, _ = build_model_top_three_lines(r)
    assert lines == [] or lines  # empty top_families still safe
