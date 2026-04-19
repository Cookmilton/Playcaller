"""Map sideline :class:`~playcaller.domain.GameContext` → warehouse :class:`PlaySituationFilter` (predicates only)."""

from __future__ import annotations

from football_history_warehouse.query.situation.buckets import ClockBucket, ScoreDifferentialBucket
from football_history_warehouse.query.situation.filter import PlaySituationFilter

from playcaller.domain import GameContext
from playcaller.situation import yards_from_own_goal, yards_to_opponent_goal_from_abs


def _score_bucket_offense_perspective(score_diff: int) -> ScoreDifferentialBucket:
    d = int(score_diff)
    if d <= -9:
        return ScoreDifferentialBucket.TRAILING_MULTI_SCORE
    if d <= -1:
        return ScoreDifferentialBucket.TRAILING_ONE_SCORE
    if d == 0:
        return ScoreDifferentialBucket.TIED
    if d <= 8:
        return ScoreDifferentialBucket.LEADING_ONE_SCORE
    return ScoreDifferentialBucket.LEADING_MULTI_SCORE


def _clock_bucket(seconds_remaining_in_quarter: int) -> ClockBucket | None:
    s = int(seconds_remaining_in_quarter)
    if s <= 60:
        return ClockBucket.FINAL_MINUTE_OR_LESS
    if s <= 120:
        return ClockBucket.TWO_MINUTE_OR_LESS
    if s <= 300:
        return ClockBucket.FIVE_MINUTES_OR_LESS
    return ClockBucket.MORE_THAN_FIVE_MINUTES


def play_situation_core_from_context(ctx: GameContext, *, possession: str) -> PlaySituationFilter:
    """
    Situation predicates aligned to the **offense on the field** (not always “our” sideline).

    Uses a modest yard-to-goal band so warehouse retrieval is “similar field position”
    rather than a single yard line.
    """
    _abs = yards_from_own_goal(ctx.territory, int(ctx.yardline))
    ytg = int(yards_to_opponent_goal_from_abs(_abs))
    ytg = max(1, min(99, ytg))
    band = 5
    y_lo = max(1, ytg - band)
    y_hi = min(99, ytg + band)

    offense_score_diff = int(ctx.score_diff) if possession == "offense" else -int(ctx.score_diff)

    fourth = int(ctx.down) == 4
    return PlaySituationFilter(
        quarters=(int(ctx.quarter),),
        downs=(int(ctx.down),),
        distance_yards_min=int(ctx.distance),
        distance_yards_max=int(ctx.distance),
        yards_to_goal_min=y_lo,
        yards_to_goal_max=y_hi,
        clock_bucket=_clock_bucket(int(ctx.seconds_remaining)),
        score_differential_bucket=_score_bucket_offense_perspective(offense_score_diff),
        requires_fourth_down=True if fourth else None,
    )
