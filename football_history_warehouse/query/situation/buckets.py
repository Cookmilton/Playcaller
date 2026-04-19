"""
Stable bucket labels for situation filtering.

Values are string enums for logs, APIs, and future similarity features. Numeric
cutoffs live next to each enum so SQL builders and docs stay aligned.
"""

from __future__ import annotations

from enum import Enum


class ClockBucket(str, Enum):
    """
    Buckets over ``clock_seconds_remaining_in_period`` (0–900 in a 15-minute quarter).

    **Canonical v1** — coarse broadcast-style bands. OT may use different
    quarter lengths; callers may defer OT-specific buckets until data warrants it.
    """

    TWO_MINUTE_OR_LESS = "two_minute_or_less"
    """``<= 120`` seconds — two-minute drill."""

    FINAL_MINUTE_OR_LESS = "final_minute_or_less"
    """``<= 60`` seconds."""

    MORE_THAN_FIVE_MINUTES = "more_than_five_minutes"
    """``> 300`` seconds (clock still has 5:01+)."""

    FIVE_MINUTES_OR_LESS = "five_minutes_or_less"
    """``<= 300`` and ``> 120`` (between two-minute and five-minute feel)."""


class DistanceBucket(str, Enum):
    """Buckets over ``distance`` (yards to gain for a new set of downs)."""

    SHORT = "short"
    """1–3 yards — short yardage / sneaks / heavy run looks."""

    STANDARD = "standard"
    """4–9 yards — typical early-down distance."""

    LONG = "long"
    """10+ yards — long distance."""


class FieldPositionBucket(str, Enum):
    """
    Buckets over ``yards_to_goal_line`` (1–99: yards to opponent end zone).

    Aligns with common NFL coaching labels; college uses the same numeric field.
    """

    BACKED_UP = "backed_up"
    """Own ~1–10: ``yards_to_goal_line >= 90``."""

    OPEN_FIELD = "open_field"
    """Between backed-up and red zone: ``21 <= ytg <= 89``."""

    FRINGE = "fringe"
    """Outer scoring fringe / long FG territory: ``11 <= ytg <= 20`` outside goal-to-go."""

    RED_ZONE = "red_zone"
    """``yards_to_goal_line <= 20`` (classic definition)."""

    GOAL_TO_GO = "goal_to_go"
    """``yards_to_goal_line <= 10``."""


class ScoreDifferentialBucket(str, Enum):
    """
    Bands on ``score_differential_offense_perspective`` (offense score − defense).

    One-score band uses **8 points** (~1 TD) as a practical default; swap for
    league-specific “one score” later without changing stored plays.
    """

    TRAILING_MULTI_SCORE = "trailing_multi_score"
    """``<= -9``."""

    TRAILING_ONE_SCORE = "trailing_one_score"
    """``-8`` through ``-1``."""

    TIED = "tied"
    """``0``."""

    LEADING_ONE_SCORE = "leading_one_score"
    """``1`` through ``8``."""

    LEADING_MULTI_SCORE = "leading_multi_score"
    """``>= 9``."""
