"""
High-level read API for canonical games, drives, and plays.

Returns immutable :mod:`football_history_warehouse.domain.competition` models with
``provenance=()`` unless a future loader adds provenance joins.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from football_history_warehouse.domain.competition import Drive, Game, Play
from football_history_warehouse.query.filters import PlayQueryFilter
from football_history_warehouse.query.mappers import drive_from_row, game_from_row, play_from_row
from football_history_warehouse.query.pagination import DEFAULT_PAGE_LIMIT, PageParams, PagedItems
from football_history_warehouse.query.repositories.competition import CompetitionQueryRepository
from football_history_warehouse.query.situation.filter import PlaySituationFilter


class FootballHistoryQueryService:
    """
    Application-facing query service for warehouse history.

    **Extension points**
        - Add optional ``include_provenance`` flags that join ``provenance_records``
          and hydrate ``Game`` / ``Play`` provenance tuples.
        - Add keyset pagination using ``(game_id, sequence_in_game, play_id)`` for huge slices.
        - Layer win-probability or EP filters once those columns exist.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CompetitionQueryRepository(session)

    def get_game_by_id(self, game_id: str) -> Game | None:
        row = self._repo.get_game_row(game_id)
        return None if row is None else game_from_row(row)

    def list_games(
        self,
        *,
        league_id: str | None = None,
        season_id: str | None = None,
        team_id: str | None = None,
        page: PageParams | None = None,
    ) -> PagedItems[Game]:
        """
        List games with optional filters. ``team_id`` matches home **or** away.

        Ordered by ``scheduled_start_utc`` (unknowns last), then ``game_id``.
        """
        p = page or PageParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
        rows, has_more = self._repo.fetch_game_rows_page(
            league_id=league_id,
            season_id=season_id,
            team_id=team_id,
            limit=p.limit,
            offset=p.offset,
        )
        return PagedItems(
            items=tuple(game_from_row(r) for r in rows),
            limit=p.limit,
            offset=p.offset,
            has_more=has_more,
        )

    def list_drives_for_game(self, game_id: str) -> tuple[Drive, ...]:
        """All drives for a game, ordered by ``drive_order``."""
        rows = self._repo.fetch_drive_rows_for_game(game_id)
        return tuple(drive_from_row(r) for r in rows)

    def list_plays_matching_situation(
        self,
        situation: PlaySituationFilter,
        *,
        page: PageParams | None = None,
    ) -> PagedItems[Play]:
        """
        Plays matching a composable football situation (may span games).

        Requires ``situation`` to include at least one of ``game_id``, ``league_id``, or ``season_id``.
        """
        p = page or PageParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
        rows, has_more = self._repo.fetch_play_rows_for_situation(
            situation,
            limit=p.limit,
            offset=p.offset,
        )
        return PagedItems(
            items=tuple(play_from_row(r) for r in rows),
            limit=p.limit,
            offset=p.offset,
            has_more=has_more,
        )

    def list_plays_for_game(
        self,
        game_id: str,
        *,
        situation: PlaySituationFilter | None = None,
        play_filter: PlayQueryFilter | None = None,
        page: PageParams | None = None,
    ) -> PagedItems[Play]:
        """
        Plays for one game, ordered by ``sequence_in_game`` within that game.

        Pass a :class:`~football_history_warehouse.query.situation.filter.PlaySituationFilter`
        for situation slices (red zone, two-minute, etc.). ``play_filter`` is merged on top for
        backward compatibility.
        """
        p = page or PageParams(limit=DEFAULT_PAGE_LIMIT, offset=0)
        sit = situation or PlaySituationFilter()
        if play_filter is not None:
            sit = sit.with_play_query_filter(play_filter)
        sit = replace(sit, game_id=game_id)
        rows, has_more = self._repo.fetch_play_rows_for_situation(sit, limit=p.limit, offset=p.offset)
        return PagedItems(
            items=tuple(play_from_row(r) for r in rows),
            limit=p.limit,
            offset=p.offset,
            has_more=has_more,
        )
