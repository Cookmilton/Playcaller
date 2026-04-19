"""
Structured **game review package** for film-room style surfaces.

This is the warehouse-owned contract between stored history and a future app/API.
Serialize with :meth:`GameReviewPackage.model_dump(mode="json")` for JSON APIs.

**Schema versioning:** bump ``schema_version`` when adding required fields or changing
meaning of existing fields; clients should treat unknown keys as ignorable only when
``schema_version`` matches their parser.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TeamSideSnapshot(BaseModel):
    """One side of the matchup with display-oriented labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str
    role: Literal["home", "away"]
    full_name: str
    abbreviation: str | None = None
    nickname: str | None = None


class MatchupSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    home: TeamSideSnapshot
    away: TeamSideSnapshot
    league_id: str
    league_name: str | None = None
    season_id: str
    season_year_label: str | None = None


class GameReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    game_id: str
    status: str
    scheduled_start_utc: datetime | None = None
    regulation_period_count: int = 4
    overtime_periods_played: int | None = None
    neutral_site: bool | None = None
    venue_id: str | None = None


class ScoreBlock(BaseModel):
    """Final (or latest recorded) score when present on the game row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    home_points: int | None = None
    away_points: int | None = None
    is_final_on_record: bool = False
    """True when status is :class:`~football_history_warehouse.domain.enums.GameStatus`.FINAL and both scores are integers."""


class DriveTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    drive_id: str
    drive_order: int
    offense_team_id: str
    defense_team_id: str
    offense_display: str
    defense_display: str
    result_bucket: str | None = None
    net_yards: int | None = None
    play_count: int = 0
    start_period: int | None = None
    end_period: int | None = None


class PlayTimelineEntry(BaseModel):
    """One row in chronological play order; kept flat for UI tables."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    play_id: str
    sequence_in_game: int
    drive_id: str | None = None
    period: int | None = None
    clock_seconds_remaining_in_period: int | None = None
    down: int | None = None
    distance: int | None = None
    yards_to_goal_line: int | None = None
    offense_team_id: str
    defense_team_id: str
    offense_display: str
    play_family: str
    result_category: str
    yards_gained: int | None = None
    is_touchdown: bool | None = None
    is_turnover: bool | None = None
    is_explosive: bool = False
    """Simple v1 rule: run ≥10 net yards or pass ≥15 net yards (when ``yards_gained`` known)."""

    description_text: str | None = None


class TendencyByTeam(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str
    team_display: str
    total_plays: int
    play_family_counts: dict[str, int] = Field(default_factory=dict)
    """Counts of plays where this team was **offense** (``play_family`` → count)."""


class TendencySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    by_offense_team: tuple[TendencyByTeam, ...]


class OutcomeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result_category_counts: dict[str, int] = Field(default_factory=dict)
    total_turnovers: int = 0
    total_touchdowns_scored: int = 0
    sacks: int = 0
    penalties_flagged: int = 0


class SituationalBreakdown(BaseModel):
    """Easy situational counts for chips / sidebar (same definitions as situation filters where possible)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    red_zone_plays: int = 0
    """``yards_to_goal_line`` not null and ≤ 20."""

    third_down_plays: int = 0
    fourth_down_plays: int = 0
    two_minute_drill_plays: int = 0
    """Clock not null and ≤ 120 seconds in period."""

    short_yardage_plays: int = 0
    """Distance not null and 1–3 yards to go."""

    goal_to_go_plays: int = 0
    """``yards_to_goal_line`` not null and ≤ 10."""


class ReviewDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    play_rows_loaded: int
    play_timeline_truncated: bool = False
    """True if the game hit the repository ``max_plays`` cap."""


class GameReviewPackage(BaseModel):
    """
    Full review payload for one ``game_id``.

    **Contains:** matchup + score snapshot, drive and play timelines, offensive tendency
    splits by team, game-wide outcome aggregates, and a small situational breakdown.
    **Does not contain:** video, charting labels, coach notes, or live win probability
    (add in later schema versions or parallel resources).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1"
    game_id: str
    generated_at_utc: datetime
    summary: GameReviewSummary
    matchup: MatchupSummary
    score: ScoreBlock
    drive_timeline: tuple[DriveTimelineEntry, ...]
    play_timeline: tuple[PlayTimelineEntry, ...]
    tendencies: TendencySummary
    outcomes: OutcomeSummary
    situational: SituationalBreakdown
    data_quality: ReviewDataQuality
