"""Apply :class:`PlaySituationFilter` to a SQLAlchemy ``select(PlayRow)`` statement."""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.sql import Select

from football_history_warehouse.query.situation.buckets import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    ScoreDifferentialBucket,
)
from football_history_warehouse.query.situation.filter import PlaySituationFilter
from football_history_warehouse.storage.database.models import PlayRow


def _play_family_values(families: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(f.value if hasattr(f, "value") else str(f) for f in families)


def _result_category_values(categories: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(c.value if hasattr(c, "value") else str(c) for c in categories)


def _clock_clause(bucket: ClockBucket):
    c = PlayRow.clock_seconds_remaining_in_period
    if bucket is ClockBucket.TWO_MINUTE_OR_LESS:
        return and_(c.is_not(None), c <= 120)
    if bucket is ClockBucket.FINAL_MINUTE_OR_LESS:
        return and_(c.is_not(None), c <= 60)
    if bucket is ClockBucket.MORE_THAN_FIVE_MINUTES:
        return and_(c.is_not(None), c > 300)
    if bucket is ClockBucket.FIVE_MINUTES_OR_LESS:
        return and_(c.is_not(None), c <= 300, c > 120)
    raise AssertionError(f"Unhandled ClockBucket: {bucket}")


def _distance_bucket_clause(bucket: DistanceBucket):
    d = PlayRow.distance
    if bucket is DistanceBucket.SHORT:
        return and_(d.is_not(None), d >= 1, d <= 3)
    if bucket is DistanceBucket.STANDARD:
        return and_(d.is_not(None), d >= 4, d <= 9)
    if bucket is DistanceBucket.LONG:
        return and_(d.is_not(None), d >= 10)
    raise AssertionError(f"Unhandled DistanceBucket: {bucket}")


def _field_position_bucket_clause(bucket: FieldPositionBucket):
    y = PlayRow.yards_to_goal_line
    if bucket is FieldPositionBucket.BACKED_UP:
        return and_(y.is_not(None), y >= 90)
    if bucket is FieldPositionBucket.OPEN_FIELD:
        return and_(y.is_not(None), y >= 21, y <= 89)
    if bucket is FieldPositionBucket.FRINGE:
        return and_(y.is_not(None), y >= 11, y <= 20)
    if bucket is FieldPositionBucket.RED_ZONE:
        return and_(y.is_not(None), y <= 20)
    if bucket is FieldPositionBucket.GOAL_TO_GO:
        return and_(y.is_not(None), y <= 10)
    raise AssertionError(f"Unhandled FieldPositionBucket: {bucket}")


def _score_bucket_clause(bucket: ScoreDifferentialBucket):
    s = PlayRow.score_differential_offense_perspective
    if bucket is ScoreDifferentialBucket.TRAILING_MULTI_SCORE:
        return and_(s.is_not(None), s <= -9)
    if bucket is ScoreDifferentialBucket.TRAILING_ONE_SCORE:
        return and_(s.is_not(None), s >= -8, s <= -1)
    if bucket is ScoreDifferentialBucket.TIED:
        return and_(s.is_not(None), s == 0)
    if bucket is ScoreDifferentialBucket.LEADING_ONE_SCORE:
        return and_(s.is_not(None), s >= 1, s <= 8)
    if bucket is ScoreDifferentialBucket.LEADING_MULTI_SCORE:
        return and_(s.is_not(None), s >= 9)
    raise AssertionError(f"Unhandled ScoreDifferentialBucket: {bucket}")


def apply_play_situation_filter(stmt: Select, situation: PlaySituationFilter | None) -> Select:
    """
    AND the given predicates onto an existing ``select(PlayRow)`` (or compatible).

    Caller supplies base ``WHERE`` clauses (e.g. ``game_id == …``); this function
    only adds situation dimensions.
    """
    if situation is None:
        return stmt

    s = situation

    if s.league_id is not None:
        stmt = stmt.where(PlayRow.league_id == s.league_id)
    if s.season_id is not None:
        stmt = stmt.where(PlayRow.season_id == s.season_id)
    if s.game_id is not None:
        stmt = stmt.where(PlayRow.game_id == s.game_id)
    if s.offense_team_id is not None:
        stmt = stmt.where(PlayRow.offense_team_id == s.offense_team_id)
    if s.defense_team_id is not None:
        stmt = stmt.where(PlayRow.defense_team_id == s.defense_team_id)

    if s.quarters:
        stmt = stmt.where(PlayRow.period.in_(s.quarters))
    if s.clock_bucket is not None:
        stmt = stmt.where(_clock_clause(s.clock_bucket))
    if s.downs:
        stmt = stmt.where(PlayRow.down.in_(s.downs))

    if s.distance_yards_min is not None:
        stmt = stmt.where(and_(PlayRow.distance.is_not(None), PlayRow.distance >= s.distance_yards_min))
    if s.distance_yards_max is not None:
        stmt = stmt.where(and_(PlayRow.distance.is_not(None), PlayRow.distance <= s.distance_yards_max))
    if s.distance_bucket is not None:
        stmt = stmt.where(_distance_bucket_clause(s.distance_bucket))

    if s.yards_to_goal_min is not None:
        stmt = stmt.where(
            and_(PlayRow.yards_to_goal_line.is_not(None), PlayRow.yards_to_goal_line >= s.yards_to_goal_min)
        )
    if s.yards_to_goal_max is not None:
        stmt = stmt.where(
            and_(PlayRow.yards_to_goal_line.is_not(None), PlayRow.yards_to_goal_line <= s.yards_to_goal_max)
        )
    if s.field_position_bucket is not None:
        stmt = stmt.where(_field_position_bucket_clause(s.field_position_bucket))

    if s.requires_red_zone is True:
        stmt = stmt.where(and_(PlayRow.yards_to_goal_line.is_not(None), PlayRow.yards_to_goal_line <= 20))
    if s.requires_backed_up is True:
        stmt = stmt.where(and_(PlayRow.yards_to_goal_line.is_not(None), PlayRow.yards_to_goal_line >= 90))
    if s.requires_short_yardage is True:
        stmt = stmt.where(and_(PlayRow.distance.is_not(None), PlayRow.distance >= 1, PlayRow.distance <= 3))
    if s.requires_fourth_down is True:
        stmt = stmt.where(PlayRow.down == 4)

    if s.score_differential_bucket is not None:
        stmt = stmt.where(_score_bucket_clause(s.score_differential_bucket))

    if s.play_families:
        stmt = stmt.where(PlayRow.play_family.in_(_play_family_values(s.play_families)))
    if s.play_type_detail_contains:
        stmt = stmt.where(PlayRow.play_type_detail.contains(s.play_type_detail_contains))
    if s.result_categories:
        stmt = stmt.where(PlayRow.result_category.in_(_result_category_values(s.result_categories)))

    return stmt


def select_plays_base() -> Select:
    """Convenience: ``select(PlayRow)`` for callers building situation queries."""
    return select(PlayRow)
