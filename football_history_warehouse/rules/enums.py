"""
League rule and feed conventions — warehouse-specific enums.

These complement ``football_history_warehouse.domain.enums`` (which focus on
canonical row semantics). Values here guide normalization and expectations,
not storage column enums.
"""

from __future__ import annotations

from enum import Enum


class OvertimeStructure(str, Enum):
    """How overtime periods are structured (detail filled in normalization docs)."""

    NFL_MODIFIED_SUDDEN_DEATH = "nfl_modified_sudden_death"
    NCAA_TWO_POSSESSION_MINIMUM = "ncaa_two_possession_minimum"
    PRO_GENERIC_SUDDEN_DEATH = "pro_generic_sudden_death"
    NONE_EXPECTED = "none_expected"
    UNKNOWN = "unknown"


class FieldConvention(str, Enum):
    """Hash / field geometry assumptions for yardline normalization."""

    NFL_STANDARD = "nfl_standard"
    NCAA_COLLEGIATE = "ncaa_collegiate"
    UFL_ALIGNS_PRO = "ufl_aligns_pro"
    UNKNOWN = "unknown"


class SeasonWeekLabeling(str, Enum):
    """How seasons and weeks are labeled in sources and UI."""

    NFL_STYLE_REGULAR_POST = "nfl_style_regular_post"
    NCAA_CONFERENCE_AND_BOWL = "ncaa_conference_and_bowl"
    SPRING_LEAGUE_ROUND_ROBIN = "spring_league_round_robin"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class FeedCompletenessBand(str, Enum):
    """
    Coarse expectation for play-by-play depth by league (not a data quality score).

    Normalization can branch on soft defaults (e.g. warn vs fail on missing clock).
    """

    FULL_PBP_TYPICAL = "full_pbp_typical"
    VARIABLE_BY_PROGRAM = "variable_by_program"
    SCORE_AND_MAJOR_EVENTS = "score_and_major_events"
    UNKNOWN = "unknown"
