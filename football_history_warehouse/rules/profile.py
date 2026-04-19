"""
Frozen rule profile: one object per supported league *rules configuration*.

Multiple ``LeagueId`` rows may share a profile (e.g. all NFL). Unknown leagues
fall back to ``PROFILE_GENERIC_OTHER`` with conservative ``UNKNOWN`` enums.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from football_history_warehouse.domain.base import CanonicalModel
from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.rules.enums import (
    FeedCompletenessBand,
    FieldConvention,
    OvertimeStructure,
    SeasonWeekLabeling,
)


class LeagueRuleProfile(CanonicalModel):
    """
    League-aware configuration for normalization and query helpers.

    **Not** game state — only static expectations and conventions. Mutable
    policy during ingest belongs on ``ImportJob.config_snapshot``, not here.
    """

    profile_key: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    family: LeagueFamily
    default_competition_tier: CompetitionTier = CompetitionTier.UNKNOWN
    regulation_period_count: int = Field(default=4, ge=1, le=8)
    overtime_structure: OvertimeStructure = OvertimeStructure.UNKNOWN
    field_convention: FieldConvention = FieldConvention.UNKNOWN
    season_week_labeling: SeasonWeekLabeling = SeasonWeekLabeling.UNKNOWN
    feed_completeness: FeedCompletenessBand = FeedCompletenessBand.UNKNOWN
    league_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional namespaced hints (e.g. ufl.clock_rules_version).",
    )
