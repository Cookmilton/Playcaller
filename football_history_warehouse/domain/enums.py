"""
Stable enumerations for league, competition, and football semantics.

Values are string-backed for stable serialization across leagues and storage backends. Add new members rather than overloading existing ones when a
provider uses ambiguous labels — map at normalization time.
"""

from __future__ import annotations

from enum import Enum


class LeagueFamily(str, Enum):
    """Broad league grouping for rule selection and display."""

    NFL = "nfl"
    NCAA_FBS = "ncaa_fbs"
    NCAA_FCS = "ncaa_fcs"
    UFL = "ufl"
    OTHER = "other"


class CompetitionTier(str, Enum):
    """Granularity within a family (e.g. postseason, spring league)."""

    REGULAR = "regular"
    POSTSEASON = "postseason"
    SPRING = "spring"
    UNKNOWN = "unknown"


class GameStatus(str, Enum):
    """High-level game lifecycle (canonical, not a vendor status string)."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    FORFEIT = "forfeit"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    UNKNOWN = "unknown"


class ImportJobStatus(str, Enum):
    """Batch ingest job state."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"  # completed with recoverable errors / skipped records


class DriveResultBucket(str, Enum):
    """
    Coarse end-of-drive label for analytics.

    Providers disagree on wording; normalization maps into this set. Use
    UNKNOWN when the feed marks a drive end without a clear bucket.
    """

    TOUCHDOWN = "touchdown"
    FIELD_GOAL = "field_goal"
    FIELD_GOAL_MISS = "field_goal_miss"
    SAFETY = "safety"
    PUNT = "punt"
    TURNOVER = "turnover"
    TURNOVER_ON_DOWNS = "turnover_on_downs"
    END_OF_HALF = "end_of_half"
    END_OF_GAME = "end_of_game"
    OTHER = "other"
    UNKNOWN = "unknown"


class PlayFamily(str, Enum):
    """
    Canonical play grouping for filtering (not a full play-type taxonomy).

    Finer detail lives in ``Play.play_type_detail`` and ``PlayOutcome``.
    """

    RUN = "run"
    PASS = "pass"
    KICKOFF = "kickoff"
    PUNT = "punt"
    FIELD_GOAL = "field_goal"
    EXTRA_POINT = "extra_point"
    TWO_POINT = "two_point_try"
    SPECIAL_TEAMS_OTHER = "special_teams_other"
    PENALTY_ONLY = "penalty_only"  # administrative / offsetting / clock-only
    NO_PLAY = "no_play"  # whistle, measurement, etc.
    OTHER = "other"
    UNKNOWN = "unknown"


class PlayResultCategory(str, Enum):
    """
    Normalized outcome category at play resolution.

    Deliberately provider-agnostic; map messy feed codes here during ingest.
    """

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INTERCEPTION = "interception"
    FUMBLE = "fumble"
    FUMBLE_LOST = "fumble_lost"
    SACK = "sack"
    SCRAMBLE = "scramble"
    PENALTY = "penalty"
    TOUCHDOWN = "touchdown"
    FIELD_GOAL_GOOD = "field_goal_good"
    FIELD_GOAL_NO_GOOD = "field_goal_no_good"
    PUNT = "punt"
    KICKOFF = "kickoff"
    SPIKE = "spike"
    KNEEL = "kneel"
    LATERAL = "lateral"
    ABORTED = "aborted"
    TIMEOUT = "timeout"
    OTHER = "other"
    UNKNOWN = "unknown"


class FieldSide(str, Enum):
    """Which side of the field the offense is driving toward (optional aid)."""

    OWN = "own"  # advancing toward opponent end zone from own territory framing
    OPPONENT = "opponent"
    MIDFIELD = "midfield"
    UNKNOWN = "unknown"
