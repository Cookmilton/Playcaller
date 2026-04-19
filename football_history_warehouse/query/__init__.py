"""
Query services: stable read API for applications consuming the warehouse.

This is the primary integration surface for a playcalling app: versioned,
documented methods that return domain types or DTOs — not ORM rows leaked
across the boundary.
"""

from football_history_warehouse.query.filters import PlayQueryFilter
from football_history_warehouse.query.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, PageParams, PagedItems
from football_history_warehouse.query.repositories.competition import CompetitionQueryRepository
from football_history_warehouse.query.service import get_import_job_pipeline_report
from football_history_warehouse.query.services.history import FootballHistoryQueryService
from football_history_warehouse.query.situation import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    PlaySituationFilter,
    ScoreDifferentialBucket,
    apply_play_situation_filter,
    select_plays_base,
)

__all__ = [
    "ClockBucket",
    "CompetitionQueryRepository",
    "DEFAULT_PAGE_LIMIT",
    "DistanceBucket",
    "FieldPositionBucket",
    "FootballHistoryQueryService",
    "MAX_PAGE_LIMIT",
    "PageParams",
    "PagedItems",
    "PlayQueryFilter",
    "PlaySituationFilter",
    "ScoreDifferentialBucket",
    "apply_play_situation_filter",
    "get_import_job_pipeline_report",
    "select_plays_base",
]

