"""HTTP request bodies: JSON mirrors for :class:`~football_history_warehouse.query.situation.filter.PlaySituationFilter`."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from football_history_warehouse.domain.enums import PlayFamily, PlayResultCategory
from football_history_warehouse.query.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from football_history_warehouse.query.situation.buckets import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    ScoreDifferentialBucket,
)
from football_history_warehouse.query.situation.filter import PlaySituationFilter


def _positive_bool_only(value: bool | None) -> bool | None:
    """Match warehouse semantics: only ``True`` applies a constraint."""
    return True if value is True else None


class SituationBody(BaseModel):
    """Composable situation filter (all fields optional except scope enforced at query time)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    league_id: str | None = None
    season_id: str | None = None
    game_id: str | None = None
    offense_team_id: str | None = None
    defense_team_id: str | None = None

    quarters: tuple[int, ...] | None = None
    clock_bucket: ClockBucket | None = None
    downs: tuple[int, ...] | None = None

    distance_yards_min: int | None = None
    distance_yards_max: int | None = None
    distance_bucket: DistanceBucket | None = None

    yards_to_goal_min: int | None = None
    yards_to_goal_max: int | None = None
    field_position_bucket: FieldPositionBucket | None = None

    requires_red_zone: bool | None = None
    requires_backed_up: bool | None = None
    requires_short_yardage: bool | None = None
    requires_fourth_down: bool | None = None

    score_differential_bucket: ScoreDifferentialBucket | None = None

    play_families: tuple[PlayFamily | str, ...] | None = None
    play_type_detail_contains: str | None = None
    result_categories: tuple[PlayResultCategory | str, ...] | None = None

    def to_play_situation_filter(self) -> PlaySituationFilter:
        return PlaySituationFilter(
            league_id=self.league_id,
            season_id=self.season_id,
            game_id=self.game_id,
            offense_team_id=self.offense_team_id,
            defense_team_id=self.defense_team_id,
            quarters=self.quarters,
            clock_bucket=self.clock_bucket,
            downs=self.downs,
            distance_yards_min=self.distance_yards_min,
            distance_yards_max=self.distance_yards_max,
            distance_bucket=self.distance_bucket,
            yards_to_goal_min=self.yards_to_goal_min,
            yards_to_goal_max=self.yards_to_goal_max,
            field_position_bucket=self.field_position_bucket,
            requires_red_zone=_positive_bool_only(self.requires_red_zone),
            requires_backed_up=_positive_bool_only(self.requires_backed_up),
            requires_short_yardage=_positive_bool_only(self.requires_short_yardage),
            requires_fourth_down=_positive_bool_only(self.requires_fourth_down),
            score_differential_bucket=self.score_differential_bucket,
            play_families=self.play_families,
            play_type_detail_contains=self.play_type_detail_contains,
            result_categories=self.result_categories,
        )


class PlaysBySituationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    situation: SituationBody
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)
    offset: int = Field(default=0, ge=0)


class TeamTendencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str = Field(..., min_length=1)
    situation: SituationBody


class SituationOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    situation: SituationBody
