"""
Football situation primitives: buckets + composable play filters + SQL helpers.

**Canonical v1:** clock, distance, field position, score differential buckets;
explicit ``requires_*`` flags for red zone, backed up, short yardage, fourth down.

**Deferred:** true four-down *territory* (go-for-it heuristics), win-probability
slices, “similar situation” embeddings — hooks are enum + filter fields only.
"""

from football_history_warehouse.query.situation.buckets import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    ScoreDifferentialBucket,
)
from football_history_warehouse.query.situation.filter import PlaySituationFilter, validate_situation_has_scope
from football_history_warehouse.query.situation.sql import apply_play_situation_filter, select_plays_base

__all__ = [
    "ClockBucket",
    "DistanceBucket",
    "FieldPositionBucket",
    "PlaySituationFilter",
    "ScoreDifferentialBucket",
    "apply_play_situation_filter",
    "select_plays_base",
    "validate_situation_has_scope",
]
