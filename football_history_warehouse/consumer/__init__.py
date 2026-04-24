"""
**Playcalling app boundary** for the football history warehouse.

Import from here (and :mod:`football_history_warehouse.consumer.client`) instead of
repositories, ORM models, parsers, or raw ingest paths. That keeps the app stable
when storage or ingest internals change.

Recommended (v1): use :class:`FootballWarehouseClient` in-process with a shared DB URL.
Optional: the same four operations are exposed as JSON at :mod:`football_history_warehouse.api`
(FastAPI; ``uvicorn football_history_warehouse.api.app:app`` or ``python -m football_history_warehouse.cli.serve``).

**Should use from the app**

- :class:`FootballWarehouseClient`
- :class:`~football_history_warehouse.consumer.dtos.PlaysBySituationPage`,
  :class:`~football_history_warehouse.consumer.dtos.TeamTendencySummary`,
  :class:`~football_history_warehouse.consumer.dtos.SituationOutcomeSummary`,
  :class:`~football_history_warehouse.consumer.dtos.GameInventoryPage` / :class:`~football_history_warehouse.consumer.dtos.WarehouseGameInventoryItem`
- :class:`~football_history_warehouse.review.schema.GameReviewPackage` (full review payload)
- :class:`~football_history_warehouse.query.situation.filter.PlaySituationFilter` and bucket enums
- :class:`~football_history_warehouse.query.pagination.PageParams`
- Canonical domain types: :class:`~football_history_warehouse.domain.competition.Play`, :class:`~football_history_warehouse.domain.competition.Game`, enums in :mod:`football_history_warehouse.domain.enums`

**Should not use from the app**

- ``football_history_warehouse.storage.database.models.*`` (table rows)
- ``football_history_warehouse.query.repositories.*``
- ``football_history_warehouse.ingest.*`` and parser modules
- Raw JSON/XML sources on disk or S3 — ingest belongs to the warehouse pipeline
"""

from __future__ import annotations

from football_history_warehouse.consumer.client import FootballWarehouseClient, try_client_from_env
from football_history_warehouse.consumer.dtos import (
    GameInventoryPage,
    PlaysBySituationPage,
    SituationOutcomeSummary,
    TeamTendencySummary,
    WarehouseGameInventoryItem,
)
from football_history_warehouse.consumer.inventory_filters import GameInventoryFilters
from football_history_warehouse.domain.competition import Game, Play
from football_history_warehouse.query.pagination import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, PageParams, PagedItems
from football_history_warehouse.query.situation import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    PlaySituationFilter,
    ScoreDifferentialBucket,
)
from football_history_warehouse.query.situation.filter import validate_situation_has_scope
from football_history_warehouse.review.schema import GameReviewPackage

__all__ = [
    "ClockBucket",
    "DEFAULT_PAGE_LIMIT",
    "DistanceBucket",
    "FieldPositionBucket",
    "FootballWarehouseClient",
    "Game",
    "GameInventoryFilters",
    "GameInventoryPage",
    "GameReviewPackage",
    "MAX_PAGE_LIMIT",
    "PageParams",
    "PagedItems",
    "PlaysBySituationPage",
    "Play",
    "PlaySituationFilter",
    "ScoreDifferentialBucket",
    "SituationOutcomeSummary",
    "TeamTendencySummary",
    "WarehouseGameInventoryItem",
    "try_client_from_env",
    "validate_situation_has_scope",
]
