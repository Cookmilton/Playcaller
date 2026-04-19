"""
Warehouse-owned **game review** outputs for past-game analysis (film room, coaching review).

Use :func:`build_game_review_package` to assemble a versioned :class:`GameReviewPackage`
from stored games, drives, and plays. No UI framework dependencies.
"""

from football_history_warehouse.review.schema import (
    DriveTimelineEntry,
    GameReviewPackage,
    GameReviewSummary,
    MatchupSummary,
    OutcomeSummary,
    PlayTimelineEntry,
    ReviewDataQuality,
    ScoreBlock,
    SituationalBreakdown,
    TeamSideSnapshot,
    TendencyByTeam,
    TendencySummary,
)
from football_history_warehouse.review.service import build_game_review_package

__all__ = [
    "DriveTimelineEntry",
    "GameReviewPackage",
    "GameReviewSummary",
    "MatchupSummary",
    "OutcomeSummary",
    "PlayTimelineEntry",
    "ReviewDataQuality",
    "ScoreBlock",
    "SituationalBreakdown",
    "TeamSideSnapshot",
    "TendencyByTeam",
    "TendencySummary",
    "build_game_review_package",
]
