"""
Single entry type for applications that consume warehouse history.

The playcalling (or any) app should depend on this module plus :mod:`football_history_warehouse.consumer`
re-exports — not on ORM tables, repositories, or ingest paths.

**Evolution:** v1 is an in-process Python façade over a shared ``Engine``. A future
HTTP/JSON API can implement the same method contracts as remote endpoints; keep DTOs stable.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.consumer.dtos import (
    GameInventoryPage,
    PlaysBySituationPage,
    SituationOutcomeSummary,
    TeamTendencySummary,
)
from football_history_warehouse.consumer.inventory_filters import GameInventoryFilters
from football_history_warehouse.query.pagination import DEFAULT_PAGE_LIMIT, PageParams
from football_history_warehouse.query.services.analytics import WarehouseAnalyticsService
from football_history_warehouse.query.services.history import FootballHistoryQueryService
from football_history_warehouse.query.services.inventory import WarehouseInventoryService
from football_history_warehouse.query.situation.filter import PlaySituationFilter
from football_history_warehouse.review.schema import GameReviewPackage
from football_history_warehouse.review.service import build_game_review_package
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope


class FootballWarehouseClient:
    """
    Application-facing warehouse API.

    Owns a SQLAlchemy :class:`~sqlalchemy.engine.Engine` (connection pool). Call
    :meth:`dispose` when shutting down the host process if you created the engine
    via this class; otherwise the process-level pool is fine for long-lived apps.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_database_url(cls, database_url: str, *, echo_sql: bool = False) -> FootballWarehouseClient:
        cfg = DatabaseConfig(database_url=database_url, echo_sql=echo_sql)
        return cls(create_warehouse_engine(cfg))

    @classmethod
    def from_env(cls, *, echo_sql: bool = False) -> FootballWarehouseClient:
        """``FOOTBALL_WAREHOUSE_DATABASE_URL`` (or project-specific env documented in config)."""
        cfg = DatabaseConfig.from_env()
        if echo_sql:
            cfg = DatabaseConfig(database_url=cfg.database_url, echo_sql=True)
        return cls(create_warehouse_engine(cfg))

    def dispose(self) -> None:
        """Release pool connections (optional for short scripts)."""
        self._engine.dispose()

    def get_game_review_package(self, game_id: str) -> GameReviewPackage | None:
        """Film-room style bundle for one game (scores, drives, play list, tendencies)."""
        with session_scope(self._engine) as session:
            return build_game_review_package(session, game_id)

    def get_plays_by_situation(
        self,
        situation: PlaySituationFilter,
        *,
        page: PageParams | None = None,
    ) -> PlaysBySituationPage:
        """Canonical plays matching a composable situation (bounded scope required)."""
        p = page or PageParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
        with session_scope(self._engine) as session:
            svc = FootballHistoryQueryService(session)
            result = svc.list_plays_matching_situation(situation, page=p)
        return PlaysBySituationPage(
            plays=result.items,
            limit=result.limit,
            offset=result.offset,
            has_more=result.has_more,
        )

    def get_team_tendency_summary(
        self,
        team_id: str,
        *,
        situation: PlaySituationFilter,
    ) -> TeamTendencySummary:
        """
        Offensive play-family counts for ``team_id`` over the given situation slice.

        ``situation`` must include scope (``game_id`` and/or ``league_id`` / ``season_id``).
        Offense is forced to ``team_id``; if ``situation.offense_team_id`` is set to another
        value, :class:`ValueError` is raised.
        """
        merged = situation.with_offense_team(team_id)
        with session_scope(self._engine) as session:
            analytics = WarehouseAnalyticsService(session)
            counts, total = analytics.offense_play_family_counts(merged)
        return TeamTendencySummary(team_id=team_id, total_plays=total, play_family_counts=counts)

    def get_situation_outcome_summary(self, situation: PlaySituationFilter) -> SituationOutcomeSummary:
        """
        Aggregated outcome mix for all plays matching ``situation`` (historical / multi-game when scoped).
        """
        with session_scope(self._engine) as session:
            analytics = WarehouseAnalyticsService(session)
            counts, total = analytics.outcome_category_counts(situation)
        return SituationOutcomeSummary.from_category_counts(counts, total)

    def list_games_inventory(
        self,
        filters: GameInventoryFilters | None = None,
        *,
        page: PageParams | None = None,
    ) -> GameInventoryPage:
        """
        Operator-facing list of games in the warehouse with drive/play counts and import hints.

        Read-only; does not mutate storage. Uses bounded pagination (see :class:`PageParams`).
        """
        f = filters or GameInventoryFilters()
        p = page or PageParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
        with session_scope(self._engine) as session:
            svc = WarehouseInventoryService(session)
            items, has_more = svc.list_game_inventory_page(f, p)
        return GameInventoryPage(games=items, limit=p.limit, offset=p.offset, has_more=has_more)


def try_client_from_env(*, echo_sql: bool = False) -> FootballWarehouseClient | None:
    """Return a client or ``None`` if configuration is missing (CLI / optional integrations)."""
    try:
        return FootballWarehouseClient.from_env(echo_sql=echo_sql)
    except WarehouseConfigError:
        return None
