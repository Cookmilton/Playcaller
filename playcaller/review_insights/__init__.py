"""Coaching analytics for Review Session (deterministic, reconciled-data only)."""

from __future__ import annotations

from playcaller.review_insights.drive_failure import explain_drive_failure
from playcaller.review_insights.drive_grading import compute_drive_grade, is_kneel_only_drive
from playcaller.review_insights.game_story import generate_game_story
from playcaller.review_insights.call_quality import CALL_QUALITY_RUBRIC, label_call_quality
from playcaller.review_insights.comparison_format import (
    comparison_block_markdown_lines,
    format_actual_comparison_line,
    format_film_room_timestamp,
)
from playcaller.review_insights.models import CallQualityLabel, DriveGrade, GameStoryBullet, Pattern, PlayMistake, SituationAggregate
from playcaller.review_insights.patterns import detect_patterns, related_drive_indices_for_pattern
from playcaller.review_insights.top_mistakes import rank_top_mistakes
from playcaller.review_insights.timeline import (
    DriveRange,
    GameFlowBundle,
    GameFlowTimelineRow,
    TurningPoint,
    build_game_flow,
    detect_droughts,
    detect_scoring_runs,
    detect_turning_points,
    game_flow_section_html,
)
from playcaller.review_insights.situational import (
    aggregate_situation,
    build_indexed_our_offense,
    filter_our_offense_rows,
    row_matches_situation,
    SITUATION_LABELS,
    SITUATION_ORDER,
)

__all__ = [
    "DriveRange",
    "GameFlowBundle",
    "GameFlowTimelineRow",
    "TurningPoint",
    "build_game_flow",
    "detect_droughts",
    "detect_scoring_runs",
    "detect_turning_points",
    "game_flow_section_html",
    "CALL_QUALITY_RUBRIC",
    "CallQualityLabel",
    "DriveGrade",
    "GameStoryBullet",
    "Pattern",
    "PlayMistake",
    "SituationAggregate",
    "SITUATION_LABELS",
    "SITUATION_ORDER",
    "aggregate_situation",
    "comparison_block_markdown_lines",
    "build_indexed_our_offense",
    "compute_drive_grade",
    "detect_patterns",
    "format_actual_comparison_line",
    "format_film_room_timestamp",
    "rank_top_mistakes",
    "related_drive_indices_for_pattern",
    "explain_drive_failure",
    "filter_our_offense_rows",
    "generate_game_story",
    "label_call_quality",
    "is_kneel_only_drive",
    "row_matches_situation",
]
